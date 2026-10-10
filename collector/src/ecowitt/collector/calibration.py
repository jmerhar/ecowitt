"""Whether a console's pressure calibration is right, and what to change if it is not.

A console has two pressure calibrations. The absolute one corrects the barometer itself, and a
good barometer needs none. The relative one turns absolute pressure into sea-level pressure:
some firmware takes it as an offset in hPa, other firmware -- the HP2551's, for one -- as an
"Altitude for REL" it reduces with, and its "ABS Barometer" field sets the absolute reading
directly rather than offsetting it. The warnings give both forms of the fix. Three checks cover
the calibrations, each catching what the others cannot:

* **Relative offset.** The console's relative pressure against this server's own reduction of
  the absolute reading. Judged on the median of recent reports, so one odd reading neither
  raises nor clears it.
* **Absolute step.** A change in absolute pressure faster than the weather can produce. An
  absolute offset shifts the relative reading and the reduction alike, so the first check
  cannot see one; a sudden jump is how a changed absolute offset shows in the data. Steps that
  cancel out -- an offset changed and then put back -- raise nothing, and neither does a step
  after which the absolute reading agrees with the weather model: that one was a correction.
  The second rule matters because steps are held in memory: after a restart, the step that put
  a mistake right is the only one remembered.
* **Absolute reference.** The absolute reading against a weather model's surface pressure for
  the station's coordinates. The only check that catches an absolute offset that has always
  been wrong, rather than one that changed.

Held in memory: a restart forgets steps and recent readings, and the checks rebuild within a
few reports.
"""

from __future__ import annotations

import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .readings import Reading
from .stationconfig import Station

#: Relative error worth acting on. Station barometers are good to 1-3 hPa absolute, and the
#: reduction's temperature dependence is held out of this comparison, so anything tighter is
#: noise.
RELATIVE_THRESHOLD_HPA = 2.0
#: Reports the relative check takes its median over.
RELATIVE_WINDOW = 10

#: A change in absolute pressure between consecutive reports that the weather cannot produce.
#: The steepest real falls, in the deepest storms, are a few hectopascals an hour.
STEP_HPA = 5.0
#: Consecutive reports further apart than this are not compared: after a long silence a large
#: difference may be real.
STEP_WINDOW_SECONDS = 30 * 60
#: How long a step keeps its warning, and how far back cancelling steps are looked for.
STEP_MEMORY_SECONDS = 7 * 86400
#: Net change below which a series of steps counts as put back.
STEP_CANCELLED_HPA = 1.0

#: Disagreement with the weather model worth acting on. Model surface pressure is typically
#: within a hectopascal of a good barometer, so 3 leaves room for both.
REFERENCE_THRESHOLD_HPA = 3.0
#: How long a model value stays usable, and how far from it readings are compared.
REFERENCE_MAX_AGE_SECONDS = 2 * 3600
REFERENCE_MATCH_SECONDS = 30 * 60

#: A dismissed warning stays hidden only while its correction is within this of the value it
#: had when dismissed, so a further change of calibration brings it back.
DISMISS_TOLERANCE_HPA = 1.0


@dataclass(frozen=True)
class Warning:
    """Something about a station's calibration the operator should act on."""

    kind: str
    title: str
    detail: str
    #: The change to make to the console's offset, in hPa; None when there is no number to give.
    correction_hpa: float | None = None
    #: When the problem arose, as Unix seconds, if that is known.
    since: int | None = None


@dataclass
class _Track:
    """What is remembered about one station's pressure."""

    rel_errors: deque[float] = field(default_factory=lambda: deque(maxlen=RELATIVE_WINDOW))
    absolutes: deque[tuple[int, float]] = field(default_factory=lambda: deque(maxlen=240))
    steps: list[tuple[int, float]] = field(default_factory=list)
    reference: tuple[int, float] | None = None


class CalibrationMonitor:
    """Watches each station's pressure readings and says what is wrong with them.

    `on_step` is called whenever a step is seen, so the model reference can be fetched at once
    and a correction recognised within moments rather than at the next scheduled refresh.
    """

    def __init__(self, on_step: Callable[[], None] | None = None) -> None:
        self._tracks: dict[str, _Track] = {}
        self.on_step = on_step

    def observe(self, station: str, timestamp: int, readings: list[Reading]) -> None:
        """Take note of one report's pressure readings, in canonical hPa."""
        values = {r.field: r.value for r in readings if r.table == "pressure"}
        track = self._tracks.setdefault(station, _Track())
        if isinstance(values.get("rel_error"), float):
            track.rel_errors.append(values["rel_error"])  # type: ignore[arg-type]
        absolute = values.get("abs")
        if not isinstance(absolute, float):
            return
        if track.absolutes:
            then, previous = track.absolutes[-1]
            if 0 < timestamp - then <= STEP_WINDOW_SECONDS and abs(absolute - previous) > STEP_HPA:
                track.steps.append((timestamp, absolute - previous))
                if self.on_step is not None:
                    self.on_step()
        track.absolutes.append((timestamp, absolute))
        track.steps = [s for s in track.steps if timestamp - s[0] <= STEP_MEMORY_SECONDS]

    def set_reference(self, station: str, timestamp: int, surface_hpa: float) -> None:
        """Record a weather model's surface pressure for a station's location."""
        self._tracks.setdefault(station, _Track()).reference = (timestamp, surface_hpa)

    def warnings(self, station: Station, now: int) -> list[Warning]:
        """Everything wrong with a station's calibration that the operator has not dismissed."""
        track = self._tracks.get(station.name, _Track())
        found = [
            w
            for w in (
                self._location(station),
                self._step(track, now),
                self._reference(track, now),
                self._relative(station, track),
            )
            if w is not None
        ]
        return [w for w in found if not _dismissed(station, w)]

    @staticmethod
    def _location(station: Station) -> Warning | None:
        if station.preferences.altitude_m is not None:
            return None
        return Warning(
            "location",
            "Altitude not set",
            "Without the station's altitude there is no sea-level pressure and no check of the "
            "console's relative offset. Set it, or give the coordinates and look it up.",
        )

    @classmethod
    def _step(cls, track: _Track, now: int) -> Warning | None:
        if not track.steps:
            return None
        net = sum(delta for _, delta in track.steps)
        if abs(net) < STEP_CANCELLED_HPA:
            return None
        offset = cls._reference_offset(track, now)
        if offset is not None and abs(offset) <= REFERENCE_THRESHOLD_HPA:
            return None
        return Warning(
            "absolute_step",
            "Absolute pressure jumped",
            f"Absolute pressure changed by {net:+.1f} hPa faster than any weather can. That is "
            "almost always a change to the console's absolute calibration, which a good "
            f"barometer does not need. If it was not meant, take it back: change the absolute "
            f"offset by {-net:+.1f} hPa, or on consoles with an 'ABS Barometer' field, set it "
            "to what the sensor itself reads (a WN32P shows it on its own display). Sea-level "
            "pressure is set with the relative offset or 'Altitude for REL', not here.",
            correction_hpa=-net,
            since=track.steps[0][0],
        )

    @staticmethod
    def _reference_offset(track: _Track, now: int) -> float | None:
        """How far absolute pressure is from a current model value, or None if not comparable.

        Only readings taken after the most recent step count, so a correction is judged by
        what the console reads since, not by the mistake before it.
        """
        if track.reference is None:
            return None
        fetched, model = track.reference
        if now - fetched > REFERENCE_MAX_AGE_SECONDS:
            return None
        since = track.steps[-1][0] if track.steps else None
        nearby = [
            v
            for t, v in track.absolutes
            if abs(t - fetched) <= REFERENCE_MATCH_SECONDS and (since is None or t >= since)
        ]
        if not nearby:
            return None
        return statistics.median(nearby) - model

    @classmethod
    def _reference(cls, track: _Track, now: int) -> Warning | None:
        offset = cls._reference_offset(track, now)
        if offset is None or abs(offset) <= REFERENCE_THRESHOLD_HPA:
            return None
        model = track.reference[1]  # type: ignore[index]
        return Warning(
            "absolute_reference",
            "Absolute pressure disagrees with the weather model",
            f"Absolute pressure is {offset:+.1f} hPa from a weather model's surface pressure "
            f"for this location ({model:.1f} hPa). Check the console's absolute calibration -- "
            "an absolute offset should normally be 0, and an 'ABS Barometer' field should match "
            "the sensor's own display -- and that this station's altitude and coordinates are "
            "right.",
            correction_hpa=-offset,
        )

    @staticmethod
    def _relative(station: Station, track: _Track) -> Warning | None:
        if station.preferences.altitude_m is None or len(track.rel_errors) < 3:
            return None
        error = statistics.median(track.rel_errors)
        if abs(error) <= RELATIVE_THRESHOLD_HPA:
            return None
        altitude = station.preferences.altitude_m
        return Warning(
            "relative_offset",
            "Relative pressure is off",
            f"The console's relative pressure is {error:+.1f} hPa from sea-level pressure for "
            f"{altitude:g} m. On consoles with an 'Altitude for REL' setting (the HP2551 has "
            f"it under Calibration), set it to {altitude:g} m. On consoles with a relative "
            f"offset instead, change it by {-error:+.1f} hPa ({-error / 33.8638866667:+.2f} "
            "inHg). Leave the absolute calibration alone: it sets the barometer, not sea level.",
            correction_hpa=-error,
        )


def _dismissed(station: Station, warning: Warning) -> bool:
    """Whether the operator has acknowledged this warning at roughly its present value."""
    if warning.kind not in station.dismissed:
        return False
    if warning.correction_hpa is None:
        return True
    return abs(station.dismissed[warning.kind] - warning.correction_hpa) <= DISMISS_TOLERANCE_HPA

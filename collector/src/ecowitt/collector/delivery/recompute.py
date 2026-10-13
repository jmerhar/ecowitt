"""Recompute a station's wind at 10 m over its history, when the operator asks for it.

Saving a new anemometer height or surroundings changes the estimate for readings from then on
only: the array may have been moved, and readings from its old place should keep the factor that
was right there. When the history should follow -- the factor was set late, or set wrong -- the
setup page starts this, from a chosen moment or from the first reading.

The job reads the stored wind back a day at a time, works out each row's estimate exactly as a
live report's is worked out (`derive.wind_10m`, with the weather model's stored values standing in
for stalled cups), and writes the `wind_10m` rows at the same timestamps, which replaces what
was there. Running it again writes the same values again. It runs in the background; the status
page shows its progress.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ecowitt.collector.admin.stationconfig import Station
from ecowitt.collector.ingest.derive import WIND_FIELDS, wind_10m
from ecowitt.collector.ingest.handler import Sink
from ecowitt.collector.ingest.points import render
from ecowitt.core import weathermodel, windheight
from ecowitt.core.readings import Reading
from ecowitt.core.store.base import Row
from ecowitt.core.store.query import Point, Reader, ReadError
from ecowitt.core.units import Kind, Units, convert, field_name

logger = logging.getLogger(__name__)

#: How much history is read and written at once.
CHUNK = timedelta(days=1)
#: Before any station could have reported, for a recompute of the whole history.
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
#: The units the calculation works in, as the live derivation does.
CANONICAL = Units(wind="ms")


@dataclass
class Progress:
    """What the recompute is doing, or last did, for the status page."""

    #: idle, running, done or failed.
    state: str = "idle"
    station: str = ""
    start: datetime | None = None
    end: datetime | None = None
    #: How far it has got.
    through: datetime | None = None
    rows: int = 0
    factor: float = 1.0
    error: str = ""
    finished: datetime | None = None


class WindRecompute:
    """Runs one recompute at a time, in the background."""

    def __init__(
        self,
        sink: Sink,
        make_reader: Callable[[], Reader | None],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sink = sink
        self._make_reader = make_reader
        self._clock = clock
        self.progress = Progress()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether a recompute is under way."""
        return self.progress.state == "running"

    def start(self, station: Station, since: datetime | None) -> str | None:
        """Start recomputing `station` from `since` (its first reading when None) to now.

        Returns why it cannot start, or None once started.
        """
        if self.running:
            return "A recompute is already running."
        reader = self._make_reader()
        if reader is None:
            return "The database cannot be read back, so its history cannot be recomputed."
        end = self._clock()
        self.progress = Progress(
            "running", station.name, since, end, factor=station.preferences.wind_factor
        )
        self._task = asyncio.create_task(self._run(reader, station, since, end), name="recompute")
        return None

    async def wait(self) -> None:
        """Wait for the running recompute, if any, to finish."""
        if self._task is not None:
            await asyncio.shield(self._task)

    async def aclose(self) -> None:
        """Stop a running recompute; what it has written stays."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(
        self, reader: Reader, station: Station, since: datetime | None, end: datetime
    ) -> None:
        """Recompute day by day, recording progress; a failure stops it and says why."""
        progress = self.progress
        try:
            units = station.preferences.units
            speed = field_name("speed", Kind.SPEED, units)
            if since is None:
                spans = await reader.span(station.name, "wind", [speed], start=EPOCH, end=end)
                since = spans[0].first_time if spans else end
                progress.start = since
            day = since
            while day < end:
                upto = min(day + CHUNK, end)
                rows = await self._chunk(reader, station, day, upto, last=upto >= end)
                if rows:
                    await self._sink.submit(rows)
                progress.rows += len(rows)
                progress.through = upto
                day = upto
            progress.state = "done"
            logger.info(
                "recomputed the 10 m wind of %s from %s: %d rows",
                station.name,
                since.isoformat(),
                progress.rows,
            )
        except ReadError as exc:
            progress.state, progress.error = "failed", str(exc)
            logger.error("recomputing the 10 m wind of %s failed: %s", station.name, exc)
        except Exception as exc:
            progress.state, progress.error = "failed", type(exc).__name__
            logger.exception("recomputing the 10 m wind of %s failed", station.name)
        finally:
            progress.finished = self._clock()
            await reader.aclose()

    async def _chunk(
        self, reader: Reader, station: Station, start: datetime, end: datetime, *, last: bool
    ) -> list[Row]:
        """The `wind_10m` rows for one stretch of a station's stored wind.

        A stretch leaves out its end, which the next one starts at, unless it is the last: a
        reading on the boundary would otherwise be recomputed twice.
        """
        units = station.preferences.units
        names = {field_name(f, Kind.SPEED, units): f for f in WIND_FIELDS}
        points = await reader.points(station.name, "wind", list(names), start=start, end=end)
        points = [p for p in points if last or p.time < end]
        if not points:
            return []
        models = await self._models(reader, station, start, end, units)
        rows = []
        for point in points:
            readings = [
                Reading("wind", names[name], Kind.SPEED, convert(Kind.SPEED, v, units, CANONICAL))
                for name, value in point.values.items()
                if (v := _number(value)) is not None
            ]
            timestamp = int(point.time.timestamp())
            estimate = wind_10m(
                readings, station.preferences.wind_factor, _nearest(models, timestamp), timestamp
            )
            rows += render(estimate, station.preferences, station=station.name, timestamp=timestamp)
        return rows

    @staticmethod
    async def _models(
        reader: Reader, station: Station, start: datetime, end: datetime, units: Units
    ) -> list[windheight.ModelWind]:
        """The station's weather model's wind around a stretch, in m/s, oldest first."""
        if station.model is None or not station.preferences.wind_model_fallback:
            return []
        margin = timedelta(seconds=windheight.MODEL_WITHIN_S)
        speed, gust = (field_name(f, Kind.SPEED, units) for f in ("speed", "gust"))
        points = await reader.points(
            station.name, weathermodel.TABLE, [speed, gust], start=start - margin, end=end + margin
        )
        return [
            _model_wind(p, speed, gust, units)
            for p in points
            if p.tags.get("model") == station.model and _number(p.values.get(speed)) is not None
        ]


def _model_wind(point: Point, speed: str, gust: str, units: Units) -> windheight.ModelWind:
    """A model row's wind in m/s; its speed is known to be there."""
    g = _number(point.values.get(gust))
    return windheight.ModelWind(
        int(point.time.timestamp()),
        convert(Kind.SPEED, _number(point.values[speed]) or 0.0, units, CANONICAL),
        None if g is None else convert(Kind.SPEED, g, units, CANONICAL),
    )


def _number(value: object) -> float | None:
    """A stored number as a float, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _nearest(models: list[windheight.ModelWind], timestamp: int) -> windheight.ModelWind | None:
    """The model value closest in time to `timestamp`."""
    return min(models, key=lambda m: abs(m.timestamp - timestamp), default=None)

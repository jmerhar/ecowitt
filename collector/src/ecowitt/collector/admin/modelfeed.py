"""Store a weather model's view of every station with coordinates, and check pressure against it.

Each station names its model on the setup page (`best_match` unless changed), or turns it off.
Every cycle fetches Open-Meteo's 15-minute values since the last fetch that answered and writes
them to the `model` table through the same delivery as readings. A station seen for the first
time -- at startup, or once its coordinates, altitude or model change -- is fetched back
`HISTORY_SECONDS`, which gives a new installation its comparison from the start and fills any
gap an outage left. Fetching a stretch again only rewrites the same points.

The absolute-pressure check reads the latest surface pressure from the same fetch, and the
status page the latest row, which is kept for it. A
configuration change wakes the cycle early, so coordinates saved on the setup page are fetched
within moments rather than at the next cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx2

from ecowitt.collector.admin import lookups
from ecowitt.collector.admin.calibration import CalibrationMonitor
from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.ingest.handler import Sink
from ecowitt.collector.ingest.points import render
from ecowitt.collector.state import State
from ecowitt.core import weathermodel
from ecowitt.core.readings import Reading
from ecowitt.core.store.base import Row

logger = logging.getLogger(__name__)

#: How far back a station is fetched when first seen, and the most any gap is filled.
HISTORY_SECONDS = 7 * 86400

#: The model's resolution.
QUARTER_SECONDS = 15 * 60


@dataclass(frozen=True)
class _Fetched:
    """What a station was last fetched for, and up to when."""

    place: tuple[float | None, float | None, float | None, str]
    until: int


class ModelFeed:
    """Fetches and stores model values for located stations, on a fixed cycle."""

    def __init__(
        self,
        stations: Callable[[], StationConfig],
        sink: Sink,
        calibration: CalibrationMonitor,
        client: httpx2.AsyncClient,
        *,
        url: str,
        interval_seconds: float,
        state: State | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._stations = stations
        self._sink = sink
        self._calibration = calibration
        self._client = client
        self._url = url
        self._interval = interval_seconds
        self._state = state
        self._clock = clock
        self._fetched: dict[str, _Fetched] = {}
        #: Each station's most recent model row, in its stored units.
        self.latest: dict[str, Row] = {}
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Refresh now rather than at the end of the current pause."""
        self._wake.set()

    async def refresh(self) -> int:
        """Fetch once for every station with a model, returning how many answered."""
        answered = 0
        stations = self._stations().stations
        with_model = {s.name for s in stations if s.model is not None}
        for name in set(self.latest) - with_model:
            del self.latest[name]
        for station in stations:
            if station.model is not None and await self._refresh(station, station.model):
                answered += 1
        return answered

    async def _refresh(self, station: Station, model: str) -> bool:
        """Fetch and store one station's values since its last fetch; whether it answered."""
        end = int(self._clock()) // QUARTER_SECONDS * QUARTER_SECONDS
        place = (station.latitude, station.longitude, station.preferences.altitude_m, model)
        last = self._fetched.get(station.name)
        start = end - HISTORY_SECONDS
        if last is not None and last.place == place:
            start = max(start, last.until)
        samples = await lookups.weather_model(
            self._client,
            station.latitude,  # type: ignore[arg-type]
            station.longitude,  # type: ignore[arg-type]
            station.preferences.altitude_m,
            start=start,
            end=end,
            model=model,
            open_meteo_url=self._url,
        )
        if self._state is not None:
            self._state.record_model(samples is not None)
        if samples is None:
            return False
        # The latest quarter can come back ahead of the clock; only what has happened is kept.
        samples = [s for s in samples if s.timestamp <= self._clock()]
        rows = [
            row
            for sample in samples
            for row in render(
                self._readings(sample, model),
                station.preferences,
                station=station.name,
                timestamp=sample.timestamp,
            )
        ]
        await self._sink.submit(rows)
        if rows:
            self.latest[station.name] = rows[-1]
        pressures = [s for s in samples if "surface_pressure" in s.values]
        if pressures:
            latest = pressures[-1]
            self._calibration.set_reference(
                station.name, latest.timestamp, float(latest.values["surface_pressure"])
            )
        self._fetched[station.name] = _Fetched(place, end)
        return True

    @staticmethod
    def _readings(sample: lookups.ModelSample, model: str) -> list[Reading]:
        """One sample's values as readings of the `model` table."""
        tags = (("model", model), ("source", weathermodel.SOURCE))
        readings = []
        for name, value in sample.values.items():
            field, kind = weathermodel.VARIABLES[name]
            readings.append(Reading(weathermodel.TABLE, field, kind, value, tags=tags))
        return readings

    async def run(self) -> None:
        """Refresh for ever, every interval or sooner when woken. Cancel the task to stop it."""
        while True:
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 - a lookup must never take the server down
                logger.exception("weather model refresh failed")
            await self._pause()

    async def _pause(self) -> None:
        """Wait out the interval, or until woken."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

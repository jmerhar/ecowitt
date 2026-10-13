"""Store each station's weather forecast, hour by hour and day by day, refreshed every hour.

For every station with a weather model the forecast comes from that model, so it agrees with the
model values stored beside the readings. Each fetch writes the hours from now on and the days
from today on, each tagged with its `lead` -- how many hours, or days, ahead of the fetch it is --
so the newest forecast for any moment is the one with the smallest lead, and forecasts made at
every distance ahead are kept to be compared with what the station then measured. A fetch
replaces the previous one's row for the same moment and lead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx2

from ecowitt.collector.admin import lookups
from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.ingest.handler import Sink
from ecowitt.collector.ingest.points import render
from ecowitt.collector.state import State
from ecowitt.core import weathermodel
from ecowitt.core.readings import Reading
from ecowitt.core.store.base import Row

logger = logging.getLogger(__name__)

HOUR_SECONDS = 3600


class ForecastFeed:
    """Fetches and stores the forecast of every station with a weather model, on a cycle."""

    def __init__(
        self,
        stations: Callable[[], StationConfig],
        sink: Sink,
        client: httpx2.AsyncClient,
        *,
        url: str,
        interval_seconds: float,
        state: State | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._stations = stations
        self._sink = sink
        self._client = client
        self._url = url
        self._interval = interval_seconds
        self._state = state
        self._clock = clock
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Refresh now rather than at the end of the current pause."""
        self._wake.set()

    async def refresh(self) -> int:
        """Fetch once for every station with a model, returning how many answered."""
        answered = 0
        for station in self._stations().stations:
            if station.model is not None and await self._refresh(station, station.model):
                answered += 1
        return answered

    async def _refresh(self, station: Station, model: str) -> bool:
        """Fetch and store one station's forecast; whether it answered."""
        forecast = await lookups.weather_forecast(
            self._client,
            station.latitude,  # type: ignore[arg-type]
            station.longitude,  # type: ignore[arg-type]
            station.preferences.altitude_m,
            model=model,
            timezone=station.timezone,
            open_meteo_url=self._url,
        )
        if self._state is not None:
            self._state.record_forecast(forecast is not None)
        if forecast is None:
            return False
        issued = int(self._clock()) // HOUR_SECONDS * HOUR_SECONDS
        zone = ZoneInfo(station.timezone) if station.timezone else UTC
        today = datetime.fromtimestamp(issued, zone).date()
        rows: list[Row] = []
        for sample in forecast.hours:
            if sample.timestamp >= issued:
                lead = (sample.timestamp - issued) // HOUR_SECONDS
                rows += self._rows(station, model, weathermodel.FORECAST_TABLE, sample, lead)
        for sample in forecast.days:
            lead = (datetime.fromtimestamp(sample.timestamp, zone).date() - today).days
            if lead >= 0:
                rows += self._rows(station, model, weathermodel.FORECAST_DAILY_TABLE, sample, lead)
        await self._sink.submit(rows)
        return True

    @staticmethod
    def _rows(
        station: Station, model: str, table: str, sample: lookups.ModelSample, lead: int
    ) -> list[Row]:
        """One forecast sample as a row of `table`, in the station's units."""
        variables = (
            weathermodel.FORECAST_HOURLY
            if table == weathermodel.FORECAST_TABLE
            else weathermodel.FORECAST_DAILY
        )
        tags = (("lead", str(lead)), ("model", model), ("source", weathermodel.SOURCE))
        readings = [
            Reading(table, variables[name][0], variables[name][1], value, tags=tags)
            for name, value in sample.values.items()
        ]
        return render(
            readings, station.preferences, station=station.name, timestamp=sample.timestamp
        )

    async def run(self) -> None:
        """Refresh for ever, every interval or sooner when woken. Cancel the task to stop it."""
        while True:
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 - a forecast must never take the server down
                logger.exception("weather forecast refresh failed")
            await self._pause()

    async def _pause(self) -> None:
        """Wait out the interval, or until woken."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

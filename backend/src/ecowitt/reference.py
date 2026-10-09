"""Keep a weather model's surface pressure current for every station with coordinates.

The absolute-pressure check compares the console with this. Fetched on a slow cycle -- pressure
changes over hours, and the service is free -- and only for stations whose coordinates the
operator has entered. A configuration change wakes the cycle early, so coordinates saved on the
setup page are checked within moments rather than at the next half hour.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

import httpx2

from . import lookups
from .calibration import CalibrationMonitor
from .stationconfig import StationConfig

logger = logging.getLogger(__name__)


class ReferenceUpdater:
    """Fetches model surface pressure for located stations, on a fixed cycle."""

    def __init__(
        self,
        stations: Callable[[], StationConfig],
        calibration: CalibrationMonitor,
        client: httpx2.AsyncClient,
        *,
        url: str,
        interval_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._stations = stations
        self._calibration = calibration
        self._client = client
        self._url = url
        self._interval = interval_seconds
        self._clock = clock
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Refresh now rather than at the end of the current pause."""
        self._wake.set()

    async def refresh(self) -> int:
        """Fetch once for every located station, returning how many answered."""
        answered = 0
        for station in self._stations().stations:
            if not station.located:
                continue
            value = await lookups.surface_pressure(
                self._client,
                station.latitude,  # type: ignore[arg-type]
                station.longitude,  # type: ignore[arg-type]
                station.preferences.altitude_m,
                open_meteo_url=self._url,
            )
            if value is not None:
                self._calibration.set_reference(station.name, int(self._clock()), value)
                answered += 1
        return answered

    async def run(self) -> None:
        """Refresh for ever, every interval or sooner when woken. Cancel the task to stop it."""
        while True:
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 - a lookup must never take the server down
                logger.exception("reference pressure refresh failed")
            await self._pause()

    async def _pause(self) -> None:
        """Wait out the interval, or until woken."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

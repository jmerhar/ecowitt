"""Publish each station's settings to the database, for the dashboard to read.

A station's `station_info` row is written when the collector starts and again only when a
configuration change alters it. What was last published is remembered in memory, so the first
publication after a restart always writes -- which also repopulates a database that was
replaced -- and an unchanged station writes nothing.

Rows go through the same delivery as readings, so while the database is unreachable they wait
in the spool rather than being lost.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.ingest.handler import Sink
from ecowitt.core.readings import Value
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.base import Row

logger = logging.getLogger(__name__)


def info_for(station: Station) -> StationInfo:
    """The settings a station publishes: nothing secret, nothing the dashboard cannot use."""
    prefs = station.preferences
    return StationInfo(
        station=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        altitude_m=prefs.altitude_m,
        timezone=station.timezone,
        units=prefs.units,
        sensors=dict(prefs.names),
    )


class MetadataPublisher:
    """Writes a station's `station_info` row whenever its settings differ from the last one."""

    def __init__(
        self,
        sink: Sink,
        *,
        encode: Callable[[list[Row]], str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sink = sink
        self._encode = encode
        self._clock = clock
        self._published: dict[str, dict[str, Value]] = {}
        self._config = StationConfig()
        self._due = asyncio.Event()

    def update(self, config: StationConfig) -> None:
        """Note the current configuration; `run` publishes whatever it changed."""
        self._config = config
        self._due.set()

    async def publish(self, config: StationConfig) -> int:
        """Write the rows of stations whose settings changed, returning how many."""
        now = int(self._clock())
        changed = {}
        for station in config.stations:
            row = info_for(station).to_row(now)
            if self._published.get(station.name) != row.fields:
                changed[station.name] = row
        if changed:
            await self._sink.submit(self._encode(list(changed.values())))
            self._published.update({name: row.fields for name, row in changed.items()})
            logger.info("published settings of %s", ", ".join(changed))
        return len(changed)

    async def run(self) -> None:
        """Publish after each configuration update. Cancel the task to stop it.

        An unexpected error is logged and the loop carries on, so one failure does not stop
        later changes from being published.
        """
        while True:
            await self._due.wait()
            self._due.clear()
            try:
                await self.publish(self._config)
            except Exception:
                logger.exception("publishing station settings failed")

"""Tell a monitoring service that readings are reaching InfluxDB.

A push monitor -- Uptime Kuma's, healthchecks.io's -- alerts when its URL stops being called.
Calling it after each write InfluxDB accepts makes one monitor cover the whole chain: a console
that stops uploading, an unreachable server, and a database that refuses or cannot take writes
all stop the calls alike, while a report that is merely spooled does not count as delivered.

The calls run on their own task, at most once per interval, so a replayed backlog costs one
call rather than one per report and a slow monitor never holds up ingest.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx2

from ecowitt.collector.state import State
from ecowitt.core import stationinfo, weathermodel, windheight
from ecowitt.core.store.base import Row

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0

#: Tables the collector writes itself rather than from a station's report.
#: The 10 m wind is one: a live report writes it beside the station's readings, which beat, and a
#: recompute writes it alone, which must not.
OWN_TABLES = frozenset({stationinfo.TABLE, weathermodel.TABLE, windheight.TABLE})


class Heartbeat:
    """Calls a URL after readings are written, no more often than once per interval."""

    def __init__(
        self,
        client: httpx2.AsyncClient,
        url: str,
        *,
        interval_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        state: State | None = None,
    ) -> None:
        self._client = client
        self._state = state
        if state is not None:
            state.heartbeat_configured = True
        self._url = url
        self._interval = interval_seconds
        self._sleep = sleep
        self._due = asyncio.Event()
        self._failing = False

    @property
    def host(self) -> str:
        """Where the calls go, without the path or any credentials in the URL.

        Push URLs carry their monitor's token in the path, and some carry a login, so only the
        host is ever logged.
        """
        return urlsplit(self._url).hostname or "?"

    def beat(self) -> None:
        """Note that readings were written; the next call goes out as soon as one may."""
        self._due.set()

    def written(self, rows: list[Row]) -> None:
        """Beat if a write carried a station's readings.

        The collector writes rows of its own as well -- station settings, the weather model --
        and those must not keep the monitor happy while the console has stopped uploading.
        """
        if any(row.table not in OWN_TABLES for row in rows):
            self.beat()

    async def run(self) -> None:
        """Call the URL for each beat, an interval apart at most. Cancel the task to stop it.

        An unexpected error is logged and the loop carries on: ending it would stop the calls,
        and the monitor would report readings missing that are arriving.
        """
        while True:
            await self._due.wait()
            self._due.clear()
            try:
                await self.call()
            except Exception:
                logger.exception("heartbeat to %s failed unexpectedly", self.host)
            await self._sleep(self._interval)

    async def call(self) -> bool:
        """Call the URL once, returning whether the monitor accepted it.

        A failure is logged when calls start failing and again when they recover, not on every
        attempt: the monitor itself raises the alarm, and the log only has to explain it.
        """
        try:
            response = await self._client.get(self._url, timeout=TIMEOUT_SECONDS)
            ok, reason = response.is_success, f"HTTP {response.status_code}"
        except httpx2.RequestError as exc:
            ok, reason = False, type(exc).__name__
        if not ok and not self._failing:
            logger.warning("heartbeat to %s failed: %s", self.host, reason)
        elif ok and self._failing:
            logger.info("heartbeat to %s is getting through again", self.host)
        self._failing = not ok
        if self._state is not None:
            self._state.record_heartbeat(ok)
        return ok

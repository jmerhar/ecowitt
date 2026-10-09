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

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0


class Heartbeat:
    """Calls a URL after readings are written, no more often than once per interval."""

    def __init__(
        self,
        client: httpx2.AsyncClient,
        url: str,
        *,
        interval_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
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

    async def run(self) -> None:
        """Call the URL for each beat, an interval apart at most. Cancel the task to stop it."""
        while True:
            await self._due.wait()
            self._due.clear()
            await self.call()
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
        return ok

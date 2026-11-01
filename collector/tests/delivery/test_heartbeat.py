"""The collector's heartbeat: jigkit's, counted in the state and beating only for readings.

jigkit tests the calls and their pacing; these test what the collector adds.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx2
import pytest

from ecowitt.collector.delivery.heartbeat import Heartbeat
from ecowitt.core.store.base import Row
from ecowitt.core.testing import StubInflux, serving

DEAD = "http://127.0.0.1:1/api/push/s3cr3t"


class Pauses:
    """Records each pause, and holds the loop in it until released."""

    def __init__(self) -> None:
        self.taken: list[float] = []
        self.release = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)
        await self.release.wait()
        self.release.clear()


async def until(condition, timeout: float = 5.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.001)


@contextlib.asynccontextmanager
async def beating(heartbeat: Heartbeat):  # noqa: ANN201
    task = asyncio.create_task(heartbeat.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_calls_are_counted_in_the_state_the_status_page_reads() -> None:
    from ecowitt.collector.state import State

    state = State()
    async with serving(StubInflux(status=503)) as stub, httpx2.AsyncClient() as client:
        heartbeat = Heartbeat(client, stub.url + "/p", interval_seconds=60, state=state)
        assert state.heartbeat_configured
        await heartbeat.call()
        assert (state.heartbeat_failures, state.seconds_since_last_heartbeat) == (1, None)
        stub.status = 200
        await heartbeat.call()
    assert state.heartbeat_failures == 1
    assert state.seconds_since_last_heartbeat is not None


@pytest.mark.parametrize(
    ("tables", "beats"),
    [
        (["outdoor"], True),
        (["model", "outdoor"], True),
        (["model"], False),
        (["station_info"], False),
        (["model", "station_info"], False),
        # A recompute writes the 10 m wind alone; a live report writes it with the readings.
        (["wind_10m"], False),
        (["forecast", "forecast_daily"], False),
        (["wind_10m", "wind"], True),
    ],
)
def test_only_a_stations_readings_count_as_written(tables: list[str], beats: bool) -> None:
    """Rows the collector writes itself must not keep the monitor happy without the console."""
    heartbeat = Heartbeat(httpx2.AsyncClient(), "http://monitor.invalid/push", interval_seconds=60)

    heartbeat.written([Row(table, (("station", "Home"),), 0, {"x": 1.0}) for table in tables])

    assert heartbeat._due.is_set() is beats

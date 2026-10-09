"""The heartbeat: one call per interval after writes, against a real HTTP server."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx2
import pytest

from ecowitt.heartbeat import Heartbeat

from .conftest import StubInflux, serving

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


async def test_a_call_reaches_the_url() -> None:
    async with serving(StubInflux(status=200)) as stub, httpx2.AsyncClient() as client:
        ok = await Heartbeat(client, stub.url + "/api/push/abc", interval_seconds=60).call()

    assert ok
    assert stub.requests[0].method == "GET"
    assert stub.requests[0].path == "/api/push/abc"


async def test_a_refused_call_warns_once_and_recovery_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The monitor raises the alarm; the log explains it once, not on every attempt."""
    async with serving(StubInflux(status=503)) as stub, httpx2.AsyncClient() as client:
        heartbeat = Heartbeat(client, stub.url + "/api/push/abc", interval_seconds=60)
        with caplog.at_level(logging.INFO, logger="ecowitt.heartbeat"):
            assert not await heartbeat.call()
            assert not await heartbeat.call()
            stub.status = 200
            assert await heartbeat.call()
            assert await heartbeat.call()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == ["heartbeat to 127.0.0.1 failed: HTTP 503"]
    assert sum("getting through again" in r.getMessage() for r in caplog.records) == 1


async def test_an_unreachable_monitor_never_logs_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with httpx2.AsyncClient() as client:
        with caplog.at_level(logging.INFO, logger="ecowitt.heartbeat"):
            ok = await Heartbeat(client, DEAD, interval_seconds=60).call()

    assert not ok
    assert "heartbeat to 127.0.0.1 failed: ConnectError" in caplog.text
    assert "s3cr3t" not in caplog.text


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://user:pw@hc-ping.com/uuid-token", "hc-ping.com"),
        ("http://10.0.0.5:3001/api/push/token?status=up", "10.0.0.5"),
        ("not a url", "?"),
    ],
)
def test_only_the_host_is_shown(url: str, host: str) -> None:
    assert Heartbeat(httpx2.AsyncClient(), url, interval_seconds=60).host == host


async def test_nothing_is_called_until_readings_are_written() -> None:
    async with serving(StubInflux(status=200)) as stub, httpx2.AsyncClient() as client:
        heartbeat = Heartbeat(client, stub.url + "/hb", interval_seconds=60)
        async with beating(heartbeat):
            await asyncio.sleep(0.05)

    assert stub.requests == []


async def test_beats_within_an_interval_make_one_call() -> None:
    """A replayed backlog writes many reports in a moment; the monitor hears of it once."""
    pauses = Pauses()
    async with serving(StubInflux(status=200)) as stub, httpx2.AsyncClient() as client:
        heartbeat = Heartbeat(client, stub.url + "/hb", interval_seconds=42, sleep=pauses)
        async with beating(heartbeat):
            heartbeat.beat()
            await until(lambda: pauses.taken)
            for _ in range(5):
                heartbeat.beat()
            await asyncio.sleep(0.05)
            assert len(stub.requests) == 1

            pauses.release.set()
            await until(lambda: len(stub.requests) == 2)
            await until(lambda: len(pauses.taken) == 2)
            pauses.release.set()
            await asyncio.sleep(0.05)

    assert pauses.taken == [42, 42]
    assert len(stub.requests) == 2

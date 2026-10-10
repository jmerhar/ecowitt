"""An InfluxDB outage end to end: the real handler, delivery, spool and writer.

Only the database is a stand-in, and it is a real HTTP server, so what is checked is what
InfluxDB would actually have received.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.delivery.delivery import Delivery
from ecowitt.collector.delivery.spool import Spool
from ecowitt.collector.ingest.handler import StationHandler
from ecowitt.collector.state import State
from ecowitt.core.preferences import Preferences
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.store.lineprotocol import encode
from ecowitt.core.testing import StubInflux, serving

from ..conftest import FIXTURE_PASSKEY, payload

CONFIG = StationConfig((Station("Home", Preferences(), FIXTURE_PASSKEY),))


#: The receipt time every report is processed at. Reports are stamped in the minutes just
#: before it, inside the parser's clock-skew allowance, so each keeps its own timestamp.
RECEIVED = datetime(2026, 10, 8, 23, 30, tzinfo=UTC)
FIRST_MINUTE = 25


def reports(count: int) -> list[dict[str, str]]:
    """The recorded payload at `count` successive minutes, so each is a distinct report."""
    base = dict(urllib.parse.parse_qsl(payload("hp2551_indoor"), keep_blank_values=True))
    return [base | {"dateutc": f"2026-10-08 23:{FIRST_MINUTE + i:02d}:24"} for i in range(count)]


def stamp(index: int) -> str:
    """The line-protocol timestamp of the `index`th report."""
    moment = datetime(2026, 10, 8, 23, FIRST_MINUTE + index, 24, tzinfo=UTC)
    return str(int(moment.timestamp()))


async def no_pause(_: float) -> None:
    await asyncio.sleep(0)


async def until(condition, timeout: float = 10.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


def handler_for(delivery: Delivery) -> StationHandler:
    return StationHandler(CONFIG, delivery, encode=encode, clock=lambda: RECEIVED)


def stored_timestamps(stub: StubInflux) -> list[str]:
    """Report timestamps in the order InfluxDB accepted them, one per accepted request."""
    return [r.body.split()[-1] for r in stub.requests if r.status == 204]


async def test_an_outage_loses_nothing_and_keeps_order(tmp_path: Path) -> None:
    async with serving(StubInflux(status=503)) as stub:
        writer = Influx3Store(stub.url, "weather", "t")
        spool, state = Spool(tmp_path / "spool", 10_000_000), State()
        delivery = Delivery(writer, spool, state, sleep=no_pause)
        handler = handler_for(delivery)
        replay = asyncio.create_task(delivery.run())
        try:
            for fields in reports(5):
                assert await handler.handle(fields, "192.0.2.9") is True
            await until(lambda: len(stub.requests) >= 8)
            assert len(spool) == 5

            stub.status = 204
            await until(lambda: len(spool) == 0)
        finally:
            replay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await replay
            await writer.aclose()

    assert stored_timestamps(stub) == [stamp(i) for i in range(5)]
    assert state.writes_succeeded == 5
    assert state.writes_failed >= 4
    assert state.reports_spooled == 5


async def test_a_backlog_survives_a_restart_and_lands_when_influxdb_returns(tmp_path: Path) -> None:
    """Database unreachable, process restarted, database back: every report arrives."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    # First process: nothing is listening, so every report is spooled. It then stops
    # without ever reaching the database.
    writer = Influx3Store(url, "weather")
    delivery = Delivery(writer, Spool(tmp_path / "spool", 10_000_000), State(), sleep=no_pause)
    try:
        for fields in reports(3):
            await handler_for(delivery).handle(fields, "192.0.2.9")
    finally:
        await writer.aclose()

    # Second process, same data directory, and the database is back on the same address.
    async with serving(StubInflux(), port) as stub:
        writer = Influx3Store(url, "weather")
        spool = Spool(tmp_path / "spool", 10_000_000)
        assert len(spool) == 3
        replay = asyncio.create_task(Delivery(writer, spool, State(), sleep=no_pause).run())
        try:
            await until(lambda: len(spool) == 0)
        finally:
            replay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await replay
            await writer.aclose()

    assert stored_timestamps(stub) == [stamp(i) for i in range(3)]


async def test_a_report_influxdb_refuses_is_kept_aside_and_the_rest_flow(tmp_path: Path) -> None:
    async with serving(StubInflux(status=400, reply="field type conflict")) as stub:
        writer = Influx3Store(stub.url, "weather")
        spool, state = Spool(tmp_path / "spool", 10_000_000), State()
        delivery = Delivery(writer, spool, state, sleep=no_pause)
        try:
            first, second = reports(2)
            await handler_for(delivery).handle(first, "192.0.2.9")
            stub.status = 204
            await handler_for(delivery).handle(second, "192.0.2.9")
        finally:
            await writer.aclose()

    assert stored_timestamps(stub) == [stamp(1)]
    assert spool.rejected_count() == 1
    assert state.writes_rejected == 1
    assert len(spool) == 0

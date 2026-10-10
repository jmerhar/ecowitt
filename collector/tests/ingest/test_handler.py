"""Authenticating, processing and writing a report."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime

import pytest

from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.ingest.handler import MAX_ANNOUNCED_UNKNOWN, StationHandler
from ecowitt.core.preferences import Preferences
from ecowitt.core.store.base import Row
from ecowitt.core.store.lineprotocol import encode

from ..conftest import FIXTURE_PASSKEY, payload


class MemorySink:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def submit(self, rows: list[Row]) -> None:
        self.bodies.append(encode(rows))


CONFIG = StationConfig((Station("Home", Preferences(names={"ch1": "Bathroom"}), FIXTURE_PASSKEY),))
CLOCK = lambda: datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC)  # noqa: E731


def report() -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(payload("hp2551_indoor"), keep_blank_values=True))


async def test_a_configured_station_is_written_under_its_name() -> None:
    writer = MemorySink()
    handler = StationHandler(CONFIG, writer, clock=CLOCK)

    assert await handler.handle(report(), "192.0.2.9") is True

    (body,) = writer.bodies
    assert "station=Home" in body
    assert "name=Bathroom,sensor=ch1" in body
    assert FIXTURE_PASSKEY not in body


async def test_an_unknown_station_is_refused_and_nothing_written(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = MemorySink()
    handler = StationHandler(CONFIG, writer, clock=CLOCK)
    fields = report() | {"PASSKEY": "FFFF0000FFFF0000FFFF0000FFFF0000"}

    with caplog.at_level(logging.WARNING):
        assert await handler.handle(fields, "192.0.2.9") is False

    assert writer.bodies == []
    assert "no configured station has this PASSKEY" in caplog.text
    assert "FFFF0000FFFF0000" not in caplog.text


async def test_a_report_without_a_passkey_is_refused() -> None:
    handler = StationHandler(CONFIG, MemorySink(), clock=CLOCK)

    assert await handler.handle({"tempf": "50"}, "192.0.2.9") is False


async def test_each_unknown_station_is_announced_once(caplog: pytest.LogCaptureFixture) -> None:
    handler = StationHandler(CONFIG, MemorySink(), clock=CLOCK)

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            await handler.handle({"PASSKEY": "X"}, "192.0.2.9")

    assert caplog.text.count("discarded") == 1


async def test_announcements_are_bounded(caplog: pytest.LogCaptureFixture) -> None:
    """A scan of invented PASSKEYs cannot fill the log."""
    handler = StationHandler(CONFIG, MemorySink(), clock=CLOCK)

    with caplog.at_level(logging.WARNING):
        for i in range(MAX_ANNOUNCED_UNKNOWN + 50):
            await handler.handle({"PASSKEY": f"guess-{i}"}, "192.0.2.9")

    assert caplog.text.count("discarded") == MAX_ANNOUNCED_UNKNOWN


async def test_staleness_carries_across_reports() -> None:
    """The handler keeps one tracker, so a repeated report shows its age."""
    writer = MemorySink()
    times = iter(
        [datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC), datetime(2026, 10, 8, 23, 2, 26, tzinfo=UTC)]
    )
    handler = StationHandler(CONFIG, writer, clock=lambda: next(times))
    first = report()
    second = first | {"dateutc": "2026-10-08 23:02:24"}

    await handler.handle(first, "192.0.2.9")
    await handler.handle(second, "192.0.2.9")

    assert "unchanged_s=60.0" in writer.bodies[1]


async def test_the_latest_report_is_kept_per_station() -> None:
    handler = StationHandler(CONFIG, MemorySink(), clock=CLOCK)

    await handler.handle(report(), "192.0.2.9")

    latest = handler.latest["Home"]
    assert latest.received_at == CLOCK()
    assert any(p.table == "indoor" for p in latest.points)


async def test_an_unknown_station_is_offered_for_adoption() -> None:
    from ecowitt.collector.ingest.pending import PendingStations

    pending = PendingStations()
    handler = StationHandler(CONFIG, MemorySink(), pending=pending, clock=CLOCK)

    await handler.handle(report() | {"PASSKEY": "NEWCONSOLE"}, "192.0.2.9")

    (entry,) = pending.list()
    assert (entry.passkey, entry.model) == ("NEWCONSOLE", "HP2551AE_Pro_V2.1.4")


async def test_reports_feed_the_calibration_checks_in_canonical_units() -> None:
    """The monitor sees hPa whatever units the operator stores in."""
    from ecowitt.collector.admin.calibration import CalibrationMonitor
    from ecowitt.core.units import Units

    monitor = CalibrationMonitor()
    inhg = StationConfig(
        (Station("Home", Preferences(units=Units(pressure="inhg")), FIXTURE_PASSKEY),)
    )
    handler = StationHandler(inhg, MemorySink(), calibration=monitor, clock=CLOCK)

    await handler.handle(report(), "192.0.2.9")

    ((_, absolute),) = monitor._tracks["Home"].absolutes
    assert absolute == pytest.approx(29.796 * 33.8638866667)


async def test_a_replaced_configuration_takes_effect_on_the_next_report() -> None:
    handler = StationHandler(StationConfig(), MemorySink(), clock=CLOCK)
    assert await handler.handle(report(), "192.0.2.9") is False

    handler.config = CONFIG

    assert await handler.handle(report(), "192.0.2.9") is True

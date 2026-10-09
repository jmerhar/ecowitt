"""Authenticating, processing and writing a report."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime

import pytest

from ecowitt.handler import MAX_ANNOUNCED_UNKNOWN, StationHandler
from ecowitt.preferences import Preferences
from ecowitt.state import State
from ecowitt.stationconfig import Station, StationConfig

from ..conftest import FIXTURE_PASSKEY, payload


class MemoryWriter:
    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.bodies: list[str] = []

    async def write(self, body: str) -> bool:
        self.bodies.append(body)
        return self.succeed


CONFIG = StationConfig((Station("Home", Preferences(names={"ch1": "Bathroom"}), FIXTURE_PASSKEY),))
CLOCK = lambda: datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC)  # noqa: E731


def report() -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(payload("hp2551_indoor"), keep_blank_values=True))


async def test_a_configured_station_is_written_under_its_name() -> None:
    writer, state = MemoryWriter(), State()
    handler = StationHandler(CONFIG, writer, state, clock=CLOCK)

    assert await handler.handle(report(), "192.0.2.9") is True

    (body,) = writer.bodies
    assert "station=Home" in body
    assert "name=Bathroom,sensor=ch1" in body
    assert FIXTURE_PASSKEY not in body
    assert state.writes_succeeded == 1


async def test_an_unknown_station_is_refused_and_nothing_written(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = MemoryWriter()
    handler = StationHandler(CONFIG, writer, State(), clock=CLOCK)
    fields = report() | {"PASSKEY": "FFFF0000FFFF0000FFFF0000FFFF0000"}

    with caplog.at_level(logging.WARNING):
        assert await handler.handle(fields, "192.0.2.9") is False

    assert writer.bodies == []
    assert "no configured station has this PASSKEY" in caplog.text
    assert "FFFF0000FFFF0000" not in caplog.text


async def test_a_report_without_a_passkey_is_refused() -> None:
    handler = StationHandler(CONFIG, MemoryWriter(), State(), clock=CLOCK)

    assert await handler.handle({"tempf": "50"}, "192.0.2.9") is False


async def test_each_unknown_station_is_announced_once(caplog: pytest.LogCaptureFixture) -> None:
    handler = StationHandler(CONFIG, MemoryWriter(), State(), clock=CLOCK)

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            await handler.handle({"PASSKEY": "X"}, "192.0.2.9")

    assert caplog.text.count("discarded") == 1


async def test_announcements_are_bounded(caplog: pytest.LogCaptureFixture) -> None:
    """A scan of invented PASSKEYs cannot fill the log."""
    handler = StationHandler(CONFIG, MemoryWriter(), State(), clock=CLOCK)

    with caplog.at_level(logging.WARNING):
        for i in range(MAX_ANNOUNCED_UNKNOWN + 50):
            await handler.handle({"PASSKEY": f"guess-{i}"}, "192.0.2.9")

    assert caplog.text.count("discarded") == MAX_ANNOUNCED_UNKNOWN


async def test_a_failed_write_still_counts_the_report_as_authentic() -> None:
    """The station did nothing wrong; the failure is recorded against the database."""
    state = State()
    handler = StationHandler(CONFIG, MemoryWriter(succeed=False), state, clock=CLOCK)

    assert await handler.handle(report(), "192.0.2.9") is True
    assert (state.writes_succeeded, state.writes_failed) == (0, 1)


async def test_staleness_carries_across_reports() -> None:
    """The handler keeps one tracker, so a repeated report shows its age."""
    writer = MemoryWriter()
    times = iter(
        [datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC), datetime(2026, 10, 8, 23, 2, 26, tzinfo=UTC)]
    )
    handler = StationHandler(CONFIG, writer, State(), clock=lambda: next(times))
    first = report()
    second = first | {"dateutc": "2026-10-08 23:02:24"}

    await handler.handle(first, "192.0.2.9")
    await handler.handle(second, "192.0.2.9")

    assert "unchanged_s=60.0" in writer.bodies[1]

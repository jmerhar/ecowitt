"""The collector's delivery: jigkit's write-or-spool loop, counted in the collector's state.

jigkit tests the loop itself; these test what the collector adds to it: the state the status
page reads, and the line protocol files an older version spooled.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from ecowitt.collector.delivery.delivery import Delivery
from ecowitt.collector.delivery.spool import Spool
from ecowitt.collector.state import State
from ecowitt.core.store.base import Outcome, Row


def report(name: str) -> list[Row]:
    """One report's rows, labelled so a test can tell reports apart."""
    return [Row("indoor", (("station", "home"),), 1791500484, {"report": name})]


class ScriptedSender:
    """Answers each send with the next scripted outcome, then OK for ever."""

    def __init__(self, outcomes: Iterable[Outcome] = ()) -> None:
        self.outcomes = list(outcomes)
        self.sent: list[str] = []

    async def write(self, rows: list[Row]) -> Outcome:
        self.sent.append(str(rows[0].fields["report"]))
        return self.outcomes.pop(0) if self.outcomes else Outcome.OK


class Pauses:
    """Records each pause instead of waiting it out."""

    async def __call__(self, seconds: float) -> None:
        await asyncio.sleep(0)


@pytest.fixture
def spool(tmp_path: Path) -> Spool:
    return Spool(tmp_path / "spool", 1_000_000)


@contextlib.asynccontextmanager
async def replaying(delivery: Delivery) -> AsyncIterator[None]:
    task = asyncio.create_task(delivery.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def until(condition, timeout: float = 5.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.001)


async def test_every_outcome_is_counted_in_the_state(spool: Spool) -> None:
    state = State()
    delivery = Delivery(ScriptedSender([Outcome.OK, Outcome.REJECT, Outcome.RETRY]), spool, state)

    await delivery.submit(report("stored"))
    await delivery.submit(report("refused"))
    await delivery.submit(report("waiting"))

    assert (state.writes_succeeded, state.writes_failed) == (1, 2)
    assert (state.writes_rejected, state.reports_spooled) == (1, 1)


async def test_a_report_that_cannot_be_spooled_is_counted_as_lost_not_spooled(
    spool: Spool,
) -> None:
    state = State()
    spool.pending_dir.chmod(0o500)
    try:
        await Delivery(ScriptedSender([Outcome.RETRY]), spool, state).submit(report("r1"))
    finally:
        spool.pending_dir.chmod(0o700)

    assert state.reports_spooled == 0


async def test_line_protocol_an_older_version_spooled_is_set_aside(
    spool: Spool, caplog: pytest.LogCaptureFixture
) -> None:
    """Such files are listed, reach delivery, and are kept apart rather than left unseen."""
    legacy = spool.pending_dir / "00000000000000000001-0000000000.lp"
    legacy.write_text("indoor,station=home temp_c=21.0 1791500484", encoding="utf-8")
    spool = Spool(spool.pending_dir.parent, 1_000_000)
    sender = ScriptedSender()

    async with replaying(Delivery(sender, spool, State(), sleep=Pauses())):
        await until(lambda: len(spool) == 0)

    assert sender.sent == []
    assert spool.rejected_count() == 1
    assert "is not points" in caplog.text

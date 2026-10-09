"""Delivery: write now, or spool and replay, against a scripted sender."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from ecowitt.delivery import FIRST_PAUSE_SECONDS, MAX_PAUSE_SECONDS, Delivery
from ecowitt.spool import Spool
from ecowitt.state import State
from ecowitt.writer import Outcome


class ScriptedSender:
    """Answers each send with the next scripted outcome, then OK for ever."""

    def __init__(self, outcomes: Iterable[Outcome] = ()) -> None:
        self.outcomes = list(outcomes)
        self.sent: list[str] = []

    async def send(self, body: str) -> Outcome:
        self.sent.append(body)
        return self.outcomes.pop(0) if self.outcomes else Outcome.OK


class Pauses:
    """Records each pause instead of waiting it out."""

    def __init__(self) -> None:
        self.taken: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)
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


async def test_a_healthy_database_is_written_straight_away(spool: Spool) -> None:
    sender, state = ScriptedSender(), State()

    await Delivery(sender, spool, state).submit("r1")

    assert sender.sent == ["r1"]
    assert len(spool) == 0
    assert state.writes_succeeded == 1


async def test_an_empty_report_is_not_sent(spool: Spool) -> None:
    sender = ScriptedSender()

    await Delivery(sender, spool, State()).submit("")

    assert sender.sent == []


async def test_a_failed_write_is_spooled_not_lost(spool: Spool) -> None:
    sender, state = ScriptedSender([Outcome.RETRY]), State()

    await Delivery(sender, spool, state).submit("r1")

    assert len(spool) == 1
    assert (state.writes_failed, state.reports_spooled) == (1, 1)


async def test_while_anything_waits_new_reports_queue_behind_it(spool: Spool) -> None:
    """An outage costs one attempt per pause, not one per report, and order is kept."""
    sender = ScriptedSender([Outcome.RETRY])
    delivery = Delivery(sender, spool, State())

    await delivery.submit("r1")
    await delivery.submit("r2")
    await delivery.submit("r3")

    assert sender.sent == ["r1"]
    assert len(spool) == 3


async def test_the_backlog_replays_in_arrival_order(spool: Spool) -> None:
    sender, state = ScriptedSender([Outcome.RETRY]), State()
    delivery = Delivery(sender, spool, state, sleep=Pauses())
    for body in ("r1", "r2", "r3"):
        await delivery.submit(body)

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)

    assert sender.sent == ["r1", "r1", "r2", "r3"]
    assert state.writes_succeeded == 3


async def test_pauses_double_up_to_the_maximum_and_reset_on_success(spool: Spool) -> None:
    pauses = Pauses()
    sender = ScriptedSender([Outcome.RETRY] * 10)
    delivery = Delivery(sender, spool, State(), sleep=pauses)
    await delivery.submit("r1")

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)
        # A second outage: the live attempt fails, then the loop's first retry does too.
        sender.outcomes = [Outcome.RETRY, Outcome.RETRY]
        await delivery.submit("r2")
        await until(lambda: len(spool) == 0)

    assert pauses.taken[:8] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        32.0,
        MAX_PAUSE_SECONDS,
        MAX_PAUSE_SECONDS,
    ]
    # After the success, the second outage starts again from the first pause.
    assert pauses.taken[9:] == [FIRST_PAUSE_SECONDS]


async def test_a_report_refused_live_is_set_aside_not_retried(spool: Spool) -> None:
    sender, state = ScriptedSender([Outcome.REJECT]), State()

    await Delivery(sender, spool, state).submit("bad")

    assert len(spool) == 0
    assert spool.rejected_count() == 1
    assert state.writes_rejected == 1


async def test_a_refused_report_does_not_block_the_queue(spool: Spool) -> None:
    """A poisoned report is set aside and the ones behind it still land."""
    sender, state = ScriptedSender([Outcome.RETRY]), State()
    delivery = Delivery(sender, spool, state, sleep=Pauses())
    for body in ("bad", "good1", "good2"):
        await delivery.submit(body)
    sender.outcomes = [Outcome.REJECT]

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)

    assert sender.sent == ["bad", "bad", "good1", "good2"]
    assert spool.rejected_count() == 1
    assert state.writes_rejected == 1


async def test_an_unreadable_spool_file_is_set_aside(spool: Spool) -> None:
    sender = ScriptedSender([Outcome.RETRY])
    delivery = Delivery(sender, spool, State(), sleep=Pauses())
    await delivery.submit("r1")
    path = spool.oldest()
    assert path is not None
    path.write_bytes(b"\xff\xfe\x00 not utf-8")
    await delivery.submit("r2")

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)

    assert sender.sent == ["r1", "r2"]
    assert spool.rejected_count() == 1


async def test_the_replay_loop_sleeps_while_nothing_waits(spool: Spool) -> None:
    """An idle loop sends nothing, and wakes when a report is queued."""
    sender = ScriptedSender()
    delivery = Delivery(sender, spool, State(), sleep=Pauses())

    async with replaying(delivery):
        await asyncio.sleep(0.01)
        assert sender.sent == []
        sender.outcomes = [Outcome.RETRY]
        await delivery.submit("r1")
        await until(lambda: len(spool) == 0)

    assert sender.sent == ["r1", "r1"]


async def test_a_backlog_left_by_a_previous_process_is_replayed(tmp_path: Path) -> None:
    """Persisted before a restart, delivered after it."""
    before = Spool(tmp_path / "spool", 1_000_000)
    before.enqueue("from-yesterday")
    after = Spool(tmp_path / "spool", 1_000_000)
    sender = ScriptedSender()

    async with replaying(Delivery(sender, after, State(), sleep=Pauses())):
        await until(lambda: len(after) == 0)

    assert sender.sent == ["from-yesterday"]


async def test_a_report_that_cannot_be_spooled_is_counted_as_lost_not_spooled(
    spool: Spool,
) -> None:
    state = State()
    spool.pending_dir.chmod(0o500)
    try:
        await Delivery(ScriptedSender([Outcome.RETRY]), spool, state).submit("r1")
    finally:
        spool.pending_dir.chmod(0o700)

    assert state.reports_spooled == 0


async def test_a_success_mid_backlog_resets_the_pause(spool: Spool) -> None:
    """After a long outage, one success means the next failure waits a second, not minutes.

    Every outcome is scripted up front: changing the script while the loop runs would race it.
    """
    pauses = Pauses()
    # r1 fails live and five more times in the loop, then succeeds; r2 fails once more.
    sender = ScriptedSender([Outcome.RETRY] * 6 + [Outcome.OK, Outcome.RETRY])
    delivery = Delivery(sender, spool, State(), sleep=pauses)
    for body in ("r1", "r2", "r3"):
        await delivery.submit(body)

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)

    assert pauses.taken == [1.0, 2.0, 4.0, 8.0, 16.0, FIRST_PAUSE_SECONDS]


async def test_every_accepted_write_is_announced_live_or_replayed(spool: Spool) -> None:
    """The heartbeat hangs off this: a write counts once InfluxDB has accepted it."""
    written: list[bool] = []
    sender = ScriptedSender([Outcome.OK, Outcome.RETRY, Outcome.RETRY])
    delivery = Delivery(
        sender, spool, State(), sleep=Pauses(), on_written=lambda: written.append(True)
    )

    await delivery.submit("live")
    assert written == [True]

    await delivery.submit("spooled")
    assert written == [True]

    async with replaying(delivery):
        await until(lambda: not len(spool))

    assert sender.sent == ["live", "spooled", "spooled", "spooled"]
    assert written == [True, True]


@pytest.mark.parametrize("live", [True, False])
async def test_a_refused_write_is_not_announced(spool: Spool, live: bool) -> None:
    written: list[bool] = []
    outcomes = [Outcome.REJECT] if live else [Outcome.RETRY, Outcome.REJECT]
    delivery = Delivery(
        ScriptedSender(outcomes), spool, State(), on_written=lambda: written.append(True)
    )

    await delivery.submit("refused")
    async with replaying(delivery):
        await until(lambda: not len(spool))

    assert written == []


class ExplodingSender(ScriptedSender):
    """Raises something no outcome covers on its first send, then behaves."""

    def __init__(self) -> None:
        super().__init__()
        self.exploded = False

    async def send(self, body: str) -> Outcome:
        if not self.exploded:
            self.exploded = True
            self.sent.append(body)
            raise RuntimeError("a client error the writer does not classify")
        return await super().send(body)


async def test_an_unexpected_error_does_not_end_the_replay_loop(
    spool: Spool, caplog: pytest.LogCaptureFixture
) -> None:
    """With the loop gone, every later report would queue with nothing left to drain it."""
    spool.enqueue("r1")
    sender, pauses = ExplodingSender(), Pauses()
    delivery = Delivery(sender, spool, State(), sleep=pauses)

    async with replaying(delivery):
        await until(lambda: len(spool) == 0)

    assert sender.sent == ["r1", "r1"]
    assert pauses.taken == [FIRST_PAUSE_SECONDS]
    assert "replaying the spool failed" in caplog.text

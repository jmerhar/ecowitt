"""Getting reports into InfluxDB eventually: write now if possible, spool and replay if not.

A report is written straight away while nothing is waiting. Once anything is, new reports join
the end of the queue instead, and one background loop drains it oldest first with growing
pauses between failed attempts -- so an outage costs one retry per pause rather than one per
report, and the backlog lands in the order it arrived.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .spool import Spool
from .state import State
from .writer import Outcome

logger = logging.getLogger(__name__)

FIRST_PAUSE_SECONDS = 1.0
MAX_PAUSE_SECONDS = 60.0


class Sender(Protocol):
    """Something that attempts one write and says what became of it."""

    async def send(self, body: str) -> Outcome:
        """Write rows once."""


class Delivery:
    """Writes reports, spooling the ones that cannot be written yet."""

    def __init__(
        self,
        sender: Sender,
        spool: Spool,
        state: State,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sender = sender
        self._spool = spool
        self._state = state
        self._sleep = sleep
        self._wake = asyncio.Event()

    async def submit(self, body: str) -> None:
        """Deliver one report's rows now, or queue them for the replay loop."""
        if not body:
            return
        if len(self._spool):
            self._queue(body)
            return
        outcome = await self._sender.send(body)
        self._state.record_write(outcome is Outcome.OK)
        if outcome is Outcome.RETRY:
            self._queue(body)
        elif outcome is Outcome.REJECT:
            self._state.record_rejected_write()
            self._spool.quarantine_body(body)

    async def run(self) -> None:
        """Replay spooled reports for ever, oldest first. Cancel the task to stop it."""
        pause = FIRST_PAUSE_SECONDS
        while True:
            path = self._spool.oldest()
            if path is None:
                pause = FIRST_PAUSE_SECONDS
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                body = self._spool.read(path)
            except OSError, UnicodeDecodeError:
                logger.exception("cannot read spooled report %s; setting it aside", path.name)
                self._spool.quarantine(path)
                continue

            outcome = await self._sender.send(body)
            self._state.record_write(outcome is Outcome.OK)
            if outcome is Outcome.OK:
                self._spool.ack(path)
                pause = FIRST_PAUSE_SECONDS
                if not len(self._spool):
                    logger.info("spool drained")
            elif outcome is Outcome.REJECT:
                self._state.record_rejected_write()
                self._spool.quarantine(path)
            else:
                await self._sleep(pause)
                pause = min(pause * 2, MAX_PAUSE_SECONDS)

    def _queue(self, body: str) -> None:
        """Add a report to the spool and wake the replay loop."""
        if self._spool.enqueue(body):
            self._state.record_spooled()
        self._wake.set()

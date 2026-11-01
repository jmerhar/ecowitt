"""Getting reports into InfluxDB eventually: write now if possible, spool and replay if not.

jigkit's delivery loop: a report is written straight away while nothing is waiting, and once
anything is, new reports join the queue and one background loop drains it oldest first with
growing pauses between failed attempts. Every attempt, spooled report and refusal is counted in
the collector's state, which the status page shows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from jigkit.delivery import FIRST_PAUSE_SECONDS, MAX_PAUSE_SECONDS, Writer
from jigkit.delivery import Delivery as _Delivery

from ecowitt.collector.delivery.spool import Spool
from ecowitt.collector.state import State
from ecowitt.core.store.base import Row

__all__ = ["FIRST_PAUSE_SECONDS", "MAX_PAUSE_SECONDS", "Delivery", "Writer"]


class Delivery(_Delivery):
    """Writes reports, spooling the ones that cannot be written yet, counted in `state`.

    `on_written` is called with the rows of every write the database accepts, live or replayed.
    """

    def __init__(
        self,
        store: Writer,
        spool: Spool,
        state: State,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_written: Callable[[list[Row]], None] = lambda _: None,
    ) -> None:
        super().__init__(store, spool, events=state, sleep=sleep, on_written=on_written)

"""Answers kept for a short while, so a crowd of visitors costs the database one query each.

Concurrent requests for the same key share one computation: the first starts it and the rest
wait on its result, so a burst of visitors arriving together does not become a burst of queries.
A failure is not kept; the next request tries again.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TtlCache:
    """At most `max_entries` results, each for as long as the caller asked."""

    max_entries: int = 1024
    clock: Callable[[], float] = time.monotonic
    _entries: OrderedDict[Hashable, tuple[float, asyncio.Future[Any]]] = field(
        default_factory=OrderedDict
    )

    async def get[T](self, key: Hashable, ttl: float, compute: Callable[[], Awaitable[T]]) -> T:
        """The cached result for `key`, or `compute()`'s, kept for `ttl` seconds.

        The computation runs as its own task, so a visitor who disconnects while waiting does
        not cancel it for the others.
        """
        entry = self._entries.get(key)
        if entry is not None and (not entry[1].done() or entry[0] > self.clock()):
            self._entries.move_to_end(key)
            return await asyncio.shield(entry[1])
        task: asyncio.Future[T] = asyncio.ensure_future(compute())
        self._entries[key] = (math.inf, task)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

        def settle(done: asyncio.Future[T]) -> None:
            # Asking for the exception marks it retrieved even when no visitor is left waiting.
            failed = done.cancelled() or done.exception() is not None
            if self._entries.get(key, (0.0, None))[1] is not done:
                return
            if failed:
                del self._entries[key]
            else:
                self._entries[key] = (self.clock() + ttl, done)

        task.add_done_callback(settle)
        return await asyncio.shield(task)

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()

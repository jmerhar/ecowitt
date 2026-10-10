"""The database the configuration names, swapped in place when the configuration changes.

Delivery and the handler hold this one object for the process's life; saving a new connection on
the setup page replaces the store behind it, so the change applies at the next write with no
restart. Until a connection is configured every write is a RETRY, and reports wait in the spool.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from ecowitt.core.store.base import Outcome, Row, Store
from ecowitt.core.store.settings import store_from

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "no database is configured"


class ConfiguredStore:
    """A `Store` that forwards to whichever store the configuration currently names."""

    def __init__(self) -> None:
        self._current: Store | None = None
        self._connection: tuple[str, tuple[tuple[str, str], ...]] | None = None
        #: Stores replaced by a configuration change, closed at shutdown: a write in flight may
        #: still be using one when it is replaced.
        self._retired: list[Store] = []
        self._last_error: str | None = None
        #: The kind of the current store, or None.
        self.kind: str | None = None

    @property
    def configured(self) -> bool:
        """Whether a connection is configured."""
        return self._current is not None and self._current.configured

    @property
    def last_error(self) -> str | None:
        """Why the last write failed, or None after a success."""
        return self._current.last_error if self._current else self._last_error

    def configure(self, kind: str | None, values: Mapping[str, str]) -> None:
        """Use the store this connection describes, or none; unchanged settings change nothing."""
        connection = (kind, tuple(sorted(values.items()))) if kind else None
        if connection == self._connection:
            return
        if self._current is not None:
            self._retired.append(self._current)
        self._current = store_from(kind, values) if kind else None
        self._connection, self.kind = connection, kind
        logger.info("database: %s", kind or "none configured")

    async def write(self, rows: list[Row]) -> Outcome:
        """Write through the current store; without one, a RETRY so the rows are spooled."""
        if self._current is None:
            self._last_error = NOT_CONFIGURED
            return Outcome.RETRY
        return await self._current.write(rows)

    async def check(self) -> str | None:
        """Whether the current store would accept a write."""
        return await self._current.check() if self._current else NOT_CONFIGURED

    async def aclose(self) -> None:
        """Close the current store and every one it replaced."""
        for store in [*self._retired, *([self._current] if self._current else [])]:
            await store.aclose()
        self._retired.clear()

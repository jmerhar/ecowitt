"""The interface every database implements, and the rows that pass through it.

Rows go in as `Row`s and leave as a payload of text in the database's own wire format, which is
what the collector's spool keeps while the database is unreachable. Encoding first and writing
later keeps the spool independent of the database: it stores whatever `encode` produced and
hands it back to `write`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from ecowitt.core.readings import Value


@dataclass(frozen=True)
class Row:
    """One row: a table, its tags, its fields, and when it was measured (Unix seconds)."""

    table: str
    tags: tuple[tuple[str, str], ...]
    timestamp: int
    fields: dict[str, Value] = field(default_factory=dict)


class Outcome(Enum):
    """What became of one attempt to write."""

    #: Stored.
    OK = "ok"
    #: Not stored, and worth trying again: the database is unreachable, overloaded, or
    #: refusing this client for a reason someone can fix.
    RETRY = "retry"
    #: Not stored, and never will be: the database refused the data itself. Retrying would
    #: block every payload queued behind this one.
    REJECT = "reject"


class Store(Protocol):
    """A database readings are written to."""

    #: Why the last write failed, or None after a success.
    last_error: str | None

    @property
    def configured(self) -> bool:
        """Whether there is anywhere to write to."""

    def encode(self, rows: list[Row]) -> str:
        """Rows as this database's payload; empty when there is nothing to write."""

    async def write(self, payload: str) -> Outcome:
        """Write one payload, returning what became of it. Never raises for a failed write."""

    async def aclose(self) -> None:
        """Release connections."""

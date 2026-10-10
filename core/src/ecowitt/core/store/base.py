"""The interface every database implements, and the rows that pass through it.

Rows go to `Store.write` as `Row`s; each store encodes them in its own wire format at that
moment. While a write cannot happen the collector's spool keeps rows in the neutral text form
`dump_rows` produces, so a backlog survives the database being configured, replaced or changed
to another kind before it drains.
"""

from __future__ import annotations

import json
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
    #: block every write queued behind this one.
    REJECT = "reject"


class Store(Protocol):
    """A database readings are written to."""

    #: Why the last write failed, or None after a success.
    last_error: str | None

    @property
    def configured(self) -> bool:
        """Whether there is anywhere to write to."""

    async def write(self, rows: list[Row]) -> Outcome:
        """Write rows once, returning what became of them. Never raises for a failed write."""

    async def check(self) -> str | None:
        """Whether this store would accept a write, without writing: None, or the reason not."""

    async def aclose(self) -> None:
        """Release connections."""


def dump_rows(rows: list[Row]) -> str:
    """Rows as text any store can be given later: one JSON array, field types preserved.

    Every number is a float already (the collector writes no integers), and JSON keeps the
    distinction between `60.0` and `true`, so nothing changes type on the way through.
    """
    return json.dumps(
        [[row.table, [list(tag) for tag in row.tags], row.timestamp, row.fields] for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def load_rows(text: str) -> list[Row]:
    """Rows from `dump_rows`' text. Raises ValueError for anything else."""
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            raise TypeError(f"a {type(data).__name__}, not a list")
        return [
            Row(table, tuple((k, v) for k, v in tags), timestamp, dict(fields))
            for table, tags, timestamp, fields in data
        ]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"not a list of rows: {exc}") from exc

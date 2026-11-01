"""The rows readings are written as, and the interface every database implements.

Built on jigkit's sinks: a `Row` is a jigkit `Point` whose timestamp is in whole seconds, the
precision every reading and every row the collector writes itself carries. Each store encodes
rows in its own wire format when it writes. While a write cannot happen the collector's spool
keeps rows in the neutral text form `dump_rows` produces, so a backlog survives the database
being configured, replaced or changed to another kind before it drains.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jigkit.sinks import Outcome, Point, Precision, dump_points, load_points
from jigkit.sinks import Sink as Store

__all__ = ["Outcome", "Row", "Store", "dump_rows", "load_rows"]


@dataclass(frozen=True)
class Row(Point):
    """One row: a table, its tags, its fields, and when it was measured (Unix seconds)."""

    precision: Precision = field(default=Precision.SECONDS, kw_only=True)


def dump_rows(rows: list[Row]) -> str:
    """Rows as text any store can be given later, field types and precision preserved."""
    return dump_points(list(rows))


def load_rows(text: str) -> list[Row]:
    """Rows from `dump_rows`' text, including the form spooled before rows carried a precision.

    Raises ValueError for anything else.
    """
    return [
        Row(point.table, point.tags, point.timestamp, point.fields, precision=point.precision)
        for point in load_points(text)
    ]

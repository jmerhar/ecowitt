"""Encode rows as InfluxDB line protocol, through jigkit's encoder.

Every row carries whole seconds, so the text is what InfluxDB is sent at second precision.
"""

from __future__ import annotations

from collections.abc import Sequence

from jigkit.influx.lineprotocol import encode as encode_points
from jigkit.influx.lineprotocol import encode_point as encode_one

from ecowitt.core.store.base import Row


def encode(rows: Sequence[Row]) -> str:
    """Encode rows as newline-separated line protocol, skipping any that have no fields."""
    return encode_points(rows)[0]


def encode_point(row: Row) -> str:
    """Encode one row, or return an empty string if none of its fields can be written."""
    return encode_one(row, row.precision)

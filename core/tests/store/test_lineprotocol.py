"""Rows as line protocol: jigkit encodes them, always at second precision."""

from __future__ import annotations

from ecowitt.core.store.base import Row
from ecowitt.core.store.lineprotocol import encode, encode_point

ROW = Row("indoor", (("station", "home"),), 1791500484, {"temp_c": 23.2})


def test_a_row_is_one_line_in_seconds() -> None:
    assert encode_point(ROW) == "indoor,station=home temp_c=23.2 1791500484"


def test_rows_are_lines_and_unwritable_ones_are_dropped() -> None:
    empty = Row("indoor", (("station", "home"),), 1791500484, {"x": float("nan")})

    assert encode([ROW, empty, ROW]) == "\n".join([encode_point(ROW)] * 2)

"""The neutral text form rows wait in while the database cannot take them."""

from __future__ import annotations

import pytest

from ecowitt.core.store.base import Row, dump_rows, load_rows

ROWS = [
    Row("indoor", (("name", "Spare room"), ("station", "home")), 1791500484, {"temp_c": 21.0}),
    Row("battery", (("station", "home"),), 1791500484, {"low": False, "model": "WH65 é"}),
]


def test_rows_survive_the_round_trip_with_their_types() -> None:
    """60.0 must not come back as 60, nor False as 0: the database fixes a field's type."""
    back = load_rows(dump_rows(ROWS))

    assert back == ROWS
    assert isinstance(back[0].fields["temp_c"], float)
    assert back[1].fields["low"] is False


def test_no_rows_survive_too() -> None:
    assert load_rows(dump_rows([])) == []


@pytest.mark.parametrize(
    "text", ["indoor,station=home temp_c=21.0 1791500484", "{}", "[[1, 2]]", '[["t", 3, 1, {}]]']
)
def test_anything_else_is_refused(text: str) -> None:
    """A file in another format -- line protocol from before rows were spooled -- is not rows."""
    with pytest.raises(ValueError, match="not a list of rows"):
        load_rows(text)

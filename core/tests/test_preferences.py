"""Preferences: how a station's readings are named and reduced."""

from __future__ import annotations

import pytest

from ecowitt.core.preferences import Preferences
from ecowitt.core.units import Units


def test_a_named_sensor_uses_its_name() -> None:
    assert Preferences(names={"ch1": "Bathroom"}).name_for("ch1") == "Bathroom"


@pytest.mark.parametrize("names", [{}, {"ch1": ""}])
def test_an_unnamed_sensor_falls_back_to_its_identifier(names: dict[str, str]) -> None:
    """Every row of a named table keeps the same tag set, so naming one later changes a value."""
    assert Preferences(names=names).name_for("ch1") == "ch1"


def test_the_defaults_are_european_units_and_no_altitude() -> None:
    prefs = Preferences()

    assert prefs.units == Units()
    assert prefs.altitude_m is None

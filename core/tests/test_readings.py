"""Readings and reports: the values between a station's upload and the stored rows."""

from __future__ import annotations

import dataclasses

import pytest

from ecowitt.core.readings import Reading, Report
from ecowitt.core.units import Kind


def test_a_reading_keeps_its_canonical_value_and_describes_no_sensor_by_default() -> None:
    reading = Reading("indoor", "temp", Kind.TEMPERATURE, 21.5)

    assert (reading.table, reading.field, reading.value) == ("indoor", "temp", 21.5)
    assert reading.tags == ()
    assert reading.sensor is None


def test_a_reading_cannot_be_changed_after_it_is_made() -> None:
    reading = Reading("indoor", "temp", Kind.TEMPERATURE, 21.5, sensor="indoor")

    with pytest.raises(dataclasses.FrozenInstanceError):
        reading.value = 22.0  # type: ignore[misc]


def test_reports_do_not_share_a_readings_list() -> None:
    """A shared default list would carry one report's readings into the next."""
    first, second = Report(timestamp=1), Report(timestamp=2)
    first.readings.append(Reading("indoor", "temp", Kind.TEMPERATURE, 21.5))

    assert second.readings == []

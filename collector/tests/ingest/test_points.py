"""Grouping readings into rows, in the operator's units."""

from __future__ import annotations

from ecowitt.collector.ingest.points import render
from ecowitt.core.preferences import Preferences
from ecowitt.core.readings import Reading
from ecowitt.core.units import Kind, Units


def test_readings_sharing_a_table_and_tags_become_one_row() -> None:
    readings = [
        Reading("channel", "temp", Kind.TEMPERATURE, 20.0, (("channel", "1"),), "ch1"),
        Reading("channel", "humidity", Kind.HUMIDITY, 60.0, (("channel", "1"),), "ch1"),
        Reading("channel", "temp", Kind.TEMPERATURE, 18.0, (("channel", "2"),), "ch2"),
    ]

    points = render(readings, Preferences(), station="home", timestamp=7)

    assert len(points) == 2
    assert points[0].fields == {"humidity_pct": 60.0, "temp_c": 20.0}
    assert points[0].timestamp == 7


def test_named_rows_carry_the_sensor_id_and_display_name() -> None:
    """`sensor` joins a room across tables; `name` labels it."""
    reading = Reading("indoor", "temp", Kind.TEMPERATURE, 20.0, sensor="indoor")

    (point,) = render(
        [reading], Preferences(names={"indoor": "Lounge"}), station="home", timestamp=0
    )

    assert dict(point.tags) == {"name": "Lounge", "sensor": "indoor", "station": "home"}


def test_an_unnamed_sensor_is_labelled_with_its_id() -> None:
    """Every named row has the same tag set, named or not."""
    reading = Reading("channel", "temp", Kind.TEMPERATURE, 20.0, (("channel", "4"),), "ch4")

    (point,) = render([reading], Preferences(), station="home", timestamp=0)

    assert dict(point.tags)["name"] == "ch4"


def test_unnamed_tables_carry_only_the_station() -> None:
    reading = Reading("wind", "speed", Kind.SPEED, 2.0, sensor="wind")

    (point,) = render([reading], Preferences(), station="home", timestamp=0)

    assert point.tags == (("station", "home"),)


def test_values_take_the_operators_units_and_name_them() -> None:
    readings = [
        Reading("outdoor", "temp", Kind.TEMPERATURE, 20.0, sensor="outdoor"),
        Reading("wind", "speed", Kind.SPEED, 10.0, sensor="wind"),
        Reading("pressure", "abs", Kind.PRESSURE, 1013.25, sensor="pressure"),
    ]
    units = Units(temperature="f", wind="mph", pressure="inhg")

    points = {
        p.table: p.fields
        for p in render(readings, Preferences(units=units), station="h", timestamp=0)
    }

    assert points["outdoor"] == {"temp_f": 68.0}
    assert points["wind"] == {"speed_mph": 22.3694}
    assert points["pressure"] == {"abs_inhg": 29.9213}


def test_converted_values_are_rounded() -> None:
    """Float noise from a conversion is not stored."""
    reading = Reading("indoor", "temp", Kind.TEMPERATURE, (73.8 - 32) * 5 / 9, sensor="indoor")

    (point,) = render([reading], Preferences(), station="h", timestamp=0)

    assert point.fields == {"temp_c": 23.2222}


def test_flags_and_text_pass_through_unconverted() -> None:
    readings = [
        Reading("battery", "low", Kind.FLAG, True, sensor="ch1"),
        Reading("station", "model", Kind.TEXT, "HP2551"),
    ]

    points = {p.table: p.fields for p in render(readings, Preferences(), station="h", timestamp=0)}

    assert points == {"battery": {"low": True}, "station": {"model": "HP2551"}}


def test_the_later_of_two_spellings_wins() -> None:
    """`tempinf` and `indoortempf` in one report are one field."""
    readings = [
        Reading("indoor", "temp", Kind.TEMPERATURE, 20.0, sensor="indoor"),
        Reading("indoor", "temp", Kind.TEMPERATURE, 21.0, sensor="indoor"),
    ]

    (point,) = render(readings, Preferences(), station="h", timestamp=0)

    assert point.fields == {"temp_c": 21.0}


def test_rows_and_fields_come_out_in_a_stable_order() -> None:
    """Deterministic output is what makes the golden test possible."""
    readings = [
        Reading("wind", "speed", Kind.SPEED, 1.0, sensor="wind"),
        Reading("indoor", "temp", Kind.TEMPERATURE, 20.0, sensor="indoor"),
        Reading("indoor", "humidity", Kind.HUMIDITY, 50.0, sensor="indoor"),
    ]

    points = render(readings, Preferences(), station="h", timestamp=0)

    assert [p.table for p in points] == ["indoor", "wind"]
    assert list(points[0].fields) == ["humidity_pct", "temp_c"]

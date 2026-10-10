"""Station metadata: the row the collector publishes and the dashboard reads back."""

from __future__ import annotations

from ecowitt.core.stationinfo import TABLE, StationInfo
from ecowitt.core.store.lineprotocol import encode_point
from ecowitt.core.units import Units

FULL = StationInfo(
    station="Home",
    latitude=52.37,
    longitude=4.9,
    altitude_m=12,
    timezone="Europe/Amsterdam",
    units=Units(temperature="f", wind="ms"),
    sensors={"ch1": "Study", "indoor": "Lounge"},
)


def test_the_row_carries_every_setting_with_units_in_the_field_names() -> None:
    row = FULL.to_row(1791500484)

    assert (row.table, row.tags, row.timestamp) == (TABLE, (("station", "Home"),), 1791500484)
    assert row.fields == {
        "altitude_m": 12.0,
        "latitude_deg": 52.37,
        "longitude_deg": 4.9,
        "sensor_ch1": "Study",
        "sensor_indoor": "Lounge",
        "timezone": "Europe/Amsterdam",
        "units_distance": "km",
        "units_pressure": "hpa",
        "units_rain": "mm",
        "units_temperature": "f",
        "units_wind": "ms",
    }


def test_what_is_not_set_is_left_out() -> None:
    row = StationInfo(station="Home").to_row(1)

    assert set(row.fields) == {
        f"units_{q}" for q in ("distance", "pressure", "rain", "temperature", "wind")
    }


def test_every_number_is_written_as_a_float() -> None:
    """The database fixes a field's type on its first write; an integer altitude would stick."""
    assert "altitude_m=12.0" in encode_point(FULL.to_row(1))


def test_a_row_reads_back_as_the_same_settings() -> None:
    assert StationInfo.from_fields("Home", FULL.to_row(1).fields) == FULL


def test_nulls_from_a_query_are_unset() -> None:
    """Columns a row never had come back as nulls from a SQL query of the whole table."""
    info = StationInfo.from_fields(
        "Home", {"latitude_deg": None, "timezone": None, "sensor_x": None}
    )

    assert info == StationInfo(station="Home")


def test_an_unknown_unit_falls_back_to_the_defaults() -> None:
    """A newer collector's row must not stop an older dashboard showing the station."""
    info = StationInfo.from_fields("Home", {"units_temperature": "kelvin", "units_wind": "ms"})

    assert info.units == Units()


def test_values_of_the_wrong_type_are_ignored() -> None:
    info = StationInfo.from_fields(
        "Home", {"latitude_deg": "north", "timezone": 3.0, "sensor_ch1": 1.0, "units_rain": 2.0}
    )

    assert info == StationInfo(station="Home")

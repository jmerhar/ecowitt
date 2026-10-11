"""The model table's schema, which the collector writes and the dashboard and Grafana read."""

from __future__ import annotations

from ecowitt.core import weathermodel
from ecowitt.core.units import Units, field_name


def test_each_variable_is_stored_under_its_own_field() -> None:
    fields = [base for base, _ in weathermodel.VARIABLES.values()]

    assert len(set(fields)) == len(fields)


def test_stored_names_follow_the_station_tables_in_the_default_units() -> None:
    """The same names as `outdoor`, `wind`, `pressure` and `solar`, so the two line up."""
    stored = {field_name(base, kind, Units()) for base, kind in weathermodel.VARIABLES.values()}

    assert stored == {
        "temp_c",
        "humidity_pct",
        "dewpoint_c",
        "speed_kmh",
        "gust_kmh",
        "dir_deg",
        "abs_hpa",
        "sea_hpa",
        "precip_15m_mm",
        "radiation_wm2",
        "uv_index",
        "cloud_cover_pct",
        "weather_code",
        "is_day",
    }

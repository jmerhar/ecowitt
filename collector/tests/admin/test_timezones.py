"""Time zones from coordinates, offline, and validation of zone names."""

from __future__ import annotations

import pytest

from ecowitt.collector.admin import timezones


@pytest.mark.parametrize(
    ("latitude", "longitude", "zone"),
    [
        (52.37, 4.9, "Europe/Amsterdam"),
        (38.72, -9.14, "Europe/Lisbon"),
        (40.71, -74.01, "America/New_York"),
        (-33.87, 151.21, "Australia/Sydney"),
    ],
)
def test_coordinates_give_their_zone(latitude: float, longitude: float, zone: str) -> None:
    assert timezones.zone_at(latitude, longitude) == zone


def test_the_open_sea_still_has_a_zone() -> None:
    zone = timezones.zone_at(0.0, -30.0)

    assert zone is not None and zone.startswith("Etc/GMT")


@pytest.mark.parametrize(("latitude", "longitude"), [(None, 4.9), (52.37, None), (None, None)])
def test_without_both_coordinates_there_is_no_zone(
    latitude: float | None, longitude: float | None
) -> None:
    assert timezones.zone_at(latitude, longitude) is None


def test_an_answer_this_system_does_not_know_is_no_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timezones.tzfpy, "get_tz", lambda _lon, _lat: "Mars/Olympus_Mons")

    assert timezones.zone_at(1.0, 1.0) is None


@pytest.mark.parametrize(
    ("name", "known"),
    [
        ("Europe/Lisbon", True),
        ("UTC", True),
        ("Europe/Atlantis", False),
        ("../etc", False),
        ("", False),
    ],
)
def test_zone_names_are_checked_against_the_system(name: str, known: bool) -> None:
    assert timezones.is_zone(name) is known


def test_the_zone_list_is_sorted_and_complete() -> None:
    zones = timezones.all_zones()

    assert zones == sorted(zones)
    assert {"Europe/Lisbon", "UTC"} <= set(zones)

"""Sun times against the US Naval Observatory's almanac, which gives them to the minute."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from ecowitt.dashboard.sun import sun_times


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "lat", "lon", "rise", "noon", "set_"),
    [
        (date(2026, 6, 21), 38.72, -9.14, "06-21T05:12", "06-21T12:38", "06-21T20:05"),
        (date(2026, 12, 21), 38.72, -9.14, "12-21T07:51", "12-21T12:35", "12-21T17:18"),
        (date(2026, 10, 10), 64.15, -21.94, "10-10T08:03", "10-10T13:15", "10-10T18:25"),
        # East of Greenwich a local day's sunrise falls on the UTC day before.
        (date(2026, 3, 21), -33.87, 151.21, "03-20T19:59", "03-21T02:03", "03-21T08:06"),
    ],
)  # fmt: skip
def test_sun_times_match_the_almanac(
    day: date, lat: float, lon: float, rise: str, noon: str, set_: str
) -> None:
    rise, noon, set_ = (f"2026-{t}" for t in (rise, noon, set_))
    times = sun_times(day, lat, lon)
    tolerance = timedelta(minutes=1)
    assert times.sunrise is not None and times.sunset is not None
    assert abs(times.sunrise - at(rise)) <= tolerance
    assert abs(times.noon - at(noon)) <= tolerance
    assert abs(times.sunset - at(set_)) <= tolerance
    assert times.daylight == times.sunset - times.sunrise
    assert times.polar is None


def test_midnight_sun() -> None:
    times = sun_times(date(2026, 6, 21), 69.65, 18.96)
    assert (times.sunrise, times.sunset, times.polar) == (None, None, "day")
    assert times.daylight == timedelta(days=1)
    assert abs(times.noon - at("2026-06-21T10:46")) <= timedelta(minutes=1)


def test_polar_night() -> None:
    times = sun_times(date(2026, 12, 21), 69.65, 18.96)
    assert (times.sunrise, times.polar, times.daylight) == (None, "night", timedelta(0))

"""Words and judgements from readings, checked against the published tables they come from."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from ecowitt.dashboard import weather
from ecowitt.dashboard.service import DEWPOINT_TREND, TREND_STEP
from ecowitt.dashboard.weather import Airing, Tendency

from .conftest import REPO


@pytest.mark.parametrize(
    ("degrees", "point"),
    [(0, "N"), (11.2, "N"), (11.3, "NNE"), (135, "SE"), (348.75, "N"), (359.9, "N"), (-90, "W")],
)
def test_compass(degrees: float, point: str) -> None:
    assert weather.compass(degrees) == point


@pytest.mark.parametrize(
    ("kmh", "force"),
    # WMO bounds in m/s: 0.5 is force 1, 32.7 force 12.
    [(0.0, 0), (1.7, 0), (1.8, 1), (15.0, 3), (61.9, 7), (62.0, 8), (117.7, 11), (117.8, 12)],
)
def test_beaufort(kmh: float, force: int) -> None:
    assert weather.beaufort(kmh) == force
    assert len(weather.BEAUFORT_NAMES) == len(weather.BEAUFORT_FROM_MS) + 1


@pytest.mark.parametrize(
    # Environment and Climate Change Canada's wind chill table.
    ("temp", "kmh", "chill"),
    [(-10, 20, -18), (0, 10, -3), (-25, 40, -41), (5, 60, -2)],
)
def test_wind_chill(temp: float, kmh: float, chill: float) -> None:
    assert round(weather.wind_chill(temp, kmh)) == chill


@pytest.mark.parametrize(
    # The US National Weather Service heat index chart, in °F.
    ("temp_f", "humidity", "index_f"),
    [(90, 60, 100), (96, 65, 121), (80, 40, 80), (104, 40, 119), (86, 90, 105), (70, 50, 69)],
)
def test_heat_index(temp_f: float, humidity: float, index_f: float) -> None:
    index = weather.heat_index((temp_f - 32) * 5 / 9, humidity) * 9 / 5 + 32
    assert round(index) == index_f


def rothfusz(t: float, rh: float) -> float:
    """The NWS regression alone, in °F."""
    return (
        -42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
        - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
        + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh
    )  # fmt: skip


@pytest.mark.parametrize(
    # The NWS adjustments: below 13% between 80 and 112 °F, above 85% between 80 and 87 °F.
    ("temp_f", "humidity", "adjustment"),
    [(95, 10, -0.75), (84, 95, 0.6), (95, 50, 0.0)],
)
def test_heat_index_adjusts_for_very_dry_and_very_humid_air(
    temp_f: float, humidity: float, adjustment: float
) -> None:
    index = weather.heat_index((temp_f - 32) * 5 / 9, humidity) * 9 / 5 + 32
    assert index == pytest.approx(rothfusz(temp_f, humidity) + adjustment)


@pytest.mark.parametrize(
    ("temp", "humidity", "kmh", "feels"),
    [
        (-10, 50, 20, -17.9),
        (10, 50, 4.8, 9.8),
        (10, 50, 4.7, 10),
        (11, 50, 30, 11),
        (-5, 50, None, -5),
        (32, 60, 10, 37.1),
        (27, 20, 10, 27),
        (30, None, 10, 30),
        (20, 90, 30, 20),
    ],
)
def test_feels_like(temp: float, humidity: float | None, kmh: float | None, feels: float) -> None:
    assert weather.feels_like(temp, humidity, kmh) == pytest.approx(feels, abs=0.05)


@pytest.mark.parametrize(
    ("change", "tendency"),
    [
        (0.0, Tendency.STEADY),
        (-0.09, Tendency.STEADY),
        (0.1, Tendency.RISING_SLOWLY),
        (-0.1, Tendency.FALLING_SLOWLY),
        (-1.5, Tendency.FALLING_SLOWLY),
        (1.6, Tendency.RISING),
        (-3.5, Tendency.FALLING),
        (3.6, Tendency.RISING_QUICKLY),
        (-6.0, Tendency.FALLING_QUICKLY),
        (6.1, Tendency.RISING_VERY_RAPIDLY),
        (-6.1, Tendency.FALLING_VERY_RAPIDLY),
    ],
)
def test_tendency(change: float, tendency: Tendency) -> None:
    assert weather.tendency(change) is tendency


@pytest.mark.parametrize(
    ("humidity", "delta", "after", "advice"),
    [
        (70, 2.1, 58, Airing.OPEN),
        (65, 2.1, 55, Airing.OPEN),
        (64.9, 5, 40, Airing.NO_NEED),
        (90, 2.0, 80, Airing.NO_NEED),
        # Airing would not help a damp room, but would not hurt it either.
        (90, 0.5, 89, Airing.NO_NEED),
        (60, 0.2, 59, Airing.NO_NEED),
        # It would leave a room damp and damper than it is, by more than the sensors' error.
        (70, -1.0, 75, Airing.KEEP_CLOSED),
        (60, -1.0, 65, Airing.KEEP_CLOSED),
        (60.5, -1.0, 65, Airing.NO_NEED),
        (69, -0.2, 70.2, Airing.NO_NEED),
        # Damper, but not damp: nothing to warn of.
        (50, -2, 62, Airing.NO_NEED),
        (70, -0.5, None, Airing.NO_NEED),
    ],
)
def test_airing(humidity: float, delta: float, after: float | None, advice: Airing) -> None:
    assert weather.airing(humidity, delta, after) is advice


def test_the_thresholds_match_the_alert_rules() -> None:
    rules = {
        rule["title"]: rule
        for group in json.loads((REPO / "grafana/alerts.json").read_text())["groups"]
        for rule in group["rules"]
    }

    def condition(title: str) -> dict[str, Any]:
        (step,) = [d for d in rules[title]["data"] if d["refId"] == "C"]
        return step["model"]

    def threshold(title: str) -> float:
        return condition(title)["conditions"][0]["evaluator"]["params"][0]

    air = {d["refId"]: d["model"] for d in rules["Good time to air"]["data"]}
    assert air["E"]["expression"] == (
        f"$A < {weather.WINDOWS_OPEN_SHARE:g} && $B >= {weather.AIRING_HUMIDITY_PCT:g}"
        f" && $B - $D >= {weather.DAMPER_BY_PCT:g}"
    )
    assert f"interval '{weather.WINDOWS_OPEN_WITHIN_MIN} minutes'" in air["A"]["rawSql"]
    close = {d["refId"]: d["model"] for d in rules["Close the windows"]["data"]}
    assert close["E"]["expression"] == (
        f"$A >= {weather.WINDOWS_OPEN_SHARE:g} && ($C >= {weather.DAMPER_DEWPOINT_RISE_C:g}"
        f" || $D >= {weather.DAMPER_HUMIDITY_RISE_PCT:g})"
    )
    assert f"interval '{weather.WINDOWS_OPEN_WITHIN_MIN} minutes'" in close["A"]["rawSql"]
    assert f"interval '{weather.DAMPER_LOW_WITHIN_H} hours'" in close["D"]["rawSql"]
    trend, step = DEWPOINT_TREND // timedelta(minutes=1), TREND_STEP // timedelta(minutes=1)
    for minutes in (trend, trend - 2 * step, step):
        assert f"interval '{minutes} minutes'" in close["C"]["rawSql"]
    assert threshold("Sensor not updating") == weather.STALE_AFTER_S
    silent = next(d for d in rules["Sensor not updating"]["data"] if d["refId"] == "A")
    # The sensors the dashboard judges too (service._judged): the outdoor one and the rooms.
    assert "d.sensor IN ('indoor', 'outdoor') OR d.sensor LIKE 'ch%'" in silent["model"]["rawSql"]


@pytest.mark.parametrize(
    ("rooms", "humidity", "after", "advice"),
    [
        # Any room airing would dry, whatever the median room would do.
        ([(70, 3.0, 55), (50, -2.0, 62), (50, -2.0, 62)], 50, 62, Airing.OPEN),
        # The median room, 60%, would settle at 66%.
        ([(58, -1.0, 64), (60, -1.0, 66), (64, -0.5, 70)], 60, 66, Airing.KEEP_CLOSED),
        # 60% to 59%: no help, and no harm.
        ([(58, 0.2, 57), (60, 0.2, 59), (62, 0.3, 61)], 60, 59, Airing.NO_NEED),
        ([(50, 1.0, 48), (55, 3.0, 45)], 52.5, 46.5, Airing.NO_NEED),
        ([(60, -1.0, None)], 60, None, Airing.NO_NEED),
        ([], 60, 70, Airing.KEEP_CLOSED),
    ],
)
def test_house_airing(
    rooms: list[tuple[float, float, float | None]],
    humidity: float,
    after: float | None,
    advice: Airing,
) -> None:
    assert weather.house_airing(rooms, humidity, after) is advice


DRYING = [(70, 3.0, 55), (66, 0.0, 66)]
SHARING = [(66, 0.1, 66), (67, -0.2, 67)]


@pytest.mark.parametrize(
    ("rooms", "windows_open", "damper", "advice"),
    [
        # The windows look open and the air is turning damper: close them, even with a room
        # that airing would still dry.
        (DRYING, True, True, Airing.CLOSE),
        (SHARING, True, True, Airing.CLOSE),
        # Open, and not getting damper: a room still drying says keep airing...
        (DRYING, True, False, Airing.OPEN),
        # ...and rooms that already hold the outdoor air say the windows are open.
        (SHARING, True, False, Airing.AIRED),
        # Damper air means nothing with the windows closed.
        (SHARING, False, True, Airing.NO_NEED),
        (DRYING, False, True, Airing.OPEN),
    ],
)
def test_house_airing_with_the_windows_open(
    rooms: list[tuple[float, float, float | None]], windows_open: bool, damper: bool, advice: Airing
) -> None:
    got = weather.house_airing(rooms, 66, 66, windows_open=windows_open, damper=damper)
    assert got is advice


@pytest.mark.parametrize(
    ("share", "expected"), [(None, False), (0.0, False), (0.74, False), (0.75, True), (1.0, True)]
)
def test_windows_open(share: float | None, expected: bool) -> None:
    assert weather.windows_open(share) is expected


@pytest.mark.parametrize(
    ("dewpoint_rise", "humidity_rise", "expected"),
    [
        (None, None, False),
        (0.69, 3.9, False),
        (0.7, None, True),
        (None, 4.0, True),
        (-2.0, 4.0, True),
        (1.0, -1.0, True),
    ],
)
def test_damper(dewpoint_rise: float | None, humidity_rise: float | None, expected: bool) -> None:
    assert weather.damper(dewpoint_rise, humidity_rise) is expected


@pytest.mark.parametrize(
    ("temp", "humidity", "lowest", "flags"),
    [
        (21, 50, 45, []),
        (7.9, 50, 45, ["cold"]),
        (32.1, 50, 45, ["hot"]),
        # Damp for six hours, whatever it reads now.
        (20, 72, 70, ["damp"]),
        (20, 60, 70, ["damp"]),
        # Damp now, after a shower: it has not stayed so.
        (20, 90, 62, []),
        (20, 90, None, []),
        (20, 30, 28, ["dry"]),
        (5, 80, 75, ["cold", "damp"]),
        (None, None, None, []),
    ],
)
def test_room_flags(
    temp: float | None, humidity: float | None, lowest: float | None, flags: list[str]
) -> None:
    assert weather.room_flags(temp, humidity, lowest) == flags


def test_the_notices_share_the_alert_rules_thresholds() -> None:
    rules = {
        rule["title"]: rule
        for group in json.loads((REPO / "grafana/alerts.json").read_text())["groups"]
        for rule in group["rules"]
    }

    def threshold(title: str) -> float:
        (condition,) = [d for d in rules[title]["data"] if d["refId"] == "C"]
        return condition["model"]["conditions"][0]["evaluator"]["params"][0]

    assert threshold("Strong wind") == weather.STRONG_GUST_KMH
    assert threshold("Heavy rain") == weather.HEAVY_RAIN_MM_H
    assert threshold("Pressure falling fast") == weather.FAST_FALL_HPA
    assert threshold("Room too cold") == weather.ROOM_COLD_C
    assert threshold("Room too hot") == weather.ROOM_HOT_C
    # The rule compares whole percents with "above 69.5".
    assert threshold("Damp room") == weather.ROOM_DAMP_PCT - 0.5
    damp = next(d for d in rules["Damp room"]["data"] if d["refId"] == "A")["model"]["rawSql"]
    assert f"interval '{weather.DAMP_FOR_H} hours'" in damp

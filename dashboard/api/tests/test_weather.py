"""Words and judgements from readings, checked against the published tables they come from."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ecowitt.dashboard import weather
from ecowitt.dashboard.weather import Airing

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
    ("change", "words"),
    [
        (0.0, "steady"),
        (-0.09, "steady"),
        (0.1, "rising slowly"),
        (-1.5, "falling slowly"),
        (1.6, "rising"),
        (-3.5, "falling"),
        (3.6, "rising quickly"),
        (-6.0, "falling quickly"),
        (6.1, "rising very rapidly"),
    ],
)
def test_tendency(change: float, words: str) -> None:
    assert weather.tendency(change) == words


@pytest.mark.parametrize(
    ("humidity", "delta", "advice"),
    [
        (70, 2.1, Airing.OPEN),
        (65, 2.1, Airing.OPEN),
        (64.9, 5, Airing.NO_NEED),
        (90, 2.0, Airing.NO_NEED),
        (90, 1.0, Airing.NO_NEED),
        (90, 0.9, Airing.KEEP_CLOSED),
        (65, -3, Airing.KEEP_CLOSED),
        (64.9, -3, Airing.NO_NEED),
    ],
)
def test_airing(humidity: float, delta: float, advice: Airing) -> None:
    assert weather.airing(humidity, delta) is advice


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

    assert condition("Good time to air")["expression"] == (
        f"$A > {weather.AIRING_DEWPOINT_DELTA_C:g} && $B >= {weather.AIRING_HUMIDITY_PCT:g}"
    )
    assert condition("Close the windows")["expression"] == (
        f"$A < {weather.CLOSING_DEWPOINT_DELTA_C:g} && $B >= {weather.AIRING_HUMIDITY_PCT:g}"
    )
    assert threshold("Sensor not updating") == weather.STALE_AFTER_S

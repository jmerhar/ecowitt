"""The bounds a station's difference from its weather model is judged against."""

from __future__ import annotations

import pytest

from ecowitt.collector.admin.modelcompare import Verdict, judge
from ecowitt.core.units import Units

METRIC = Units()
IMPERIAL = Units(temperature="f", pressure="inhg", wind="mph")

#: A model wind well above the calm bound, in km/h.
WINDY = 20.0


@pytest.mark.parametrize(
    ("base", "difference", "verdict"),
    [
        ("temp", 2.9, Verdict(True, "within 3 °C")),
        ("temp", -3.1, Verdict(False, "more than 3 °C off")),
        ("dewpoint", 3.0, Verdict(True, "within 3 °C")),
        ("humidity", -15.0, Verdict(True, "within 15%")),
        ("humidity", 16.0, Verdict(False, "more than 15% off")),
        ("abs", 3.5, Verdict(False, "more than 3 hPa off")),
        ("dir", -60.0, Verdict(True, "within 60°")),
        ("dir", 172.0, Verdict(False, "more than 60° off")),
        ("radiation", 400.0, Verdict(None, "not judged: it changes with every passing cloud")),
        ("uv_index", 3.0, Verdict(None, "not judged: it changes with every passing cloud")),
    ],
)
def test_each_quantity_has_its_bound(base: str, difference: float, verdict: Verdict) -> None:
    assert judge(base, 0.0, 0.0, difference, WINDY, METRIC) == verdict


@pytest.mark.parametrize(
    ("station", "model", "verdict"),
    [
        (10.0, 20.0, Verdict(True, "a third to twice the model's")),
        (6.0, 20.0, Verdict(False, "under a third of the model's: sheltered?")),
        (41.0, 20.0, Verdict(False, "over twice the model's")),
    ],
)
def test_wind_is_judged_as_a_share_of_the_models(
    station: float, model: float, verdict: Verdict
) -> None:
    assert judge("speed", station, model, station - model, model, METRIC) == verdict
    assert judge("gust", station, model, station - model, model, METRIC) == verdict


@pytest.mark.parametrize("base", ["speed", "gust", "dir"])
def test_wind_is_not_judged_when_the_model_is_nearly_calm(base: str) -> None:
    """3 m/s is 10.8 km/h: below it a vane wanders and any speed is plausible."""
    calm = Verdict(None, "too little wind in the model to judge")

    assert judge(base, 0.0, 10.0, 170.0, 10.7, METRIC) == calm
    assert judge(base, 0.0, 10.0, 170.0, None, METRIC) == calm
    assert judge(base, 5.0, 10.9, 170.0, 10.9, METRIC).ok is not None


def test_a_station_reading_no_wind_at_all_is_sheltered() -> None:
    assert judge("speed", 0.0, 0.0, 0.0, WINDY, METRIC).ok is False


def test_bounds_are_given_in_the_stored_units() -> None:
    assert judge("temp", 0.0, 0.0, 5.0, None, IMPERIAL) == Verdict(True, "within 5.4 °F")
    assert judge("temp", 0.0, 0.0, 5.5, None, IMPERIAL) == Verdict(False, "more than 5.4 °F off")
    assert judge("abs", 0.0, 0.0, 0.1, None, IMPERIAL) == Verdict(
        False, "more than 0.0886 inHg off"
    )
    # 3 m/s is 6.7 mph, so a 7 mph model wind is judged.
    assert judge("dir", 0.0, 0.0, 10.0, 7.0, IMPERIAL).ok is True
    assert judge("dir", 0.0, 0.0, 10.0, 6.0, IMPERIAL).ok is None

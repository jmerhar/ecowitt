"""Unit conversions and the operator's unit preferences."""

from __future__ import annotations

import pytest

from ecowitt.core.units import (
    CONVERTIBLE,
    FIXED_SUFFIX,
    Kind,
    Units,
    UnknownUnit,
    from_canonical,
    to_canonical,
)


@pytest.mark.parametrize(
    ("kind", "unit", "raw", "canonical"),
    [
        (Kind.TEMPERATURE, "f", 32.0, 0.0),
        (Kind.TEMPERATURE, "f", 212.0, 100.0),
        (Kind.TEMPERATURE, "f", -40.0, -40.0),
        (Kind.TEMPERATURE, "c", 21.5, 21.5),
        (Kind.PRESSURE, "inhg", 29.92126, 1013.25),
        (Kind.PRESSURE, "inhg", 1.0, 33.8639),
        (Kind.PRESSURE, "hpa", 1009.0, 1009.0),
        (Kind.RAIN, "in", 1.0, 25.4),
        (Kind.RAIN, "mm", 3.2, 3.2),
        (Kind.RAIN_RATE, "in", 0.5, 12.7),
        (Kind.RAIN_RATE, "mm", 4.0, 4.0),
        (Kind.SPEED, "mph", 10.0, 4.4704),
        (Kind.SPEED, "kmh", 36.0, 10.0),
        (Kind.SPEED, "ms", 5.0, 5.0),
        (Kind.DISTANCE, "mi", 1.0, 1.609344),
        (Kind.DISTANCE, "km", 7.0, 7.0),
        (Kind.HUMIDITY, None, 55.0, 55.0),
    ],
)
def test_to_canonical(kind: Kind, unit: str | None, raw: float, canonical: float) -> None:
    """Station units convert to °C, hPa, mm, mm/h, m/s and km by their defining constants."""
    assert to_canonical(kind, unit, raw) == pytest.approx(canonical, abs=1e-3)


@pytest.mark.parametrize(
    ("kind", "unit"),
    [(Kind.TEMPERATURE, "k"), (Kind.PRESSURE, None), (Kind.HUMIDITY, "pct"), (Kind.SPEED, "kn")],
)
def test_an_undeclared_source_unit_is_refused(kind: Kind, unit: str | None) -> None:
    """A field table entry naming a unit its kind cannot convert from fails loudly."""
    with pytest.raises(UnknownUnit):
        to_canonical(kind, unit, 1.0)


@pytest.mark.parametrize(
    ("kind", "units", "canonical", "expected", "suffix"),
    [
        (Kind.TEMPERATURE, Units(), 20.0, 20.0, "c"),
        (Kind.TEMPERATURE, Units(temperature="f"), 20.0, 68.0, "f"),
        (Kind.PRESSURE, Units(), 1013.25, 1013.25, "hpa"),
        (Kind.PRESSURE, Units(pressure="inhg"), 1013.25, 29.9213, "inhg"),
        (Kind.PRESSURE, Units(pressure="mmhg"), 1013.25, 760.0, "mmhg"),
        (Kind.RAIN, Units(), 25.4, 25.4, "mm"),
        (Kind.RAIN, Units(rain="in"), 25.4, 1.0, "in"),
        (Kind.RAIN_RATE, Units(), 2.0, 2.0, "mm_h"),
        (Kind.RAIN_RATE, Units(rain="in"), 25.4, 1.0, "in_h"),
        (Kind.SPEED, Units(), 10.0, 36.0, "kmh"),
        (Kind.SPEED, Units(wind="ms"), 10.0, 10.0, "ms"),
        (Kind.SPEED, Units(wind="mph"), 4.4704, 10.0, "mph"),
        (Kind.SPEED, Units(wind="kn"), 1852 / 3600, 1.0, "kn"),
        (Kind.DISTANCE, Units(), 5.0, 5.0, "km"),
        (Kind.DISTANCE, Units(distance="mi"), 1.609344, 1.0, "mi"),
    ],
)
def test_from_canonical(
    kind: Kind, units: Units, canonical: float, expected: float, suffix: str
) -> None:
    """Each preference produces its unit, and names it in the suffix."""
    value, got_suffix = from_canonical(kind, canonical, units)

    assert value == pytest.approx(expected, abs=1e-3)
    assert got_suffix == suffix


def test_a_temperature_difference_converts_without_the_offset() -> None:
    """A 10 °C difference is an 18 °F difference, not 50 °F."""
    assert from_canonical(Kind.TEMPERATURE_DELTA, 10.0, Units()) == (10.0, "c")
    assert from_canonical(Kind.TEMPERATURE_DELTA, 10.0, Units(temperature="f")) == (18.0, "f")


@pytest.mark.parametrize("kind", sorted(FIXED_SUFFIX, key=lambda k: k.value))
def test_fixed_unit_kinds_keep_value_and_take_their_suffix(kind: Kind) -> None:
    """Preferences never touch a fixed-unit kind."""
    assert from_canonical(kind, 42.0, Units(temperature="f", wind="mph")) == (
        42.0,
        FIXED_SUFFIX[kind],
    )


@pytest.mark.parametrize("kind", [Kind.COUNT, Kind.LEVEL, Kind.UV_INDEX])
def test_unitless_kinds_have_no_suffix(kind: Kind) -> None:
    """A count or an index has no unit to name."""
    assert from_canonical(kind, 3.0, Units()) == (3.0, "")


def test_every_kind_is_either_convertible_fixed_or_unitless() -> None:
    """No kind is in both sets, so its suffix is never ambiguous."""
    assert not CONVERTIBLE & set(FIXED_SUFFIX)


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": "k"},
        {"pressure": "bar"},
        {"rain": "cm"},
        {"wind": "fps"},
        {"distance": "nm"},
    ],
)
def test_an_unknown_preference_is_refused_with_the_choices(bad: dict[str, str]) -> None:
    """A typo in the configuration file fails at load time and lists what is allowed."""
    with pytest.raises(ValueError, match="is not one of"):
        Units(**bad)  # type: ignore[arg-type]


def test_the_defaults_are_european() -> None:
    """Celsius, hectopascals, millimetres, kilometres per hour, kilometres."""
    assert Units() == Units(temperature="c", pressure="hpa", rain="mm", wind="kmh", distance="km")

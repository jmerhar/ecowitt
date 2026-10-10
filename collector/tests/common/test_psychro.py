"""Psychrometric formulas against published reference values.

The expected values come from standard tables, not from this implementation: WMO saturation
vapour pressures over water, the usual dew-point and absolute-humidity tables, and the
international standard atmosphere. Tolerances reflect the Magnus approximation's stated
accuracy, about 0.4% against Goff-Gratch over -40..50 °C.
"""

from __future__ import annotations

import pytest

from ecowitt.collector import psychro


@pytest.mark.parametrize(
    ("temp", "hpa"),
    # WMO (Goff-Gratch) saturation vapour pressure over water.
    [(-10.0, 2.865), (0.0, 6.112), (10.0, 12.28), (20.0, 23.39), (30.0, 42.46), (40.0, 73.84)],
)
def test_saturation_vapour_pressure(temp: float, hpa: float) -> None:
    """Within the Magnus formula's 0.4% of the reference."""
    assert psychro.saturation_vapour_pressure(temp) == pytest.approx(hpa, rel=0.004)


@pytest.mark.parametrize(
    ("temp", "humidity", "dew"),
    [
        (20.0, 50.0, 9.3),
        (30.0, 80.0, 26.2),
        (25.0, 60.0, 16.7),
        (10.0, 90.0, 8.4),
        (0.0, 100.0, 0.0),
    ],
)
def test_dew_point(temp: float, humidity: float, dew: float) -> None:
    """Dew points from standard tables, to the tenth of a degree they are published to."""
    assert psychro.dew_point(temp, humidity) == pytest.approx(dew, abs=0.1)


def test_saturated_air_is_at_its_dew_point() -> None:
    """At 100% the dew point is the air temperature itself."""
    for temp in (-15.0, 0.0, 12.3, 35.0):
        assert psychro.dew_point(temp, 100.0) == pytest.approx(temp, abs=1e-9)


@pytest.mark.parametrize(
    ("temp", "grams"),
    # Saturated absolute humidity, g/m³.
    [(0.0, 4.85), (10.0, 9.40), (20.0, 17.3), (30.0, 30.4)],
)
def test_absolute_humidity_of_saturated_air(temp: float, grams: float) -> None:
    """Within 1% of the tabulated saturated vapour density."""
    assert psychro.absolute_humidity(temp, 100.0) == pytest.approx(grams, rel=0.01)


def test_mixing_ratio_of_saturated_air_at_standard_pressure() -> None:
    """14.7 g/kg at 20 °C and 1013.25 hPa."""
    assert psychro.mixing_ratio(20.0, 100.0, 1013.25) == pytest.approx(14.7, abs=0.15)


def test_vapour_pressure_deficit() -> None:
    """1.58 kPa at 25 °C and 50%, the textbook horticultural example."""
    assert psychro.vapour_pressure_deficit(25.0, 50.0) == pytest.approx(15.8, abs=0.1)


def test_saturated_air_has_no_deficit() -> None:
    """At 100% the air cannot take more water."""
    assert psychro.vapour_pressure_deficit(18.0, 100.0) == pytest.approx(0.0, abs=1e-12)


def test_humidity_at_its_own_temperature_is_unchanged() -> None:
    """Vapour pressure and humidity are inverses at one temperature."""
    e = psychro.vapour_pressure(21.0, 47.0)

    assert psychro.humidity_at(e, 21.0) == pytest.approx(47.0, abs=1e-9)


def test_cool_damp_air_warmed_indoors_is_dry() -> None:
    """Outdoor air at 5 °C and 90%, warmed to 21 °C, settles at 31.6%.

    The expected value is worked from the WMO table rather than from this module:
    0.90 × 8.72 hPa / 24.87 hPa. It is the reason winter ventilation dries a house -- the same
    water spread through warmer air is a far smaller fraction of what that air could hold.
    """
    e = psychro.vapour_pressure(5.0, 90.0)

    assert psychro.humidity_at(e, 21.0) == pytest.approx(0.90 * 8.72 / 24.87 * 100, abs=0.3)


def test_humidity_never_exceeds_saturation() -> None:
    """Warm damp air brought into a cold room condenses rather than reading over 100%."""
    e = psychro.vapour_pressure(25.0, 90.0)

    assert psychro.humidity_at(e, 10.0) == 100.0


@pytest.mark.parametrize("altitude", [0.0, 180.0, 500.0, 1500.0])
def test_standard_atmosphere_reduces_to_standard_sea_level(altitude: float) -> None:
    """The ISA's own pressure and temperature at an altitude reduce to 1013.25 hPa.

    The station pressure is computed with the ISA's formula and its more precise exponent, not
    with the function under test, so this checks the reduction against an independent model.
    """
    station = 1013.25 * (1 - 2.25577e-5 * altitude) ** 5.25588
    temp = psychro.standard_temperature(altitude)

    assert psychro.sea_level_pressure(station, altitude, temp) == pytest.approx(1013.25, abs=0.1)


def test_reduction_depends_on_temperature_by_about_a_tenth_per_degree() -> None:
    """At 250 m the result moves about 0.1 hPa per degree, so a year's range is several hPa.

    Why the reduction needs the real outdoor temperature, and why a constant console offset
    can only ever be right at one temperature.
    """
    cold = psychro.sea_level_pressure(985.0, 250.0, -5.0)
    hot = psychro.sea_level_pressure(985.0, 250.0, 35.0)

    assert (cold - hot) / 40 == pytest.approx(0.1, abs=0.02)
    assert cold > hot  # cold air is denser, so the column below weighs more

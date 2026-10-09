"""Psychrometric and barometric formulas, in canonical units (°C, %, hPa, m).

Pure functions with no knowledge of reports, so each can be checked against published
reference values on its own.
"""

from __future__ import annotations

import math

# Magnus coefficients over water from Alduchov & Eskridge (1996), accurate to within 0.4% of
# the Goff-Gratch reference between -40 °C and 50 °C -- the range a weather station lives in.
MAGNUS_A = 6.1094
MAGNUS_B = 17.625
MAGNUS_C = 243.04

#: Specific gas constant of water vapour, J/(kg·K).
R_VAPOUR = 461.5
#: Ratio of the molar masses of water and dry air, times 1000 for grams per kilogram.
EPSILON_G_PER_KG = 621.97
ZERO_CELSIUS_K = 273.15

#: Temperature lapse rate of the international standard atmosphere, K/m.
LAPSE_RATE = 0.0065
#: Exponent g·M/(R·L) of the barometric formula for that lapse rate.
BAROMETRIC_EXPONENT = 5.257


def saturation_vapour_pressure(temp_c: float) -> float:
    """Vapour pressure of saturated air at `temp_c`, in hPa."""
    return MAGNUS_A * math.exp(MAGNUS_B * temp_c / (temp_c + MAGNUS_C))


def vapour_pressure(temp_c: float, humidity_pct: float) -> float:
    """Partial pressure of the water vapour actually present, in hPa."""
    return humidity_pct / 100 * saturation_vapour_pressure(temp_c)


def dew_point(temp_c: float, humidity_pct: float) -> float:
    """Temperature to which air must cool for its vapour to condense, in °C.

    The quantity that decides whether ventilating dries a room: outdoor air only takes moisture
    out if its dew point is below the indoor one. Relative humidity cannot answer that, because
    it depends on temperature as much as on how much water the air holds.
    """
    gamma = math.log(humidity_pct / 100) + MAGNUS_B * temp_c / (temp_c + MAGNUS_C)
    return MAGNUS_C * gamma / (MAGNUS_B - gamma)


def absolute_humidity(temp_c: float, humidity_pct: float) -> float:
    """Mass of water vapour per volume of air, in g/m³."""
    pascals = vapour_pressure(temp_c, humidity_pct) * 100
    return pascals / (R_VAPOUR * (temp_c + ZERO_CELSIUS_K)) * 1000


def mixing_ratio(temp_c: float, humidity_pct: float, pressure_hpa: float) -> float:
    """Mass of water vapour per mass of dry air, in g/kg.

    Unlike absolute humidity this does not change as air warms or expands, which makes it the
    measure to compare between a room and the outside.
    """
    e = vapour_pressure(temp_c, humidity_pct)
    return EPSILON_G_PER_KG * e / (pressure_hpa - e)


def vapour_pressure_deficit(temp_c: float, humidity_pct: float) -> float:
    """How far the air is from saturation, in hPa: the drying power of the air."""
    return saturation_vapour_pressure(temp_c) - vapour_pressure(temp_c, humidity_pct)


def humidity_at(vapour_pressure_hpa: float, temp_c: float) -> float:
    """Relative humidity that air holding this much vapour would have at `temp_c`, in %.

    Capped at 100: beyond it the excess condenses rather than raising the humidity.
    """
    return min(100.0, vapour_pressure_hpa / saturation_vapour_pressure(temp_c) * 100)


def sea_level_pressure(station_hpa: float, altitude_m: float, temp_c: float) -> float:
    """Reduce a station pressure to sea level, in hPa.

    The barometric formula with the standard lapse rate, taking the column of air below the
    station to be as warm at its base as the standard atmosphere would make it given `temp_c`
    at the top. A console's relative-pressure offset approximates this with a constant, which
    is exact only at one temperature: the result moves by about 0.1 hPa per degree at 250 m.
    """
    lapse = LAPSE_RATE * altitude_m
    return station_hpa * (1 - lapse / (temp_c + lapse + ZERO_CELSIUS_K)) ** -BAROMETRIC_EXPONENT


def standard_temperature(altitude_m: float) -> float:
    """Temperature of the international standard atmosphere at `altitude_m`, in °C."""
    return 15.0 - LAPSE_RATE * altitude_m

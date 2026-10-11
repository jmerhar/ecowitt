"""How far a station's readings may sit from its weather model's before they are worth a look.

A model's value describes a grid cell kilometres wide, at that cell's height and exposure; a
station's describes one point, often in the lee of a building. Some difference is normal, so
each quantity has a bound beyond which the difference says more about the sensor or its siting
than about the model. The comparison is of the station's latest report with the model's latest
quarter, so a passing shower or squall can cross a bound for a while; one that stays crossed is
what deserves attention.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecowitt.collector.admin.calibration import REFERENCE_THRESHOLD_HPA
from ecowitt.core.units import Kind, Units, from_canonical

#: Temperature and dew point: a model's 2 m temperature is commonly 1-2 °C from a well-sited
#: thermometer, more on a coast or slope, so 3 °C is past that.
TEMPERATURE_C = 3.0
#: Relative humidity, in percentage points, for the same reasons.
HUMIDITY_PCT = 15.0
#: Wind is judged only when the model has some: below this, speed and direction are noise.
WIND_JUDGED_FROM_MS = 3.0
#: An anemometer on a house commonly reads half the model's 10 m wind; under a third means it is
#: sheltered, over twice that something is wrong with it.
WIND_RATIO_LOW = 1 / 3
WIND_RATIO_HIGH = 2.0
#: Direction: more than this from the model's, beyond what a building's eddies explain.
DIRECTION_DEG = 60.0


@dataclass(frozen=True)
class Verdict:
    """Whether a difference is within its bound (None when it is not judged), and why."""

    ok: bool | None
    note: str


def judge(
    base: str,
    station: float,
    model: float,
    difference: float,
    model_speed: float | None,
    units: Units,
) -> Verdict:
    """Judge one quantity's station-minus-model `difference`, all in the stored `units`.

    `difference` is given rather than recomputed because directions arrive already wrapped to
    ±180°. `model_speed` is the model's wind speed, which decides whether wind is judged at all.
    """
    match base:
        case "temp" | "dewpoint":
            return _within(abs(difference), Kind.TEMPERATURE_DELTA, TEMPERATURE_C, units)
        case "humidity":
            return _within(abs(difference), Kind.HUMIDITY, HUMIDITY_PCT, units)
        case "abs":
            return _within(abs(difference), Kind.PRESSURE, REFERENCE_THRESHOLD_HPA, units)
        case "speed" | "gust" | "dir":
            calm = from_canonical(Kind.SPEED, WIND_JUDGED_FROM_MS, units)[0]
            if model_speed is None or model_speed < calm:
                return Verdict(None, "too little wind in the model to judge")
            if base == "dir":
                return _within(abs(difference), Kind.ANGLE, DIRECTION_DEG, units)
            ratio = station / model if model else 0.0
            if ratio < WIND_RATIO_LOW:
                return Verdict(False, "under a third of the model's: sheltered?")
            if ratio > WIND_RATIO_HIGH:
                return Verdict(False, "over twice the model's")
            return Verdict(True, "a third to twice the model's")
    return Verdict(None, "not judged: it changes with every passing cloud")


def _within(size: float, kind: Kind, bound: float, units: Units) -> Verdict:
    """Whether `size` is within `bound` (canonical), said in the stored unit."""
    limit, suffix = from_canonical(kind, bound, units)
    text = f"{limit:.3g}{_SYMBOLS.get(suffix, ' ' + suffix)}"
    if size <= limit:
        return Verdict(True, f"within {text}")
    return Verdict(False, f"more than {text} off")


_SYMBOLS = {
    "c": " °C",
    "f": " °F",
    "pct": "%",
    "deg": "°",
    "hpa": " hPa",
    "inhg": " inHg",
    "mmhg": " mmHg",
}

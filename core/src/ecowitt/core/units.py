"""Physical quantities, the units they arrive in, and the units they are stored in.

Every numeric reading is converted to one canonical unit per quantity as soon as it is parsed,
so derived quantities are computed from values in a single, known unit whatever the station
sent. It is converted again, to the unit the operator keeps, only when it is written -- and
that unit becomes part of the field's name (`temp_c`, `speed_kmh`), so a change of preference
starts new fields rather than mixing two units into one series.

Canonical units: °C, hPa, mm, mm/h, m/s, km.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, get_args

#: hPa per inch of mercury, at 0 °C and standard gravity.
HPA_PER_INHG = 33.8638866667
#: hPa per millimetre of mercury.
HPA_PER_MMHG = 1.33322387415
MM_PER_INCH = 25.4
MS_PER_MPH = 0.44704
MS_PER_KNOT = 1852 / 3600
KM_PER_MILE = 1.609344


class Kind(Enum):
    """What a reading measures, which decides how it converts and what its field is called."""

    # Converted to the operator's preferred unit when written.
    TEMPERATURE = "temperature"
    #: A difference between two temperatures. Converts by scale alone: a 1 °C difference is a
    #: 1.8 °F difference, with none of the 32-degree offset an absolute temperature carries.
    TEMPERATURE_DELTA = "temperature_delta"
    PRESSURE = "pressure"
    RAIN = "rain"
    RAIN_RATE = "rain_rate"
    SPEED = "speed"
    DISTANCE = "distance"

    # Stored in the one unit everyone uses for them.
    HUMIDITY = "humidity"
    PERCENT = "percent"
    ANGLE = "angle"
    IRRADIANCE = "irradiance"
    ILLUMINANCE = "illuminance"
    UV_INDEX = "uv_index"
    PARTICULATE = "particulate"
    CO2 = "co2"
    ABSOLUTE_HUMIDITY = "absolute_humidity"
    MIXING_RATIO = "mixing_ratio"
    VOLTAGE = "voltage"
    DURATION = "duration"
    BYTES = "bytes"
    LENGTH = "length"
    CONDUCTIVITY = "conductivity"
    UNIX_TIME = "unix_time"

    # No unit at all.
    COUNT = "count"
    LEVEL = "level"
    FLAG = "flag"
    TEXT = "text"


#: The suffix each fixed-unit kind carries in its field name. Kinds absent from this and from
#: the convertible set have no unit and no suffix.
FIXED_SUFFIX: dict[Kind, str] = {
    Kind.HUMIDITY: "pct",
    Kind.PERCENT: "pct",
    Kind.ANGLE: "deg",
    Kind.IRRADIANCE: "wm2",
    Kind.ILLUMINANCE: "lux",
    Kind.PARTICULATE: "ugm3",
    Kind.CO2: "ppm",
    Kind.ABSOLUTE_HUMIDITY: "gm3",
    Kind.MIXING_RATIO: "gkg",
    Kind.VOLTAGE: "v",
    Kind.DURATION: "s",
    Kind.BYTES: "bytes",
    Kind.LENGTH: "mm",
    Kind.CONDUCTIVITY: "uscm",
    Kind.UNIX_TIME: "unix",
}

TemperatureUnit = Literal["c", "f"]
PressureUnit = Literal["hpa", "inhg", "mmhg"]
RainUnit = Literal["mm", "in"]
WindUnit = Literal["kmh", "ms", "mph", "kn"]
DistanceUnit = Literal["km", "mi"]


@dataclass(frozen=True)
class Units:
    """The units the operator keeps, one per convertible quantity.

    The defaults are what most of Europe reads: Celsius, hectopascals, millimetres, kilometres
    per hour and kilometres. Rain rate follows the rain unit, per hour.
    """

    temperature: TemperatureUnit = "c"
    pressure: PressureUnit = "hpa"
    rain: RainUnit = "mm"
    wind: WindUnit = "kmh"
    distance: DistanceUnit = "km"

    def __post_init__(self) -> None:
        """Reject a unit this module cannot produce, naming the choices.

        These values come from a hand-editable file, so a typo has to fail at load time with
        the valid spellings in the message, rather than as a KeyError on the first report.
        """
        for name, allowed in (
            ("temperature", TemperatureUnit),
            ("pressure", PressureUnit),
            ("rain", RainUnit),
            ("wind", WindUnit),
            ("distance", DistanceUnit),
        ):
            value = getattr(self, name)
            choices = get_args(allowed)
            if value not in choices:
                raise ValueError(f"{name} unit {value!r} is not one of {', '.join(choices)}")


class UnknownUnit(ValueError):
    """Raised when a field table entry names a source unit its kind cannot convert from."""


def to_canonical(kind: Kind, unit: str | None, value: float) -> float:
    """Convert a value as the station sent it into this module's canonical unit."""
    match kind, unit:
        case Kind.TEMPERATURE, "f":
            return (value - 32) * 5 / 9
        case Kind.PRESSURE, "inhg":
            return value * HPA_PER_INHG
        case (Kind.RAIN, "in") | (Kind.RAIN_RATE, "in"):
            return value * MM_PER_INCH
        case Kind.SPEED, "mph":
            return value * MS_PER_MPH
        case Kind.SPEED, "kmh":
            return value / 3.6
        case Kind.DISTANCE, "mi":
            return value * KM_PER_MILE
        case (
            (Kind.TEMPERATURE, "c")
            | (Kind.PRESSURE, "hpa")
            | (Kind.RAIN, "mm")
            | (Kind.RAIN_RATE, "mm")
            | (Kind.SPEED, "ms")
            | (Kind.DISTANCE, "km")
        ):
            return value
        case _ if kind not in CONVERTIBLE and unit is None:
            return value
    raise UnknownUnit(f"cannot convert {kind.value} from {unit!r}")


def from_canonical(kind: Kind, value: float, units: Units) -> tuple[float, str]:
    """Convert a canonical value to the operator's unit, returning it with its field suffix.

    The suffix is empty for kinds that have no unit.
    """
    match kind:
        case Kind.TEMPERATURE:
            if units.temperature == "f":
                return value * 9 / 5 + 32, "f"
            return value, "c"
        case Kind.TEMPERATURE_DELTA:
            if units.temperature == "f":
                return value * 9 / 5, "f"
            return value, "c"
        case Kind.PRESSURE:
            if units.pressure == "inhg":
                return value / HPA_PER_INHG, "inhg"
            if units.pressure == "mmhg":
                return value / HPA_PER_MMHG, "mmhg"
            return value, "hpa"
        case Kind.RAIN:
            if units.rain == "in":
                return value / MM_PER_INCH, "in"
            return value, "mm"
        case Kind.RAIN_RATE:
            if units.rain == "in":
                return value / MM_PER_INCH, "in_h"
            return value, "mm_h"
        case Kind.SPEED:
            if units.wind == "ms":
                return value, "ms"
            if units.wind == "mph":
                return value / MS_PER_MPH, "mph"
            if units.wind == "kn":
                return value / MS_PER_KNOT, "kn"
            return value * 3.6, "kmh"
        case Kind.DISTANCE:
            if units.distance == "mi":
                return value / KM_PER_MILE, "mi"
            return value, "km"
    return value, FIXED_SUFFIX.get(kind, "")


#: Kinds whose stored unit depends on the operator's preferences.
CONVERTIBLE = frozenset(
    {
        Kind.TEMPERATURE,
        Kind.TEMPERATURE_DELTA,
        Kind.PRESSURE,
        Kind.RAIN,
        Kind.RAIN_RATE,
        Kind.SPEED,
        Kind.DISTANCE,
    }
)

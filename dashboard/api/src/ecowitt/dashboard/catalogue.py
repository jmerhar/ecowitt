"""The metrics the API serves: where each is stored, what it measures, and how it summarises.

A metric names a reading's base field (`temp`), not its stored name: the stored name carries the
unit the station keeps (`temp_c`, `temp_f`), which comes from its published settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import get_args

from ecowitt.core.store.query import Aggregate
from ecowitt.core.units import (
    DistanceUnit,
    Kind,
    PressureUnit,
    RainUnit,
    TemperatureUnit,
    Units,
    WindUnit,
    field_name,
    from_canonical,
)

#: The quantity whose unit preference converts each kind.
QUANTITIES: dict[Kind, str] = {
    Kind.TEMPERATURE: "temperature",
    Kind.TEMPERATURE_DELTA: "temperature",
    Kind.PRESSURE: "pressure",
    Kind.RAIN: "rain",
    Kind.RAIN_RATE: "rain",
    Kind.SPEED: "wind",
    Kind.DISTANCE: "distance",
}

#: The units each quantity can be asked for in.
CHOICES: dict[str, tuple[str, ...]] = {
    "temperature": get_args(TemperatureUnit),
    "pressure": get_args(PressureUnit),
    "rain": get_args(RainUnit),
    "wind": get_args(WindUnit),
    "distance": get_args(DistanceUnit),
}

#: Rooms are the console's own indoor sensor and its numbered channels.
ROOM_SENSOR = re.compile(r"indoor|ch\d+")


class Scope(Enum):
    """Which of a table's sensors a metric covers."""

    #: The table has no sensors (wind, pressure), or every group counts (rain gauges).
    ALL = "all"
    #: The outdoor sensor alone.
    OUTDOOR = "outdoor"
    #: Each room.
    ROOMS = "rooms"


class Sides(Enum):
    """Which extremes of a metric mean something."""

    NONE = "none"
    MAX = "max"
    BOTH = "both"


@dataclass(frozen=True)
class Metric:
    """One quantity a visitor can chart."""

    id: str
    label: str
    tables: tuple[str, ...]
    base: str
    kind: Kind
    #: How its values summarise into a chart's buckets; the first is the main line.
    aggregates: tuple[Aggregate, ...]
    scope: Scope = Scope.ALL
    extremes: Sides = Sides.BOTH

    def field(self, units: Units) -> str:
        """The stored field in a station's units."""
        return field_name(self.base, self.kind, units)

    @property
    def quantity(self) -> str | None:
        """The unit preference that converts it, or None if it has one fixed unit."""
        return QUANTITIES.get(self.kind)

    @property
    def per_sensor(self) -> bool:
        """Whether it comes as one series per room rather than one for the station."""
        return self.scope is Scope.ROOMS

    def sensors(self) -> list[str] | None:
        """The sensors to ask the store for, or None for all of them."""
        return ["outdoor"] if self.scope is Scope.OUTDOOR else None

    def covers(self, sensor: str | None) -> bool:
        """Whether a group's sensor belongs to this metric."""
        if self.scope is Scope.ROOMS:
            return sensor is not None and ROOM_SENSOR.fullmatch(sensor) is not None
        if self.scope is Scope.OUTDOOR:
            return sensor == "outdoor"
        return True


_RANGE = (Aggregate.MEAN, Aggregate.MIN, Aggregate.MAX)
_ROOMS = ("indoor", "channel")
_OUT = ("outdoor",)
_DERIVED = ("derived",)
T, H = Kind.TEMPERATURE, Kind.HUMIDITY

METRICS: dict[str, Metric] = {
    metric.id: metric
    for metric in (
        Metric("outdoor.temperature", "Temperature", _OUT, "temp", T, _RANGE, Scope.OUTDOOR),
        Metric("outdoor.humidity", "Humidity", _OUT, "humidity", H, _RANGE, Scope.OUTDOOR),
        Metric("outdoor.dew_point", "Dew point", _DERIVED, "dewpoint", T, _RANGE, Scope.OUTDOOR),
        Metric(
            "wind.speed", "Wind speed", ("wind",), "speed", Kind.SPEED,
            (Aggregate.MEAN, Aggregate.MAX), extremes=Sides.MAX,
        ),
        Metric(
            "wind.gust", "Wind gust", ("wind",), "gust", Kind.SPEED, (Aggregate.MAX,),
            extremes=Sides.MAX,
        ),
        Metric(
            "wind.direction", "Wind direction", ("wind",), "dir", Kind.ANGLE,
            (Aggregate.CIRCULAR,), extremes=Sides.NONE,
        ),
        Metric(
            "rain.rate", "Rain rate", ("rain",), "rate", Kind.RAIN_RATE, (Aggregate.MAX,),
            extremes=Sides.MAX,
        ),
        # The console's own running total for its day, so a bucket's highest value is how much
        # had fallen by its end, and a day's is the day's rain.
        Metric(
            "rain.daily", "Rain today", ("rain",), "daily", Kind.RAIN, (Aggregate.MAX,),
            extremes=Sides.MAX,
        ),
        Metric("pressure.sea_level", "Pressure", ("pressure",), "sea", Kind.PRESSURE, _RANGE),
        Metric(
            "pressure.absolute", "Station pressure", ("pressure",), "abs", Kind.PRESSURE, _RANGE
        ),
        Metric(
            "solar.radiation", "Solar radiation", ("solar",), "radiation", Kind.IRRADIANCE,
            (Aggregate.MEAN, Aggregate.MAX), extremes=Sides.MAX,
        ),
        Metric(
            "solar.uv_index", "UV index", ("solar",), "uv_index", Kind.UV_INDEX, (Aggregate.MAX,),
            extremes=Sides.MAX,
        ),
        Metric("rooms.temperature", "Temperature", _ROOMS, "temp", T, _RANGE, Scope.ROOMS),
        Metric("rooms.humidity", "Humidity", _ROOMS, "humidity", H, _RANGE, Scope.ROOMS),
        Metric("rooms.dew_point", "Dew point", _DERIVED, "dewpoint", T, _RANGE, Scope.ROOMS),
        Metric(
            "rooms.airing_humidity", "Humidity after airing", ("ventilation",),
            "predicted_humidity", H, (Aggregate.MEAN,), Scope.ROOMS, Sides.NONE,
        ),
    )
}  # fmt: skip

#: Symbols for the units values are given in, by the suffix their field name carries.
SYMBOLS = {
    "c": "°C",
    "f": "°F",
    "hpa": "hPa",
    "inhg": "inHg",
    "mmhg": "mmHg",
    "mm": "mm",
    "in": "in",
    "mm_h": "mm/h",
    "in_h": "in/h",
    "kmh": "km/h",
    "ms": "m/s",
    "mph": "mph",
    "kn": "kn",
    "km": "km",
    "mi": "mi",
    "pct": "%",
    "deg": "°",
    "wm2": "W/m²",
    "": "",
}

#: Decimal places worth showing, by unit suffix; anything finer is noise from conversion.
DECIMALS = {"inhg": 2, "in": 2, "in_h": 2, "pct": 0, "deg": 0, "wm2": 0, "": 0}


def unit(kind: Kind, units: Units) -> str:
    """The unit suffix a value of `kind` is given in, empty for a unitless one."""
    return from_canonical(kind, 0.0, units)[1]


def rounded(value: float, suffix: str) -> float:
    """A value rounded to what its unit is worth showing."""
    return round(value, DECIMALS.get(suffix, 1))

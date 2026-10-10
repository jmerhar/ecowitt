"""The intermediate form between a station's report and the points written to InfluxDB."""

from __future__ import annotations

from dataclasses import dataclass, field

from .units import Kind

Value = float | bool | str


@dataclass(frozen=True)
class Reading:
    """One measured or derived value, in its quantity's canonical unit.

    `field` is the base name; the unit suffix is added when the reading is written, because
    the stored unit is a preference and not a property of the measurement.
    """

    table: str
    field: str
    kind: Kind
    value: Value
    #: Tags beyond the station and the sensor's display name, which are added when written.
    tags: tuple[tuple[str, str], ...] = ()
    #: The physical sensor this came from -- `indoor`, `outdoor`, `ch3`, `wind` -- which is
    #: what display names, derived quantities and staleness are keyed on. None for values that
    #: describe no sensor, such as the console's own uptime.
    sensor: str | None = None


@dataclass(frozen=True)
class Report:
    """Everything parsed from one upload."""

    #: Unix seconds. The station's own timestamp, unless it was missing or implausible.
    timestamp: int
    readings: list[Reading] = field(default_factory=list)

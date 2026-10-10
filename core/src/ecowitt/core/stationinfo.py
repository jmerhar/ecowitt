"""What a station's operator has configured, as the collector publishes it to the database.

The dashboard needs a station's location, time zone, stored units and sensor names, and finds
them here rather than in a second configuration. The collector writes one `station_info` row per
station when it starts and whenever the configuration changes it -- never otherwise, so an
unchanged station costs a handful of rows over its life.

Read the most recent row as a whole: a setting that was cleared is absent from the newest row,
so taking each field's latest value separately would resurrect it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields

from ecowitt.core.readings import Value
from ecowitt.core.store.base import Row
from ecowitt.core.units import Units

TABLE = "station_info"

#: Units are stored as `units_<quantity>`; sensor names as `sensor_<identifier>`.
UNITS_PREFIX = "units_"
SENSOR_PREFIX = "sensor_"


@dataclass(frozen=True)
class StationInfo:
    """One station's published settings. Holds nothing secret."""

    station: str
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    #: An IANA zone name such as `Europe/Lisbon`: where the station's day begins and ends.
    timezone: str | None = None
    units: Units = field(default_factory=Units)
    #: Display names by sensor identifier, as on the setup page.
    sensors: Mapping[str, str] = field(default_factory=dict)

    def to_row(self, timestamp: int) -> Row:
        """The `station_info` row for these settings, leaving out what is not set."""
        values: dict[str, Value] = {}
        for name, value in (
            ("latitude_deg", self.latitude),
            ("longitude_deg", self.longitude),
            ("altitude_m", self.altitude_m),
        ):
            if value is not None:
                values[name] = float(value)
        if self.timezone:
            values["timezone"] = self.timezone
        for unit in fields(Units):
            values[UNITS_PREFIX + unit.name] = getattr(self.units, unit.name)
        for sensor, name in self.sensors.items():
            values[SENSOR_PREFIX + sensor] = name
        return Row(TABLE, (("station", self.station),), timestamp, dict(sorted(values.items())))

    @classmethod
    def from_fields(cls, station: str, values: Mapping[str, Value | None]) -> StationInfo:
        """Settings from the fields of one `station_info` row; absent or null ones are unset.

        A unit this version does not know falls back to the default, so a newer collector's row
        never stops an older dashboard from showing the station.
        """
        present = {k: v for k, v in values.items() if v is not None}

        def number(name: str) -> float | None:
            value = present.get(name)
            return float(value) if isinstance(value, int | float) else None

        units = {
            unit.name: present[UNITS_PREFIX + unit.name]
            for unit in fields(Units)
            if isinstance(present.get(UNITS_PREFIX + unit.name), str)
        }
        try:
            stored_units = Units(**units)  # type: ignore[arg-type]
        except ValueError:
            stored_units = Units()
        timezone = present.get("timezone")
        return cls(
            station=station,
            latitude=number("latitude_deg"),
            longitude=number("longitude_deg"),
            altitude_m=number("altitude_m"),
            timezone=timezone if isinstance(timezone, str) and timezone else None,
            units=stored_units,
            sensors={
                k[len(SENSOR_PREFIX) :]: v
                for k, v in sorted(present.items())
                if k.startswith(SENSOR_PREFIX) and isinstance(v, str)
            },
        )

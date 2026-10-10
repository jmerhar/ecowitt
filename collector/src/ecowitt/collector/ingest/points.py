"""Group readings into the rows written to the database, in the operator's units."""

from __future__ import annotations

from collections.abc import Iterable

from ecowitt.collector.ingest.fields import NAMED_TABLES
from ecowitt.core.preferences import Preferences
from ecowitt.core.readings import Reading, Value
from ecowitt.core.store.base import Row
from ecowitt.core.units import Kind, from_canonical

#: Decimal places kept after conversion. Enough to round-trip every sensor's resolution --
#: the finest is 0.001 inHg, about 0.03 hPa -- while dropping the float noise a conversion
#: leaves behind, which would otherwise make 73.8 °F read as 23.222222222222225 °C.
PRECISION = 4


def render(
    readings: Iterable[Reading], preferences: Preferences, *, station: str, timestamp: int
) -> list[Row]:
    """Convert readings to the operator's units and group them into rows.

    Readings sharing a table and tags become one row. Where two report keys mean the same
    field, the later one in the report wins.
    """
    rows: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Value]] = {}
    for reading in readings:
        tags = dict(reading.tags)
        tags["station"] = station
        if reading.sensor is not None and reading.table in NAMED_TABLES:
            tags["sensor"] = reading.sensor
            tags["name"] = preferences.name_for(reading.sensor)
        key = (reading.table, tuple(sorted(tags.items())))
        name, value = _field(reading, preferences)
        rows.setdefault(key, {})[name] = value
    return [
        Row(table, tags, timestamp, dict(sorted(values.items())))
        for (table, tags), values in sorted(rows.items())
    ]


def _field(reading: Reading, preferences: Preferences) -> tuple[str, Value]:
    """The stored field name and value: unit suffix added, numbers converted and rounded."""
    if reading.kind in (Kind.TEXT, Kind.FLAG):
        return reading.field, reading.value
    value, suffix = from_canonical(reading.kind, float(reading.value), preferences.units)
    name = f"{reading.field}_{suffix}" if suffix else reading.field
    return name, round(value, PRECISION)

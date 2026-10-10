"""Encode rows as InfluxDB line protocol.

Both InfluxDB 2.x and 3 accept this format. Timestamps are whole seconds, so writes must ask
for second precision.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from ecowitt.collector.ingest.points import Point
from ecowitt.core.readings import Value


def encode(points: Iterable[Point]) -> str:
    """Encode rows as newline-separated line protocol, skipping any that have no fields."""
    lines = [line for point in points if (line := encode_point(point))]
    return "\n".join(lines)


def encode_point(point: Point) -> str:
    """Encode one row, or return an empty string if none of its fields can be written."""
    fields = ",".join(
        f"{_escape_key(name)}={encoded}"
        for name, value in point.fields.items()
        if (encoded := _value(value)) is not None
    )
    if not fields:
        return ""
    # Line protocol forbids an empty tag value, so such a tag is left off rather than written.
    tags = "".join(
        f",{_escape_key(key)}={_escape_key(value)}" for key, value in point.tags if value
    )
    return f"{_escape_measurement(point.table)}{tags} {fields} {point.timestamp}"


def _value(value: Value) -> str | None:
    """Encode a field value, or None for one line protocol cannot represent.

    Every number is written as a float, never an integer, even when it has no fraction:
    InfluxDB fixes a field's type on its first write, so a humidity first seen as `60` would
    otherwise reject every later `60.5`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else None
    escaped = _flatten(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _flatten(text: str) -> str:
    """Replace line breaks with spaces: line protocol has no escape for them, and one would end
    the line mid-point, making InfluxDB refuse the whole write."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _escape_measurement(name: str) -> str:
    """Escape a measurement name: commas and spaces would end it early."""
    return _flatten(name).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")


def _escape_key(name: str) -> str:
    """Escape a tag key, tag value or field key: commas, equals signs and spaces."""
    return (
        _flatten(name)
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace("=", "\\=")
        .replace(" ", "\\ ")
    )

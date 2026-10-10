"""Turn the fields of one upload into readings in canonical units.

Total by design: this runs on whatever an authenticated caller chooses to send, so a value that
does not parse is skipped and the rest of the report is kept, rather than one bad field costing
the whole upload -- or raising, and costing the station its reply.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime

from ecowitt.collector.ingest import fields
from ecowitt.collector.readings import Reading, Report
from ecowitt.collector.units import Kind, UnknownUnit, to_canonical

logger = logging.getLogger(__name__)

#: How far the station's clock may disagree with this server's before its timestamp is
#: replaced by the time of receipt. Consoles lose their clock on a power cut and can come back
#: years in the past until they next sync, and a report written at the wrong time is harder to
#: find than one written a few seconds late.
MAX_CLOCK_SKEW_SECONDS = 600


def parse(raw: Mapping[str, str], received_at: datetime) -> Report:
    """Parse one report's fields, timestamping it with the station's clock where plausible."""
    timestamp, skew = _timestamp(raw.get("dateutc"), received_at)
    readings: list[Reading] = []
    for key, value in raw.items():
        if key in fields.NOT_STORED:
            continue
        reading = _reading(key, value)
        if reading is not None:
            readings.append(reading)
    if skew is not None:
        readings.append(Reading("station", "clock_skew", Kind.DURATION, float(skew)))
    return Report(timestamp=timestamp, readings=readings)


def _reading(key: str, value: str) -> Reading | None:
    """Map one field to a reading, or None if its value cannot be used."""
    found = fields.match(key)
    if found is None:
        return _unmapped(key, value)
    spec, groups = found

    tags = tuple((k, v.format(**groups)) for k, v in spec.tags)
    sensor = spec.sensor.format(**groups) if spec.sensor else None
    name = spec.field.format(**groups)

    if spec.kind is Kind.TEXT:
        return Reading(spec.table, name, spec.kind, value.strip(), tags, sensor)

    number = _number(value)
    if number is None:
        logger.debug("field %s: unusable value %r", key, value)
        return None
    if spec.kind is Kind.FLAG:
        return Reading(spec.table, name, spec.kind, number != 0, tags, sensor)
    try:
        canonical = to_canonical(spec.kind, spec.unit, number)
    except UnknownUnit:
        # A field table entry naming a unit its kind cannot convert is a bug in the table, which
        # the suite checks for; this keeps one such entry from taking the report down with it.
        logger.exception("field %s: no conversion for its declared unit", key)
        return None
    return Reading(spec.table, name, spec.kind, canonical, tags, sensor)


def _unmapped(key: str, value: str) -> Reading:
    """Keep a field no spec recognises, under its own name.

    A numeric value and a textual one go to different field names, because InfluxDB fixes a
    field's type on its first write and rejects later writes of another type -- so a key that
    sent `12` once and `--` the next time would otherwise start failing whole reports.
    """
    number = _number(value)
    if number is not None:
        return Reading("unmapped", key, Kind.COUNT, number)
    return Reading("unmapped", key + "_text", Kind.TEXT, value)


def _number(value: str) -> float | None:
    """Parse a finite number, or return None.

    NaN and infinity are refused: `float` accepts the strings "nan" and "inf", and line
    protocol has no way to write either.
    """
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _timestamp(dateutc: str | None, received_at: datetime) -> tuple[int, float | None]:
    """Choose the report's timestamp, returning it with the station clock's skew if known.

    Skew is receipt time minus station time, so a positive value means the station is behind.
    """
    received = int(received_at.timestamp())
    station = _station_time(dateutc)
    if station is None:
        return received, None
    skew = received_at.timestamp() - station.timestamp()
    if abs(skew) > MAX_CLOCK_SKEW_SECONDS:
        logger.warning(
            "station clock is %.0f s from this server's; using the time of receipt", skew
        )
        return received, skew
    return int(station.timestamp()), skew


def _station_time(dateutc: str | None) -> datetime | None:
    """Parse the station's `dateutc`, which is UTC without a zone marker.

    Ecowitt sends `2026-10-08 23:01:24` (the `+` of the form encoding already decoded to a
    space); Wunderground allows the literal `now`, which says nothing about the station's clock.
    """
    if not dateutc:
        return None
    text = dateutc.strip()
    try:
        if text.isdigit():
            return datetime.fromtimestamp(int(text), UTC)
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError, OverflowError, OSError:
        # A digit string too large for the platform's time functions overflows rather than
        # failing to parse, and must not escape a parser that promises never to raise.
        return None

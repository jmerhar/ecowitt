"""Checks shared by the Grafana tests: which tables and fields a query names, and what exists.

A Grafana query that names a field the server no longer writes fails nothing at ingest time; a
panel goes blank, or an alert rule quietly never fires. So every table and field a query names
must be one the pipeline writes for the recorded payloads -- in the units the files are rendered
for, since a field's name carries its unit.
"""

from __future__ import annotations

import dataclasses
import functools
import re
import urllib.parse

from ecowitt.collector.ingest.pipeline import process
from ecowitt.collector.ingest.staleness import StalenessTracker
from ecowitt.core import weathermodel
from ecowitt.core.stationinfo import TABLE, StationInfo
from ecowitt.core.units import Units, field_name

from ..conftest import payload
from ..ingest.test_pipeline import PREFERENCES, RECEIVED, RECEIVED_WS69

#: The recorded payloads, with when each was received (inside its clock-skew allowance).
PAYLOADS = {"hp2551_indoor": RECEIVED, "hp2551_ws69": RECEIVED_WS69}

#: The SQL functions the queries call. Keywords are written in capitals and so never match
#: IDENTIFIER; every other lowercase word must be a table, a field, a CTE or an alias.
FUNCTIONS = {
    "avg",
    "min",
    "max",
    "median",
    "sum",
    "last_value",
    "first_value",
    "now",
    "interval",
    "date_part",
    "date_trunc",
    # A shower is found in minute buckets.
    "date_bin",
    "initcap",
    "coalesce",
    # The newest forecast for a time is the row numbered first by its lead.
    "row_number",
    # A direction's mean is taken around the circle: the angle of the summed unit vectors.
    "sin",
    "cos",
    "atan2",
    "radians",
    "degrees",
}
IDENTIFIER = re.compile(r"\b[a-z][a-z0-9_]*\b")
#: Quoted strings and Grafana's macros and variables, which hold no column names.
NOT_SQL = re.compile(r"'[^']*'|\"[^\"]*\"|\$__[A-Za-z]+|\$\{[^}]*\}")
#: A name as tables, CTEs and aliases are written: `wind_10m` as well as `wind`.
NAME = r"[a-z_][a-z0-9_]*"
ALIAS = re.compile(rf"\bAS\s+({NAME})|\b(?:FROM|JOIN)\s+{NAME}\s+([a-z])\b")
SOURCE = re.compile(rf"\b(?:FROM|JOIN)\s+({NAME})", re.IGNORECASE)
CTE = re.compile(rf"(?:\bWITH|,)\s*({NAME})\s+AS\s*\(", re.IGNORECASE)


@functools.cache
def schema(units: Units = Units()) -> dict[str, set[str]]:  # noqa: B008 -- frozen, so shared safely
    """Every table the pipeline writes for the recorded payloads in `units`, with its timestamp
    and the tags and fields written."""
    preferences = dataclasses.replace(PREFERENCES, units=units)
    tables: dict[str, set[str]] = {}
    for name, received in PAYLOADS.items():
        raw = dict(urllib.parse.parse_qsl(payload(name), keep_blank_values=True))
        for row in process(
            raw,
            received_at=received,
            station="example",
            preferences=preferences,
            tracker=StalenessTracker(),
        ):
            columns = tables.setdefault(row.table, {"time"})
            columns.update(tag for tag, _ in row.tags)
            columns.update(row.fields)
    # Written by the collector's metadata publisher rather than from a report, so it is in no
    # golden file: its columns come from a row with every setting present.
    info = StationInfo("s", 0.0, 0.0, 0.0, "UTC", sensors={"ch1": "x"}, weather_model="m").to_row(0)
    tables[TABLE] = {"time", *(tag for tag, _ in info.tags), *info.fields}
    # Written by the weather model feed, from its declared variables.
    tables[weathermodel.TABLE] = {
        "time",
        "station",
        "source",
        "model",
        *(field_name(base, kind, units) for base, kind in weathermodel.VARIABLES.values()),
    }
    # Written by the forecast feed: each table's declared variables, tagged with their lead.
    for table, variables in (
        (weathermodel.FORECAST_TABLE, weathermodel.FORECAST_HOURLY),
        (weathermodel.FORECAST_DAILY_TABLE, weathermodel.FORECAST_DAILY),
    ):
        tables[table] = {
            "time",
            "station",
            "source",
            "model",
            "lead",
            *(field_name(base, kind, units) for base, kind in variables.values()),
        }
    return tables


SCHEMA = schema()
FIELDS = set().union(*SCHEMA.values())


def queried_tables(sql: str) -> set[str]:
    """The tables a query reads, leaving out its CTEs."""
    ctes = set(CTE.findall(sql))
    return {t for t in SOURCE.findall(sql) if t not in ctes}


def queried_fields(sql: str) -> set[str]:
    """The lowercase words in a query that are not a function, a table, a CTE or an alias."""
    code = NOT_SQL.sub(" ", sql)
    named = {a for pair in ALIAS.findall(code) for a in pair if a} | set(CTE.findall(code))
    return set(IDENTIFIER.findall(code)) - named - FUNCTIONS - SCHEMA.keys()

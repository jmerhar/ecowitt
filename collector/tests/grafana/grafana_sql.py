"""Checks shared by the Grafana tests: which tables and fields a query names, and what exists.

A Grafana query that names a field the server no longer writes fails nothing at ingest time; a
panel goes blank, or an alert rule quietly never fires. The golden line-protocol files are the
pipeline's pinned output, so every table and field a query names must appear in them.
"""

from __future__ import annotations

import re

from ecowitt.core.stationinfo import TABLE, StationInfo

from ..conftest import FIXTURES

GOLDEN = [FIXTURES / "hp2551_indoor.lp", FIXTURES / "hp2551_ws69.lp"]

#: The SQL functions the queries call. Keywords are written in capitals and so never match
#: IDENTIFIER; every other lowercase word must be a table, a field, a CTE or an alias.
FUNCTIONS = {
    "avg",
    "min",
    "max",
    "last_value",
    "first_value",
    "now",
    "interval",
    "date_part",
    "initcap",
}
IDENTIFIER = re.compile(r"\b[a-z][a-z0-9_]*\b")
#: Quoted strings and Grafana's macros and variables, which hold no column names.
NOT_SQL = re.compile(r"'[^']*'|\"[^\"]*\"|\$__[A-Za-z]+|\$\{[^}]*\}")
ALIAS = re.compile(r"\bAS\s+([a-z_]+)|\b(?:FROM|JOIN)\s+[a-z_]+\s+([a-z])\b")
SOURCE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.IGNORECASE)
CTE = re.compile(r"(?:\bWITH|,)\s*([a-z_]+)\s+AS\s*\(", re.IGNORECASE)
#: Line protocol: measurement and tags, a space, the fields, a space, the timestamp.
LINE = re.compile(r"((?:[^ \\]|\\.)+) ((?:[^ \\]|\\.)+) \d+")


def schema() -> dict[str, set[str]]:
    """Every table in the golden output, with its timestamp and the tags and fields written."""
    tables: dict[str, set[str]] = {}
    for golden in GOLDEN:
        for line in golden.read_text(encoding="utf-8").splitlines():
            match = LINE.fullmatch(line)
            assert match, line
            series, values = match.groups()
            table, *tags = re.split(r"(?<!\\),", series)
            columns = tables.setdefault(table, {"time"})
            columns.update(tag.split("=", 1)[0] for tag in tags)
            columns.update(re.findall(r"(?:^|,)([a-z0-9_]+)=", values))
    # Written by the collector's metadata publisher rather than from a report, so it is in no
    # golden file: its columns come from a row with every setting present.
    info = StationInfo("s", 0.0, 0.0, 0.0, "UTC", sensors={"ch1": "x"}).to_row(0)
    tables[TABLE] = {"time", *(tag for tag, _ in info.tags), *info.fields}
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

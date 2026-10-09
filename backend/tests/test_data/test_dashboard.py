"""The Grafana dashboard: its queries name only tables and fields the pipeline writes.

A dashboard query that names a field the server no longer writes fails nothing at ingest time; the
panel just goes blank. The golden line-protocol files are the pipeline's pinned output, so every
table and unit-suffixed field the dashboard queries must appear in them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from ..conftest import FIXTURES

DASHBOARD = Path(__file__).parents[3] / "grafana" / "weather.json"
GOLDEN = [FIXTURES / "hp2551_indoor.lp", FIXTURES / "hp2551_ws69.lp"]

#: The SQL functions the queries call. Keywords are written in capitals and so never match
#: IDENTIFIER; every other lowercase word must be a table, a field, a CTE or an alias.
FUNCTIONS = {"avg", "max", "last_value", "first_value", "now", "interval", "date_part", "initcap"}
IDENTIFIER = re.compile(r"\b[a-z][a-z0-9_]*\b")
#: Quoted strings and Grafana's macros and variables, which hold no column names.
NOT_SQL = re.compile(r"'[^']*'|\"[^\"]*\"|\$__[A-Za-z]+|\$\{[^}]*\}")
ALIAS = re.compile(r"\bAS\s+([a-z_]+)|\b(?:FROM|JOIN)\s+[a-z_]+\s+([a-z])\b")
SOURCE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.IGNORECASE)
CTE = re.compile(r"(?:\bWITH|,)\s*([a-z_]+)\s+AS\s*\(", re.IGNORECASE)
#: Line protocol: measurement and tags, a space, the fields, a space, the timestamp.
LINE = re.compile(r"((?:[^ \\]|\\.)+) ((?:[^ \\]|\\.)+) \d+")


def _schema() -> dict[str, set[str]]:
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
    return tables


def _panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The dashboard's panels, with those inside rows flattened in."""
    flat = []
    for panel in panels:
        flat.append(panel)
        flat.extend(_panels(panel.get("panels", [])))
    return flat


DOC = json.loads(DASHBOARD.read_text(encoding="utf-8"))
PANELS = [p for p in _panels(DOC["panels"]) if p["type"] != "row"]
PANEL_QUERIES = [
    pytest.param(t["rawSql"], id=f"{p['title']}/{t['refId']}") for p in PANELS for t in p["targets"]
]
QUERIES = PANEL_QUERIES + [
    pytest.param(v["query"]["query"], id=f"variable/{v['name']}")
    for v in DOC["templating"]["list"]
    if v["type"] == "query"
]
SCHEMA = _schema()
FIELDS = set().union(*SCHEMA.values())


def test_the_dashboard_queries_something() -> None:
    """Guards against an emptied dashboard, which would pass every test below."""
    assert len(QUERIES) > 30


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_table_is_written(sql: str) -> None:
    ctes = set(CTE.findall(sql))
    tables = {t for t in SOURCE.findall(sql) if t not in ctes}

    assert tables, sql
    assert tables <= SCHEMA.keys(), tables - SCHEMA.keys()


def _queried_fields(sql: str) -> set[str]:
    """The lowercase words in a query that are not a function, a table, a CTE or an alias."""
    code = NOT_SQL.sub(" ", sql)
    named = {a for pair in ALIAS.findall(code) for a in pair if a} | set(CTE.findall(code))
    return set(IDENTIFIER.findall(code)) - named - FUNCTIONS - SCHEMA.keys()


def test_the_field_check_sees_the_fields() -> None:
    """Guards against a pattern that silently extracts nothing, passing the test below."""
    seen = set().union(*(_queried_fields(q.values[0]) for q in QUERIES))

    assert len(seen) > 20


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_field_is_written(sql: str) -> None:
    queried = _queried_fields(sql)

    assert queried <= FIELDS, queried - FIELDS


@pytest.mark.parametrize("sql", PANEL_QUERIES)
def test_every_panel_query_is_scoped_to_the_selected_station(sql: str) -> None:
    """Without it, a second station's readings would be averaged into the first's panels."""
    assert "station = '${station}'" in sql


def test_every_panel_reads_the_selected_data_source() -> None:
    sources = {json.dumps(p["datasource"]) for p in PANELS}
    sources |= {json.dumps(t["datasource"]) for p in PANELS for t in p["targets"]}

    assert sources == {json.dumps({"type": "influxdb", "uid": "${datasource}"})}


def test_panel_ids_are_unique() -> None:
    ids = [p["id"] for p in _panels(DOC["panels"])]

    assert len(ids) == len(set(ids))


def test_no_two_panels_overlap() -> None:
    """Grafana pushes an overlapping panel down, so the layout would not be the one written."""
    cells: dict[tuple[int, int], str] = {}
    for panel in _panels(DOC["panels"]):
        pos = panel["gridPos"]
        assert pos["x"] + pos["w"] <= 24, panel["title"]
        for x in range(pos["x"], pos["x"] + pos["w"]):
            for y in range(pos["y"], pos["y"] + pos["h"]):
                assert (x, y) not in cells, (panel["title"], cells.get((x, y)))
                cells[(x, y)] = panel["title"]

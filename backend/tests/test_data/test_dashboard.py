"""The Grafana dashboard: its queries name only tables and fields the pipeline writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .grafana_sql import FIELDS, SCHEMA, queried_fields, queried_tables

DASHBOARD = Path(__file__).parents[3] / "grafana" / "weather.json"


def _panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The dashboard's panels, with those inside rows flattened in."""
    flat = []
    for panel in panels:
        flat.append(panel)
        flat.extend(_panels(panel.get("panels", [])))
    return flat


DOC = json.loads(DASHBOARD.read_text(encoding="utf-8"))
PANELS = [p for p in _panels(DOC["panels"]) if p.get("targets")]
PANEL_QUERIES = [
    pytest.param(t["rawSql"], id=f"{p['title']}/{t['refId']}") for p in PANELS for t in p["targets"]
]
QUERIES = PANEL_QUERIES + [
    pytest.param(v["query"]["query"], id=f"variable/{v['name']}")
    for v in DOC["templating"]["list"]
    if v["type"] == "query"
]


def test_the_dashboard_queries_something() -> None:
    """Guards against an emptied dashboard, which would pass every test below."""
    assert len(QUERIES) > 30


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_table_is_written(sql: str) -> None:
    tables = queried_tables(sql)

    assert tables, sql
    assert tables <= SCHEMA.keys(), tables - SCHEMA.keys()


def test_the_field_check_sees_the_fields() -> None:
    """Guards against a pattern that silently extracts nothing, passing the test below."""
    seen = set().union(*(queried_fields(q.values[0]) for q in QUERIES))

    assert len(seen) > 20


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_field_is_written(sql: str) -> None:
    queried = queried_fields(sql)

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


def test_the_alert_panel_lists_the_alert_rules() -> None:
    """The panel filters on a label; a rule without it would fire unseen on the dashboard."""
    lists = [p for p in _panels(DOC["panels"]) if p["type"] == "alertlist"]
    alerts = json.loads((DASHBOARD.parent / "alerts.json").read_text(encoding="utf-8"))
    labels = {r["labels"]["app"] for g in alerts["groups"] for r in g["rules"]}

    assert len(lists) == 1
    assert labels == {"ecowitt"}
    assert lists[0]["options"]["alertInstanceLabelFilter"] == '{app="ecowitt"}'

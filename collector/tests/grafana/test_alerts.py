"""The Grafana alert rules: real tables and fields, and the shape alerting and routing rely on."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from .grafana_sql import FIELDS, SCHEMA, queried_fields, queried_tables

ALERTS = Path(__file__).parents[3] / "grafana" / "alerts.json"
DOC = json.loads(ALERTS.read_text(encoding="utf-8"))
RULES: list[dict[str, Any]] = [r for g in DOC["groups"] for r in g["rules"]]
BY_TITLE = [pytest.param(r, id=r["title"]) for r in RULES]
QUERIES = [
    pytest.param(d["model"]["rawSql"], id=f"{r['title']}/{d['refId']}")
    for r in RULES
    for d in r["data"]
    if d["datasourceUid"] != "__expr__"
]
#: A value from a rule's queries or expressions, as a summary refers to it.
VALUE_REF = re.compile(r"\$values\.([A-Z])\.")


def test_the_rules_are_there() -> None:
    """Guards against an emptied file, which would pass every test below."""
    assert len(RULES) >= 9
    assert len(QUERIES) >= 9


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_table_is_written(sql: str) -> None:
    tables = queried_tables(sql)

    assert tables, sql
    assert tables <= SCHEMA.keys(), tables - SCHEMA.keys()


@pytest.mark.parametrize("sql", QUERIES)
def test_every_queried_field_is_written(sql: str) -> None:
    queried = queried_fields(sql)

    assert queried <= FIELDS, queried - FIELDS


@pytest.mark.parametrize("sql", QUERIES)
def test_every_query_yields_one_value_per_row(sql: str) -> None:
    """Alerting turns each row into an instance: string columns become labels, `value` its value.

    A second numeric column would be refused, and a time column would make it a time series
    that needs reducing first.
    """
    assert re.search(r"\bAS value\b", sql), sql
    assert not re.search(r"\bAS time\b", sql), sql


@pytest.mark.parametrize("sql", QUERIES)
def test_every_query_groups_by_station(sql: str) -> None:
    """One instance per station, so a second station's readings never mix into the first's."""
    assert re.search(r"GROUP BY (\w+\.)?station\b", sql), sql


@pytest.mark.parametrize("rule", BY_TITLE)
def test_every_rule_is_routed_by_its_labels(rule: dict[str, Any]) -> None:
    """The notification policy matches `app` and, for quiet hours, `severity`."""
    assert rule["labels"]["app"] == "ecowitt"
    assert rule["labels"]["severity"] in {"info", "warning"}


@pytest.mark.parametrize("rule", BY_TITLE)
def test_every_rule_reads_the_weather_data_source(rule: dict[str, Any]) -> None:
    assert {d["datasourceUid"] for d in rule["data"]} <= {"weather", "__expr__"}


@pytest.mark.parametrize("rule", BY_TITLE)
def test_every_rule_refers_only_to_its_own_steps(rule: dict[str, Any]) -> None:
    """A condition or summary naming a step the rule lacks fails at evaluation or renders blank."""
    refs = {d["refId"] for d in rule["data"]}
    expressions = [d["model"] for d in rule["data"] if d["datasourceUid"] == "__expr__"]

    assert rule["condition"] in refs
    assert {e["expression"] for e in expressions} <= refs
    for text in (rule["annotations"][k] for k in ("summary", "item") if k in rule["annotations"]):
        assert set(VALUE_REF.findall(text)) <= refs


@pytest.mark.parametrize("rule", BY_TITLE)
def test_no_rows_is_normal_and_a_failed_query_is_reported(rule: dict[str, Any]) -> None:
    """A sensor with no recent rows has nothing to alert on; a query that fails is a fault."""
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_rule_uids_are_unique() -> None:
    uids = [r["uid"] for r in RULES]

    assert len(uids) == len(set(uids))


@pytest.mark.parametrize(
    "uid",
    [
        "ecowitt-airing",
        "ecowitt-close-windows",
        "ecowitt-gusts",
        "ecowitt-rain",
        "ecowitt-pressure-fall",
    ],
)
def test_weather_rules_hold_before_resolving(uid: str) -> None:
    """Gusts, showers and humidity cross their thresholds back and forth; without a hold each
    crossing sends a firing and a resolved message."""
    rule = next(r for r in RULES if r["uid"] == uid)

    assert rule.get("keep_firing_for", "0s") not in {"", "0s"}


def test_a_silent_sensor_is_measured_against_the_station_not_the_clock() -> None:
    """A station that stops uploading must not flag every sensor, and a sensor that stops
    reporting must stay flagged rather than ageing out of a short window."""
    sql = next(r for r in RULES if r["uid"] == "ecowitt-sensor-silent")["data"][0]["model"]
    assert "FROM station" in sql["rawSql"]
    assert "interval '7 days'" in sql["rawSql"]


@pytest.mark.parametrize("rule", BY_TITLE)
def test_a_rule_with_an_alert_per_room_lists_them_under_one_headline(rule: dict[str, Any]) -> None:
    """Rooms firing together share one message: the headline once, then each room's item."""
    per_room = " AS room" in rule["data"][0]["model"]["rawSql"]
    annotations = rule["annotations"]
    assert ("headline" in annotations) == per_room
    if per_room:
        assert "{{" not in annotations["headline"], "the headline is the same for every room"
        assert annotations["item"].startswith("{{ $labels.room }}")


def test_daily_rules_are_the_slow_house_conditions() -> None:
    daily = {r["title"] for r in RULES if r["labels"].get("notify") == "daily"}
    assert daily == {"Damp room", "Close the windows"}

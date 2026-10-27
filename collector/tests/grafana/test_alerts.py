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
#: A step a math expression refers to.
MATH_REF = re.compile(r"\$([A-Z])\b")


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
    for expression in expressions:
        # A math expression names its steps as $A; a threshold or reduction names one bare.
        named = (
            MATH_REF.findall(expression["expression"])
            if expression["type"] == "math"
            else [expression["expression"]]
        )
        assert set(named) <= refs
    texts = ("summary", "group", "item")
    for text in (rule["annotations"][k] for k in texts if k in rule["annotations"]):
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
        "ecowitt-open-windows-damper",
        "ecowitt-gusts",
        "ecowitt-rain",
        "ecowitt-pressure-fall",
    ],
)
def test_weather_rules_hold_before_resolving(uid: str) -> None:
    """Gusts, showers and humidity cross their thresholds back and forth; without a hold each
    crossing sends a firing and a resolved message."""
    rule = next(r for r in RULES if r["uid"] == uid)

    assert rule.get("keepFiringFor", "0s") not in {"", "0s"}


#: The keys a rule may carry in a provisioning file, as Grafana reads them
#: (pkg/services/provisioning/alerting/rules_types.go). The HTTP API spells some differently
#: (keep_firing_for), and a key the file format does not know is dropped without a word.
FILE_RULE_KEYS = {
    "uid", "title", "condition", "data", "dashboardUid", "panelId", "noDataState",
    "execErrState", "for", "keepFiringFor", "missing_series_evals_to_resolve", "annotations",
    "labels", "isPaused", "notification_settings", "record",
}  # fmt: skip


@pytest.mark.parametrize("rule", BY_TITLE)
def test_every_rule_key_is_one_a_provisioning_file_reads(rule: dict[str, Any]) -> None:
    assert set(rule) <= FILE_RULE_KEYS


#: Rules about the station's own hardware, for whoever runs it rather than the household.
OPERATOR_RULES = {"ecowitt-sensor-silent", "ecowitt-battery"}


@pytest.mark.parametrize("rule", BY_TITLE)
def test_only_the_hardware_rules_are_for_the_operator(rule: dict[str, Any]) -> None:
    """A silent sensor or a flat battery is the operator's to fix; the rest is about the house."""
    audience = rule["labels"].get("audience")

    assert audience == ("operator" if rule["uid"] in OPERATOR_RULES else None)


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


def test_good_time_to_air_says_what_airing_would_do() -> None:
    """One message for the house, giving the humidity airing would leave the rooms at, in words
    anyone reads, not the dew point behind it; it waits while the windows already look open."""
    rule = next(r for r in RULES if r["uid"] == "ecowitt-airing")
    sql = {d["refId"]: d["model"].get("rawSql", "") for d in rule["data"]}
    summary = rule["annotations"]["summary"]
    assert any("predicted_humidity_pct" in sql[ref] for ref in VALUE_REF.findall(summary))
    assert "dew point" not in summary.lower()
    assert "headline" not in rule["annotations"], "the house is one alert, not one per room"
    assert all("FROM house" in q for q in sql.values() if q)
    assert "aired" in sql["A"]


def test_damp_room_says_what_airing_would_do_to_each_room() -> None:
    """Each room's advice gives the humidity airing would bring it to, judged by the room's own
    humidity rather than by dew points: the measure Good time to air judges the house by, so the
    two never disagree about whether the outside air is drier."""
    rule = next(r for r in RULES if r["uid"] == "ecowitt-damp")
    sql = {d["refId"]: d["model"].get("rawSql", "") for d in rule["data"]}
    annotations = rule["annotations"]
    assert "predicted_humidity_pct" in sql["D"]
    assert "FROM indoor" in sql["H"] and "FROM channel" in sql["H"]
    assert "dewpoint" not in "".join(sql.values())
    for key in ("summary", "group", "item"):
        assert "dew point" not in annotations[key].lower()
    assert annotations["item"].count("$values.D.Value") == 1
    assert annotations["summary"].count("$values.D.Value") == 2


def test_damp_room_groups_the_rooms_by_what_airing_would_do() -> None:
    """Rooms sharing a verdict are listed under it once: in most messages that is every room.

    The group gives each of the summary's three verdicts, decided by the same steps in the same
    order, so a room's group and its summary always agree.
    """
    annotations = next(r for r in RULES if r["uid"] == "ecowitt-damp")["annotations"]
    branches = ".*".join(
        re.escape(step)
        for step in (
            "{{ if eq $values.F.Value 1.0 }}",
            "{{ else if eq $values.E.Value 1.0 }}",
            "{{ else }}",
        )
    )
    assert re.search(branches, annotations["group"])
    assert re.search(branches, annotations["summary"])
    assert "airing would not dry it," in annotations["summary"]


@pytest.mark.parametrize("rule", BY_TITLE)
def test_a_group_is_shared_by_rooms_and_heads_their_list(rule: dict[str, Any]) -> None:
    """A group is printed once above its rooms, so it names none of them and introduces a list."""
    annotations = rule["annotations"]
    if "group" not in annotations:
        return
    assert "headline" in annotations
    assert "$labels" not in annotations["group"]
    for text in re.split(r"\{\{[^}]*\}\}", annotations["group"]):
        assert not text or text.endswith(":"), text


def test_a_shower_and_a_damp_room_never_fire_together() -> None:
    """Air the bathroom only speaks for a room that has dropped below the level Damp room clears
    at within the same six hours: such a room cannot be damp, and a damp room cannot qualify."""
    rules = {r["uid"]: r for r in RULES}
    shower = rules["ecowitt-shower"]["data"][0]["model"]["rawSql"]
    damp = rules["ecowitt-damp"]
    (condition,) = [d["model"] for d in damp["data"] if d["model"].get("type") == "threshold"]
    clears = condition["conditions"][0]["unloadEvaluator"]["params"][0]
    assert f"WHERE l.low < {clears:g}" in shower
    assert "interval '6 hours'" in shower
    assert "interval '6 hours'" in damp["data"][0]["model"]["rawSql"]
    assert "t >= now() - interval '90 minutes' AND t <= now() - interval '40 minutes'" in shower


def test_one_shower_sends_one_message() -> None:
    """A bathroom hovering at 70% would otherwise fire again each time it crosses the line."""
    rule = next(r for r in RULES if r["uid"] == "ecowitt-shower")
    assert rule["keepFiringFor"] == "30m"


@pytest.mark.parametrize("rule", BY_TITLE)
def test_no_template_compares_a_value_with_a_number(rule: dict[str, Any]) -> None:
    """Go templates refuse to compare a value, a float, with a whole number such as a threshold
    rendered as "2", and Grafana then sends the template unexpanded: a comparison belongs in a
    math step, and the template tests that step's 1 or 0."""
    for text in rule["annotations"].values():
        for found in re.findall(r"\b(?:gt|lt|ge|le|eq|ne) \$values\.\w+\.Value (\S+)", text):
            assert found == "1.0", (rule["title"], text)


def test_a_damp_room_stays_damp_until_it_dries_well_below_the_line() -> None:
    """Rooms that hover at 70% would otherwise clear and fire again every day."""
    rule = next(r for r in RULES if r["uid"] == "ecowitt-damp")
    (condition,) = [d["model"] for d in rule["data"] if d["model"].get("type") == "threshold"]
    (step,) = condition["conditions"]
    assert step["evaluator"] == {"type": "gt", "params": [69.5]}
    assert step["unloadEvaluator"] == {"type": "lt", "params": [65]}


def test_the_shower_alert_is_sent_at_any_hour_and_never_resolves() -> None:
    """Quiet hours mute info alerts, and an evening shower's warning is no use the next morning."""
    labels = next(r for r in RULES if r["uid"] == "ecowitt-shower")["labels"]
    assert (labels["severity"], labels["resolve_message"]) == ("warning", "off")
    assert "notify" not in labels


def test_daily_rules_are_the_slow_house_conditions() -> None:
    daily = {r["title"] for r in RULES if r["labels"].get("notify") == "daily"}
    assert daily == {
        "Damp room",
        "Good time to air",
        "Close the windows",
    }
    quiet = {r["title"] for r in RULES if r["labels"].get("resolve_message") == "off"}
    assert quiet == {"Damp room", "Good time to air", "Close the windows", "Air the bathroom"}


@pytest.mark.parametrize("rule", BY_TITLE)
def test_no_query_hides_a_condition_in_its_value(rule: dict[str, Any]) -> None:
    """A value replaced by a stand-in (-99) when some other test fails is what a summary shows
    while the rule keeps firing after that test stops holding; conditions belong in the
    expression."""
    for step in rule["data"]:
        if step["datasourceUid"] != "__expr__":
            assert not re.search(r"\b(?:-?99)\b", step["model"]["rawSql"]), step["refId"]


@pytest.mark.parametrize("rule", BY_TITLE)
def test_a_rule_that_resolves_says_so_in_its_own_words(rule: dict[str, Any]) -> None:
    """A resolve message reads as what changed ("Wind easing"), not as the rule's name. It names
    no value: Grafana fills it from the evaluation that cleared, not the one that fired."""
    annotations = rule["annotations"]
    sends = rule["labels"].get("resolve_message") != "off"
    assert ("resolved" in annotations, "resolved_title" in annotations) == (sends, sends)
    if sends:
        assert "{{" not in annotations["resolved_title"], "the title is one for every alert"
        assert "$values" not in annotations["resolved"]


@pytest.mark.parametrize("rule", BY_TITLE)
def test_values_are_printed_no_finer_than_the_sensors_read(rule: dict[str, Any]) -> None:
    """humanize prints every digit it is given (a gust of 63.78 km/h): each value is printed with
    a fixed number of decimals instead, or as a duration."""
    for text in rule["annotations"].values():
        for printed in re.findall(r"\{\{[^}]*\$values\.\w+\.Value[^}]*\}\}", text):
            if printed.startswith(("{{ if ", "{{ else if ")):
                continue
            assert re.match(r'\{\{ (printf "%\.\d+f%*"|humanizeDuration) ', printed), printed


def test_strong_wind_needs_gusts_in_three_separate_minutes() -> None:
    """One stray gust sends nothing: the threshold is held to the third strongest minute's gust in
    the last 10 minutes, while the message gives the strongest."""
    rule = next(r for r in RULES if r["uid"] == "ecowitt-gusts")
    steps = {d["refId"]: d["model"] for d in rule["data"]}
    assert steps["C"]["expression"] == "B"
    assert "date_bin(interval '1 minute', time)" in steps["B"]["rawSql"]
    assert "array_element(array_agg(gust ORDER BY gust DESC), 3)" in steps["B"]["rawSql"]
    assert all("interval '10 minutes'" in steps[ref]["rawSql"] for ref in "AB")
    assert "max(gust_kmh)" in steps["A"]["rawSql"]
    assert "$values.A.Value" in rule["annotations"]["summary"]

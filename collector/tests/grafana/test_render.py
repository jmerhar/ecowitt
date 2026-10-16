"""The Grafana templates, rendered for every choice of units the collector can store."""

from __future__ import annotations

import importlib.util
import itertools
import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from ecowitt.collector.grafana import render
from ecowitt.core.units import PressureUnit, RainUnit, TemperatureUnit, Units, WindUnit

from .grafana_sql import queried_fields, queried_tables, schema

REPO = Path(__file__).parents[3]
EVERY_UNITS = [
    Units(temperature=t, pressure=p, rain=r, wind=w)
    for t, p, r, w in itertools.product(
        get_args(TemperatureUnit), get_args(PressureUnit), get_args(RainUnit), get_args(WindUnit)
    )
]
UNIT_IDS = [f"{u.temperature}-{u.pressure}-{u.rain}-{u.wind}" for u in EVERY_UNITS]
#: Grafana's own display units the renderer may produce (packages/grafana-data/src/valueFormats/
#: categories.ts); a `suffix:` unit is any text Grafana appends.
GRAFANA_IDS = {
    "celsius", "fahrenheit", "pressurehpa", "pressurehg",
    "velocitykmh", "velocityms", "velocitymph", "velocityknot",
}  # fmt: skip


def _strings(node: Any, key: str = "") -> list[tuple[str, str]]:
    """Every string in a document, with the key it sits under."""
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings(v, k)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v, key)]
    return [(key, node)] if isinstance(node, str) else []


def _queries(dashboard: dict[str, Any], alerts: dict[str, Any]) -> list[str]:
    """Every SQL statement in both files: panel targets, variables and rule queries."""
    flat = []
    stack = list(dashboard["panels"])
    while stack:
        panel = stack.pop()
        stack.extend(panel.get("panels", []))
        flat.extend(t["rawSql"] for t in panel.get("targets", []))
    flat.extend(
        v["query"]["query"] for v in dashboard["templating"]["list"] if v["type"] == "query"
    )
    flat.extend(
        step["model"]["rawSql"]
        for rule in alerts["groups"][0]["rules"]
        for step in rule["data"]
        if step["datasourceUid"] != "__expr__"
    )
    return flat


def _rule(alerts: dict[str, Any], uid: str) -> dict[str, Any]:
    return next(r for r in alerts["groups"][0]["rules"] if r["uid"] == uid)


def _threshold(alerts: dict[str, Any], uid: str) -> float:
    model = next(
        s["model"] for s in _rule(alerts, uid)["data"] if s["model"].get("type") == "threshold"
    )
    return model["conditions"][0]["evaluator"]["params"][0]


def _panel(dashboard: dict[str, Any], panel_id: int) -> dict[str, Any]:
    return next(p for p in dashboard["panels"] if p["id"] == panel_id)


def test_the_repository_files_are_the_default_render() -> None:
    """They are what a hand import downloads; bin/grafana.py rewrites them from the templates."""
    for name, document in (("weather.json", render.dashboard), ("alerts.json", render.alerts)):
        assert (REPO / "grafana" / name).read_text(encoding="utf-8") == render.dumps(
            document(Units())
        ), f"grafana/{name} is out of date: run .venv/bin/python bin/grafana.py"


@pytest.mark.parametrize("units", EVERY_UNITS, ids=UNIT_IDS)
def test_every_choice_renders_completely_and_names_only_what_is_written(units: Units) -> None:
    dashboard, alerts = render.dashboard(units), render.alerts(units)
    written = schema(units)
    fields = set().union(*written.values())

    assert "%{" not in json.dumps(dashboard) + json.dumps(alerts)
    for sql in _queries(dashboard, alerts):
        assert queried_tables(sql) <= written.keys(), sql
        assert queried_fields(sql) <= fields, sql


@pytest.mark.parametrize("units", EVERY_UNITS, ids=UNIT_IDS)
def test_every_display_unit_is_one_grafana_has(units: Units) -> None:
    for key, value in _strings(render.dashboard(units)):
        if key in {"unit", "value"} and value in GRAFANA_IDS | set(render.GRAFANA_UNITS.values()):
            assert value in GRAFANA_IDS or value.startswith("suffix: "), value


def test_numbers_follow_the_units() -> None:
    """Worked out by hand rather than through units.convert, which the renderer itself uses."""
    american = Units(temperature="f", pressure="inhg", rain="in", wind="mph")
    alerts, dashboard = render.alerts(american), render.dashboard(american)

    assert _threshold(alerts, "ecowitt-cold") == 46.4  # 8 °C
    assert _threshold(alerts, "ecowitt-hot") == 89.6  # 32 °C
    assert _threshold(alerts, "ecowitt-gusts") == 37.3  # 60 km/h
    assert _threshold(alerts, "ecowitt-rain") == 0.394  # 10 mm/h
    assert _threshold(alerts, "ecowitt-pressure-fall") == 0.0886  # 3 hPa
    # A difference of 2 °C is 3.6 °F: no 32 added.
    damp = _rule(alerts, "ecowitt-damp")["annotations"]["item"]
    assert "gt $values.D.Value 3.6 " in damp
    # 0.7 °C is 1.26 °F.
    close = next(
        s for s in _rule(alerts, "ecowitt-open-windows-damper")["data"] if s["refId"] == "E"
    )
    assert close["model"]["expression"] == "$A >= 0.75 && ($C >= 1.26 || $D >= 4)"
    temperature = _panel(dashboard, 3)["fieldConfig"]["defaults"]
    assert [s["value"] for s in temperature["thresholds"]["steps"]] == [None, 41, 77, 89.6]
    assert temperature["unit"] == "fahrenheit"
    trend = _panel(dashboard, 10)["fieldConfig"]["defaults"]
    assert (trend["unit"], trend["decimals"]) == ("pressurehg", 2)
    delta = _panel(dashboard, 37)["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert [s["value"] for s in delta] == [None, -5.4, 5.4]


def test_messages_name_the_units() -> None:
    alerts = render.alerts(Units(temperature="f", pressure="inhg", rain="in", wind="ms"))

    assert _rule(alerts, "ecowitt-cold")["annotations"]["headline"].startswith(
        "These rooms are below 46.4 °F"
    )
    assert "m/s" in _rule(alerts, "ecowitt-gusts")["annotations"]["summary"]
    assert "in/h" in _rule(alerts, "ecowitt-rain")["annotations"]["description"]
    pressure = _rule(alerts, "ecowitt-pressure-fall")["annotations"]["summary"]
    assert '{{ printf "%.2f" $values.A.Value }} inHg' in pressure


def test_the_templates_leave_nothing_unit_bound_outside_a_placeholder() -> None:
    """A field, display unit or unit word written out in the defaults is a spot the units do
    not reach -- the way a template falls behind when a panel is added to the rendered file."""
    convertible = {
        name
        for name in set().union(*schema().values())
        if re.search(r"_(c|hpa|kmh|mm|mm_h)$", name)
    }
    for name in ("weather.template.json", "alerts.template.json"):
        text = render.PLACEHOLDER.sub("", (render.TEMPLATES / name).read_text(encoding="utf-8"))
        assert not {w for w in re.findall(r"\b[a-z][a-z0-9_]*\b", text) if w in convertible}
        assert not re.search(r"celsius|velocitykmh|pressurehpa|suffix: mm|°C|km/h|hPa", text)


def test_a_lone_number_becomes_a_number_and_text_stays_text() -> None:
    feet = Units(wind="mph")

    assert render.render(["%{60 speed}", "%{decimals rain}"], feet) == [37.3, 1]
    assert render.render("above %{60 speed} %{symbol speed}", feet) == "above 37.3 mph"
    assert render.render("%{unit speed}", feet) == "velocitymph"
    assert render.render({"n": 3, "flag": True}, feet) == {"n": 3, "flag": True}


@pytest.mark.parametrize(
    "template", ["%{temp}", "%{8 furlongs}", "%{size speed}", "%{8 speed extra}"]
)
def test_an_unknown_placeholder_is_refused(template: str) -> None:
    with pytest.raises(render.UnknownPlaceholder):
        render.render(template, Units())


def test_zero_converts_to_zero() -> None:
    assert render.render("%{0 rain}", Units(rain="in")) == 0


def test_the_script_writes_the_default_render(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("grafana_script", REPO / "bin" / "grafana.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    (tmp_path / "grafana").mkdir()

    script.main(["--root", str(tmp_path)])

    for name in ("weather.json", "alerts.json"):
        assert (tmp_path / "grafana" / name).read_text(encoding="utf-8") == (
            REPO / "grafana" / name
        ).read_text(encoding="utf-8")

"""The metrics, checked against what the collector writes."""

from __future__ import annotations

import re

import pytest

from ecowitt.core.units import Kind, Units
from ecowitt.dashboard.catalogue import CHOICES, METRICS, SYMBOLS, Scope, rounded, unit

from .conftest import REPO

#: The collector's pinned output: every table and field its pipeline writes for these payloads.
GOLDEN = sorted((REPO / "collector/tests/fixtures").glob("*.lp"))
LINE = re.compile(r"((?:[^ \\]|\\.)+) ((?:[^ \\]|\\.)+) \d+")


def written() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for golden in GOLDEN:
        for line in golden.read_text(encoding="utf-8").splitlines():
            match = LINE.fullmatch(line)
            assert match, line
            series, values = match.groups()
            table = re.split(r"(?<!\\),", series)[0]
            tables.setdefault(table, set()).update(re.findall(r"(?:^|,)([a-z0-9_]+)=", values))
    return tables


@pytest.mark.parametrize("metric", METRICS.values(), ids=lambda m: m.id)
def test_every_metric_is_a_field_the_collector_writes(metric) -> None:  # type: ignore[no-untyped-def]
    tables = written()
    assert GOLDEN
    for table in metric.tables:
        assert metric.field(Units()) in tables.get(table, set()), (table, metric.field(Units()))


def test_stored_names_follow_the_stations_units() -> None:
    imperial = Units(temperature="f", pressure="inhg", rain="in", wind="mph")
    assert METRICS["outdoor.temperature"].field(imperial) == "temp_f"
    assert METRICS["rain.rate"].field(imperial) == "rate_in_h"
    assert METRICS["solar.uv_index"].field(imperial) == "uv_index"


def test_scopes_pick_their_sensors() -> None:
    rooms, outdoor, wind = (
        METRICS["rooms.humidity"],
        METRICS["outdoor.humidity"],
        METRICS["wind.gust"],
    )
    assert [rooms.covers(s) for s in ("indoor", "ch12", "outdoor", "pressure", None)] == [
        True, True, False, False, False,
    ]  # fmt: skip
    assert (outdoor.covers("outdoor"), outdoor.covers("bgt")) == (True, False)
    assert wind.covers(None)
    assert (outdoor.sensors(), rooms.sensors(), wind.sensors()) == (["outdoor"], None, None)
    assert rooms.scope is Scope.ROOMS and rooms.per_sensor and not outdoor.per_sensor


def test_every_unit_has_a_symbol() -> None:
    for codes in CHOICES.values():
        assert all(code in SYMBOLS for code in codes)
    for metric in METRICS.values():
        for units in (Units(), Units("f", "inhg", "in", "mph", "mi")):
            assert unit(metric.kind, units) in SYMBOLS


def test_values_are_rounded_to_what_their_unit_is_worth() -> None:
    assert rounded(1013.2567, "hpa") == 1013.3
    assert rounded(29.9213, "inhg") == 29.92
    assert rounded(54.6, "pct") == 55
    assert unit(Kind.RAIN_RATE, Units(rain="in")) == "in_h"

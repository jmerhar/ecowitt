"""The field table: every known key maps to exactly one row, and every row is reachable."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecowitt.collector.ingest import fields
from ecowitt.collector.units import CONVERTIBLE, Kind, to_canonical

KNOWN_KEYS = [
    line.strip()
    for line in (Path(__file__).parent.parent / "fixtures" / "known_keys.txt")
    .read_text()
    .splitlines()
    if line.strip() and not line.startswith("#")
]
STORED_KEYS = [k for k in KNOWN_KEYS if k not in fields.NOT_STORED]


def test_the_known_keys_list_is_substantial() -> None:
    """Guards against the fixture being emptied, which would pass every test below."""
    assert len(KNOWN_KEYS) > 400


@pytest.mark.parametrize("key", STORED_KEYS)
def test_every_known_key_matches_exactly_one_spec(key: str) -> None:
    """None falls through to `unmapped`, and none is claimed by two rows.

    A key matching no row is not lost -- it is stored as unmapped -- so a typo in a pattern
    fails nothing else in the suite. This is the test that catches it.
    """
    hits = [spec for spec in fields.SPECS if spec.pattern.fullmatch(key)]

    assert len(hits) == 1, [(h.table, h.field) for h in hits]


def test_every_spec_is_reached_by_some_known_key() -> None:
    """A row no known key reaches is either dead or mistyped."""
    unreached = [
        spec.pattern.pattern
        for spec in fields.SPECS
        if not any(spec.pattern.fullmatch(key) for key in STORED_KEYS)
    ]

    assert unreached == []


@pytest.mark.parametrize("spec", fields.SPECS, ids=lambda s: s.pattern.pattern)
def test_every_spec_declares_a_unit_its_kind_converts_from(spec: fields.FieldSpec) -> None:
    """Convertible kinds name their source unit; every other kind names none."""
    if spec.kind in CONVERTIBLE:
        assert spec.unit is not None
        to_canonical(spec.kind, spec.unit, 1.0)
    else:
        assert spec.unit is None


@pytest.mark.parametrize(
    ("key", "table", "field", "sensor", "tags"),
    [
        ("tempinf", "indoor", "temp", "indoor", ()),
        ("temp3f", "channel", "temp", "ch3", (("channel", "3"),)),
        ("humidity8", "channel", "humidity", "ch8", (("channel", "8"),)),
        ("soilmoisture12", "soil", "moisture", "soil12", (("channel", "12"),)),
        ("dailyrainin", "rain", "daily", "rain", (("gauge", "bucket"),)),
        ("drain_piezomm", "rain", "daily", "piezo", (("gauge", "piezo"),)),
        ("wbgt", "outdoor", "wbgt", "bgt", ()),
        ("tf_ch2", "probe", "temp", "probe2", (("channel", "2"),)),
        ("batt5", "battery", "low", "ch5", ()),
        ("wh25batt", "battery", "low", "indoor", ()),
        ("wh65batt", "battery", "low", "outdoor", ()),
        ("wh90batt", "battery", "voltage", "outdoor", ()),
        ("wh40batt", "battery", "voltage", "wh40", ()),
    ],
)
def test_representative_keys_land_where_expected(
    key: str, table: str, field: str, sensor: str, tags: tuple[tuple[str, str], ...]
) -> None:
    """Templates are filled from the key: channel numbers, rain periods, sensor ids."""
    found = fields.match(key)
    assert found is not None
    spec, groups = found

    assert spec.table == table
    assert spec.field.format(**groups) == field
    assert spec.sensor is not None and spec.sensor.format(**groups) == sensor
    assert tuple((k, v.format(**groups)) for k, v in spec.tags) == tags


@pytest.mark.parametrize(
    ("key", "unit"),
    [
        ("wbgt", "f"),
        ("wbgtc", "c"),
        ("tf_co2", "f"),
        ("tf_co2c", "c"),
        ("tf_ch1", "f"),
        ("tf_ch1c", "c"),
        ("soil_ec_temp3", "f"),
        ("soil_ec_temp3c", "c"),
        ("tempf", "f"),
    ],
)
def test_bare_and_suffixed_temperature_spellings(key: str, unit: str) -> None:
    """Newer families send Fahrenheit under the bare stem; older ones suffix it with `f`."""
    found = fields.match(key)

    assert found is not None
    assert found[0].kind is Kind.TEMPERATURE
    assert found[0].unit == unit


def test_battery_encodings_follow_their_family() -> None:
    """A 0/1 flag, a voltage and a 0-5 level are three different fields."""
    kinds = {key: fields.match(key)[0] for key in ("batt1", "wh65batt", "tf_batt1", "pm25batt1")}  # type: ignore[index]

    assert (kinds["batt1"].field, kinds["batt1"].kind) == ("low", Kind.FLAG)
    assert (kinds["wh65batt"].field, kinds["wh65batt"].kind) == ("low", Kind.FLAG)
    assert (kinds["tf_batt1"].field, kinds["tf_batt1"].kind) == ("voltage", Kind.VOLTAGE)
    assert (kinds["pm25batt1"].field, kinds["pm25batt1"].kind) == ("level", Kind.LEVEL)


@pytest.mark.parametrize("key", ["PASSKEY", "PASSWORD", "ID", "dateutc"])
def test_credentials_and_plumbing_are_never_stored(key: str) -> None:
    """These are consumed or discarded, never written."""
    assert key in fields.NOT_STORED


def test_an_unknown_key_matches_nothing() -> None:
    """Which is what sends it to the unmapped table."""
    assert fields.match("frobnicator_ch1") is None

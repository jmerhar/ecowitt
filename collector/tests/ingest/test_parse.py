"""Parsing a report into canonical readings."""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime

import pytest

from ecowitt.collector.ingest.parse import MAX_CLOCK_SKEW_SECONDS, parse
from ecowitt.collector.readings import Reading
from ecowitt.collector.units import Kind

from ..conftest import payload

#: The moment the recorded payload's station clock read, as Unix seconds.
RECORDED_AT = int(datetime(2026, 10, 8, 23, 1, 24, tzinfo=UTC).timestamp())
RECEIVED = datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC)


def _fields(name: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(payload(name), keep_blank_values=True))


def _find(readings: list[Reading], table: str, field: str, sensor: str | None = None) -> Reading:
    matches = [
        r
        for r in readings
        if r.table == table and r.field == field and (sensor is None or r.sensor == sensor)
    ]
    assert len(matches) == 1, matches
    return matches[0]


def test_the_recorded_payload_parses_completely() -> None:
    """Every field of a real HP2551 upload lands somewhere, and nothing goes to unmapped."""
    report = parse(_fields("hp2551_indoor"), RECEIVED)

    assert report.timestamp == RECORDED_AT
    assert not [r for r in report.readings if r.table == "unmapped"]
    indoor = _find(report.readings, "indoor", "temp")
    assert indoor.value == pytest.approx((73.8 - 32) * 5 / 9)
    assert _find(report.readings, "channel", "temp", "ch8").value == pytest.approx(
        (74.1 - 32) * 5 / 9
    )
    assert _find(report.readings, "pressure", "abs").value == pytest.approx(29.796 * 33.8638866667)
    assert _find(report.readings, "station", "model").value == "HP2551AE_Pro_V2.1.4"
    assert _find(report.readings, "battery", "low", "ch3").value is False


def test_credentials_never_become_readings() -> None:
    """PASSKEY and PASSWORD are read by nothing that stores."""
    report = parse({"PASSKEY": "ABC", "PASSWORD": "pw", "ID": "x", "tempf": "50"}, RECEIVED)

    assert [r.field for r in report.readings] == ["temp"]
    assert "ABC" not in repr(report) and "pw" not in repr(report)


def test_celsius_and_fahrenheit_spellings_agree() -> None:
    """Firmware that sends Celsius is converted to the same canonical value."""
    imperial = parse({"tempf": "68"}, RECEIVED).readings[0]
    metric = parse({"tempc": "20"}, RECEIVED).readings[0]

    assert (imperial.table, imperial.field) == (metric.table, metric.field)
    assert imperial.value == pytest.approx(metric.value)


@pytest.mark.parametrize("value", ["--", "", "None", "nan", "inf", "-inf", "12,5"])
def test_an_unusable_value_is_skipped_and_the_rest_kept(value: str) -> None:
    """One bad field costs that field, not the report."""
    report = parse({"tempf": value, "humidity": "71"}, RECEIVED)

    assert [(r.field, r.value) for r in report.readings] == [("humidity", 71.0)]


def test_a_flag_is_true_for_any_non_zero_value() -> None:
    """A battery low flag or a leak is a boolean, whatever number carries it."""
    readings = parse({"batt1": "1", "batt2": "0", "leak_ch1": "1"}, RECEIVED).readings

    assert [r.value for r in readings] == [True, False, True]


def test_text_is_kept_trimmed() -> None:
    """Console metadata is stored as strings."""
    reading = parse({"freq": " 868M "}, RECEIVED).readings[0]

    assert (reading.kind, reading.value) == (Kind.TEXT, "868M")


def test_an_unknown_numeric_key_is_kept_under_its_own_name() -> None:
    """A sensor this server has never heard of still produces data."""
    reading = parse({"frob_ch1": "12.5"}, RECEIVED).readings[0]

    assert (reading.table, reading.field, reading.value) == ("unmapped", "frob_ch1", 12.5)


def test_an_unknown_textual_key_gets_a_distinct_field() -> None:
    """Text and numbers under one key would conflict once InfluxDB fixed the field's type."""
    readings = parse({"frob": "--", "frob2": "7"}, RECEIVED).readings

    assert {(r.field, r.kind) for r in readings} == {
        ("frob_text", Kind.TEXT),
        ("frob2", Kind.COUNT),
    }


def test_channel_templates_are_filled() -> None:
    """The channel number lands in the tags, the sensor id and nowhere else."""
    reading = parse({"humidity7": "60"}, RECEIVED).readings[0]

    assert reading.tags == (("channel", "7"),)
    assert reading.sensor == "ch7"
    assert reading.field == "humidity"


def test_a_spec_with_an_unconvertible_unit_drops_only_that_field(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken table row is logged as a bug, and the rest of the report survives it."""
    from ecowitt.collector.ingest import fields

    broken = fields.spec("tempf", "outdoor", "temp", Kind.TEMPERATURE, "kelvin", sensor="outdoor")
    monkeypatch.setattr(fields, "SPECS", [broken, *fields.SPECS])

    report = parse({"tempf": "50", "humidity": "40"}, RECEIVED)

    assert [r.field for r in report.readings] == ["humidity"]
    assert "no conversion" in caplog.text


class TestTimestamp:
    """Which clock a report is timestamped with."""

    def test_the_station_clock_is_used_when_plausible(self) -> None:
        report = parse({"dateutc": "2026-10-08 23:01:24"}, RECEIVED)

        assert report.timestamp == RECORDED_AT
        assert _find(report.readings, "station", "clock_skew").value == 2.0

    def test_unix_seconds_are_accepted(self) -> None:
        assert parse({"dateutc": str(RECORDED_AT)}, RECEIVED).timestamp == RECORDED_AT

    @pytest.mark.parametrize(
        "dateutc", [None, "", "now", "yesterday", "2026-13-45 99:99:99", "9" * 30]
    )
    def test_receipt_time_when_the_station_gives_none_usable(self, dateutc: str | None) -> None:
        raw = {} if dateutc is None else {"dateutc": dateutc}

        report = parse(raw, RECEIVED)

        assert report.timestamp == int(RECEIVED.timestamp())
        assert not [r for r in report.readings if r.field == "clock_skew"]

    def test_a_badly_wrong_clock_is_replaced_but_its_skew_recorded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A console back from a power cut thinking it is 2000 is not believed."""
        report = parse({"dateutc": "2000-01-01 00:00:00"}, RECEIVED)

        assert report.timestamp == int(RECEIVED.timestamp())
        skew = _find(report.readings, "station", "clock_skew").value
        assert skew > MAX_CLOCK_SKEW_SECONDS
        assert "station clock" in caplog.text

    def test_the_skew_limit_is_inclusive(self) -> None:
        """Exactly the limit is still believed; one second more is not."""
        at_limit = datetime.fromtimestamp(RECORDED_AT + MAX_CLOCK_SKEW_SECONDS, UTC)
        beyond = datetime.fromtimestamp(RECORDED_AT + MAX_CLOCK_SKEW_SECONDS + 1, UTC)

        assert parse({"dateutc": "2026-10-08 23:01:24"}, at_limit).timestamp == RECORDED_AT
        assert parse({"dateutc": "2026-10-08 23:01:24"}, beyond).timestamp != RECORDED_AT

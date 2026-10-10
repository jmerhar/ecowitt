"""Reading back from InfluxDB 3 with SQL, against a real HTTP server answering each query."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ecowitt.core.store import influx3
from ecowitt.core.store.factory import reader_for
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.store.query import Aggregate, Extreme, ReadError
from ecowitt.core.store.settings import KINDS, reader_from
from ecowitt.core.testing import Received, StubInflux

START = datetime(2026, 10, 10, tzinfo=UTC)
END = START + timedelta(days=1)
#: Columns by table; tags are upper-case here, and stored as InfluxDB stores tags.
COLUMNS = {
    "outdoor": ["time", "STATION", "SENSOR", "NAME", "temp_c", "humidity_pct"],
    "pressure": ["time", "STATION", "sea_hpa"],
    "battery": ["time", "STATION", "SENSOR", "low"],
    "rain": ["time", "STATION", "GAUGE", "rate_mm_h"],
    "wind": ["time", "STATION", "dir_deg", "speed_kmh"],
    "station_info": ["time", "STATION", "timezone", "units_temperature", "sensor_ch1"],
}


class Database:
    """Answers the catalogue query from COLUMNS and every other query with `rows`."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.status = 200
        self.error = ""
        self.queries: list[dict[str, Any]] = []

    def __call__(self, request: Received) -> tuple[int, str]:
        body = json.loads(request.body)
        if "information_schema" in body["q"]:
            columns = [
                {
                    "table_name": table,
                    "column_name": column.lower(),
                    "data_type": "Dictionary(Int32, Utf8)" if column.isupper() else "Float64",
                }
                for table, names in COLUMNS.items()
                for column in names
            ]
            return 200, json.dumps(columns)
        self.queries.append(body)
        if self.status != 200:
            return self.status, self.error
        return 200, json.dumps(self.rows)


@pytest.fixture
async def db(influx: StubInflux) -> Database:
    database = Database()
    influx.respond = database
    return database


@pytest.fixture
async def reader(influx: StubInflux, db: Database) -> AsyncIterator[Influx3Store]:
    store = Influx3Store(influx.url, "weather", "apiv3_read")
    yield store
    await store.aclose()


async def test_a_query_goes_to_query_sql_with_the_token_and_parameters(
    reader: Influx3Store, influx: StubInflux, db: Database
) -> None:
    db.rows = [{"timezone": "Europe/Lisbon", "units_temperature": "f", "sensor_ch1": "Attic"}]
    info = await reader.station_info("home")
    assert info is not None
    assert (info.timezone, info.units.temperature, info.sensors) == (
        "Europe/Lisbon",
        "f",
        {"ch1": "Attic"},
    )
    request = influx.requests[-1]
    assert request.path == "/api/v3/query_sql"
    assert request.headers["authorization"] == "Bearer apiv3_read"
    assert db.queries[-1]["db"] == "weather"
    assert db.queries[-1]["params"] == {"station": "home"}
    assert "home" not in db.queries[-1]["q"]


async def test_a_station_that_published_nothing_has_no_info(
    reader: Influx3Store, db: Database
) -> None:
    assert await reader.station_info("home") is None


async def test_stations_are_listed(reader: Influx3Store, db: Database) -> None:
    db.rows = [{"station": "a"}, {"station": "b"}, {}]
    assert await reader.stations() == ["a", "b"]


async def test_a_missing_table_reads_as_no_rows(reader: Influx3Store, db: Database) -> None:
    db.status, db.error = 400, "Error during planning: table 'public.iox.station_info' not found"
    assert await reader.stations() == []


async def test_a_span_takes_first_and_last_values_per_sensor(
    reader: Influx3Store, db: Database
) -> None:
    db.rows = [
        {
            "sensor": "outdoor",
            "name": "Garden",
            "first_time": "2026-10-10T00:00:30",
            "last_time": "2026-10-10T10:18:42.123456789",
            "first_0": 12.5,
            "last_0": 17.6,
            "last_1": 80.0,
        },
        # A group whose window held no rows at all.
        {"sensor": "ch9"},
    ]
    spans = await reader.span(
        "home", "outdoor", ["temp_c", "humidity_pct", "wind_kmh"], start=START, end=END
    )
    assert len(spans) == 1
    span = spans[0]
    assert (span.tags, span.sensor, span.name) == ({"sensor": "outdoor"}, "outdoor", "Garden")
    assert span.first == {"temp_c": 12.5}
    assert span.last == {"temp_c": 17.6, "humidity_pct": 80.0}
    assert span.last_time == datetime(2026, 10, 10, 10, 18, 42, 123456, tzinfo=UTC)
    sql = db.queries[-1]["q"]
    assert "wind_kmh" not in sql, "a field the table lacks is not queried"
    assert "GROUP BY sensor" in sql
    assert "TIMESTAMP '2026-10-10T00:00:00Z'" in sql
    assert "TIMESTAMP '2026-10-11T00:00:00Z'" in sql


async def test_a_table_without_sensors_is_one_group(reader: Influx3Store, db: Database) -> None:
    db.rows = [{"first_time": "2026-10-10T00:00:00", "last_time": "2026-10-10T03:00:00"}]
    spans = await reader.span("home", "pressure", ["sea_hpa"], start=START, end=END)
    assert spans[0].tags == {} and spans[0].sensor is None and spans[0].last == {}
    assert "GROUP BY" not in db.queries[-1]["q"]


async def test_a_table_with_sensors_but_no_names_groups_without_them(
    reader: Influx3Store, db: Database
) -> None:
    db.rows = [
        {"sensor": "ch1", "first_time": "2026-10-10T00:00:00", "last_time": "2026-10-10T00:00:00"}
    ]
    (span,) = await reader.span("home", "battery", ["low"], start=START, end=END)
    assert (span.sensor, span.name) == ("ch1", None)
    assert "name" not in db.queries[-1]["q"]


async def test_an_empty_window_has_no_span(reader: Influx3Store, db: Database) -> None:
    db.rows = [{}]
    assert await reader.span("home", "pressure", ["sea_hpa"], start=START, end=END) == []


async def test_fields_none_of_which_exist_are_not_queried(
    reader: Influx3Store, db: Database
) -> None:
    assert await reader.span("home", "solar", ["uv_index"], start=START, end=END) == []
    assert await reader.extremes("home", "outdoor", ["temp_f"], start=START, end=END) == []
    found = await reader.buckets(
        "home",
        "outdoor",
        [("temp_f", Aggregate.MEAN)],
        start=START,
        end=END,
        step=timedelta(hours=1),
        origin=START,
    )
    assert found == []
    assert db.queries == []


async def test_sensors_are_filtered_by_parameter(reader: Influx3Store, db: Database) -> None:
    await reader.span(
        "home", "outdoor", ["temp_c"], start=START, end=END, sensors=["outdoor", "ch1"]
    )
    query = db.queries[-1]
    assert "sensor IN ($s0, $s1)" in query["q"]
    assert query["params"] == {"station": "home", "s0": "ch1", "s1": "outdoor"}


async def test_an_empty_sensor_filter_matches_nothing(reader: Influx3Store, db: Database) -> None:
    assert await reader.span("home", "outdoor", ["temp_c"], start=START, end=END, sensors=[]) == []
    assert db.queries == []


async def test_a_sensor_filter_on_a_table_without_sensors_is_ignored(
    reader: Influx3Store, db: Database
) -> None:
    await reader.span("home", "pressure", ["sea_hpa"], start=START, end=END, sensors=["x"])
    assert "sensor" not in db.queries[-1]["q"]


async def test_rain_groups_by_gauge(reader: Influx3Store, db: Database) -> None:
    db.rows = [
        {
            "gauge": "bucket",
            "first_time": "2026-10-10T00:00:00",
            "last_time": "2026-10-10T00:00:00",
        },
        {"gauge": "piezo", "first_time": "2026-10-10T00:00:00", "last_time": "2026-10-10T00:00:00"},
    ]
    spans = await reader.span("home", "rain", ["rate_mm_h"], start=START, end=END)
    assert [span.tags for span in spans] == [{"gauge": "bucket"}, {"gauge": "piezo"}]
    assert "GROUP BY gauge" in db.queries[-1]["q"]


async def test_extremes_come_with_the_time_each_was_first_reached(
    reader: Influx3Store, db: Database
) -> None:
    db.rows = [
        {
            "sensor": "outdoor",
            "name": "Garden",
            "min_0": 11.0,
            "min_0_at": "2026-10-10T06:00:00",
            "max_0": 21.0,
            "max_0_at": "2026-10-10T14:00:00",
        },
        {"sensor": "ch1"},
    ]
    found = await reader.extremes("home", "outdoor", ["temp_c"], start=START, end=END)
    assert len(found) == 1
    assert found[0].minimum == {"temp_c": Extreme(11.0, datetime(2026, 10, 10, 6, tzinfo=UTC))}
    assert found[0].maximum == {"temp_c": Extreme(21.0, datetime(2026, 10, 10, 14, tzinfo=UTC))}
    assert 'ORDER BY "temp_c" DESC NULLS LAST, time' in db.queries[-1]["q"]


async def test_buckets_group_by_sensor_and_bucket_in_order(
    reader: Influx3Store, db: Database
) -> None:
    db.rows = [
        {"sensor": "outdoor", "bucket": "2026-10-10T00:00:00", "value_0": 12.0, "name": "Old"},
        {"sensor": "outdoor", "bucket": "2026-10-10T01:00:00", "name": "Garden"},
        {"sensor": "ch1", "bucket": "2026-10-10T00:00:00", "value_0": 20.0, "value_1": 21},
    ]
    found = await reader.buckets(
        "home",
        "outdoor",
        [("temp_c", Aggregate.MEAN), ("temp_c", Aggregate.MAX), ("temp_c", Aggregate.MEAN)],
        start=START,
        end=END,
        step=timedelta(hours=1),
        origin=START - timedelta(hours=1),
    )
    garden, attic = found
    assert (garden.tags, garden.name) == ({"sensor": "outdoor"}, "Garden")
    assert garden.times == [START, START + timedelta(hours=1)]
    assert garden.values == {
        ("temp_c", Aggregate.MEAN): [12.0, None],
        ("temp_c", Aggregate.MAX): [None, None],
    }
    assert attic.values[("temp_c", Aggregate.MAX)] == [21.0]
    sql = db.queries[-1]["q"]
    assert "date_bin(INTERVAL '3600 seconds', time, TIMESTAMP '2026-10-09T23:00:00Z')" in sql
    assert "GROUP BY sensor, bucket ORDER BY sensor, bucket" in sql


async def test_a_circular_mean_is_an_angle_between_0_and_360(
    reader: Influx3Store, db: Database
) -> None:
    db.rows = [{"bucket": "2026-10-10T00:00:00", "value_0": -10.0}]
    (found,) = await reader.buckets(
        "home",
        "wind",
        [("dir_deg", Aggregate.CIRCULAR)],
        start=START,
        end=END,
        step=timedelta(hours=1),
        origin=START,
    )
    assert found.values[("dir_deg", Aggregate.CIRCULAR)] == [350.0]
    assert (
        'atan2(avg(sin(radians("dir_deg"))), avg(cos(radians("dir_deg"))))' in db.queries[-1]["q"]
    )


@pytest.mark.parametrize("aggregate", [Aggregate.MIN, Aggregate.MAX, Aggregate.MEAN])
async def test_each_aggregate_has_its_sql(
    reader: Influx3Store, db: Database, aggregate: Aggregate
) -> None:
    await reader.buckets(
        "home",
        "wind",
        [("speed_kmh", aggregate)],
        start=START,
        end=END,
        step=timedelta(minutes=5),
        origin=START,
    )
    function = {"min": "min", "max": "max", "mean": "avg"}[aggregate.value]
    assert f'{function}("speed_kmh") AS value_0' in db.queries[-1]["q"]


async def test_a_bucket_shorter_than_a_second_is_refused(reader: Influx3Store) -> None:
    with pytest.raises(ValueError, match="at least a second"):
        await reader.buckets(
            "home",
            "wind",
            [("speed_kmh", Aggregate.MEAN)],
            start=START,
            end=END,
            step=timedelta(0),
            origin=START,
        )


@pytest.mark.parametrize("name", ["temp_c; DROP", "Temp", "time", "sensor", 'a"b'])
async def test_anything_but_a_field_name_is_refused(reader: Influx3Store, name: str) -> None:
    with pytest.raises(ValueError, match="not a field name"):
        await reader.span("home", "outdoor", [name], start=START, end=END)


async def test_anything_but_a_table_name_is_refused(reader: Influx3Store) -> None:
    with pytest.raises(ValueError, match="not a table name"):
        await reader.span("home", 'outdoor" --', ["temp_c"], start=START, end=END)


async def test_a_naive_time_is_refused(reader: Influx3Store) -> None:
    with pytest.raises(ValueError, match="time zone"):
        await reader.span("home", "outdoor", ["temp_c"], start=datetime(2026, 1, 1), end=END)


async def test_the_catalogue_is_cached(
    reader: Influx3Store, influx: StubInflux, monkeypatch: pytest.MonkeyPatch
) -> None:
    await reader.span("home", "outdoor", ["temp_c"], start=START, end=END)
    await reader.span("home", "outdoor", ["temp_c"], start=START, end=END)
    catalogue = [r for r in influx.requests if "information_schema" in r.body]
    assert len(catalogue) == 1
    monkeypatch.setattr(influx3, "COLUMNS_TTL_SECONDS", -1.0)
    await reader.span("home", "outdoor", ["temp_c"], start=START, end=END)
    assert len([r for r in influx.requests if "information_schema" in r.body]) == 2


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "the token was not accepted"),
        (403, "the token may not read that database"),
        (404, "no such database"),
        (500, "InfluxDB answered HTTP 500"),
        (400, "InfluxDB answered HTTP 400"),
    ],
)
async def test_a_failed_query_raises_with_the_reason(
    reader: Influx3Store, db: Database, status: int, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    db.status, db.error = status, "Schema error: internals"
    with caplog.at_level(logging.ERROR), pytest.raises(ReadError) as raised:
        await reader.stations()
    assert str(raised.value) == reason
    assert "internals" in caplog.text, "the body is logged for the operator"
    assert await reader.check_read() == reason


async def test_an_answer_that_is_not_rows_is_an_error(reader: Influx3Store, db: Database) -> None:
    db.rows = {"error": "no"}  # type: ignore[assignment]
    with pytest.raises(ReadError, match="other than rows"):
        await reader.stations()


async def test_a_check_runs_a_trivial_query(reader: Influx3Store, db: Database) -> None:
    db.rows = [{"Int64(1)": 1}]
    assert await reader.check_read() is None
    assert db.queries[-1]["q"] == "SELECT 1"


async def test_an_unreachable_server_cannot_be_read() -> None:
    store = Influx3Store("http://127.0.0.1:1", "weather")
    try:
        assert await store.check_read() == "cannot connect (ConnectError)"
        with pytest.raises(ReadError):
            await store.stations()
    finally:
        await store.aclose()


async def test_without_a_url_nothing_is_read() -> None:
    store = Influx3Store("", "weather")
    try:
        assert await store.check_read() == "no database is configured"
        with pytest.raises(ReadError, match="no database"):
            await store.stations()
    finally:
        await store.aclose()


async def test_no_token_sends_no_authorization(influx: StubInflux, db: Database) -> None:
    store = Influx3Store(influx.url, "weather")
    try:
        await store.stations()
    finally:
        await store.aclose()
    assert "authorization" not in influx.requests[-1].headers


async def test_only_influxdb_3_can_be_read() -> None:
    assert [kind.name for kind in KINDS.values() if kind.readable] == ["influx3"]
    reader = reader_from("influx3", {"url": "http://db:8181"})
    assert isinstance(reader, Influx3Store) and reader.database == "weather"
    await reader.aclose()
    with pytest.raises(ValueError, match="not supported"):
        reader_for("influx2", url="http://db:8086", database="weather")
    with pytest.raises(ValueError, match="URL is required"):
        reader_from("influx3", {})

"""Recomputing a station's 10 m wind over its stored history."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

import pytest

from ecowitt.collector.admin.stationconfig import Station
from ecowitt.collector.delivery.recompute import WindRecompute
from ecowitt.core.preferences import Preferences
from ecowitt.core.store.base import Row
from ecowitt.core.store.query import Point, ReadError, Span

#: 2026-10-10 00:00 UTC, the first stored reading.
FIRST = datetime(2026, 10, 10, tzinfo=UTC)
NOW = FIRST + timedelta(days=2, hours=1)

HOME = Station(
    "Home",
    Preferences(wind_factor=2.0),
    "K",
    latitude=45.0,
    longitude=7.0,
    weather_model="best_match",
)


def wind(at: datetime, speed: float, gust: float) -> Point:
    return Point(at, {}, {"speed_kmh": speed, "gust_kmh": gust})


def model(at: datetime, speed: float, gust: float, name: str = "best_match") -> Point:
    return Point(
        at, {"model": name, "source": "open_meteo"}, {"speed_kmh": speed, "gust_kmh": gust}
    )


class Reader:
    """Answers from stored points, by table, as the database would within each window."""

    def __init__(self, tables: dict[str, list[Point]], *, fail: Exception | None = None) -> None:
        self.tables = tables
        self.fail = fail
        self.asked: list[tuple[str, datetime, datetime]] = []
        self.closed = False

    async def span(self, station: str, table: str, fields: Collection[str], *, start, end):  # noqa: ANN001, ANN201
        points = [p for p in self.tables.get(table, []) if start <= p.time <= end]
        if not points:
            return []
        return [Span({}, None, points[0].time, points[-1].time)]

    async def points(self, station: str, table: str, fields: Collection[str], *, start, end):  # noqa: ANN001, ANN201
        self.asked.append((table, start, end))
        if self.fail is not None:
            raise self.fail
        return [
            Point(p.time, p.tags, {k: v for k, v in p.values.items() if k in fields})
            for p in self.tables.get(table, [])
            if start <= p.time <= end
        ]

    async def aclose(self) -> None:
        self.closed = True


class Sink:
    def __init__(self) -> None:
        self.rows: list[Row] = []

    async def submit(self, rows: list[Row]) -> None:
        self.rows.extend(rows)


async def run(reader: Reader | None, station: Station = HOME, since: datetime | None = None):  # noqa: ANN201
    sink = Sink()
    job = WindRecompute(sink, lambda: reader, clock=lambda: NOW)
    assert job.start(station, since) is None
    await job.wait()
    return job, sink


def ten(rows: list[Row]) -> dict[datetime, dict[str, object]]:
    return {datetime.fromtimestamp(r.timestamp, UTC): r.fields for r in rows}


async def test_the_whole_history_is_recomputed_day_by_day() -> None:
    reader = Reader(
        {
            "wind": [
                wind(FIRST, 10.0, 20.0),
                wind(FIRST + timedelta(days=1, hours=3), 0.0, 1.8),
                wind(FIRST + timedelta(days=2), 7.2, 9.0),
            ],
            "model": [
                model(FIRST + timedelta(days=1, hours=2, minutes=45), 18.0, 30.0),
                # Nearer in time, but an earlier model's: not the station's now.
                model(FIRST + timedelta(days=1, hours=3), 99.0, 99.0, "icon_seamless"),
                # The station's, nearer still, but with no wind speed to stand in with.
                Point(
                    FIRST + timedelta(days=1, hours=3), {"model": "best_match"}, {"gust_kmh": 5.0}
                ),
            ],
        }
    )

    job, sink = await run(reader)

    assert ten(sink.rows) == {
        FIRST: {"gust_kmh": 30.0, "source": "sensor", "speed_kmh": 20.0},
        # Stalled cups take the station's model's wind, a quarter-hour before.
        FIRST + timedelta(days=1, hours=3): {
            "gust_kmh": 30.0,
            "source": "model",
            "speed_kmh": 18.0,
        },
        FIRST + timedelta(days=2): {"gust_kmh": 16.2, "source": "sensor", "speed_kmh": 14.4},
    }
    assert all(r.table == "wind_10m" and dict(r.tags) == {"station": "Home"} for r in sink.rows)
    p = job.progress
    assert (p.state, p.start, p.end, p.through, p.rows, p.factor) == (
        "done",
        FIRST,
        NOW,
        NOW,
        3,
        2.0,
    )
    # A day at a time: three days and the hour of the fourth.
    assert [s for t, s, _ in reader.asked if t == "wind"] == [
        FIRST + timedelta(days=d) for d in range(3)
    ]
    assert reader.closed


async def test_a_start_leaves_earlier_readings_alone() -> None:
    since = FIRST + timedelta(days=1, hours=6)
    reader = Reader({"wind": [wind(FIRST, 10.0, 20.0), wind(since, 10.0, 20.0)]})

    job, sink = await run(reader, since=since)

    assert list(ten(sink.rows)) == [since]
    assert job.progress.start == since


async def test_a_station_without_a_model_never_reads_one() -> None:
    reader = Reader({"wind": [wind(FIRST, 0.0, 0.0)]})
    plain = Station("Home", Preferences(wind_factor=2.0), "K")

    _, sink = await run(reader, plain)

    assert ten(sink.rows)[FIRST]["source"] == "sensor"
    assert {t for t, _, _ in reader.asked} == {"wind"}


async def test_no_wind_stored_is_done_with_nothing_written() -> None:
    job, sink = await run(Reader({}))

    assert (job.progress.state, job.progress.rows, sink.rows) == ("done", 0, [])


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (ReadError("the database refused the token"), "the database refused the token"),
        (KeyError("x"), "KeyError"),
    ],
)
async def test_a_failure_stops_it_and_says_why(failure: Exception, error: str) -> None:
    reader = Reader({"wind": [wind(FIRST, 10.0, 20.0)]}, fail=failure)

    job, sink = await run(reader)

    assert (job.progress.state, job.progress.error, sink.rows) == ("failed", error, [])
    assert job.progress.finished == NOW
    assert reader.closed


async def test_one_at_a_time_and_only_with_a_reader() -> None:
    blocked = asyncio.Event()

    class Slow(Reader):
        async def points(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            await blocked.wait()
            return []

    sink = Sink()
    job = WindRecompute(sink, lambda: Slow({"wind": [wind(FIRST, 1.0, 1.0)]}), clock=lambda: NOW)
    assert job.start(HOME, None) is None
    await asyncio.sleep(0)
    assert job.running
    assert job.start(HOME, None) == "A recompute is already running."
    await job.aclose()
    refused = WindRecompute(sink, lambda: None).start(HOME, None)
    assert refused is not None and "cannot be read back" in refused


async def test_closing_with_nothing_running_is_harmless() -> None:
    job = WindRecompute(Sink(), lambda: None)
    await job.aclose()
    await job.wait()


async def test_with_the_fallback_off_no_model_is_read() -> None:
    reader = Reader({"wind": [wind(FIRST, 0.0, 0.0)], "model": [model(FIRST, 18.0, 30.0)]})
    station = Station(
        "Home",
        Preferences(wind_factor=2.0, wind_model_fallback=False),
        "K",
        latitude=45.0,
        longitude=7.0,
    )

    _, sink = await run(reader, station)

    assert ten(sink.rows)[FIRST]["source"] == "sensor"
    assert {t for t, _, _ in reader.asked} == {"wind"}

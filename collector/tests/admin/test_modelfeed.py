"""The weather model feed: what it fetches, what it stores, and what the pressure check gets."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx2
import pytest

from ecowitt.collector.admin.calibration import CalibrationMonitor
from ecowitt.collector.admin.modelfeed import HISTORY_SECONDS, ModelFeed
from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.state import State
from ecowitt.core.preferences import Preferences
from ecowitt.core.store.base import Row
from ecowitt.core.testing import StubInflux, serving
from ecowitt.core.units import Units
from ecowitt.core.windheight import ModelWind

DEAD = "http://127.0.0.1:1/nothing"

#: 2026-10-11 12:00 UTC, and the clock a few minutes into the quarter after it.
NOON = 1791720000
NOW = NOON + 900 + 200

HOME = Station(
    "Home",
    Preferences(altitude_m=180.0, units=Units(wind="kmh")),
    "K",
    latitude=45.0,
    longitude=7.0,
)
CABIN = Station("Cabin", Preferences(), "L")

#: Two quarters that have happened and one the clock has not reached.
REPLY = json.dumps(
    {
        "minutely_15": {
            "time": [NOON, NOON + 900, NOON + 1800],
            "temperature_2m": [18.4, 18.0, 17.5],
            "wind_speed_10m": [2.5, 3.0, 3.5],
            "surface_pressure": [1009.3, 1009.1, 1008.9],
            "weather_code": [3, 61, 61],
            "is_day": [1, 1, 1],
        }
    }
)


class Sink:
    """Keeps every row submitted."""

    def __init__(self) -> None:
        self.rows: list[Row] = []

    async def submit(self, rows: list[Row]) -> None:
        self.rows.extend(rows)


class Clock:
    """A settable wall clock."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def feed(
    url: str,
    client: httpx2.AsyncClient,
    stations: list[Station],
    *,
    sink: Sink | None = None,
    calibration: CalibrationMonitor | None = None,
    state: State | None = None,
    clock: Clock | None = None,
) -> ModelFeed:
    config = StationConfig(tuple(stations))
    return ModelFeed(
        lambda: config,
        sink or Sink(),
        calibration or CalibrationMonitor(),
        client,
        url=url,
        interval_seconds=60,
        state=state,
        clock=clock or Clock(NOW),
    )


def starts(stub: StubInflux) -> list[int]:
    """Each request's window start, as seconds before the quarter `NOW` is in."""
    quarter = NOW // 900 * 900
    return [
        quarter
        - int(
            datetime.strptime(r.query["start_minutely_15"], "%Y-%m-%dT%H:%M")
            .replace(tzinfo=UTC)
            .timestamp()
        )
        for r in stub.requests
    ]


async def test_rows_land_in_the_model_table_in_the_operators_units() -> None:
    sink, calibration, state = Sink(), CalibrationMonitor(), State()
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        model = feed(
            stub.url, client, [HOME, CABIN], sink=sink, calibration=calibration, state=state
        )
        answered = await model.refresh()

    # Only the located station is asked about, and the quarter ahead of the clock is not kept.
    assert answered == 1
    assert len(stub.requests) == 1
    tags = (("model", "best_match"), ("source", "open_meteo"), ("station", "Home"))
    assert sink.rows == [
        Row(
            "model",
            tags,
            NOON,
            {
                "abs_hpa": 1009.3,
                "is_day": True,
                "speed_kmh": 9.0,
                "temp_c": 18.4,
                "weather_code": 3,
            },
        ),
        Row(
            "model",
            tags,
            NOON + 900,
            {
                "abs_hpa": 1009.1,
                "is_day": True,
                "speed_kmh": 10.8,
                "temp_c": 18.0,
                "weather_code": 61,
            },
        ),
    ]
    # The pressure check gets the latest surface pressure, at the time it is valid for.
    assert calibration._tracks["Home"].reference == (NOON + 900, 1009.1)
    # The status page compares the latest row with the readings, and stalled cups take the
    # latest wind, in m/s as fetched.
    assert model.latest == {"Home": sink.rows[-1]}
    assert model.wind("Home") == ModelWind(NOON + 900, 3.0, None)
    assert model.wind("Cabin") is None
    assert state.last_model_ok_at is not None
    assert state.model_failures == 0


async def test_a_station_is_fetched_back_a_week_then_from_where_it_left_off() -> None:
    clock = Clock(NOW)
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        model = feed(stub.url, client, [HOME], clock=clock)
        await model.refresh()
        clock.now += 900
        await model.refresh()

    # The second picks up at the quarter the first fetched up to.
    assert starts(stub) == [HISTORY_SECONDS, 0]


async def test_new_coordinates_altitude_or_model_fetch_back_a_week_again() -> None:
    moved = Station("Home", Preferences(altitude_m=200.0), "K", latitude=45.0, longitude=7.0)
    pinned = replace(moved, weather_model="icon_seamless")
    stations = [HOME]
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        config = lambda: StationConfig(tuple(stations))  # noqa: E731
        model = ModelFeed(
            config,
            Sink(),
            CalibrationMonitor(),
            client,
            url=stub.url,
            interval_seconds=60,
            clock=Clock(NOW),
        )
        await model.refresh()
        stations[0] = moved
        await model.refresh()
        stations[0] = pinned
        await model.refresh()

    assert starts(stub) == [HISTORY_SECONDS] * 3
    assert [r.query["models"] for r in stub.requests] == ["best_match"] * 2 + ["icon_seamless"]
    assert dict(model.latest["Home"].tags)["model"] == "icon_seamless"


async def test_a_station_with_the_model_off_is_not_fetched_and_its_row_is_forgotten() -> None:
    stations = [HOME]
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        model = ModelFeed(
            lambda: StationConfig(tuple(stations)),
            Sink(),
            CalibrationMonitor(),
            client,
            url=stub.url,
            interval_seconds=60,
            clock=Clock(NOW),
        )
        await model.refresh()
        assert "Home" in model.latest
        assert model.wind("Home") is not None
        stations[0] = replace(HOME, weather_model="off")
        assert await model.refresh() == 0

    assert len(stub.requests) == 1
    assert model.latest == {}
    assert model.wind("Home") is None


async def test_a_failed_fetch_stores_nothing_and_the_next_one_fills_the_gap() -> None:
    sink, calibration, state = Sink(), CalibrationMonitor(), State()
    async with serving(StubInflux(status=500, reply="{}")) as stub, httpx2.AsyncClient() as client:
        model = feed(stub.url, client, [HOME], sink=sink, calibration=calibration, state=state)
        assert await model.refresh() == 0
        assert await model.refresh() == 0

    assert sink.rows == []
    assert "Home" not in calibration._tracks
    assert state.model_failures == 2
    assert state.last_model_ok_at is None
    # Nothing answered, so nothing is assumed fetched: each attempt asks for the whole week.
    assert starts(stub) == [HISTORY_SECONDS, HISTORY_SECONDS]


async def test_an_answer_with_nothing_yet_happened_keeps_the_last_row() -> None:
    reply = json.dumps({"minutely_15": {"time": [NOW + 900], "temperature_2m": [18.4]}})
    sink = Sink()
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        model = feed(stub.url, client, [HOME], sink=sink)
        assert await model.refresh() == 1

    assert sink.rows == []
    assert model.latest == {}


async def test_an_answer_without_pressure_leaves_the_check_alone() -> None:
    reply = json.dumps({"minutely_15": {"time": [NOON], "temperature_2m": [18.4]}})
    calibration = CalibrationMonitor()
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        assert await feed(stub.url, client, [HOME], calibration=calibration).refresh() == 1

    assert "Home" not in calibration._tracks


async def test_run_survives_an_unexpected_error_and_keeps_its_cycle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def explode() -> StationConfig:
        raise RuntimeError("config gone")

    async with httpx2.AsyncClient() as client:
        model = ModelFeed(
            explode,
            Sink(),
            CalibrationMonitor(),
            client,
            url=DEAD,
            interval_seconds=0.01,
        )
        task = asyncio.create_task(model.run())
        try:
            async with asyncio.timeout(5):
                while caplog.text.count("weather model refresh failed") < 3:
                    await asyncio.sleep(0.005)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert caplog.text.count("weather model refresh failed") >= 3


async def test_waking_refreshes_without_waiting_out_the_interval() -> None:
    """Coordinates saved on the setup page are fetched within moments."""
    refreshes: list[int] = []

    def stations() -> StationConfig:
        refreshes.append(1)
        return StationConfig()

    async with httpx2.AsyncClient() as client:
        model = ModelFeed(
            stations,
            Sink(),
            CalibrationMonitor(),
            client,
            url=DEAD,
            interval_seconds=3600,
        )
        task = asyncio.create_task(model.run())
        try:
            async with asyncio.timeout(5):
                while len(refreshes) < 1:
                    await asyncio.sleep(0.005)
                model.wake()
                while len(refreshes) < 2:
                    await asyncio.sleep(0.005)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert len(refreshes) == 2


async def test_the_models_gust_comes_with_its_wind() -> None:
    reply = json.dumps(
        {"minutely_15": {"time": [NOON], "wind_speed_10m": [3.0], "wind_gusts_10m": [7.5]}}
    )
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        model = feed(stub.url, client, [HOME])
        await model.refresh()

    assert model.wind("Home") == ModelWind(NOON, 3.0, 7.5)

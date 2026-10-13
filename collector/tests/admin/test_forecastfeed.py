"""The weather forecast feed: what it asks for, and the rows it stores with their lead."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import replace

import httpx2
import pytest

from ecowitt.collector.admin.forecastfeed import ForecastFeed
from ecowitt.collector.admin.stationconfig import Station, StationConfig
from ecowitt.collector.state import State
from ecowitt.core.preferences import Preferences
from ecowitt.core.store.base import Row
from ecowitt.core.testing import StubInflux, serving
from ecowitt.core.units import Units

DEAD = "http://127.0.0.1:1/nothing"
#: 2026-10-13 23:00 UTC, midnight of 14 Oct in Lisbon; the clock 20 minutes into the next hour.
MIDNIGHT = 1791932400
NOW = MIDNIGHT + 3600 + 1200

HOME = Station(
    "Home",
    Preferences(units=Units(wind="kmh"), altitude_m=180.0),
    "K",
    latitude=45.0,
    longitude=7.0,
    timezone="Europe/Lisbon",
    weather_forecast=True,
)
CABIN = Station("Cabin", Preferences(), "L")

REPLY = json.dumps(
    {
        "hourly": {
            "time": [MIDNIGHT, MIDNIGHT + 3600, MIDNIGHT + 7200],
            "temperature_2m": [15.0, 14.5, 14.0],
            "wind_speed_10m": [2.5, 3.0, 3.5],
            "precipitation_probability": [0, 10, 70],
            "weather_code": [2, 3, 61],
        },
        "daily": {
            # Yesterday's local day is left out; today is lead 0.
            "time": [MIDNIGHT - 86400, MIDNIGHT, MIDNIGHT + 86400],
            "temperature_2m_max": [20.0, 21.0, 22.0],
            "temperature_2m_min": [12.0, 13.0, 14.0],
        },
    }
)


class Sink:
    def __init__(self) -> None:
        self.rows: list[Row] = []

    async def submit(self, rows: list[Row]) -> None:
        self.rows.extend(rows)


def feed(url: str, client: httpx2.AsyncClient, stations: list[Station], **kwargs) -> ForecastFeed:  # noqa: ANN003
    config = StationConfig(tuple(stations))
    return ForecastFeed(
        lambda: config, kwargs.pop("sink", Sink()), client, url=url, interval_seconds=60,
        clock=lambda: float(NOW), **kwargs,
    )  # fmt: skip


async def test_hours_from_now_and_days_from_today_are_stored_with_their_lead() -> None:
    sink, state = Sink(), State()
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        answered = await feed(stub.url, client, [HOME, CABIN], sink=sink, state=state).refresh()

    assert answered == 1 and len(stub.requests) == 1
    query = stub.requests[0].query
    assert (query["models"], query["timezone"], query["forecast_days"]) == (
        "best_match",
        "Europe/Lisbon",
        "7",
    )
    assert (query["latitude"], query["wind_speed_unit"], query["timeformat"]) == (
        "45.0",
        "ms",
        "unixtime",
    )
    # At the station's altitude, as the model values beside the readings are.
    assert query["elevation"] == "180.0"
    hours = [r for r in sink.rows if r.table == "forecast"]
    days = [r for r in sink.rows if r.table == "forecast_daily"]
    # The hour already begun when it was fetched is lead 0; the one before is past, not stored.
    assert [(r.timestamp, dict(r.tags)["lead"]) for r in hours] == [
        (MIDNIGHT + 3600, "0"),
        (MIDNIGHT + 7200, "1"),
    ]
    assert hours[1].fields == {
        "precip_probability_pct": 70.0,
        "speed_kmh": 12.6,
        "temp_c": 14.0,
        "weather_code": 61,
    }
    assert dict(hours[0].tags) == {
        "lead": "0",
        "model": "best_match",
        "source": "open_meteo",
        "station": "Home",
    }
    assert [(r.timestamp, dict(r.tags)["lead"], r.fields["temp_max_c"]) for r in days] == [
        (MIDNIGHT, "0", 21.0),
        (MIDNIGHT + 86400, "1", 22.0),
    ]
    assert state.last_forecast_ok_at is not None


async def test_the_stations_model_is_asked_for_and_utc_without_a_time_zone() -> None:
    station = replace(HOME, weather_model="icon_seamless", timezone=None, preferences=Preferences())
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        await feed(stub.url, client, [station]).refresh()

    query = stub.requests[0].query
    assert (query["models"], query["timezone"]) == ("icon_seamless", "UTC")
    assert "elevation" not in query


async def test_a_station_without_a_model_or_not_storing_its_forecast_is_not_fetched() -> None:
    stations = [replace(HOME, weather_model="off"), replace(HOME, weather_forecast=False)]
    async with serving(StubInflux(status=200, reply=REPLY)) as stub, httpx2.AsyncClient() as client:
        assert await feed(stub.url, client, stations).refresh() == 0

    assert stub.requests == []


@pytest.mark.parametrize("reply", ["{}", json.dumps({"hourly": {"time": []}})])
async def test_a_failed_or_partial_answer_stores_nothing(reply: str) -> None:
    sink, state = Sink(), State()
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        assert await feed(stub.url, client, [HOME], sink=sink, state=state).refresh() == 0

    assert sink.rows == [] and state.forecast_failures == 1


async def test_run_survives_an_unexpected_error_and_wakes_on_demand(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    def stations() -> StationConfig:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("config gone")
        return StationConfig()

    async with httpx2.AsyncClient() as client:
        forecast = ForecastFeed(stations, Sink(), client, url=DEAD, interval_seconds=3600)
        task = asyncio.create_task(forecast.run())
        try:
            async with asyncio.timeout(5):
                while not calls:
                    await asyncio.sleep(0.005)
                forecast.wake()
                while len(calls) < 2:
                    await asyncio.sleep(0.005)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert "weather forecast refresh failed" in caplog.text

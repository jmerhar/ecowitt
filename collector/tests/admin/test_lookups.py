"""Elevation and weather model values from public services, against a real HTTP server."""

from __future__ import annotations

import json

import httpx2
import pytest

from ecowitt.collector.admin import lookups
from ecowitt.core import weathermodel
from ecowitt.core.testing import StubInflux, serving

DEAD = "http://127.0.0.1:1/nothing"


async def elevation(primary: str, fallback: str) -> lookups.Elevation | None:
    async with httpx2.AsyncClient() as client:
        return await lookups.elevation(
            client, 45.0, 7.0, opentopodata_url=primary, open_elevation_url=fallback
        )


async def test_elevation_from_opentopodata() -> None:
    reply = json.dumps({"results": [{"elevation": 179.6}], "status": "OK"})
    async with serving(StubInflux(status=200, reply=reply)) as stub:
        found = await elevation(stub.url + "/v1/srtm30m", DEAD)

    assert found == lookups.Elevation(179.6, "OpenTopoData (SRTM 30 m)")
    assert stub.requests[0].query == {"locations": "45.0,7.0"}


async def test_elevation_falls_back_to_open_elevation() -> None:
    reply = json.dumps({"results": [{"latitude": 45.0, "longitude": 7.0, "elevation": 180}]})
    async with serving(StubInflux(status=200, reply=reply)) as stub:
        found = await elevation(DEAD, stub.url)

    assert found == lookups.Elevation(180.0, "Open-Elevation")


@pytest.mark.parametrize(
    ("status", "reply"),
    [
        (500, "{}"),
        (200, "not json"),
        (200, "[]"),
        (200, '{"results": []}'),
        (200, '{"results": ["x"]}'),
        (200, '{"results": [{"elevation": null}]}'),
        (200, '{"results": [{"elevation": true}]}'),
        (200, '{"results": [{"elevation": "180"}]}'),
    ],
)
async def test_any_bad_answer_gives_none(status: int, reply: str) -> None:
    async with serving(StubInflux(status=status, reply=reply)) as stub:
        assert await elevation(stub.url, stub.url) is None


async def test_no_network_gives_none() -> None:
    assert await elevation(DEAD, DEAD) is None


#: 2026-10-11 12:00 and 12:15 UTC.
NOON = 1791720000
QUARTER = NOON + 900


def answer(**columns: list[object]) -> str:
    """An Open-Meteo answer with two 15-minute times and the given columns."""
    return json.dumps({"elevation": 180.0, "minutely_15": {"time": [NOON, QUARTER], **columns}})


async def weather_model(
    url: str, altitude: float | None = 180.0
) -> list[lookups.ModelSample] | None:
    async with httpx2.AsyncClient() as client:
        return await lookups.weather_model(
            client,
            45.0,
            7.0,
            altitude,
            start=NOON,
            end=QUARTER + 600,
            model="best_match",
            open_meteo_url=url,
        )


async def test_weather_model_asks_for_every_variable_at_the_station_altitude() -> None:
    async with serving(StubInflux(status=200, reply=answer())) as stub:
        await weather_model(stub.url)

    query = stub.requests[0].query
    assert query.pop("minutely_15").split(",") == list(weathermodel.VARIABLES)
    assert query == {
        "latitude": "45.0",
        "longitude": "7.0",
        "elevation": "180.0",
        "models": "best_match",
        # Open-Meteo takes the window in UTC to the minute; its own quarters answer it.
        "start_minutely_15": "2026-10-11T12:00",
        "end_minutely_15": "2026-10-11T12:25",
        "wind_speed_unit": "ms",
        "timeformat": "unixtime",
    }


async def test_weather_model_without_an_altitude_leaves_it_to_open_meteo() -> None:
    async with serving(StubInflux(status=200, reply=answer())) as stub:
        await weather_model(stub.url, altitude=None)

    assert "elevation" not in stub.requests[0].query


async def test_weather_model_values_come_typed_by_kind() -> None:
    reply = answer(
        temperature_2m=[18.4, 18.0],
        relative_humidity_2m=[64, 66],
        weather_code=[3, 61.0],
        is_day=[1, 0],
    )
    async with serving(StubInflux(status=200, reply=reply)) as stub:
        samples = await weather_model(stub.url)

    assert samples == [
        lookups.ModelSample(
            NOON,
            {
                "temperature_2m": 18.4,
                "relative_humidity_2m": 64.0,
                "weather_code": 3,
                "is_day": True,
            },
        ),
        lookups.ModelSample(
            QUARTER,
            {
                "temperature_2m": 18.0,
                "relative_humidity_2m": 66.0,
                "weather_code": 61,
                "is_day": False,
            },
        ),
    ]
    # A humidity of 64 is stored as the float every other humidity is, and a code as an integer.
    values = samples[0].values  # type: ignore[index]
    assert type(values["relative_humidity_2m"]) is float
    assert type(values["weather_code"]) is int


async def test_weather_model_skips_what_it_cannot_use() -> None:
    reply = answer(
        temperature_2m=[None, 18.0],
        relative_humidity_2m=[64],
        dew_point_2m=["x", True],
        unknown_thing=[1, 2],
    )
    async with serving(StubInflux(status=200, reply=reply)) as stub:
        samples = await weather_model(stub.url)

    # A null, a column of the wrong length, a non-number and an unasked variable are left out,
    # and a time left with nothing is dropped.
    assert samples == [lookups.ModelSample(QUARTER, {"temperature_2m": 18.0})]


@pytest.mark.parametrize(
    "reply",
    [
        "[1]",
        "{}",
        '{"minutely_15": 5}',
        '{"minutely_15": {"time": 5}}',
        '{"minutely_15": {"time": ["2026-10-11T12:00"], "temperature_2m": [1.0]}}',
        '{"minutely_15": {"time": [true], "temperature_2m": [1.0]}}',
    ],
)
async def test_weather_model_bad_answers_give_none(reply: str) -> None:
    async with serving(StubInflux(status=200, reply=reply)) as stub:
        assert await weather_model(stub.url) is None


async def test_weather_model_without_the_network_gives_none() -> None:
    assert await weather_model(DEAD) is None

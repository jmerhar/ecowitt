"""Elevation and model surface pressure from public services, against a real HTTP server."""

from __future__ import annotations

import json

import httpx2
import pytest

from ecowitt import lookups
from ecowitt.calibration import CalibrationMonitor
from ecowitt.preferences import Preferences
from ecowitt.reference import ReferenceUpdater
from ecowitt.stationconfig import Station, StationConfig

from .conftest import StubInflux, serving

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


async def test_surface_pressure_asks_for_the_station_altitude() -> None:
    reply = json.dumps({"current": {"surface_pressure": 1009.3}})
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        value = await lookups.surface_pressure(client, 45.0, 7.0, 180.0, open_meteo_url=stub.url)

    assert value == 1009.3
    assert stub.requests[0].query == {
        "latitude": "45.0",
        "longitude": "7.0",
        "current": "surface_pressure",
        "elevation": "180.0",
    }


async def test_surface_pressure_without_an_altitude_omits_it() -> None:
    reply = json.dumps({"current": {"surface_pressure": 1000.0}})
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        await lookups.surface_pressure(client, 45.0, 7.0, None, open_meteo_url=stub.url)

    assert "elevation" not in stub.requests[0].query


@pytest.mark.parametrize(
    "reply", ["{}", '{"current": 5}', '{"current": {"surface_pressure": "x"}}', "[1]"]
)
async def test_surface_pressure_bad_answers_give_none(reply: str) -> None:
    async with serving(StubInflux(status=200, reply=reply)) as stub, httpx2.AsyncClient() as client:
        assert (
            await lookups.surface_pressure(client, 1.0, 2.0, None, open_meteo_url=stub.url) is None
        )


class TestReferenceUpdater:
    located = Station("Home", Preferences(altitude_m=180.0), "K", latitude=45.0, longitude=7.0)
    unlocated = Station("Cabin", Preferences(), "L")

    async def test_refresh_fetches_only_for_located_stations(self) -> None:
        monitor = CalibrationMonitor()
        reply = json.dumps({"current": {"surface_pressure": 1009.3}})
        async with (
            serving(StubInflux(status=200, reply=reply)) as stub,
            httpx2.AsyncClient() as client,
        ):
            updater = ReferenceUpdater(
                lambda: StationConfig((self.located, self.unlocated)),
                monitor,
                client,
                url=stub.url,
                interval_seconds=60,
                clock=lambda: 5000.0,
            )
            answered = await updater.refresh()

        assert answered == 1
        assert len(stub.requests) == 1
        assert monitor._tracks["Home"].reference == (5000, 1009.3)
        assert "Cabin" not in monitor._tracks

    async def test_a_failed_fetch_records_nothing(self) -> None:
        monitor = CalibrationMonitor()
        async with httpx2.AsyncClient() as client:
            updater = ReferenceUpdater(
                lambda: StationConfig((self.located,)),
                monitor,
                client,
                url=DEAD,
                interval_seconds=60,
            )
            assert await updater.refresh() == 0

        assert "Home" not in monitor._tracks

    async def test_run_survives_an_unexpected_error_and_keeps_its_cycle(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        pauses: list[float] = []

        class Stop(Exception):
            pass

        async def sleep(seconds: float) -> None:
            pauses.append(seconds)
            if len(pauses) == 2:
                raise Stop

        def explode() -> StationConfig:
            raise RuntimeError("config gone")

        async with httpx2.AsyncClient() as client:
            updater = ReferenceUpdater(
                explode, CalibrationMonitor(), client, url=DEAD, interval_seconds=1800, sleep=sleep
            )
            with pytest.raises(Stop):
                await updater.run()

        assert pauses == [1800, 1800]
        assert caplog.text.count("reference pressure refresh failed") == 2

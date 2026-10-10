"""Station settings published to the database: once at startup, then only when they change."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from ecowitt.collector.admin.stationconfig import ConfigDocument, StationEntry, build
from ecowitt.collector.delivery.metadata import MetadataPublisher, info_for
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.lineprotocol import encode
from ecowitt.core.units import Units


class Recorder:
    def __init__(self) -> None:
        self.bodies: list[str] = []
        self.fail = False

    async def submit(self, body: str) -> None:
        if self.fail:
            raise RuntimeError("delivery is broken")
        self.bodies.append(body)


def config(*entries: StationEntry, units: Units | None = None):  # noqa: ANN201
    return build(ConfigDocument(units=units or Units(), stations=list(entries)))


HOME = StationEntry(
    name="Home",
    passkey="A",
    latitude=52.37,
    longitude=4.9,
    altitude_m=12,
    sensors={"indoor": "Lounge"},
)
COTTAGE = StationEntry(name="Cottage", passkey="B")


def publisher(sink: Recorder) -> MetadataPublisher:
    return MetadataPublisher(sink, encode=encode, clock=lambda: 1791500484.7)


def test_a_station_publishes_its_settings_and_its_zone_from_the_coordinates() -> None:
    (station,) = config(HOME).stations

    assert info_for(station) == StationInfo(
        station="Home",
        latitude=52.37,
        longitude=4.9,
        altitude_m=12,
        timezone="Europe/Amsterdam",
        units=Units(),
        sensors={"indoor": "Lounge"},
    )


async def test_every_station_is_published_at_startup() -> None:
    sink = Recorder()

    assert await publisher(sink).publish(config(HOME, COTTAGE)) == 2
    (body,) = sink.bodies
    assert body.count("station_info,station=") == 2
    assert body.splitlines()[0].endswith(" 1791500484")


async def test_an_unchanged_configuration_publishes_nothing() -> None:
    sink = Recorder()
    pub = publisher(sink)
    await pub.publish(config(HOME, COTTAGE))

    assert await pub.publish(config(HOME, COTTAGE)) == 0
    assert len(sink.bodies) == 1


async def test_only_the_station_that_changed_is_published_again() -> None:
    sink = Recorder()
    pub = publisher(sink)
    await pub.publish(config(HOME, COTTAGE))

    renamed = HOME.model_copy(update={"sensors": {"indoor": "Living room"}})
    assert await pub.publish(config(renamed, COTTAGE)) == 1
    assert "station=Home" in sink.bodies[1] and "Cottage" not in sink.bodies[1]
    assert 'sensor_indoor="Living room"' in sink.bodies[1]


async def test_a_change_of_units_republishes_every_station() -> None:
    sink = Recorder()
    pub = publisher(sink)
    await pub.publish(config(HOME, COTTAGE))

    assert await pub.publish(config(HOME, COTTAGE, units=Units(temperature="f"))) == 2


async def test_no_stations_publish_nothing() -> None:
    sink = Recorder()

    assert await publisher(sink).publish(config()) == 0
    assert sink.bodies == []


async def test_a_failed_delivery_is_tried_again_with_the_next_change() -> None:
    """Nothing is remembered as published until delivery has taken it."""
    sink = Recorder()
    pub = publisher(sink)
    sink.fail = True
    with pytest.raises(RuntimeError):
        await pub.publish(config(HOME))
    sink.fail = False

    assert await pub.publish(config(HOME)) == 1


async def test_the_loop_publishes_each_update_and_survives_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = Recorder()
    pub = publisher(sink)
    task = asyncio.create_task(pub.run())
    try:
        sink.fail = True
        with caplog.at_level(logging.ERROR):
            pub.update(config(HOME))
            async with asyncio.timeout(5):
                while "publishing station settings failed" not in caplog.text:
                    await asyncio.sleep(0.001)
        sink.fail = False
        pub.update(config(HOME))
        async with asyncio.timeout(5):
            while not sink.bodies:
                await asyncio.sleep(0.001)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert "station=Home" in sink.bodies[0]

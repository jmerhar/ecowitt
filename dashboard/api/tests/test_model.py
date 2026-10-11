"""The weather model stored beside a station: its sky on /now, and its series on /series."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from fastapi.testclient import TestClient

from ecowitt.dashboard.service import Dashboard

from .conftest import INFO, NOW, readings, row
from .memory import MemoryReader

MODELLED = dataclasses.replace(INFO, weather_model="best_match")
QUARTER = NOW - timedelta(minutes=15)


def model_row(at=QUARTER, model: str = "best_match", **fields: object):  # noqa: ANN001, ANN201
    """A row of the model table, by default the station's current model a quarter ago."""
    values = {
        "temp_c": 17.0,
        "humidity_pct": 72.0,
        "dewpoint_c": 12.0,
        "speed_kmh": 20.0,
        "dir_deg": 350.0,
        "sea_hpa": 1013.0,
        "cloud_cover_pct": 90.0,
        "weather_code": 3,
        "is_day": True,
    }
    values.update(fields)
    return row(
        "model",
        at,
        {k: v for k, v in values.items() if v is not None},
        model=model,
        source="open_meteo",
    )


def board(*rows: object, info=MODELLED) -> Dashboard:  # noqa: ANN001
    return Dashboard(MemoryReader([*readings(), *rows], {"example": info}), clock=lambda: NOW)  # type: ignore[list-item]


async def test_the_sky_comes_from_the_model() -> None:
    now = await board(model_row()).now("example")

    assert now.sky is not None
    assert (now.sky.code, now.sky.description) == (3, "Overcast")
    assert (now.sky.is_day, now.sky.cloud_cover, now.sky.time) == (True, 90.0, QUARTER)
    assert now.summary.startswith("Overcast. 18 °C.")


async def test_only_the_stations_current_model_counts() -> None:
    """A model chosen before stays in the table under its own tag, newer rows and all."""
    now = await board(
        model_row(), model_row(NOW - timedelta(minutes=5), "icon_seamless", weather_code=61)
    ).now("example")

    assert now.sky is not None and now.sky.description == "Overcast"


async def test_a_stale_model_shows_no_sky() -> None:
    """Values over an hour old mean the collector stopped fetching; yesterday's sky is wrong."""
    now = await board(model_row(NOW - timedelta(minutes=61))).now("example")

    assert now.sky is None
    assert now.summary.startswith("18 °C.")


async def test_no_model_no_sky() -> None:
    assert (await board(model_row(), info=INFO).now("example")).sky is None
    assert (await board(model_row(model="icon_seamless")).now("example")).sky is None


async def test_without_a_weather_code_there_is_no_sky() -> None:
    assert (await board(model_row(weather_code=None)).now("example")).sky is None
    assert (await board(model_row(weather_code=True)).now("example")).sky is None


async def test_what_the_model_left_out_is_unknown() -> None:
    now = await board(model_row(is_day=None, cloud_cover_pct=None)).now("example")

    assert now.sky is not None
    assert (now.sky.is_day, now.sky.cloud_cover) == (None, None)


async def test_series_add_the_models_where_asked() -> None:
    found = await board(model_row(), model_row(model="icon_seamless", temp_c=30.0)).series(
        "example", ["outdoor.temperature", "wind.direction", "rain.rate"], "24h", model=True
    )

    by = {(s.metric, s.source): s for s in found.series}
    station, modelled = by["outdoor.temperature", "station"], by["outdoor.temperature", "model"]
    assert (modelled.sensor, modelled.name, modelled.unit) == (None, None, "c")
    assert set(modelled.values) == set(station.values) == {"mean", "min", "max"}
    # The current model's value, not the earlier model's.
    assert modelled.values["mean"] == [17.0]
    assert by["wind.direction", "model"].values["circular"] == [350.0]
    # The model has no rain rate.
    assert ("rain.rate", "model") not in by


async def test_model_series_are_converted() -> None:
    found = await board(model_row()).series(
        "example", ["outdoor.temperature"], "24h", {"temperature": "f"}, model=True
    )

    modelled = next(s for s in found.series if s.source == "model")
    assert (modelled.unit, modelled.values["mean"]) == ("f", [62.6])


async def test_no_model_series_unless_asked_or_the_station_has_a_model() -> None:
    metrics = ["outdoor.temperature"]
    asked = await board(model_row()).series("example", metrics, "24h")
    none = await board(model_row(), info=INFO).series("example", metrics, "24h", model=True)
    other = await board(model_row(model="icon_seamless")).series(
        "example", metrics, "24h", model=True
    )

    for found in (asked, none, other):
        assert [s.source for s in found.series] == ["station"]


async def test_a_metric_the_rows_lack_has_no_model_series() -> None:
    """The rows have a speed but no gust: one model series, not an empty one."""
    found = await board(model_row()).series(
        "example", ["wind.speed", "wind.gust"], "24h", model=True
    )

    assert [(s.metric, s.source) for s in found.series] == [
        ("wind.speed", "station"),
        ("wind.speed", "model"),
        ("wind.gust", "station"),
    ]
    only_gust = await board(model_row()).series("example", ["wind.gust"], "24h", model=True)
    assert [s.source for s in only_gust.series] == ["station"]


async def test_only_model_metrics_ask_the_model_table() -> None:
    dashboard = board(model_row())
    await dashboard.series("example", ["rain.rate"], "24h", model=True)

    assert not [c for c in dashboard.reader.calls if c[2] == "model"]  # type: ignore[attr-defined]


async def test_a_station_without_a_model_never_asks_the_model_table() -> None:
    dashboard = board(model_row(), info=INFO)
    await dashboard.series("example", ["outdoor.temperature"], "24h", model=True)

    assert not [c for c in dashboard.reader.calls if c[2] == "model"]  # type: ignore[attr-defined]


async def test_stations_name_their_model() -> None:
    (named,) = await board().stations()
    (unnamed,) = await board(info=INFO).stations()
    (custom,) = await board(
        info=dataclasses.replace(INFO, weather_model="knmi_seamless")
    ).stations()

    assert named.weather_model is not None
    assert (named.weather_model.id, named.weather_model.label) == (
        "best_match",
        "Best for this location",
    )
    assert unnamed.weather_model is None
    assert custom.weather_model is not None and custom.weather_model.label == "knmi_seamless"


def test_meta_says_which_metrics_the_model_has() -> None:
    metrics = {m.id: m.model for m in board().meta().metrics}

    assert metrics["outdoor.temperature"] and metrics["wind.direction"]
    assert not metrics["rain.rate"] and not metrics["rooms.temperature"]


def test_the_route_passes_the_model_flag(client: TestClient, reader: MemoryReader) -> None:
    reader.infos["example"] = MODELLED
    reader.rows.append(model_row())

    plain = client.get("/api/v1/stations/example/series?metrics=outdoor.temperature").json()
    modelled = client.get(
        "/api/v1/stations/example/series?metrics=outdoor.temperature&model=true"
    ).json()

    assert [s["source"] for s in plain["series"]] == ["station"]
    assert [s["source"] for s in modelled["series"]] == ["station", "model"]

"""The web application: API routes, errors, limits, and first-run setup."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ecowitt.core.stationinfo import StationInfo
from ecowitt.dashboard import app as app_module
from ecowitt.dashboard import siteconfig
from ecowitt.dashboard.app import build_app
from ecowitt.dashboard.settings import Settings

from .conftest import CONFIG, NOW, readings
from .memory import MemoryReader

FORM = {
    "kind": "influx3",
    "influx3.url": "http://db:8181",
    "influx3.database": "weather",
    "influx3.token": "apiv3_read",
    "title": "Home",
    "stations": "example, other",
}


def config_path(client: TestClient) -> Path:
    return client.app.state.site.settings.config_path  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def fresh(tmp_path: Path, reader: MemoryReader) -> Iterator[TestClient]:
    """The app before setup, whose test connection reaches the example station."""
    settings = Settings(data_dir=tmp_path / "fresh", rate=1000.0, burst=1000)
    made: list[tuple[str, dict[str, str]]] = []

    def make(kind: str, values: dict[str, str]) -> MemoryReader:
        made.append((kind, dict(values)))
        return reader

    app = build_app(settings, make_reader=make)  # type: ignore[arg-type]
    app.state.made = made
    with TestClient(app, follow_redirects=False) as client:
        yield client


def test_health(client: TestClient, fresh: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert fresh.get("/healthz").json() == {"status": "unconfigured"}


def test_the_front_page_sends_to_setup_until_it_is_done(
    client: TestClient, fresh: TestClient
) -> None:
    assert fresh.get("/").headers["location"] == "/setup"
    assert client.get("/").headers["location"] == "/api/v1/docs"


def test_the_api_waits_for_setup(fresh: TestClient) -> None:
    response = fresh.get("/api/v1/stations")
    assert response.status_code == 503
    assert "setup" in response.json()["detail"]


def test_stations(client: TestClient) -> None:
    response = client.get("/api/v1/stations")
    assert response.json()[0]["id"] == "example"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_meta(client: TestClient) -> None:
    meta = client.get("/api/v1/meta").json()
    assert meta["title"] == "Test weather"
    assert "outdoor.temperature" in {m["id"] for m in meta["metrics"]}


def test_now_with_chosen_units(client: TestClient) -> None:
    response = client.get("/api/v1/stations/example/now?temperature=f&wind=ms")
    assert response.status_code == 200
    now = response.json()
    assert now["units"] == {
        "temperature": "f", "pressure": "hpa", "rain": "mm", "wind": "ms", "distance": "km",
    }  # fmt: skip
    assert now["outdoor"]["temperature"] == 64.4
    assert now["wind"]["speed"] == 4.2
    assert response.headers["cache-control"] == "public, max-age=30"


def test_an_unknown_unit_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/stations/example/now?temperature=k").status_code == 422


def test_series(client: TestClient) -> None:
    response = client.get(
        "/api/v1/stations/example/series", params={"metrics": "outdoor.temperature, wind.gust"}
    )
    found = response.json()
    assert (found["range"], found["step_s"]) == ("24h", 300)
    assert [s["metric"] for s in found["series"]] == ["outdoor.temperature", "wind.gust"]
    assert response.headers["cache-control"] == "public, max-age=60"
    week = client.get("/api/v1/stations/example/series?metrics=wind.gust&range=7d")
    assert week.json()["step_s"] == 1800


@pytest.mark.parametrize(
    ("query", "problem"),
    [
        ("metrics=outdoor.colour", "unknown metrics: outdoor.colour"),
        ("metrics=,", "ask for between 1 and 12 metrics"),
        ("metrics=" + ",".join(["wind.gust"] * 13), "ask for between 1 and 12 metrics"),
        ("metrics=wind.gust&range=2h", "range must be one of 24h, 7d, 30d, 1y"),
    ],
)
def test_a_bad_series_request_is_refused(client: TestClient, query: str, problem: str) -> None:
    response = client.get(f"/api/v1/stations/example/series?{query}")
    assert response.status_code == 422
    assert response.json()["detail"] == problem


def test_extremes(client: TestClient) -> None:
    response = client.get("/api/v1/stations/example/extremes?period=month")
    assert response.json()["period"] == "month"
    assert response.headers["cache-control"] == "public, max-age=600"
    assert client.get("/api/v1/stations/example/extremes").json()["period"] == "today"
    refused = client.get("/api/v1/stations/example/extremes?period=decade")
    assert refused.status_code == 422


def test_an_unknown_station_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/stations/nowhere/now")
    assert response.status_code == 404
    assert response.json() == {"detail": "no station named nowhere"}


def test_a_database_failure_is_a_503_without_its_reason(
    client: TestClient, reader: MemoryReader
) -> None:
    reader.failure = "the token was not accepted"
    response = client.get("/api/v1/stations")
    assert response.status_code == 503
    assert response.json() == {"detail": "the database could not be read"}


def test_every_api_route_goes_through_access(client: TestClient) -> None:
    async def deny() -> None:
        raise HTTPException(403, "no")

    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert len(paths) == 5
    client.app.dependency_overrides[app_module.access] = deny  # type: ignore[attr-defined]
    for path in paths:
        url = path.replace("{station}", "example") + "?metrics=wind.gust"
        assert client.get(url).status_code == 403, path


def test_the_openapi_document_is_published(client: TestClient) -> None:
    document = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/stations/{station}/now" in document["paths"]
    assert "/setup" not in document["paths"]


def test_each_address_is_held_to_its_budget(settings: Settings, reader: MemoryReader) -> None:
    settings.rate, settings.burst = 0.001, 2
    settings.config_path.write_text(CONFIG, encoding="utf-8")
    with TestClient(build_app(settings, make_reader=lambda *_: reader)) as client:
        assert [client.get("/api/v1/meta").status_code for _ in range(3)] == [200, 200, 429]
        assert client.get("/api/v1/meta").headers["retry-after"] == "1"
        assert client.get("/healthz").status_code == 200


def test_closing_the_app_closes_the_database(client: TestClient, reader: MemoryReader) -> None:
    client.__exit__(None, None, None)
    assert reader.closed


def test_a_broken_config_file_stops_the_app(settings: Settings) -> None:
    settings.config_path.write_text("title: x\n", encoding="utf-8")
    with pytest.raises(siteconfig.ConfigError):
        build_app(settings)


def test_the_setup_page_offers_only_readable_kinds(fresh: TestClient) -> None:
    page = fresh.get("/setup")
    assert page.status_code == 200
    assert 'value="influx3"' in page.text
    assert 'value="influx2"' not in page.text
    assert 'name="influx3.token" type="password"' in page.text


def test_a_test_connection_lists_the_stations_and_keeps_the_form(fresh: TestClient) -> None:
    page = fresh.post("/setup", data=FORM | {"action": "test"})
    assert page.status_code == 200
    assert "Stations that published settings: example." in page.text
    assert 'value="http://db:8181"' in page.text and 'value="Home"' in page.text
    assert not config_path(fresh).exists()


def test_a_test_with_no_stations_yet_says_so(fresh: TestClient, reader: MemoryReader) -> None:
    reader.infos.clear()
    assert "none yet" in fresh.post("/setup", data=FORM | {"action": "test"}).text


def test_saving_writes_the_file_and_starts_serving(fresh: TestClient) -> None:
    response = fresh.post("/setup", data=FORM | {"action": "save"})
    assert (response.status_code, response.headers["location"]) == (303, "/")
    config = siteconfig.load(config_path(fresh))
    assert config is not None
    assert config.connection == {
        "url": "http://db:8181", "database": "weather", "token": "apiv3_read",
    }  # fmt: skip
    assert (config.title, config.stations) == ("Home", ("example", "other"))
    assert fresh.app.state.made[-1] == ("influx3", dict(config.connection))  # type: ignore[attr-defined]
    fresh.app.state.site.dashboard.clock = lambda: NOW  # type: ignore[attr-defined]
    assert fresh.get("/api/v1/stations").json()[0]["id"] == "example"
    assert fresh.get("/setup").status_code == 404
    assert fresh.post("/setup", data=FORM).status_code == 404


def test_empty_settings_take_their_defaults(fresh: TestClient) -> None:
    form = {"kind": "influx3", "influx3.url": "http://db:8181", "title": " "}
    fresh.post("/setup", data=form)
    config = siteconfig.load(config_path(fresh))
    assert config is not None
    assert (config.title, config.stations, config.connection) == (
        "Weather",
        (),
        {"url": "http://db:8181"},
    )


@pytest.mark.parametrize(
    ("form", "problem"),
    [
        ({"kind": "influx2"}, "Choose a kind of database."),
        ({"kind": "nothing"}, "Choose a kind of database."),
        ({"kind": "influx3", "influx3.url": "ftp://db"}, "URL must start with http"),
    ],
)
def test_a_form_with_problems_is_refused(
    fresh: TestClient, form: dict[str, str], problem: str
) -> None:
    page = fresh.post("/setup", data=form)
    assert page.status_code == 400
    assert problem in page.text
    assert not config_path(fresh).exists()


def test_a_database_that_refuses_is_not_saved(fresh: TestClient, reader: MemoryReader) -> None:
    reader.failure = "the token may not read that database"
    page = fresh.post("/setup", data=FORM)
    assert page.status_code == 400
    assert "InfluxDB 3 refused: the token may not read that database." in page.text
    assert reader.closed
    assert not config_path(fresh).exists()


def test_a_database_that_fails_listing_stations_is_not_saved(
    fresh: TestClient, reader: MemoryReader
) -> None:
    class Broken(MemoryReader):
        async def check_read(self) -> str | None:
            return None

    broken = Broken(readings(), {"example": StationInfo("example")})
    broken.failure = "InfluxDB answered HTTP 500"
    fresh.app.state.site.make_reader = lambda *_: broken  # type: ignore[attr-defined]
    page = fresh.post("/setup", data=FORM)
    assert "refused: InfluxDB answered HTTP 500." in page.text
    assert not config_path(fresh).exists()


def test_someone_else_finishing_setup_first_wins(fresh: TestClient) -> None:
    config_path(fresh).parent.mkdir(parents=True)
    config_path(fresh).write_text(CONFIG, encoding="utf-8")
    response = fresh.post("/setup", data=FORM)
    assert response.status_code == 409
    assert siteconfig.load(config_path(fresh)) == siteconfig.parse(CONFIG)


@pytest.mark.parametrize("declared", [True, False])
def test_an_oversized_form_is_refused(fresh: TestClient, declared: bool) -> None:
    body = b"title=" + b"x" * (app_module.MAX_FORM_BYTES + 1)
    if declared:
        response = fresh.post("/setup", content=body)
    else:
        response = fresh.post("/setup", content=iter([body[:10], body[10:]]))
    assert response.status_code == 413


def test_the_default_reader_comes_from_the_store_settings(tmp_path: Path) -> None:
    (tmp_path / "dashboard.yaml").write_text(CONFIG, encoding="utf-8")
    app = build_app(Settings(data_dir=tmp_path))
    reader = app.state.site.dashboard.reader
    assert (reader.url, reader.database, reader.token) == (
        "http://db:8181",
        "weather",
        "apiv3_read",
    )

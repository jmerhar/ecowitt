"""The admin listener's status and health."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt.collector.admin import app as admin
from ecowitt.collector.config import Settings
from ecowitt.collector.state import State


def test_healthz_reports_starting_until_both_listeners_serve(
    admin_client: TestClient, state: State
) -> None:
    """One listener serving is not healthy: the station's reports would go nowhere."""
    state.ingest_serving = True
    assert admin_client.get("/healthz").json()["status"] == "starting"

    state.admin_serving = True
    body = admin_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["ingest_serving"] is True
    assert body["admin_serving"] is True


def test_status_counts_what_arrived(admin_client: TestClient, state: State) -> None:
    """Accepted and rejected reports are counted separately."""
    state.record_accepted()
    state.record_rejected()

    body = admin_client.get("/api/status").json()

    assert body["reports_accepted"] == 1
    assert body["reports_rejected"] == 1
    assert body["seconds_since_last_report"] is not None
    assert body["ingest_path"] == "/data/report/"


def test_status_reports_no_database_until_one_is_configured(admin_client: TestClient) -> None:
    assert admin_client.get("/api/status").json()["database"] == {"kind": None, "configured": False}


def test_status_before_any_report(admin_client: TestClient) -> None:
    """With nothing received, the age of the last report is null rather than zero."""
    assert admin_client.get("/api/status").json()["seconds_since_last_report"] is None


def test_status_reports_writes_and_rate_limiting(state: State, tmp_path) -> None:
    """Write outcomes and refused floods are visible without reading the log."""

    state.record_write(True)
    state.record_write(False)
    state.record_rate_limited()
    with TestClient(
        base_url="http://localhost",
        app=admin.build_app(
            admin.AdminContext(Settings(data_dir=tmp_path), state, stations=["Home"])
        ),
    ) as client:
        body = client.get("/api/status").json()

    assert body["writes"]["succeeded"] == 1
    assert body["writes"]["failed"] == 1
    assert body["writes"]["seconds_since_last_success"] is not None
    assert body["reports_rate_limited"] == 1
    assert body["stations"] == ["Home"]


def test_status_before_any_write(admin_client: TestClient) -> None:
    body = admin_client.get("/api/status").json()

    assert body["writes"] == {
        "succeeded": 0,
        "failed": 0,
        "rejected": 0,
        "seconds_since_last_success": None,
    }
    assert body["stations"] == []
    assert body["spool"] is None


def test_status_reports_what_is_waiting_in_the_spool(state: State, tmp_path) -> None:
    """The backlog's size and age are visible without reading the log."""
    from ecowitt.collector.delivery.spool import Spool

    spool = Spool(tmp_path / "spool", 1_000_000)
    spool.enqueue("r1")
    spool.enqueue("r2")
    spool.quarantine_body("refused")
    state.record_spooled()
    state.record_spooled()
    with TestClient(
        base_url="http://localhost",
        app=admin.build_app(
            admin.AdminContext(Settings(data_dir=tmp_path), state, stations=["Home"], spool=spool)
        ),
    ) as client:
        body = client.get("/api/status").json()

    assert body["spool"]["waiting"] == 2
    assert body["spool"]["bytes"] == 4
    assert body["spool"]["oldest_seconds"] is not None
    assert body["spool"]["spooled_total"] == 2
    assert body["spool"]["dropped"] == 0
    assert body["spool"]["rejected_kept"] == 1


def test_a_request_naming_another_host_is_refused(tmp_path: Path) -> None:
    """DNS rebinding: a hostile page points its own name at this listener's address."""
    state = State()
    app = admin.build_app(admin.AdminContext(Settings(data_dir=tmp_path), state))
    with TestClient(base_url="http://rebind.attacker.example", app=app) as client:
        page = client.get("/setup")
        health = client.get("/healthz")

    assert page.status_code == 421
    assert health.status_code == 200


def test_a_configured_host_name_is_answered(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, admin_hosts="wx.example")
    with TestClient(
        base_url="https://wx.example", app=admin.build_app(admin.AdminContext(settings, State()))
    ) as client:
        assert client.get("/").status_code == 200


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("http://writer:s3cr3t@influx:8181", "http://influx:8181"),
        ("https://user@[::1]:8181/x", "https://[::1]:8181/x"),
        ("http://influx:8181", "http://influx:8181"),
    ],
)
def test_status_shows_the_connection_but_never_a_secret(
    state: State, tmp_path: Path, url: str, shown: str
) -> None:
    from ecowitt.collector.admin.configstore import ConfigStore
    from ecowitt.collector.admin.stationconfig import ConfigDocument, StoreEntry

    store = ConfigStore(tmp_path / "config.yaml")
    entry = StoreEntry(kind="influx3", url=url, token="apiv3_do-not-leak-this")  # type: ignore[call-arg]
    store.replace(ConfigDocument(store=entry))
    context = admin.AdminContext(Settings(data_dir=tmp_path), state, store=store)
    with TestClient(base_url="http://localhost", app=admin.build_app(context)) as client:
        response = client.get("/api/status")

    database = response.json()["database"]
    assert database["url"] == shown
    assert database["database"] == "weather"
    assert database["token_set"] is True
    assert "do-not-leak-this" not in response.text and "s3cr3t" not in response.text

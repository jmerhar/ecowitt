"""The admin listener's status and health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ecowitt.config import Settings
from ecowitt.state import State


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


def test_status_never_returns_the_influx_token(state: State, tmp_path) -> None:
    """The token's presence is reported; its value is not."""
    secret = "apiv3_do-not-leak-this"
    settings = Settings(data_dir=tmp_path, influx_token=secret)
    from ecowitt import admin

    with TestClient(admin.build_app(settings, state)) as client:
        response = client.get("/api/status")

    assert response.json()["influx"]["token_configured"] is True
    assert secret not in response.text


def test_status_before_any_report(admin_client: TestClient) -> None:
    """With nothing received, the age of the last report is null rather than zero."""
    assert admin_client.get("/api/status").json()["seconds_since_last_report"] is None

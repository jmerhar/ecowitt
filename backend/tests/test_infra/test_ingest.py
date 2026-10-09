"""The public listener's surface and its limits."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ecowitt import ingest
from ecowitt.config import MAX_BODY_BYTES, MAX_BODY_FIELDS, Settings
from ecowitt.state import State

from ..conftest import FIXTURE_PASSKEY, RecordingHandler, payload

FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def test_accepts_a_real_console_report(
    ingest_client: TestClient, handler: RecordingHandler, state: State
) -> None:
    """A recorded HP2551 payload is received whole and answered the way a station expects."""
    response = ingest_client.post("/data/report/", content=payload("hp2551_indoor"), headers=FORM)

    assert response.status_code == 200
    assert response.json() == {"errcode": "0", "errmsg": "ok"}
    assert len(handler.reports) == 1
    report = handler.reports[0]
    assert report["PASSKEY"] == FIXTURE_PASSKEY
    assert report["tempinf"] == "73.8"
    assert report["temp8f"] == "74.1"
    assert report["model"] == "HP2551AE_Pro_V2.1.4"
    # The captured payload carries 37 fields; the count guards against a parser that
    # silently drops any of them.
    assert len(report) == 37
    assert state.reports_accepted == 1
    assert state.reports_rejected == 0


@pytest.mark.parametrize("path", ["/data/report", "/data/report/"])
def test_serves_both_slash_spellings_without_redirecting(
    path: str, ingest_client: TestClient
) -> None:
    """Either spelling is answered outright, with no redirect in between.

    Asserting the absence of a redirect is the substance here, not the 200: a station that
    receives a 307 never follows it, so a route reached only by redirection is a route the
    console can never reach.
    """
    response = ingest_client.post(path, content="PASSKEY=x", headers=FORM)

    assert response.status_code == 200
    assert response.history == []


def test_accepts_query_string_fields(ingest_client: TestClient, handler: RecordingHandler) -> None:
    """The Wunderground variant puts the same names in the query string."""
    response = ingest_client.get("/data/report/?tempf=51.8&humidity=71")

    assert response.status_code == 200
    assert handler.reports[0] == {"tempf": "51.8", "humidity": "71"}


def test_a_rejected_report_still_answers_200(settings: Settings, state: State) -> None:
    """A refusal is indistinguishable from acceptance, so it is no guessing oracle."""
    handler = RecordingHandler(accept=False)
    with TestClient(ingest.build_app(settings, state, handler)) as client:
        response = client.post("/data/report/", content="PASSKEY=wrong", headers=FORM)

    assert response.status_code == 200
    assert response.json() == {"errcode": "0", "errmsg": "ok"}
    assert state.reports_accepted == 0
    assert state.reports_rejected == 1


def test_an_oversized_body_is_refused_before_the_handler(
    ingest_client: TestClient, handler: RecordingHandler, state: State
) -> None:
    """A body over the cap is rejected, and the handler never sees it."""
    response = ingest_client.post(
        "/data/report/", content="x=" + "y" * MAX_BODY_BYTES, headers=FORM
    )

    assert response.status_code == 413
    assert response.text == ""
    assert handler.reports == []
    assert state.reports_rejected == 1


def test_too_many_fields_is_refused(ingest_client: TestClient, handler: RecordingHandler) -> None:
    """A body within the size cap but with absurdly many fields is still refused."""
    body = "&".join(f"f{i}=1" for i in range(MAX_BODY_FIELDS + 1))
    response = ingest_client.post("/data/report/", content=body, headers=FORM)

    assert response.status_code == 413
    assert handler.reports == []


def test_malformed_body_degrades_rather_than_failing(
    ingest_client: TestClient, handler: RecordingHandler
) -> None:
    """Garbage parses to whatever it can; nothing raises."""
    response = ingest_client.post(
        "/data/report/", content=b"\xff\xfe not form data at all", headers=FORM
    )

    assert response.status_code == 200
    assert len(handler.reports) == 1


@pytest.mark.parametrize(
    "path",
    ["/", "/healthz", "/api/status", "/docs", "/redoc", "/openapi.json", "/status", "/setup"],
)
def test_admin_routes_are_absent_from_the_public_listener(
    path: str, ingest_client: TestClient
) -> None:
    """Every admin route answers 404 here -- not 401.

    A 401 would mean the route is mounted on the internet-facing listener and merely guarded,
    which is the thing this split exists to avoid: a guard can be got wrong, an unmounted
    route cannot. So the status code is the assertion, not the fact that access failed.
    """
    response = ingest_client.get(path)

    assert response.status_code == 404
    assert response.text == ""


def test_redact_hides_the_passkey() -> None:
    """A report is loggable only with its credential replaced."""
    redacted = ingest.redact({"PASSKEY": FIXTURE_PASSKEY, "tempinf": "73.8"})

    assert redacted == {"PASSKEY": "<redacted>", "tempinf": "73.8"}
    assert FIXTURE_PASSKEY not in str(redacted)


async def test_the_logging_handler_records_and_accepts() -> None:
    """The default handler keeps what it was given and accepts it."""
    handler = ingest.LoggingHandler()

    accepted = await handler.handle({"tempinf": "73.8", "PASSKEY": FIXTURE_PASSKEY}, "192.0.2.9")

    assert accepted is True
    assert handler.reports == [{"tempinf": "73.8", "PASSKEY": FIXTURE_PASSKEY}]


def test_a_request_without_a_peer_address_is_still_served(settings: Settings, state: State) -> None:
    """A missing client address must not raise; the report still counts."""
    handler = RecordingHandler()
    app = ingest.build_app(settings, state, handler)
    with TestClient(app, client=None, follow_redirects=False) as client:  # type: ignore[arg-type]
        response = client.post("/data/report/", content="tempinf=70", headers=FORM)

    assert response.status_code == 200
    assert handler.sources


def test_an_oversized_chunked_body_is_refused_mid_stream(
    ingest_client: TestClient, handler: RecordingHandler, state: State
) -> None:
    """A body with no declared length is still capped, by aborting as it arrives.

    This is the shape that matters: the Content-Length check cannot see a chunked upload, so
    without the in-stream guard an anonymous caller could stream unbounded data into memory.
    """

    def endless() -> Iterator[bytes]:
        for _ in range(100):
            yield b"y" * 4096

    response = ingest_client.post("/data/report/", content=endless(), headers=FORM)

    assert response.status_code == 413
    assert handler.reports == []
    assert state.reports_rejected == 1

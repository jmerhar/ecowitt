"""Writing line protocol to InfluxDB, against a real HTTP server."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest

from ecowitt.collector.config import Settings
from ecowitt.collector.delivery.writer import ERROR_EXCERPT, InfluxWriter, Outcome, classify

from ..stubs import StubInflux

LINE = "indoor,station=home temp_c=23.2 1791500484"


@pytest.fixture
async def writer_for(influx: StubInflux) -> AsyncIterator:
    made: list[InfluxWriter] = []

    def make(**overrides: object) -> InfluxWriter:
        settings = Settings(influx_url=influx.url, influx_token="apiv3_test", **overrides)  # type: ignore[arg-type]
        made.append(InfluxWriter(settings))
        return made[-1]

    yield make
    for writer in made:
        await writer.aclose()


async def test_v3_writes_line_protocol_with_a_bearer_token(influx: StubInflux, writer_for) -> None:
    assert await writer_for().send(LINE) is Outcome.OK

    (request,) = influx.requests
    assert (request.method, request.path) == ("POST", "/api/v3/write_lp")
    assert request.query == {"db": "weather", "precision": "second"}
    assert request.headers["authorization"] == "Bearer apiv3_test"
    assert request.headers["content-type"].startswith("text/plain")
    assert request.body == LINE


async def test_v2_writes_to_a_bucket_with_a_token_scheme(influx: StubInflux, writer_for) -> None:
    writer = writer_for(influx_api="v2", influx_org="home", influx_database="wx")

    assert await writer.send(LINE) is Outcome.OK

    (request,) = influx.requests
    assert request.path == "/api/v2/write"
    assert request.query == {"bucket": "wx", "org": "home", "precision": "s"}
    assert request.headers["authorization"] == "Token apiv3_test"


@pytest.mark.parametrize("api", ["v3", "v2"])
async def test_no_token_sends_no_authorization(influx: StubInflux, api: str) -> None:
    """An InfluxDB with authentication disabled needs none, and an empty header would be wrong."""
    writer = InfluxWriter(Settings(influx_url=influx.url, influx_api=api, influx_org="home"))  # type: ignore[arg-type]
    try:
        await writer.send(LINE)
    finally:
        await writer.aclose()

    assert "authorization" not in influx.requests[0].headers


async def test_a_trailing_slash_on_the_url_is_tolerated(influx: StubInflux) -> None:
    writer = InfluxWriter(Settings(influx_url=influx.url + "/"))
    try:
        await writer.send(LINE)
    finally:
        await writer.aclose()

    assert influx.requests[0].path == "/api/v3/write_lp"


async def test_a_rejected_write_reports_failure_with_the_reason(
    influx: StubInflux, writer_for, caplog: pytest.LogCaptureFixture
) -> None:
    influx.status, influx.reply = 400, "partial write: field type conflict"
    writer = writer_for()

    assert await writer.send(LINE) is Outcome.REJECT
    assert writer.last_error is not None and "field type conflict" in writer.last_error
    assert "HTTP 400" in caplog.text
    assert "not retrying" in caplog.text


async def test_a_long_error_body_is_truncated(influx: StubInflux, writer_for) -> None:
    influx.status, influx.reply = 502, "<html>" + "x" * 5000
    writer = writer_for()

    await writer.send(LINE)

    assert writer.last_error is not None
    assert len(writer.last_error) <= ERROR_EXCERPT + len("HTTP 502: ")


async def test_a_success_clears_the_last_error(influx: StubInflux, writer_for) -> None:
    writer = writer_for()
    influx.status = 500
    await writer.send(LINE)
    influx.status = 204

    assert await writer.send(LINE) is Outcome.OK
    assert writer.last_error is None


async def test_an_unreachable_server_is_a_failure_not_an_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Port 1 refuses connections; the station's reply must not depend on the database."""
    writer = InfluxWriter(Settings(influx_url="http://127.0.0.1:1"))
    try:
        with caplog.at_level(logging.ERROR):
            assert await writer.send(LINE) is Outcome.RETRY
    finally:
        await writer.aclose()

    assert writer.last_error is not None and "ConnectError" in writer.last_error


async def test_nothing_to_write_is_not_sent(influx: StubInflux, writer_for) -> None:
    assert await writer_for().send("") is Outcome.OK
    assert influx.requests == []


async def test_without_a_url_nothing_is_attempted() -> None:
    writer = InfluxWriter(Settings())
    try:
        assert writer.configured is False
        assert await writer.send(LINE) is Outcome.RETRY
        assert writer.last_error == "INFLUX_URL is not set"
    finally:
        await writer.aclose()


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, Outcome.OK),
        (204, Outcome.OK),
        (400, Outcome.REJECT),
        (413, Outcome.REJECT),
        (422, Outcome.REJECT),
        (401, Outcome.RETRY),
        (403, Outcome.RETRY),
        (404, Outcome.RETRY),
        (408, Outcome.RETRY),
        (429, Outcome.RETRY),
        (500, Outcome.RETRY),
        (503, Outcome.RETRY),
    ],
)
def test_classify(status: int, outcome: Outcome) -> None:
    """Data the server refuses is rejected; everything someone could fix is retried."""
    assert classify(status) is outcome


@pytest.mark.parametrize(
    ("status", "outcome"), [(503, Outcome.RETRY), (401, Outcome.RETRY), (422, Outcome.REJECT)]
)
async def test_send_reports_the_classified_outcome(
    influx: StubInflux, writer_for, status: int, outcome: Outcome
) -> None:
    influx.status = status

    assert await writer_for().send(LINE) is outcome

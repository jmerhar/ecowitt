"""Writing line protocol to InfluxDB 3 and 2.x, against a real HTTP server."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

import pytest

from ecowitt.core.store.base import Outcome, Row
from ecowitt.core.store.factory import KINDS, store_for
from ecowitt.core.store.influx import ERROR_EXCERPT, InfluxStore, classify
from ecowitt.core.store.influx2 import Influx2Store
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.testing import StubInflux

LINE = "indoor,station=home temp_c=23.2 1791500484"


@pytest.fixture
async def store_for_stub(influx: StubInflux) -> AsyncIterator[Callable[..., InfluxStore]]:
    made: list[InfluxStore] = []

    def make(kind: str = "influx3", **overrides: str) -> InfluxStore:
        connection = {"url": influx.url, "database": "weather", "token": "apiv3_test"}
        made.append(store_for(kind, **(connection | overrides)))  # type: ignore[arg-type]
        return made[-1]  # type: ignore[return-value]

    yield make
    for store in made:
        await store.aclose()


async def test_v3_writes_line_protocol_with_a_bearer_token(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    assert await store_for_stub().write(LINE) is Outcome.OK

    (request,) = influx.requests
    assert (request.method, request.path) == ("POST", "/api/v3/write_lp")
    assert request.query == {"db": "weather", "precision": "second"}
    assert request.headers["authorization"] == "Bearer apiv3_test"
    assert request.headers["content-type"].startswith("text/plain")
    assert request.body == LINE


async def test_v2_writes_to_a_bucket_with_a_token_scheme(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    store = store_for_stub("influx2", org="home", database="wx")

    assert await store.write(LINE) is Outcome.OK

    (request,) = influx.requests
    assert request.path == "/api/v2/write"
    assert request.query == {"bucket": "wx", "org": "home", "precision": "s"}
    assert request.headers["authorization"] == "Token apiv3_test"


@pytest.mark.parametrize("kind", KINDS)
async def test_no_token_sends_no_authorization(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore], kind: str
) -> None:
    """An InfluxDB with authentication disabled needs none, and an empty header would be wrong."""
    await store_for_stub(kind, token="").write(LINE)

    assert "authorization" not in influx.requests[0].headers


async def test_a_trailing_slash_on_the_url_is_tolerated(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    await store_for_stub(url=influx.url + "/").write(LINE)

    assert influx.requests[0].path == "/api/v3/write_lp"


async def test_a_rejected_write_reports_failure_with_the_reason(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore], caplog: pytest.LogCaptureFixture
) -> None:
    influx.status, influx.reply = 400, "partial write: field type conflict"
    store = store_for_stub()

    assert await store.write(LINE) is Outcome.REJECT
    assert store.last_error is not None and "field type conflict" in store.last_error
    assert "HTTP 400" in caplog.text
    assert "not retrying" in caplog.text


async def test_a_long_error_body_is_truncated(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    influx.status, influx.reply = 502, "<html>" + "x" * 5000
    store = store_for_stub()

    await store.write(LINE)

    assert store.last_error is not None
    assert len(store.last_error) <= ERROR_EXCERPT + len("HTTP 502: ")


async def test_a_success_clears_the_last_error(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    store = store_for_stub()
    influx.status = 500
    await store.write(LINE)
    influx.status = 204

    assert await store.write(LINE) is Outcome.OK
    assert store.last_error is None


async def test_an_unreachable_server_is_a_failure_not_an_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Port 1 refuses connections; the station's reply must not depend on the database."""
    store = Influx3Store("http://127.0.0.1:1", "weather")
    try:
        with caplog.at_level(logging.ERROR):
            assert await store.write(LINE) is Outcome.RETRY
    finally:
        await store.aclose()

    assert store.last_error is not None and "ConnectError" in store.last_error


async def test_nothing_to_write_is_not_sent(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore]
) -> None:
    assert await store_for_stub().write("") is Outcome.OK
    assert influx.requests == []


async def test_without_a_url_nothing_is_attempted() -> None:
    store = Influx3Store("", "weather")
    try:
        assert store.configured is False
        assert await store.write(LINE) is Outcome.RETRY
        assert store.last_error == "no database is configured"
    finally:
        await store.aclose()


def test_rows_are_encoded_as_line_protocol() -> None:
    store = Influx3Store("http://influx", "weather")
    rows = [Row("indoor", (("station", "home"),), 1791500484, {"temp_c": 23.2})]

    assert store.encode(rows) == LINE


def test_the_factory_builds_each_kind() -> None:
    assert isinstance(store_for("influx3", url="http://x", database="d"), Influx3Store)
    influx2 = store_for("influx2", url="http://x", database="d", org="home")
    assert isinstance(influx2, Influx2Store)
    assert influx2.org == "home"


def test_an_unknown_kind_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ValueError, match="influx3, influx2"):
        store_for("sqlite", url="", database="")


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
async def test_write_reports_the_classified_outcome(
    influx: StubInflux, store_for_stub: Callable[..., InfluxStore], status: int, outcome: Outcome
) -> None:
    influx.status = status

    assert await store_for_stub().write(LINE) is outcome

"""The configured store: swapped in place when the saved connection changes."""

from __future__ import annotations

import pytest

from ecowitt.collector.delivery.database import NOT_CONFIGURED, ConfiguredStore
from ecowitt.core.store.base import Outcome, Row
from ecowitt.core.testing import StubInflux

ROWS = [Row("indoor", (("station", "home"),), 1791500484, {"temp_c": 21.0})]


async def test_without_a_connection_every_write_waits() -> None:
    """A RETRY, so the rows go to the spool until a database is set up."""
    store = ConfiguredStore()

    assert store.configured is False
    assert await store.write(ROWS) is Outcome.RETRY
    assert store.last_error == NOT_CONFIGURED
    assert await store.check() == NOT_CONFIGURED


async def test_a_configured_connection_is_written_to(influx: StubInflux) -> None:
    store = ConfiguredStore()
    store.configure("influx3", {"url": influx.url, "token": "t"})
    try:
        assert store.configured and store.kind == "influx3"
        assert await store.write(ROWS) is Outcome.OK
        assert store.last_error is None
        influx.status, influx.reply = 400, "incoming write was empty"
        assert await store.check() is None
    finally:
        await store.aclose()

    assert influx.requests[0].body == "indoor,station=home temp_c=21.0 1791500484"
    assert influx.requests[0].headers["authorization"] == "Bearer t"


async def test_a_changed_connection_replaces_the_store_and_the_old_one_is_closed() -> None:
    store = ConfiguredStore()
    store.configure("influx3", {"url": "http://a:8181"})
    first = store._current
    store.configure("influx3", {"url": "http://b:8181"})
    second = store._current

    assert first is not second
    closed: list[object] = []
    for s in (first, second):
        real = s.aclose  # type: ignore[union-attr]

        async def track(s=s, real=real) -> None:  # noqa: ANN001
            closed.append(s)
            await real()

        s.aclose = track  # type: ignore[method-assign,union-attr]
    await store.aclose()

    assert closed == [first, second]


def test_the_same_connection_again_keeps_the_store() -> None:
    """Every save notifies the writer; reconnecting on each would drop connections for nothing."""
    store = ConfiguredStore()
    store.configure("influx3", {"url": "http://a:8181", "token": "t"})
    current = store._current

    store.configure("influx3", {"token": "t", "url": "http://a:8181"})

    assert store._current is current


def test_removing_the_connection_leaves_none() -> None:
    store = ConfiguredStore()
    store.configure("influx3", {"url": "http://a:8181"})

    store.configure(None, {})

    assert store.configured is False and store.kind is None


def test_an_invalid_connection_is_refused() -> None:
    with pytest.raises(ValueError, match="URL is required"):
        ConfiguredStore().configure("influx3", {})

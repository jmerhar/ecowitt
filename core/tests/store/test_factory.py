"""Choosing a store by kind, and how each kind writes the collector's rows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from jigkit.influx import Influx2Sink

from ecowitt.core.store.base import Outcome, Row, Store
from ecowitt.core.store.factory import KINDS, store_for
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.testing import StubInflux

ROWS = [Row("indoor", (("station", "home"),), 1791500484, {"temp_c": 23.2})]


@pytest.fixture
async def made(influx: StubInflux) -> AsyncIterator[Callable[..., Store]]:
    stores: list[Store] = []

    def make(kind: str, **overrides: str) -> Store:
        connection = {"url": influx.url, "database": "weather", "token": "apiv3_test"}
        stores.append(store_for(kind, **(connection | overrides)))  # type: ignore[arg-type]
        return stores[-1]

    yield make
    for store in stores:
        await store.aclose()


def test_the_factory_builds_each_kind() -> None:
    assert isinstance(store_for("influx3", url="http://x", database="d"), Influx3Store)
    influx2 = store_for("influx2", url="http://x", database="d", org="home")
    assert isinstance(influx2, Influx2Sink)
    assert influx2.org == "home"


def test_an_unknown_kind_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ValueError, match="influx3, influx2"):
        store_for("sqlite", url="", database="")


@pytest.mark.parametrize(
    ("kind", "path", "query"),
    [
        ("influx3", "/api/v3/write_lp", {"db": "weather", "precision": "second"}),
        ("influx2", "/api/v2/write", {"bucket": "weather", "org": "home", "precision": "s"}),
    ],
)
async def test_rows_are_written_at_second_precision(
    influx: StubInflux, made: Callable[..., Store], kind: str, path: str, query: dict[str, str]
) -> None:
    store = made(kind, org="home") if kind == "influx2" else made(kind)

    assert await store.write(ROWS) is Outcome.OK

    (request,) = influx.requests
    assert (request.path, request.query) == (path, query)
    assert request.body == "indoor,station=home temp_c=23.2 1791500484"
    assert KINDS == ("influx3", "influx2")

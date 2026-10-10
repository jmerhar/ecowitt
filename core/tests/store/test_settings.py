"""Declared connection settings: what each kind needs, checked before anything connects."""

from __future__ import annotations

import pytest

from ecowitt.core.store.influx2 import Influx2Store
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.store.settings import KINDS, problems, store_from


def test_every_kind_needs_a_url_and_keeps_its_token_secret() -> None:
    for kind in KINDS.values():
        names = {s.name: s for s in kind.settings}
        assert names["url"].required and names["url"].format == "url"
        assert names["token"].secret and not names["token"].required


def test_a_complete_connection_has_no_problems() -> None:
    assert problems("influx3", {"url": "http://influx:8181", "database": "weather"}) == []


@pytest.mark.parametrize(
    ("kind", "values", "problem"),
    [
        ("influx3", {"database": "weather"}, "URL is required"),
        ("influx3", {"url": "influx:8181", "database": "w"}, "must start with http://"),
        ("influx3", {"url": "ftp://influx", "database": "w"}, "must start with http://"),
        ("influx3", {"url": "http://[::1", "database": "w"}, "not a valid URL"),
        ("influx3", {"url": "http://influx:port", "database": "w"}, "not a valid URL"),
        ("influx2", {"url": "http://influx", "database": "w"}, "Organisation is required"),
        ("influx3", {"url": "http://influx", "database": "w", "org": "x"}, "org is not a setting"),
        ("sqlite", {}, "unknown kind of database"),
    ],
)
def test_problems_are_named(kind: str, values: dict[str, str], problem: str) -> None:
    assert any(problem in p for p in problems(kind, values))


def test_a_store_is_built_with_defaults_filled_in() -> None:
    store = store_from("influx3", {"url": " http://influx:8181 ", "token": "t"})

    assert isinstance(store, Influx3Store)
    assert (store.url, store.database, store.token) == ("http://influx:8181", "weather", "t")


def test_an_influx2_store_gets_its_organisation() -> None:
    store = store_from("influx2", {"url": "http://influx", "org": "home"})

    assert isinstance(store, Influx2Store) and store.org == "home"


def test_a_connection_with_problems_builds_nothing() -> None:
    with pytest.raises(ValueError, match="URL is required"):
        store_from("influx3", {})

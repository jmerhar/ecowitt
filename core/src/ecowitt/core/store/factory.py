"""Choose a store implementation by name."""

from __future__ import annotations

import httpx2

from ecowitt.core.store.base import Store
from ecowitt.core.store.influx2 import Influx2Store
from ecowitt.core.store.influx3 import Influx3Store
from ecowitt.core.store.query import Reader

#: The store kinds there are, by the name a configuration uses.
KINDS = ("influx3", "influx2")
#: The kinds that can be read back as well as written to.
READABLE = ("influx3",)


def store_for(
    kind: str,
    *,
    url: str,
    database: str,
    token: str = "",
    org: str = "",
    client: httpx2.AsyncClient | None = None,
) -> Store:
    """The store for `kind`, connected as given."""
    if kind == "influx3":
        return Influx3Store(url, database, token, client=client)
    if kind == "influx2":
        return Influx2Store(url, database, token, org=org, client=client)
    raise ValueError(f"unknown store kind {kind!r}; expected one of {', '.join(KINDS)}")


def reader_for(
    kind: str,
    *,
    url: str,
    database: str,
    token: str = "",
    org: str = "",  # noqa: ARG001 -- every kind's settings are passed; InfluxDB 3 has no org
    client: httpx2.AsyncClient | None = None,
) -> Reader:
    """The reader for `kind`, connected as given."""
    if kind == "influx3":
        return Influx3Store(url, database, token, client=client)
    raise ValueError(f"reading from {kind!r} is not supported; supported: {', '.join(READABLE)}")

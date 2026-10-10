"""The settings each kind of store needs, declared once for every form and check to use.

Setup pages build their database form from these declarations and validate what was entered
against them, so adding a kind of store adds its form with no page changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx2

from ecowitt.core.store.base import Store
from ecowitt.core.store.factory import READABLE, reader_for, store_for
from ecowitt.core.store.query import Reader


@dataclass(frozen=True)
class Setting:
    """One connection setting."""

    name: str
    label: str
    required: bool = True
    #: A credential: shown on no page once saved, and kept when a form leaves it empty.
    secret: bool = False
    default: str = ""
    #: The kind of value, for checking it: "url" or "text".
    format: str = "text"
    help: str = ""
    #: When an optional setting is needed, shown beside its label.
    optional: str = "optional"


@dataclass(frozen=True)
class Kind:
    """A kind of store, as a person picks it."""

    name: str
    label: str
    settings: tuple[Setting, ...]

    @property
    def readable(self) -> bool:
        """Whether stored readings can be read back from this kind, as a dashboard needs."""
        return self.name in READABLE


_URL = Setting(
    "url", "URL", format="url", help="Where the database answers, e.g. http://influxdb:8181"
)
_TOKEN = Setting(
    "token",
    "Token",
    required=False,
    secret=True,
    help="One allowed to write",
    # A database running without authentication takes none.
    optional="if the database needs one",
)

KINDS: dict[str, Kind] = {
    kind.name: kind
    for kind in (
        Kind(
            "influx3",
            "InfluxDB 3",
            (_URL, Setting("database", "Database", default="weather"), _TOKEN),
        ),
        Kind(
            "influx2",
            "InfluxDB 2.x",
            (
                _URL,
                Setting("database", "Bucket", default="weather"),
                Setting("org", "Organisation"),
                _TOKEN,
            ),
        ),
    )
}


def problems(kind: str, values: Mapping[str, str]) -> list[str]:
    """What is wrong with a connection's settings, in words a person can act on."""
    declared = KINDS.get(kind)
    if declared is None:
        return [f"unknown kind of database {kind!r}"]
    found = []
    for setting in declared.settings:
        value = values.get(setting.name, "").strip() or setting.default
        if setting.required and not value:
            found.append(f"{setting.label} is required")
        elif value and setting.format == "url":
            try:
                parts = urlsplit(value)
                parts.port  # noqa: B018 -- raises on a malformed port
            except ValueError:
                found.append(f"{setting.label} is not a valid URL")
                continue
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                found.append(f"{setting.label} must start with http:// or https:// and name a host")
    known = {s.name for s in declared.settings}
    found += [
        f"{name} is not a setting of {declared.label}" for name in values if name not in known
    ]
    return found


def store_from(
    kind: str, values: Mapping[str, str], *, client: httpx2.AsyncClient | None = None
) -> Store:
    """The store a validated connection describes. Raises ValueError if it has problems."""
    return store_for(kind, client=client, **_clean(kind, values))


def reader_from(
    kind: str, values: Mapping[str, str], *, client: httpx2.AsyncClient | None = None
) -> Reader:
    """The reader a validated connection describes. Raises ValueError if it has problems or the
    kind cannot be read from."""
    return reader_for(kind, client=client, **_clean(kind, values))


def _clean(kind: str, values: Mapping[str, str]) -> dict[str, str]:
    """A connection's settings with defaults filled in. Raises ValueError if it has problems."""
    found = problems(kind, values)
    if found:
        raise ValueError("; ".join(found))
    return {s.name: values.get(s.name, "").strip() or s.default for s in KINDS[kind].settings}

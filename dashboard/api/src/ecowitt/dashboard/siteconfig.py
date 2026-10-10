"""dashboard.yaml: the database to read, the site's title, and which stations to show.

The first-run setup page writes it once; after that it changes only by being edited or deleted
by hand, followed by a restart. It holds the database token, so it is written readable by its
owner alone.

    title: Weather
    stations: []          # every station that has published its settings
    store:
      kind: influx3
      url: http://influxdb:8181
      database: weather
      token: apiv3_...    # one allowed to read
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ecowitt.core.store import settings as store_settings

DEFAULT_TITLE = "Weather"


class ConfigError(ValueError):
    """dashboard.yaml exists but cannot be used; the message says why."""


class AlreadyConfigured(Exception):
    """dashboard.yaml was written by someone else first."""


@dataclass(frozen=True)
class SiteConfig:
    """What dashboard.yaml says."""

    kind: str
    connection: Mapping[str, str]
    title: str = DEFAULT_TITLE
    #: The stations shown, by name; empty shows every station.
    stations: tuple[str, ...] = field(default_factory=tuple)

    def to_yaml(self) -> str:
        """The file's text."""
        document = {
            "title": self.title,
            "stations": list(self.stations),
            "store": {"kind": self.kind, **self.connection},
        }
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def parse(text: str) -> SiteConfig:
    """A configuration from the file's text. Raises ConfigError naming what is wrong."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("expected a mapping with title, stations and store")
    unknown = set(document) - {"title", "stations", "store"}
    if unknown:
        raise ConfigError(f"unknown keys: {', '.join(sorted(unknown))}")
    store = document.get("store")
    if not isinstance(store, dict) or not isinstance(store.get("kind"), str):
        raise ConfigError("store must be a mapping with a kind")
    kind = store["kind"]
    connection = {str(k): str(v) for k, v in store.items() if k != "kind" and v is not None}
    found = store_settings.problems(kind, connection)
    declared = store_settings.KINDS.get(kind)
    if declared is not None and not declared.readable:
        found.append(f"{declared.label} cannot be read from yet")
    if found:
        raise ConfigError("; ".join(found))
    title = document.get("title", DEFAULT_TITLE)
    stations = document.get("stations") or []
    if not isinstance(title, str) or not title.strip():
        raise ConfigError("title must be text")
    if not isinstance(stations, list) or not all(isinstance(s, str) for s in stations):
        raise ConfigError("stations must be a list of station names")
    return SiteConfig(kind, connection, title.strip(), tuple(stations))


def load(path: Path) -> SiteConfig | None:
    """The configuration in `path`, or None if there is no file yet."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return parse(text)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def create(path: Path, config: SiteConfig) -> None:
    """Create `path`, readable by its owner alone.

    Raises AlreadyConfigured if the file exists, so two people finishing setup at once cannot
    overwrite each other: the file is written aside, then linked into place, which fails rather
    than replaces.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".dashboard-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(config.to_yaml())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise AlreadyConfigured(str(path)) from exc
    finally:
        os.unlink(temporary)

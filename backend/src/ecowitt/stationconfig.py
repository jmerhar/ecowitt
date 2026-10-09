"""The configuration file: which stations may report, and what each is called.

`/data/config.yaml` holds what describes the stations rather than the deployment -- the PASSKEY
allowlist, display names, altitudes and unit preferences -- because none of it is pleasant as
environment variables. It is plain YAML so it can be written by hand:

    units:
      temperature: c
    stations:
      - name: Home
        passkey: 0123456789ABCDEF0123456789ABCDEF
        altitude_m: 180
        latitude: 52.37        # optional; enables the absolute-pressure check
        longitude: 4.90
        sensors:
          indoor: Lounge
          ch1: Bathroom

Names, altitude and sensor names are per station, because `ch1` at one house is not `ch1` at
another. Units are shared: one database should not hold one station in °C and another in °F.

The setup page edits this file too. Saving from it rewrites the file whole, so comments added
by hand do not survive a save; the values do.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .preferences import Preferences
from .units import Units

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when the configuration file exists but cannot be used."""


class StationEntry(BaseModel):
    """One station, as written in the file."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    #: The console sends it on every report; it is the MD5 of the console's MAC address.
    passkey: str = Field(min_length=1)
    altitude_m: float | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    sensors: dict[str, str] = Field(default_factory=dict)
    #: Calibration warnings the operator has acknowledged, by kind, with the error at the time.
    #: A warning stays hidden only while the error stays close to that value.
    dismissed: dict[str, float] = Field(default_factory=dict)


class AdminLogin(BaseModel):
    """The optional login guarding the admin interface. Only a hash of the password is kept."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password_hash: str = Field(min_length=1)


class ConfigDocument(BaseModel):
    """The whole file. Unknown keys are refused, so a misspelt one is not silently ignored."""

    model_config = ConfigDict(extra="forbid")

    units: Units = Field(default_factory=Units)
    stations: list[StationEntry] = Field(default_factory=list)
    admin: AdminLogin | None = None

    @model_validator(mode="after")
    def _unique(self) -> Self:
        """Refuse two stations sharing a name or a PASSKEY.

        A shared name would merge two stations' series; a shared PASSKEY would make which entry
        a report belongs to depend on the order of the file.
        """
        for attribute in ("name", "passkey"):
            values = [getattr(s, attribute) for s in self.stations]
            if len(values) != len(set(values)):
                raise ValueError(f"two stations share a {attribute}")
        return self

    def station(self, name: str) -> StationEntry | None:
        """The entry with this name, if there is one."""
        return next((s for s in self.stations if s.name == name), None)


@dataclass(frozen=True)
class Station:
    """A station allowed to report, with the preferences its readings are processed under."""

    name: str
    preferences: Preferences
    _passkey: str
    latitude: float | None = None
    longitude: float | None = None
    dismissed: dict[str, float] = field(default_factory=dict)

    def matches(self, passkey: str) -> bool:
        """Whether a report's PASSKEY is this station's, compared in constant time."""
        return hmac.compare_digest(self._passkey.encode(), passkey.encode())

    @property
    def located(self) -> bool:
        """Whether both coordinates are known."""
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True)
class StationConfig:
    """Every configured station."""

    stations: tuple[Station, ...] = ()

    def lookup(self, passkey: str) -> Station | None:
        """The station a PASSKEY belongs to, or None if it belongs to none.

        Every entry is compared, so the time taken does not depend on which one matched.
        """
        found = None
        for station in self.stations:
            if station.matches(passkey):
                found = station
        return found

    def get(self, name: str) -> Station | None:
        """The station with this name, if there is one."""
        return next((s for s in self.stations if s.name == name), None)

    @property
    def names(self) -> list[str]:
        """The configured station names, for display. Never the PASSKEYs."""
        return [s.name for s in self.stations]


def load_document(path: Path) -> ConfigDocument:
    """Read the configuration file, or return an empty document if there is none.

    A missing file is the normal state of a fresh install and accepts no reports. A file that
    exists but is malformed is an error, raised with the reason: running on with no stations
    would discard every report while looking healthy.
    """
    if not path.exists():
        logger.warning("no configuration at %s: no station's reports will be accepted", path)
        return ConfigDocument()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return ConfigDocument.model_validate(raw)
    except (yaml.YAMLError, ValidationError, ValueError, TypeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def save_document(path: Path, document: ConfigDocument) -> None:
    """Write the configuration file atomically, readable by its owner only.

    Owner-only because it holds every station's PASSKEY and the admin password's hash.
    Written to a temporary file and renamed into place, so a crash mid-save leaves the old
    file intact rather than a truncated one that would stop the server starting.
    """
    data = document.model_dump(mode="json", exclude_none=True)
    for station in data.get("stations", []):
        for empty in [k for k in ("sensors", "dismissed") if not station.get(k)]:
            station.pop(empty, None)
    text = "# Ecowitt Server configuration. Holds PASSKEYs: keep it private.\n" + yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build(document: ConfigDocument) -> StationConfig:
    """The runtime form of a configuration document."""
    return StationConfig(
        tuple(
            Station(
                name=entry.name,
                preferences=Preferences(
                    units=document.units, names=dict(entry.sensors), altitude_m=entry.altitude_m
                ),
                _passkey=entry.passkey,
                latitude=entry.latitude,
                longitude=entry.longitude,
                dismissed=dict(entry.dismissed),
            )
            for entry in document.stations
        )
    )


def load(path: Path) -> StationConfig:
    """Read the configuration file into its runtime form. See `load_document`."""
    return build(load_document(path))

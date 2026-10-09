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
        sensors:
          indoor: Lounge
          ch1: Bathroom

Names, altitude and sensor names are per station, because `ch1` at one house is not `ch1` at
another. Units are shared: one database should not hold one station in °C and another in °F.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .preferences import Preferences
from .units import Units

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when the configuration file exists but cannot be used."""


class _Station(BaseModel):
    """One station entry, as written in the file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    #: The console sends it on every report; it is the MD5 of the console's MAC address.
    passkey: str = Field(min_length=1)
    altitude_m: float | None = None
    sensors: dict[str, str] = Field(default_factory=dict)


class _File(BaseModel):
    """The whole file. Unknown keys are refused, so a misspelt one is not silently ignored."""

    model_config = ConfigDict(extra="forbid")

    units: Units = Field(default_factory=Units)
    stations: list[_Station] = Field(default_factory=list)

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


@dataclass(frozen=True)
class Station:
    """A station allowed to report, with the preferences its readings are processed under."""

    name: str
    preferences: Preferences
    _passkey: str

    def matches(self, passkey: str) -> bool:
        """Whether a report's PASSKEY is this station's, compared in constant time."""
        return hmac.compare_digest(self._passkey.encode(), passkey.encode())


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

    @property
    def names(self) -> list[str]:
        """The configured station names, for display. Never the PASSKEYs."""
        return [s.name for s in self.stations]


def load(path: Path) -> StationConfig:
    """Read the configuration file, or return an empty configuration if there is none.

    A missing file is the normal state of a fresh install and accepts no reports. A file that
    exists but is malformed is an error, raised with the reason: running on with no stations
    would discard every report while looking healthy.
    """
    if not path.exists():
        logger.warning("no configuration at %s: no station's reports will be accepted", path)
        return StationConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        parsed = _File.model_validate(raw)
    except (yaml.YAMLError, ValidationError, ValueError, TypeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    return StationConfig(
        tuple(
            Station(
                name=entry.name,
                preferences=Preferences(
                    units=parsed.units, names=dict(entry.sensors), altitude_m=entry.altitude_m
                ),
                _passkey=entry.passkey,
            )
            for entry in parsed.stations
        )
    )

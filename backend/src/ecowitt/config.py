"""Settings that describe the installation rather than its sensors.

Infrastructure lives here, in the environment: where to listen, where InfluxDB is, how much
to log. Everything describing a particular station -- channel names, unit preferences, the
PASSKEY allowlist, the site location -- belongs to the station configuration file read by
`stationconfig`, because none of it is pleasant to express as environment variables.

Every credential also accepts a `*_FILE` variant naming a file to read it from, which is what
makes a Docker secret usable without putting the value in a compose file.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Maximum size of a report body. Real payloads are a few hundred bytes -- a full station
#: with every sensor type populated is still under 4 KB -- so this is generous by two orders
#: of magnitude while still bounding what an anonymous caller can make the process allocate.
MAX_BODY_BYTES = 64 * 1024

#: Maximum number of form fields in a report, for the same reason.
MAX_BODY_FIELDS = 512


class Settings(BaseSettings):
    """Where this instance listens, and what it talks to."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    #: Holds the station configuration file and the write spool.
    data_dir: Path = Path("/data")

    # Both listeners bind every interface because the shipped artefact is a container, where
    # a loopback bind is unreachable even through a published port. Which of them the
    # internet can reach is therefore decided by the host-side publish -- the ingest port on
    # a real address, the admin port on 127.0.0.1 -- not here. See the README.
    #
    # The defaults are the published ports, so host and container numbers match. Firewalls
    # that govern Docker traffic, ufw-docker among them, match the port after Docker's address
    # translation, which is the container's: a rule for 2551 does nothing for a container
    # listening on 8000 behind a 2551 publish.
    ingest_host: str = "0.0.0.0"  # noqa: S104
    ingest_port: int = 2551
    admin_host: str = "0.0.0.0"  # noqa: S104
    admin_port: int = 2552

    #: The ingest listener's per-address budget: requests per second, and the burst allowed
    #: before that applies. A console reports at most once every 8 seconds.
    ingest_rate: float = 2.0
    ingest_burst: int = 20

    #: Most the spool may hold while InfluxDB is unreachable; beyond it the oldest reports are
    #: dropped. A report is a few kilobytes, so the default keeps days of them.
    spool_max_bytes: int = 100 * 1024 * 1024

    # Public services consulted for a station whose coordinates have been entered, and only
    # then: the coordinates are sent to them. Overridable so tests and air-gapped hosts can
    # point them elsewhere.
    opentopodata_url: str = "https://api.opentopodata.org/v1/srtm30m"
    open_elevation_url: str = "https://api.open-elevation.com/api/v1/lookup"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    #: How often a located station's model surface pressure is fetched for the absolute check.
    reference_interval_seconds: int = 1800

    #: The console's "Path" field. Ecowitt firmware sends it with a trailing slash; both
    #: spellings are served, so either value works here.
    ingest_path: str = "/data/report/"

    influx_url: str = ""
    influx_database: str = "weather"
    influx_token: str = ""
    influx_token_file: Path | None = None
    #: InfluxDB 3 writes line protocol to /api/v3/write_lp; 2.x to /api/v2/write.
    influx_api: Literal["v3", "v2"] = "v3"
    #: Required by InfluxDB 2.x only, which scopes a bucket to an organisation.
    influx_org: str = ""

    #: Called after readings are written, for a push monitor to alert when the calls stop. Push
    #: URLs carry their monitor's token, so this is a credential and has a file form too.
    heartbeat_url: str = ""
    heartbeat_url_file: Path | None = None
    #: The least time between two heartbeat calls.
    heartbeat_interval_seconds: float = 60.0

    log_level: str = "INFO"

    @field_validator("influx_token_file", "heartbeat_url_file", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat an empty value as absent rather than as a path.

        Compose interpolates an unset `${VAR:-}` to an empty string and passes it to the
        container anyway, so an optional path arrives as "" rather than not arriving. Pydantic
        would resolve that to `Path(".")` -- the working directory -- and reading a credential
        from it fails with `IsADirectoryError` at startup.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _read_secret_files(self) -> Self:
        """Load any credential given as a file, and reject one that cannot be read.

        Naming a file excludes the alternatives, so an unreadable one is an error rather than
        a fall back to the empty default -- which would otherwise surface much later as an
        authentication failure against InfluxDB.
        """
        if self.influx_token_file is not None:
            self.influx_token = self.influx_token_file.read_text(encoding="utf-8").strip()
        if self.heartbeat_url_file is not None:
            self.heartbeat_url = self.heartbeat_url_file.read_text(encoding="utf-8").strip()
        return self

    @model_validator(mode="after")
    def _normalise_ingest_path(self) -> Self:
        """Give the ingest path a leading slash, whatever was configured."""
        if not self.ingest_path.startswith("/"):
            self.ingest_path = "/" + self.ingest_path
        return self

    @property
    def ingest_paths(self) -> tuple[str, ...]:
        """Both slash spellings of the ingest path, in registration order.

        Consoles differ over the trailing slash and Starlette's own redirect would answer the
        other spelling with a 307, which the Ecowitt uploader does not follow: it would retry
        the identical request for ever. Serving both outright is the only thing that works.
        """
        bare = self.ingest_path.rstrip("/")
        if not bare:
            return ("/",)
        return (bare, bare + "/")

    @property
    def config_file(self) -> Path:
        """The station configuration file."""
        return self.data_dir / "config.yaml"

    @property
    def secret_file(self) -> Path:
        """The key the admin pages sign their forms with, created on first start."""
        return self.data_dir / "secret.key"

    @property
    def spool_dir(self) -> Path:
        """Where writes wait when InfluxDB is unreachable."""
        return self.data_dir / "spool"


@functools.cache
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment once."""
    return Settings()

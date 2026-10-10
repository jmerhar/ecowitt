"""Settings that describe the installation: where to listen, where its file lives, how much to log.

Everything about the database and the site is in `dashboard.yaml`, which the first-run setup
page writes, so an install needs nothing in its compose file.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Where this instance listens, and how it treats its visitors."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    #: Holds dashboard.yaml.
    data_dir: Path = Path("/data")

    # Every interface, because the shipped artefact is a container, where a loopback bind is
    # unreachable even through a published port.
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 2553

    log_level: str = "INFO"

    #: Addresses of reverse proxies whose X-Forwarded-For is believed, comma-separated (`*` for
    #: any). Behind a proxy every visitor arrives from its address, so without this the rate
    #: limit below would be shared by all of them.
    forwarded_allow_ips: str = "127.0.0.1"

    #: Each visitor's budget: requests per second, and the burst allowed before that applies.
    #: A page load makes a handful of requests, and answers are cached for every visitor alike.
    rate: float = 5.0
    burst: int = 60

    @property
    def config_path(self) -> Path:
        """The site's configuration file."""
        return self.data_dir / "dashboard.yaml"

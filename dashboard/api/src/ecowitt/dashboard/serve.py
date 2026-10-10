"""Run the dashboard with uvicorn."""

from __future__ import annotations

import logging

import uvicorn

from ecowitt.dashboard.app import build_app
from ecowitt.dashboard.settings import Settings

#: Libraries that log every request at INFO.
CHATTY_LOGGERS = ("httpx2", "httpcore2")


def configure_logging(level: str) -> None:
    """Send the application's logs to stderr at the configured level."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )
    configured = logging.getLevelNamesMapping()[level.upper()]
    for name in CHATTY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, configured))


def main(settings: Settings | None = None) -> None:
    """Serve until stopped."""
    settings = settings or Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        log_level=settings.log_level.lower(),
        server_header=False,
    )

"""The admin listener: status, health and the read API.

Reached through a reverse proxy or from the host, never from the open internet -- the
host-side publish binds it to loopback. Its routes are mounted only here, so the public
listener does not serve them under any configuration.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import Settings
from .state import State

logger = logging.getLogger(__name__)


def build_app(settings: Settings, state: State) -> FastAPI:
    """Build the admin application."""
    app = FastAPI(
        title="Ecowitt Server",
        description="Status and configuration for Ecowitt Server.",
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        """Report whether this process is serving.

        Both listeners are checked: one of the two failing to bind while the other serves
        would otherwise look healthy from here, with the station's reports going nowhere.
        """
        serving = state.ingest_serving and state.admin_serving
        return {
            "status": "ok" if serving else "starting",
            "ingest_serving": state.ingest_serving,
            "admin_serving": state.admin_serving,
        }

    @app.get("/api/status")
    async def status() -> dict[str, object]:
        """What this process has received since it started.

        The shape of this response is the contract a separate frontend reads, so fields are
        added to it rather than renamed.
        """
        return {
            "uptime_seconds": round(state.uptime_seconds, 1),
            "reports_accepted": state.reports_accepted,
            "reports_rejected": state.reports_rejected,
            "seconds_since_last_report": _rounded(state.seconds_since_last_report),
            "ingest_path": settings.ingest_path,
            "influx": {
                "url": settings.influx_url,
                "database": settings.influx_database,
                "api": settings.influx_api,
                # Whether a token is present, never the token itself.
                "token_configured": bool(settings.influx_token),
            },
        }

    return app


def _rounded(value: float | None) -> float | None:
    """Round a duration for display, passing None through."""
    return None if value is None else round(value, 1)

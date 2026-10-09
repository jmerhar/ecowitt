"""Send line protocol to InfluxDB.

InfluxDB 3 takes it at `/api/v3/write_lp` with a bearer token; 2.x at `/api/v2/write`, where a
database is a bucket inside an organisation and the token scheme is `Token`. Both are asked for
second precision, which is what the encoder writes.
"""

from __future__ import annotations

import logging

import httpx2

from .config import Settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
#: How much of an error response to log. InfluxDB explains a rejected write in the body, which
#: is the useful part, but a proxy's HTML error page is not worth a screenful.
ERROR_EXCERPT = 300


class InfluxWriter:
    """Writes encoded rows to one InfluxDB database."""

    def __init__(self, settings: Settings, client: httpx2.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx2.AsyncClient(timeout=TIMEOUT_SECONDS)
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        """Whether there is anywhere to write to."""
        return bool(self._settings.influx_url)

    async def write(self, body: str) -> bool:
        """Write rows, returning whether InfluxDB accepted them.

        Failures are logged and reported rather than raised: the station's reply never waits
        on, or depends on, the database.
        """
        if not body:
            return True
        if not self.configured:
            return self._fail("INFLUX_URL is not set")
        url, params, headers = self._request()
        try:
            response = await self._client.post(
                url, params=params, headers=headers, content=body.encode("utf-8")
            )
        except httpx2.RequestError as exc:
            return self._fail(f"{type(exc).__name__}: {exc}")
        if not response.is_success:
            return self._fail(f"HTTP {response.status_code}: {response.text[:ERROR_EXCERPT]}")
        self.last_error = None
        return True

    async def aclose(self) -> None:
        """Release the HTTP client's connections."""
        await self._client.aclose()

    def _request(self) -> tuple[str, dict[str, str], dict[str, str]]:
        """The URL, query and headers for this server's API version."""
        s = self._settings
        base = s.influx_url.rstrip("/")
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if s.influx_api == "v2":
            if s.influx_token:
                headers["Authorization"] = f"Token {s.influx_token}"
            params = {"bucket": s.influx_database, "org": s.influx_org, "precision": "s"}
            return f"{base}/api/v2/write", params, headers
        if s.influx_token:
            headers["Authorization"] = f"Bearer {s.influx_token}"
        params = {"db": s.influx_database, "precision": "second"}
        return f"{base}/api/v3/write_lp", params, headers

    def _fail(self, reason: str) -> bool:
        """Record and log a failed write."""
        self.last_error = reason
        logger.error("write to InfluxDB failed: %s", reason)
        return False

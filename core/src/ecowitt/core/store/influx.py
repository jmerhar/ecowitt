"""What every InfluxDB version has in common: HTTP, line protocol, and how failures classify.

InfluxDB 3 and 2.x take the same line protocol over HTTP and answer with the same statuses; they
differ in the endpoint, its parameters and the token scheme, which is all a subclass supplies.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx2

from ecowitt.core.store.base import Outcome, Row
from ecowitt.core.store.lineprotocol import encode

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
#: How much of an error response to keep. InfluxDB explains a rejected write in the body, which
#: is the useful part, but a proxy's HTML error page is not worth a screenful.
ERROR_EXCERPT = 300

#: Client errors that describe the server or the credentials rather than the data. A revoked
#: token or a dropped database is a fault to fix, and the readings should still be there once it
#: is: 401 and 403 are authentication, 404 a missing database, 408 and 429 load.
RETRYABLE_CLIENT_ERRORS = frozenset({401, 403, 404, 408, 429})


def classify(status: int) -> Outcome:
    """The outcome an HTTP status means for a write."""
    if 200 <= status < 300:
        return Outcome.OK
    if status in RETRYABLE_CLIENT_ERRORS or status >= 500:
        return Outcome.RETRY
    return Outcome.REJECT


class InfluxStore(ABC):
    """Writes line protocol to one InfluxDB database."""

    def __init__(
        self,
        url: str,
        database: str,
        token: str = "",
        *,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.token = token
        self._client = client or httpx2.AsyncClient(timeout=TIMEOUT_SECONDS)
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        """Whether there is anywhere to write to."""
        return bool(self.url)

    def encode(self, rows: list[Row]) -> str:
        """Rows as newline-separated line protocol."""
        return encode(rows)

    async def write(self, payload: str) -> Outcome:
        """Write line protocol once, returning what became of it.

        Failures are logged and reported rather than raised: the station's reply never waits
        on, or depends on, the database.
        """
        if not payload:
            return Outcome.OK
        if not self.configured:
            return self._fail(Outcome.RETRY, "no database is configured")
        path, params, scheme = self._write_endpoint()
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if self.token:
            headers["Authorization"] = f"{scheme} {self.token}"
        try:
            response = await self._client.post(
                self.url + path, params=params, headers=headers, content=payload.encode("utf-8")
            )
        except httpx2.RequestError as exc:
            return self._fail(Outcome.RETRY, f"{type(exc).__name__}: {exc}")
        outcome = classify(response.status_code)
        if outcome is not Outcome.OK:
            detail = f"HTTP {response.status_code}: {response.text[:ERROR_EXCERPT]}"
            return self._fail(outcome, detail)
        self.last_error = None
        return Outcome.OK

    async def aclose(self) -> None:
        """Release the HTTP client's connections."""
        await self._client.aclose()

    @abstractmethod
    def _write_endpoint(self) -> tuple[str, dict[str, str], str]:
        """The write path, its query parameters, and the Authorization scheme."""

    def _fail(self, outcome: Outcome, reason: str) -> Outcome:
        """Record and log a failed write."""
        self.last_error = reason
        verdict = "will retry" if outcome is Outcome.RETRY else "refused, not retrying"
        logger.error("write to InfluxDB failed (%s): %s", verdict, reason)
        return outcome

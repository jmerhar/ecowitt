"""InfluxDB 2.x: line protocol to /api/v2/write, where a database is a bucket in an organisation."""

from __future__ import annotations

import httpx2

from ecowitt.core.store.influx import InfluxStore


class Influx2Store(InfluxStore):
    """Writes to an InfluxDB 2.x bucket."""

    def __init__(
        self,
        url: str,
        database: str,
        token: str = "",
        *,
        org: str = "",
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        super().__init__(url, database, token, client=client)
        self.org = org

    def _write_endpoint(self) -> tuple[str, dict[str, str], str]:
        # The token scheme is `Token`, and second precision is spelt `s`.
        params = {"bucket": self.database, "org": self.org, "precision": "s"}
        return "/api/v2/write", params, "Token"

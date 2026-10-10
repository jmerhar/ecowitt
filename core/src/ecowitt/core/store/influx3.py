"""InfluxDB 3: line protocol to /api/v3/write_lp, with a bearer token."""

from __future__ import annotations

from ecowitt.core.store.influx import InfluxStore


class Influx3Store(InfluxStore):
    """Writes to an InfluxDB 3 database."""

    def _write_endpoint(self) -> tuple[str, dict[str, str], str]:
        # Second precision, which is what the line protocol encoder writes.
        return "/api/v3/write_lp", {"db": self.database, "precision": "second"}, "Bearer"

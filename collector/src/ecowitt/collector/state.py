"""Runtime state both listeners read.

The ingest listener writes it and the admin listener renders it, which is the reason the two
are one process: a status page in a second container could not see what the first had just
received without a round trip through storage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class State:
    """What this process has done since it started."""

    started_at: float = field(default_factory=time.monotonic)

    #: Set once each listener is accepting connections, so the health probe can tell a
    #: half-started process from a healthy one.
    ingest_serving: bool = False
    admin_serving: bool = False

    #: Monotonic clock, for ages and intervals; wall-clock times belong to the readings
    #: themselves, which carry the station's own timestamp.
    last_report_at: float | None = None
    reports_accepted: int = 0
    reports_rejected: int = 0
    #: Requests refused by the rate limiter before their body was read.
    reports_rate_limited: int = 0

    #: Attempts to write a report, live or replayed, by outcome. A report retried five times
    #: during an outage counts five failures and then one success.
    writes_succeeded: int = 0
    writes_failed: int = 0
    last_write_ok_at: float | None = None
    #: Reports InfluxDB refused outright, set aside rather than retried.
    writes_rejected: int = 0
    #: Reports put in the spool because they could not be written when they arrived.
    reports_spooled: int = 0

    #: The push monitor's calls: whether one is configured, its last accepted call and how many
    #: were refused or failed.
    heartbeat_configured: bool = False
    last_heartbeat_ok_at: float | None = None
    heartbeat_failures: int = 0

    #: Station settings rows handed to delivery (written, or spooled until they can be), and the
    #: last time any were.
    settings_published: int = 0
    last_settings_at: float | None = None

    #: The weather model's fetches: the last that answered, and how many failed since it did.
    last_model_ok_at: float | None = None
    model_failures: int = 0
    #: The weather forecast's fetches, likewise.
    last_forecast_ok_at: float | None = None
    forecast_failures: int = 0

    @property
    def uptime_seconds(self) -> float:
        """How long this process has been running."""
        return time.monotonic() - self.started_at

    @property
    def seconds_since_last_report(self) -> float | None:
        """Age of the most recent accepted report, or None if none has arrived."""
        if self.last_report_at is None:
            return None
        return time.monotonic() - self.last_report_at

    def record_accepted(self) -> None:
        """Note a report that passed the allowlist and parsed."""
        self.reports_accepted += 1
        self.last_report_at = time.monotonic()

    def record_rate_limited(self) -> None:
        """Note a request refused for exceeding its address's budget."""
        self.reports_rate_limited += 1

    def record_write(self, succeeded: bool) -> None:
        """Note the outcome of writing one report's rows."""
        if succeeded:
            self.writes_succeeded += 1
            self.last_write_ok_at = time.monotonic()
        else:
            self.writes_failed += 1

    def record_rejected_write(self) -> None:
        """Note a report InfluxDB refused outright."""
        self.writes_rejected += 1

    def record_spooled(self) -> None:
        """Note a report queued for a later attempt."""
        self.reports_spooled += 1

    @property
    def seconds_since_last_write(self) -> float | None:
        """Age of the most recent successful write, or None if none has succeeded."""
        if self.last_write_ok_at is None:
            return None
        return time.monotonic() - self.last_write_ok_at

    def record_heartbeat(self, ok: bool) -> None:
        """Note the outcome of one call to the push monitor."""
        if ok:
            self.last_heartbeat_ok_at = time.monotonic()
        else:
            self.heartbeat_failures += 1

    def record_settings(self, count: int) -> None:
        """Note station settings rows handed to delivery."""
        self.settings_published += count
        self.last_settings_at = time.monotonic()

    def record_model(self, ok: bool) -> None:
        """Note the outcome of one station's weather model fetch."""
        if ok:
            self.last_model_ok_at = time.monotonic()
            self.model_failures = 0
        else:
            self.model_failures += 1

    def record_forecast(self, ok: bool) -> None:
        """Note the outcome of one station's forecast fetch."""
        if ok:
            self.last_forecast_ok_at = time.monotonic()
            self.forecast_failures = 0
        else:
            self.forecast_failures += 1

    @property
    def seconds_since_last_forecast(self) -> float | None:
        """Age of the last forecast fetch that answered, or None if none has."""
        return _age(self.last_forecast_ok_at)

    @property
    def seconds_since_last_model(self) -> float | None:
        """Age of the last weather model fetch that answered, or None if none has."""
        return _age(self.last_model_ok_at)

    @property
    def seconds_since_last_heartbeat(self) -> float | None:
        """Age of the push monitor's last accepted call, or None if there has been none."""
        return _age(self.last_heartbeat_ok_at)

    @property
    def seconds_since_last_settings(self) -> float | None:
        """Age of the last settings publication, or None if there has been none."""
        return _age(self.last_settings_at)

    def record_rejected(self) -> None:
        """Note a report that was discarded.

        Deliberately does not touch `last_report_at`: that drives the "station has gone
        quiet" signal, and an unknown caller must not be able to reset it.
        """
        self.reports_rejected += 1


def _age(moment: float | None) -> float | None:
    """Seconds since a monotonic moment, or None for one that has not happened."""
    return None if moment is None else time.monotonic() - moment

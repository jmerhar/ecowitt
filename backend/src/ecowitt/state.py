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

    writes_succeeded: int = 0
    writes_failed: int = 0
    last_write_ok_at: float | None = None

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

    @property
    def seconds_since_last_write(self) -> float | None:
        """Age of the most recent successful write, or None if none has succeeded."""
        if self.last_write_ok_at is None:
            return None
        return time.monotonic() - self.last_write_ok_at

    def record_rejected(self) -> None:
        """Note a report that was discarded.

        Deliberately does not touch `last_report_at`: that drives the "station has gone
        quiet" signal, and an unknown caller must not be able to reset it.
        """
        self.reports_rejected += 1

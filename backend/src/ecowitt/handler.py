"""What the ingest listener does with a report: authenticate, process, deliver, remember."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from .calibration import CalibrationMonitor
from .lineprotocol import encode
from .pending import PendingStations, fingerprint
from .pipeline import process_report
from .points import Point
from .staleness import StalenessTracker
from .stationconfig import StationConfig

logger = logging.getLogger(__name__)

#: Unknown stations are announced once each, up to this many, so a misconfigured console is
#: visible in the log without a scan of invented PASSKEYs filling it.
MAX_ANNOUNCED_UNKNOWN = 100


class Sink(Protocol):
    """Where encoded rows go: written now, or kept until they can be."""

    async def submit(self, body: str) -> None:
        """Accept one report's rows for delivery."""


@dataclass(frozen=True)
class LatestReport:
    """A station's most recent report, as rows in the operator's units."""

    timestamp: int
    received_at: datetime
    points: list[Point] = field(default_factory=list)


class StationHandler:
    """Accepts reports from configured stations and delivers what they measured.

    `config` is replaced whenever the configuration changes, so a station added on the setup
    page is accepted from its next report without a restart.
    """

    def __init__(
        self,
        config: StationConfig,
        sink: Sink,
        *,
        pending: PendingStations | None = None,
        calibration: CalibrationMonitor | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self._sink = sink
        self._pending = pending or PendingStations()
        self._calibration = calibration or CalibrationMonitor()
        self._clock = clock
        self._tracker = StalenessTracker()
        self._announced: set[str] = set()
        self.latest: dict[str, LatestReport] = {}

    async def handle(self, fields: Mapping[str, str], source: str) -> bool:
        """Process one report, returning whether it came from a configured station.

        A report from a configured station counts as accepted whatever then becomes of the
        write: it was authentic, and delivery records its own outcome.
        """
        passkey = fields.get("PASSKEY", "")
        station = self.config.lookup(passkey)
        if station is None:
            self._announce_unknown(passkey, source)
            self._pending.record(passkey, source, fields)
            return False

        received = self._clock()
        processed = process_report(
            fields,
            received_at=received,
            station=station.name,
            preferences=station.preferences,
            tracker=self._tracker,
        )
        self.latest[station.name] = LatestReport(processed.timestamp, received, processed.points)
        self._calibration.observe(station.name, processed.timestamp, processed.readings)
        await self._sink.submit(encode(processed.points))
        return True

    def _announce_unknown(self, passkey: str, source: str) -> None:
        """Log a report from an unlisted station, once per PASSKEY.

        The PASSKEY itself is never logged. Its fingerprint is: enough to tell one console from
        another and to match it to the entry the setup page offers, without putting the
        credential in a file anyone can read.
        """
        key = fingerprint(passkey)
        if key in self._announced or len(self._announced) >= MAX_ANNOUNCED_UNKNOWN:
            return
        self._announced.add(key)
        logger.warning(
            "report from %s discarded: no configured station has this PASSKEY "
            "(sha256 fingerprint %s); it can be adopted on the setup page",
            source,
            key,
        )

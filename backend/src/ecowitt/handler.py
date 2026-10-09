"""What the ingest listener does with a report: authenticate, process, write."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from .lineprotocol import encode
from .pipeline import process
from .staleness import StalenessTracker
from .state import State
from .stationconfig import StationConfig

logger = logging.getLogger(__name__)

#: Unknown stations are announced once each, up to this many, so a misconfigured console is
#: visible in the log without a scan of invented PASSKEYs filling it.
MAX_ANNOUNCED_UNKNOWN = 100


class Writer(Protocol):
    """Somewhere encoded rows can be written."""

    async def write(self, body: str) -> bool:
        """Write rows, returning whether they were accepted."""


class StationHandler:
    """Accepts reports from configured stations and writes what they measured."""

    def __init__(
        self,
        config: StationConfig,
        writer: Writer,
        state: State,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._writer = writer
        self._state = state
        self._clock = clock
        self._tracker = StalenessTracker()
        self._announced: set[str] = set()

    async def handle(self, fields: Mapping[str, str], source: str) -> bool:
        """Process one report, returning whether it came from a configured station.

        A report from a configured station counts as accepted even if the write then fails: it
        was authentic, and the failure is the database's, recorded separately.
        """
        passkey = fields.get("PASSKEY", "")
        station = self._config.lookup(passkey)
        if station is None:
            self._announce_unknown(passkey, source)
            return False

        points = process(
            fields,
            received_at=self._clock(),
            station=station.name,
            preferences=station.preferences,
            tracker=self._tracker,
        )
        written = await self._writer.write(encode(points))
        self._state.record_write(written)
        return True

    def _announce_unknown(self, passkey: str, source: str) -> None:
        """Log a report from an unlisted station, once per PASSKEY.

        The PASSKEY itself is never logged. Its fingerprint is: enough to tell one console from
        another and to confirm which entry a newly added one should be, without putting the
        credential in a file anyone can read.
        """
        fingerprint = hashlib.sha256(passkey.encode()).hexdigest()[:12] if passkey else "none"
        if fingerprint in self._announced or len(self._announced) >= MAX_ANNOUNCED_UNKNOWN:
            return
        self._announced.add(fingerprint)
        logger.warning(
            "report from %s discarded: no configured station has this PASSKEY "
            "(sha256 fingerprint %s)",
            source,
            fingerprint,
        )

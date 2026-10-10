"""Stations that have reported but are not configured yet, so the setup page can offer them.

Finding a console's PASSKEY otherwise means capturing its traffic. Instead, every unknown
report is remembered here -- by fingerprint, with the model and firmware it announced -- and
the operator adopts the right one from a list. The PASSKEY itself stays in this process: the
page refers to an entry by fingerprint, and adopting it copies the PASSKEY straight into the
configuration without it ever being displayed.

Bounded and short-lived, because anyone on the internet can make an entry: only the most
recently heard stations are kept, and only for an hour after they were last heard.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

MAX_PENDING = 20
FORGET_AFTER_SECONDS = 3600


def fingerprint(passkey: str, key: bytes) -> str:
    """A short, stable name for a PASSKEY that cannot be reversed without `key`.

    Keyed, because a PASSKEY is the MD5 of a MAC address: an unkeyed hash of one could be
    reversed by trying the few million addresses of a single vendor prefix, and fingerprints
    are written to the log and shown on the setup page.
    """
    if not passkey:
        return "none"
    return hmac.new(key, passkey.encode(), hashlib.sha256).hexdigest()[:12]


@dataclass
class PendingStation:
    """An unconfigured station, as last heard."""

    fingerprint: str
    passkey: str
    model: str
    stationtype: str
    source: str
    first_seen: float
    last_seen: float
    reports: int = 1


class PendingStations:
    """The recently heard, unconfigured stations."""

    def __init__(self, clock: Callable[[], float] = time.time, *, key: bytes | None = None) -> None:
        self._clock = clock
        # Without the server's own key the fingerprints are stable only for this process.
        self._key = key if key is not None else os.urandom(32)
        self._entries: OrderedDict[str, PendingStation] = OrderedDict()

    def record(self, passkey: str, source: str, fields: Mapping[str, str]) -> None:
        """Remember a report from an unconfigured station. Reports with no PASSKEY are ignored."""
        if not passkey:
            return
        now = self._clock()
        key = self.fingerprint(passkey)
        entry = self._entries.pop(key, None)
        if entry is None:
            entry = PendingStation(
                key, passkey, "", "", source, first_seen=now, last_seen=now, reports=0
            )
        entry.reports += 1
        entry.last_seen = now
        entry.source = source
        # Bounded, because these come from an unauthenticated caller and end up on a page.
        entry.model = fields.get("model", entry.model)[:64]
        entry.stationtype = fields.get("stationtype", entry.stationtype)[:64]
        self._entries[key] = entry
        while len(self._entries) > MAX_PENDING:
            self._entries.popitem(last=False)

    def fingerprint(self, passkey: str) -> str:
        """The name this list gives a PASSKEY."""
        return fingerprint(passkey, self._key)

    def list(self) -> list[PendingStation]:
        """Stations heard within the last hour, most recent first."""
        self._expire()
        return list(reversed(self._entries.values()))

    def get(self, key: str) -> PendingStation | None:
        """An entry by fingerprint, left in place."""
        self._expire()
        return self._entries.get(key)

    def discard(self, passkey: str) -> None:
        """Forget a station that has since been configured."""
        self._entries.pop(self.fingerprint(passkey), None)

    def _expire(self) -> None:
        """Forget entries not heard from within the last hour."""
        cutoff = self._clock() - FORGET_AFTER_SECONDS
        for key in [k for k, e in self._entries.items() if e.last_seen < cutoff]:
            del self._entries[key]

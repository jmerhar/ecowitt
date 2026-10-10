"""How long each sensor's readings have gone without changing.

Ecowitt consoles keep reporting a sensor's last received values after its radio goes quiet --
a dead battery, a sensor out of range -- so a flat line in the data can mean a stable room or a
sensor that stopped transmitting hours ago. Counting how long the values have been identical
is the only way to tell them apart, and it also measures each sensor's real transmit interval.

Measured on the stations' own timestamps rather than this server's clock, so it is
reproducible from the reports alone. Held in memory: a restart begins every count again at
zero, which errs towards "fresh" for at most one stale period.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field


@dataclass
class StalenessTracker:
    """Remembers, per sensor, its last values and when they last changed."""

    _seen: dict[Hashable, tuple[Hashable, int]] = field(default_factory=dict)

    def observe(self, sensor: Hashable, signature: Hashable, timestamp: int) -> int:
        """Record a sensor's values at `timestamp`, returning seconds since they last changed.

        A timestamp earlier than the recorded change -- a station whose clock was corrected,
        or reports replayed out of order -- restarts the count rather than going negative.
        """
        previous = self._seen.get(sensor)
        if previous is None or previous[0] != signature or timestamp < previous[1]:
            self._seen[sensor] = (signature, timestamp)
            return 0
        return timestamp - previous[1]

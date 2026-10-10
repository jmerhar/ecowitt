"""A per-address request budget for the internet-facing listener."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """A token bucket per client address.

    Each address may make `burst` requests at once and `rate` per second after that. The
    tightest a console can be configured is one report every 8 seconds, so the defaults leave a
    real station more than an order of magnitude of headroom while capping what any one address
    can make this process do.

    Addresses are tracked in least-recently-used order and the oldest is forgotten beyond
    `max_clients`, so a scan from many addresses cannot grow this without bound.
    """

    rate: float = 2.0
    burst: int = 20
    max_clients: int = 10_000
    clock: Callable[[], float] = time.monotonic
    _buckets: OrderedDict[str, tuple[float, float]] = field(default_factory=OrderedDict)

    def allow(self, client: str) -> bool:
        """Spend one token for `client`, returning whether it had one."""
        now = self.clock()
        tokens, last = self._buckets.pop(client, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - last) * self.rate)
        allowed = tokens >= 1
        self._buckets[client] = (tokens - 1 if allowed else tokens, now)
        while len(self._buckets) > self.max_clients:
            self._buckets.popitem(last=False)
        return allowed

"""The per-address request budget."""

from __future__ import annotations

from ecowitt.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_burst_is_allowed_then_refused() -> None:
    limiter = RateLimiter(rate=1.0, burst=3, clock=Clock())

    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_tokens_refill_at_the_rate() -> None:
    clock = Clock()
    limiter = RateLimiter(rate=2.0, burst=2, clock=clock)
    limiter.allow("a")
    limiter.allow("a")
    assert not limiter.allow("a")

    clock.now = 0.5

    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_refill_never_exceeds_the_burst() -> None:
    """An address idle for an hour gets its burst back, not an hour's worth of requests.

    The address is seen once first: a new one starts at exactly the burst with no time
    elapsed, so jumping the clock before its first request would never exercise the cap.
    """
    clock = Clock()
    limiter = RateLimiter(rate=10.0, burst=2, clock=clock)
    limiter.allow("a")
    clock.now = 3600.0

    assert [limiter.allow("a") for _ in range(3)] == [True, True, False]


def test_a_station_at_its_fastest_interval_is_never_refused() -> None:
    """One report every 8 seconds, for a day."""
    clock = Clock()
    limiter = RateLimiter(clock=clock)

    for i in range(10_800):
        clock.now = i * 8.0
        assert limiter.allow("station")


def test_addresses_have_separate_budgets() -> None:
    limiter = RateLimiter(rate=0.0, burst=1, clock=Clock())

    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")


def test_tracked_addresses_are_bounded() -> None:
    """A scan from many addresses cannot grow the table without limit."""
    limiter = RateLimiter(rate=0.0, burst=1, max_clients=3, clock=Clock())
    for client in ("a", "b", "c", "d"):
        limiter.allow(client)

    assert list(limiter._buckets) == ["b", "c", "d"]
    # The forgotten address starts afresh with a full bucket.
    assert limiter.allow("a")


def test_recently_seen_addresses_are_kept_over_older_ones() -> None:
    limiter = RateLimiter(rate=0.0, burst=5, max_clients=2, clock=Clock())
    limiter.allow("a")
    limiter.allow("b")
    limiter.allow("a")
    limiter.allow("c")

    assert list(limiter._buckets) == ["a", "c"]

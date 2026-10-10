"""The staleness tracker on its own."""

from __future__ import annotations

from ecowitt.collector.staleness import StalenessTracker


def test_first_sight_is_zero() -> None:
    assert StalenessTracker().observe("s", (1,), 500) == 0


def test_unchanged_counts_from_the_last_change() -> None:
    tracker = StalenessTracker()
    tracker.observe("s", (1,), 100)

    assert tracker.observe("s", (1,), 160) == 60
    assert tracker.observe("s", (1,), 220) == 120


def test_a_change_restarts_the_count() -> None:
    tracker = StalenessTracker()
    tracker.observe("s", (1,), 100)

    assert tracker.observe("s", (2,), 160) == 0
    assert tracker.observe("s", (2,), 170) == 10


def test_time_going_backwards_restarts_rather_than_going_negative() -> None:
    """A corrected station clock or an out-of-order replay."""
    tracker = StalenessTracker()
    tracker.observe("s", (1,), 1000)

    assert tracker.observe("s", (1,), 900) == 0
    assert tracker.observe("s", (1,), 960) == 60


def test_sensors_are_independent() -> None:
    tracker = StalenessTracker()
    tracker.observe("a", (1,), 0)
    tracker.observe("b", (1,), 50)

    assert tracker.observe("a", (1,), 100) == 100
    assert tracker.observe("b", (1,), 100) == 50

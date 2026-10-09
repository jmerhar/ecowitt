"""Unconfigured stations remembered for adoption."""

from __future__ import annotations

from ecowitt.pending import FORGET_AFTER_SECONDS, MAX_PENDING, PendingStations, fingerprint


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_station_is_remembered_with_what_it_announced() -> None:
    pending = PendingStations(Clock())

    pending.record(
        "KEY1",
        "192.0.2.9",
        {"model": "HP2551AE_Pro_V2.1.4", "stationtype": "EasyWeatherPro_V5.2.7"},
    )
    pending.record("KEY1", "192.0.2.9", {})

    (entry,) = pending.list()
    assert entry.fingerprint == fingerprint("KEY1")
    assert (entry.model, entry.stationtype, entry.reports) == (
        "HP2551AE_Pro_V2.1.4",
        "EasyWeatherPro_V5.2.7",
        2,
    )


def test_most_recent_first() -> None:
    clock = Clock()
    pending = PendingStations(clock)
    pending.record("A", "x", {})
    clock.now += 1
    pending.record("B", "x", {})

    assert [e.passkey for e in pending.list()] == ["B", "A"]


def test_bounded_to_the_most_recent() -> None:
    pending = PendingStations(Clock())
    for i in range(MAX_PENDING + 5):
        pending.record(f"K{i}", "x", {})

    assert len(pending.list()) == MAX_PENDING
    assert pending.list()[-1].passkey == "K5"


def test_forgotten_an_hour_after_last_heard() -> None:
    clock = Clock()
    pending = PendingStations(clock)
    pending.record("A", "x", {})
    clock.now += FORGET_AFTER_SECONDS + 1

    assert pending.list() == []


def test_announced_fields_are_truncated() -> None:
    """They come from anyone on the internet and end up on a page."""
    pending = PendingStations(Clock())
    pending.record("A", "x", {"model": "m" * 500})

    assert len(pending.list()[0].model) == 64


def test_get_leaves_the_entry_and_discard_forgets() -> None:
    pending = PendingStations(Clock())
    pending.record("A", "x", {})

    assert pending.get(fingerprint("A")).passkey == "A"  # type: ignore[union-attr]
    assert pending.get(fingerprint("A")) is not None
    assert pending.get("nope") is None
    pending.discard("A")
    assert pending.list() == []


def test_a_report_without_a_passkey_is_not_remembered() -> None:
    pending = PendingStations(Clock())
    pending.record("", "x", {})

    assert pending.list() == []
    assert fingerprint("") == "none"

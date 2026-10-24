"""How much a counter rose in each bucket, from each bucket's highest and lowest value."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ecowitt.core.store.query import increases

HOUR = timedelta(hours=1)
START = datetime(2026, 10, 23, tzinfo=UTC)


def hours(*offsets: int) -> list[datetime]:
    """Bucket starts, `offsets` hours after START."""
    return [START + n * HOUR for n in offsets]


def test_a_bucket_rose_from_the_highest_value_of_the_one_before() -> None:
    # 0.3 fell between the last report of the first hour and the first of the second.
    found = increases(hours(0, 1, 2), [10.8, 12.3, 12.3], [10.0, 11.1, 12.3], HOUR)
    assert found == pytest.approx([0.8, 1.5, 0.0])


def test_after_a_gap_a_bucket_rose_from_its_own_lowest_value() -> None:
    found = increases(hours(0, 3), [10.8, 15.0], [10.0, 14.5], HOUR)
    assert found == pytest.approx([0.8, 0.5])


def test_a_counter_reset_rises_from_the_buckets_own_lowest_value() -> None:
    # The year's total starts again at 0 on 1 January.
    found = increases(hours(0, 1), [400.0, 0.4], [399.0, 0.0], HOUR)
    assert found == pytest.approx([1.0, 0.4])


def test_a_bucket_without_a_value_has_none_and_the_next_rises_from_its_own() -> None:
    found = increases(hours(0, 1, 2), [10.0, None, 11.0], [10.0, None, 10.5], HOUR)
    assert found == pytest.approx([0.0, None, 0.5])

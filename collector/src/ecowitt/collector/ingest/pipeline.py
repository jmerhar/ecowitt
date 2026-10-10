"""From one report's fields to the rows written for it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ecowitt.collector.ingest.derive import derive
from ecowitt.collector.ingest.parse import parse
from ecowitt.collector.ingest.points import render
from ecowitt.collector.ingest.staleness import StalenessTracker
from ecowitt.core.preferences import Preferences
from ecowitt.core.readings import Reading
from ecowitt.core.store.base import Row


@dataclass(frozen=True)
class Processed:
    """One report after processing: canonical readings, and the rows rendered from them."""

    timestamp: int
    #: Parsed and derived readings in canonical units, for anything that reasons about values
    #: -- the calibration checks -- rather than displaying them.
    readings: list[Reading]
    points: list[Row]


def process_report(
    raw: Mapping[str, str],
    *,
    received_at: datetime,
    station: str,
    preferences: Preferences,
    tracker: StalenessTracker,
) -> Processed:
    """Parse, derive and render one report, keeping the canonical readings."""
    report = parse(raw, received_at)
    derived = derive(
        report.readings, preferences, tracker, station=station, timestamp=report.timestamp
    )
    readings = [*report.readings, *derived]
    points = render(readings, preferences, station=station, timestamp=report.timestamp)
    return Processed(report.timestamp, readings, points)


def process(
    raw: Mapping[str, str],
    *,
    received_at: datetime,
    station: str,
    preferences: Preferences,
    tracker: StalenessTracker,
) -> list[Row]:
    """Parse, derive and render one report, returning only the rows."""
    return process_report(
        raw, received_at=received_at, station=station, preferences=preferences, tracker=tracker
    ).points

"""From one report's fields to the rows written for it."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .derive import derive
from .parse import parse
from .points import Point, render
from .preferences import Preferences
from .staleness import StalenessTracker


def process(
    raw: Mapping[str, str],
    *,
    received_at: datetime,
    station: str,
    preferences: Preferences,
    tracker: StalenessTracker,
) -> list[Point]:
    """Parse, derive and render one report."""
    report = parse(raw, received_at)
    derived = derive(
        report.readings, preferences, tracker, station=station, timestamp=report.timestamp
    )
    return render(
        [*report.readings, *derived], preferences, station=station, timestamp=report.timestamp
    )

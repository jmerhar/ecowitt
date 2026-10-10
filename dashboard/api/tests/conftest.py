"""A station's day of readings in memory, and the dashboard and app built on it."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.base import Row
from ecowitt.dashboard.app import build_app
from ecowitt.dashboard.service import Dashboard
from ecowitt.dashboard.settings import Settings

from .memory import MemoryReader

REPO = Path(__file__).resolve().parents[3]
#: 15:00 in Lisbon, where the station's day began at 23:00 UTC the day before.
NOW = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
LAST = NOW - timedelta(minutes=1)
MIDNIGHT = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)
INFO = StationInfo(
    "example",
    latitude=38.72,
    longitude=-9.14,
    altitude_m=100.0,
    timezone="Europe/Lisbon",
    sensors={"indoor": "Lounge", "ch1": "Bathroom", "outdoor": "Garden"},
)

CONFIG = """\
title: Test weather
stations: []
store:
  kind: influx3
  url: http://db:8181
  database: weather
  token: apiv3_read
"""


def row(table: str, at: datetime, fields: dict[str, object], **tags: str) -> Row:
    """A row of the example station's."""
    return Row(table, (("station", "example"), *sorted(tags.items())), int(at.timestamp()), fields)  # type: ignore[arg-type]


def readings() -> list[Row]:
    """A station whose day has a low, a high, a stale sensor, a flat battery and rain."""
    out = {"sensor": "outdoor", "name": "Garden"}
    # The newest rows carry names older than the station's settings, which win.
    lounge = {"sensor": "indoor", "name": "Living"}
    bath = {"sensor": "ch1", "name": "ch1"}
    hour = timedelta(hours=1)
    return [
        row("station", LAST, {"interval_s": 60.0, "model": "HP2551"}),
        row("outdoor", MIDNIGHT + hour / 2, {"temp_c": 12.0, "humidity_pct": 80.0}, **out),
        row("outdoor", MIDNIGHT + 7 * hour, {"temp_c": 9.5, "humidity_pct": 90.0}, **out),
        row("outdoor", NOW - hour, {"temp_c": 21.0, "humidity_pct": 60.0}, **out),
        row("outdoor", LAST, {"temp_c": 18.0, "humidity_pct": 70.0}, **out),
        # The black globe sensor shares the table, and is not the outdoor temperature.
        row("outdoor", LAST, {"temp_c": 40.0}, sensor="bgt", name="bgt"),
        row("derived", LAST, {"dewpoint_c": 12.5, "unchanged_s": 0.0}, **out),
        row("derived", LAST, {"dewpoint_c": 11.9, "unchanged_s": 60.0}, **lounge),
        row("derived", LAST, {"dewpoint_c": 15.4, "unchanged_s": 20000.0}, **bath),
        row("derived", LAST, {"unchanged_s": 0.0}, sensor="pressure", name="pressure"),
        row("wind", NOW - 4 * hour, {"speed_kmh": 30.0, "gust_kmh": 52.0, "dir_deg": 350.0}),
        row("wind", LAST - hour / 12, {"speed_kmh": 10.0, "gust_kmh": 20.0, "dir_deg": 10.0}),
        row("wind", LAST, {"speed_kmh": 15.0, "gust_kmh": 25.0, "dir_deg": 135.0}),
        row(
            "rain",
            LAST,
            {
                "rate_mm_h": 2.4,
                "daily_mm": 3.0,
                "event_mm": 3.0,
                "hourly_mm": 1.2,
                "last24h_mm": 3.5,
                "weekly_mm": 9.0,
                "monthly_mm": 20.0,
                "yearly_mm": 400.0,
            },
            gauge="bucket",
        ),  # fmt: skip
        # The console's relative pressure moves less than sea-level pressure, so a trend read from
        # the wrong one shows.
        row("pressure", LAST - 3 * hour, {"sea_hpa": 1015.0, "abs_hpa": 1003.0, "rel_hpa": 1014.0}),
        row("pressure", LAST, {"sea_hpa": 1012.0, "abs_hpa": 1000.0, "rel_hpa": 1013.0}),
        row("solar", LAST, {"radiation_wm2": 450.4, "uv_index": 4.0}),
        row("indoor", LAST, {"temp_c": 21.0, "humidity_pct": 55.0}, **lounge),
        row("channel", NOW - 2 * hour, {"temp_c": 22.0, "humidity_pct": 70.0}, **bath, channel="1"),
        row("channel", LAST, {"temp_c": 20.0, "humidity_pct": 75.0}, **bath, channel="1"),
        row(
            "ventilation",
            LAST,
            {"dewpoint_delta_c": -0.6, "predicted_humidity_pct": 58.0},
            **lounge,
        ),
        row("ventilation", LAST, {"dewpoint_delta_c": 2.9, "predicted_humidity_pct": 49.0}, **bath),
        row("battery", LAST, {"low": True}, **bath),
        row("battery", LAST, {"low": False}, **lounge),
    ]


@pytest.fixture
def reader() -> MemoryReader:
    """The example station, in memory."""
    return MemoryReader(readings(), {"example": INFO})


@pytest.fixture
def board(reader: MemoryReader) -> Dashboard:
    """A dashboard over the example station, at NOW."""
    return Dashboard(reader, title="Test weather", clock=lambda: NOW)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with an empty data directory and a generous rate limit."""
    return Settings(data_dir=tmp_path, rate=1000.0, burst=1000)


@pytest.fixture
def client(settings: Settings, reader: MemoryReader) -> Iterator[TestClient]:
    """The configured app, reading the example station at NOW."""
    settings.config_path.write_text(CONFIG, encoding="utf-8")
    app = build_app(settings, make_reader=lambda *_: reader)
    app.state.site.dashboard.clock = lambda: NOW
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client

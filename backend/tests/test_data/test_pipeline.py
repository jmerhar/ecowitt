"""End to end: a recorded console upload to the exact line protocol written for it.

The golden file pins every table, tag, field name, unit and rounding at once. The values in it
are not trusted because the code produced them -- the conversions and formulas behind them are
checked against reference values in test_units and test_psychro -- so a diff here is a change
of output to review, not a number to rubber-stamp.

Regenerate after an intended change with:
    UPDATE_GOLDEN=1 bin/test-backend.sh tests/test_data/test_pipeline.py
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import UTC, datetime

from ecowitt.lineprotocol import encode
from ecowitt.pipeline import process
from ecowitt.preferences import Preferences
from ecowitt.staleness import StalenessTracker

from ..conftest import FIXTURES, payload

#: Invented names and altitude: a fixture describes no real house.
PREFERENCES = Preferences(
    names={
        "indoor": "Lounge",
        "ch1": "Bathroom",
        "ch2": "Study",
        "ch3": "Spare room",
        "ch4": "Attic",
        "ch5": "Bedroom",
        "ch6": "En-suite",
        "ch7": "Nursery",
        "ch8": "Kitchen",
    },
    altitude_m=250,
)
RECEIVED = datetime(2026, 10, 8, 23, 1, 26, tzinfo=UTC)


def _lines(name: str) -> str:
    raw = dict(urllib.parse.parse_qsl(payload(name), keep_blank_values=True))
    points = process(
        raw,
        received_at=RECEIVED,
        station="example",
        preferences=PREFERENCES,
        tracker=StalenessTracker(),
    )
    return encode(points) + "\n"


def test_hp2551_indoor_matches_the_golden_output() -> None:
    golden = FIXTURES / "hp2551_indoor.lp"
    actual = _lines("hp2551_indoor")
    if os.environ.get("UPDATE_GOLDEN"):
        golden.write_text(actual, encoding="utf-8")

    assert actual == golden.read_text(encoding="utf-8")


def test_no_credential_reaches_the_output() -> None:
    from ..conftest import FIXTURE_PASSKEY

    assert FIXTURE_PASSKEY not in _lines("hp2551_indoor")


def test_a_full_outdoor_report_derives_ventilation_and_sea_level() -> None:
    """Indoor, outdoor and pressure together exercise every cross-sensor derivation.

    Assembled inline from known keys rather than recorded, so it is not a fixture: no outdoor
    sensor's upload has been captured yet.
    """
    raw = {
        "dateutc": "2026-10-08 23:01:24",
        "tempinf": "71.6",
        "humidityin": "62",
        "tempf": "50.0",
        "humidity": "80",
        "baromabsin": "29.10",
        "baromrelin": "29.10",
        "temp1f": "68.0",
        "humidity1": "70",
        "windspeedmph": "5.6",
        "winddir": "270",
        "dailyrainin": "0.12",
        "solarradiation": "0.0",
        "uv": "0",
        "wh65batt": "0",
    }
    points = process(
        raw,
        received_at=RECEIVED,
        station="example",
        preferences=PREFERENCES,
        tracker=StalenessTracker(),
    )
    rows = {(p.table, dict(p.tags).get("sensor")): p.fields for p in points}

    assert rows[("ventilation", "ch1")]["dewpoint_delta_c"] > 0
    assert rows[("ventilation", "indoor")]["predicted_humidity_pct"] < 62
    assert rows[("pressure", None)]["sea_temp_source"] == "outdoor"
    assert rows[("rain", None)]["daily_mm"] == 3.048
    assert rows[("wind", None)]["speed_kmh"] == 9.0123
    assert rows[("battery", "outdoor")]["low"] is False

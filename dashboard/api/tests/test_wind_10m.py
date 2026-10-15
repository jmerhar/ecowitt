"""The wind answers lead with the estimate at 10 m, with the measured wind beside it."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from ecowitt.dashboard.service import Dashboard

from .conftest import INFO, LAST, NOW, readings, row
from .memory import MemoryReader

CORRECTED = dataclasses.replace(INFO, wind_factor=2.0)


def board(ten: list | None = None, info=CORRECTED) -> Dashboard:  # noqa: ANN001
    """The example station with its 10 m rows replaced by `ten` (none at all for None)."""
    rows = [r for r in readings() if r.table != "wind_10m"]
    return Dashboard(MemoryReader(rows + (ten or []), {"example": info}), clock=lambda: NOW)


def ten(at, speed: float, gust: float, source: str = "sensor"):  # noqa: ANN001, ANN201
    return row("wind_10m", at, {"speed_kmh": speed, "gust_kmh": gust, "source": source})


async def test_the_estimate_leads_and_the_measurement_follows() -> None:
    dashboard = board([ten(LAST - timedelta(hours=4), 60.0, 104.0), ten(LAST, 30.0, 50.0)])

    wind = (await dashboard.now("example")).wind

    assert wind is not None
    assert (wind.speed, wind.gust, wind.source, wind.height_factor) == (30.0, 50.0, "sensor", 2.0)
    assert (wind.measured_speed, wind.measured_gust) == (15.0, 25.0)
    # Beaufort describes wind at 10 m, so it follows the estimate: 30 km/h is a fresh breeze,
    # where the measured 15 km/h would be a gentle one.
    assert (wind.beaufort, wind.description) == (5, "Fresh breeze")
    assert (wind.measured_beaufort, wind.measured_description) == (3, "Gentle breeze")
    assert wind.max_gust_today is not None and wind.max_gust_today.value == 104.0
    assert wind.measured_max_gust_today is not None
    assert wind.measured_max_gust_today.value == 52.0


async def test_the_models_wind_is_marked_as_such() -> None:
    wind = (await board([ten(LAST, 12.0, 20.0, "model")]).now("example")).wind

    assert wind is not None and (wind.speed, wind.source) == (12.0, "model")


async def test_without_an_estimate_the_measured_wind_leads() -> None:
    """A station whose collector writes no 10 m estimate still shows its wind."""
    wind = (await board(info=INFO).now("example")).wind

    assert wind is not None
    assert (wind.speed, wind.gust, wind.source) == (15.0, 25.0, None)
    assert wind.max_gust_today is not None and wind.max_gust_today.value == 52.0


async def test_strong_gusts_are_judged_at_10_m() -> None:
    """25 km/h measured is 61 km/h at 10 m, over the 60 km/h line."""
    notices = (await board([ten(LAST, 30.0, 61.0)]).now("example")).notices

    assert notices["wind"].text == "Strong gusts."


async def test_charts_lead_with_the_estimate_and_offer_the_measurement() -> None:
    dashboard = board([ten(LAST, 30.0, 50.0)])

    found = await dashboard.series(
        "example", ["wind.speed", "wind.measured_speed", "wind.gust", "wind.measured_gust"], "24h"
    )

    last = {s.metric: next(iter(s.values.values()))[-1] for s in found.series}
    assert last == {
        "wind.speed": 30.0,
        "wind.measured_speed": 15.0,
        "wind.gust": 50.0,
        "wind.measured_gust": 25.0,
    }


async def test_records_are_kept_at_10_m_and_as_measured() -> None:
    found = await board([ten(LAST, 30.0, 50.0)]).extremes("example", "today")

    highest = {
        e.metric: e.max.value for e in found.extremes if e.metric.startswith("wind.") and e.max
    }
    assert highest["wind.gust"] == 50.0
    assert highest["wind.measured_gust"] == 52.0
    assert {e.metric: e.min for e in found.extremes if e.metric == "wind.measured_gust"} == {
        "wind.measured_gust": None
    }


async def test_stations_publish_their_factor() -> None:
    (station,) = await board().stations()

    assert station.wind_factor == 2.0

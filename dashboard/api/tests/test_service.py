"""The answers, built from the example station's readings in memory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import ReadError
from ecowitt.dashboard.service import RANGES, Dashboard, UnknownStation

from .conftest import INFO, LAST, MIDNIGHT, NOW, readings, row
from .memory import MemoryReader


async def test_now_reads_the_latest_report(board: Dashboard) -> None:
    now = await board.now("example")
    assert now.time == LAST
    assert now.online
    assert now.timezone == "Europe/Lisbon"
    assert now.units.temperature == "c"


async def test_outdoor_conditions_with_todays_range(board: Dashboard) -> None:
    outdoor = (await board.now("example")).outdoor
    assert outdoor is not None
    assert (outdoor.temperature, outdoor.humidity, outdoor.dew_point) == (18.0, 70.0, 12.5)
    assert outdoor.feels_like == 18.0
    assert outdoor.high is not None and outdoor.low is not None
    assert (outdoor.high.value, outdoor.high.time) == (21.0, NOW - timedelta(hours=1))
    assert (outdoor.low.value, outdoor.low.time) == (9.5, MIDNIGHT + timedelta(hours=7))


async def test_today_begins_at_the_stations_midnight(reader: MemoryReader) -> None:
    reader.rows.append(
        row("outdoor", MIDNIGHT - timedelta(minutes=1), {"temp_c": 30.0}, sensor="outdoor")
    )
    board = Dashboard(reader, clock=lambda: NOW)
    outdoor = (await board.now("example")).outdoor
    assert outdoor is not None and outdoor.high is not None
    assert outdoor.high.value == 21.0


async def test_wind_in_words_and_todays_strongest_gust(board: Dashboard) -> None:
    wind = (await board.now("example")).wind
    assert wind is not None
    assert (wind.speed, wind.gust, wind.direction, wind.compass) == (15.0, 25.0, 135, "SE")
    assert (wind.beaufort, wind.description) == (3, "Gentle breeze")
    assert wind.max_gust_today is not None and wind.max_gust_today.value == 52.0


async def test_rain_pressure_and_sun(board: Dashboard) -> None:
    now = await board.now("example")
    assert now.rain is not None
    assert (now.rain.gauge, now.rain.rate, now.rain.daily, now.rain.raining) == (
        "bucket",
        2.4,
        3.0,
        True,
    )
    assert (now.rain.last_24h, now.rain.yearly) == (3.5, 400.0)
    assert now.pressure is not None and now.pressure.trend is not None
    assert (now.pressure.sea_level, now.pressure.absolute) == (1012.0, 1000.0)
    assert now.pressure.trend.change == -3.0
    assert now.pressure.trend.tendency == "falling"
    assert now.pressure.trend.hours == 3.0
    assert now.sun is not None
    assert (now.sun.radiation, now.sun.uv_index) == (450.0, 4.0)
    assert now.sun.sunrise is not None and now.sun.sunset is not None
    assert now.sun.sunrise.date() == NOW.date() and now.sun.polar is None
    assert now.sun.daylight_s == int((now.sun.sunset - now.sun.sunrise).total_seconds())


async def test_rooms_come_with_airing_advice_and_current_names(board: Dashboard) -> None:
    rooms = (await board.now("example")).rooms
    assert [(r.sensor, r.name) for r in rooms] == [("indoor", "Lounge"), ("ch1", "Bathroom")]
    lounge, bathroom = rooms
    assert (lounge.temperature, lounge.humidity, lounge.dew_point) == (21.0, 55.0, 11.9)
    assert lounge.airing is not None and lounge.airing.advice == "no_need"
    assert bathroom.airing is not None
    assert bathroom.airing.advice == "open"
    assert (bathroom.airing.humidity_after, bathroom.airing.dew_point_difference) == (49.0, 2.9)


async def test_sensor_health(board: Dashboard) -> None:
    sensors = {s.sensor: s for s in (await board.now("example")).sensors}
    assert list(sensors) == ["indoor", "outdoor", "ch1", "pressure"]
    assert sensors["ch1"].battery_low is True
    assert sensors["ch1"].updating is False
    assert sensors["indoor"].battery_low is False and sensors["indoor"].updating
    assert sensors["pressure"].battery_low is None
    assert sensors["pressure"].name == "Barometer", "written as its own identifier"
    assert sensors["outdoor"].name == "Garden"


async def test_the_summary_says_it_in_one_line(board: Dashboard) -> None:
    summary = (await board.now("example")).summary
    assert summary == "18 °C. Gentle breeze from the SE. Raining, 2.4 mm/h. Pressure falling."


async def test_units_can_be_chosen_per_quantity(board: Dashboard) -> None:
    now = await board.now("example", {"temperature": "f", "wind": "mph", "pressure": "inhg"})
    assert now.units.temperature == "f" and now.units.rain == "mm"
    assert now.outdoor is not None and now.outdoor.temperature == 64.4
    assert now.wind is not None and now.wind.speed == 9.3
    assert now.pressure is not None and now.pressure.sea_level == 29.88
    assert now.pressure.trend is not None and now.pressure.trend.change == -0.09
    assert now.rooms[1].airing is not None
    assert now.rooms[1].airing.dew_point_difference == 5.2
    assert now.summary.startswith("64.4 °F.")


async def test_a_station_storing_imperial_units_is_read_in_them() -> None:
    from ecowitt.core.units import Units

    info = StationInfo("example", units=Units(temperature="f", wind="mph"))
    rows = [
        row("station", LAST, {"interval_s": 60.0}),
        row("outdoor", LAST, {"temp_f": 32.0, "humidity_pct": 50.0}, sensor="outdoor"),
        row("wind", LAST, {"speed_mph": 10.0, "dir_deg": 0.0}),
    ]
    board = Dashboard(MemoryReader(rows, {"example": info}), clock=lambda: NOW)
    now = await board.now("example")
    assert now.outdoor is not None and now.outdoor.temperature == 32.0
    assert now.outdoor.feels_like == 23.7, "wind chill from 0 °C and 16.1 km/h, in °F"
    metric = await board.now("example", {"temperature": "c", "wind": "kmh"})
    assert metric.outdoor is not None and metric.outdoor.temperature == 0.0
    assert metric.wind is not None and metric.wind.speed == 16.1
    assert metric.summary == "0 °C, feels like -5 °C. Gentle breeze from the N."


async def test_a_quiet_station_is_offline_with_its_last_values(reader: MemoryReader) -> None:
    board = Dashboard(reader, clock=lambda: NOW + timedelta(hours=1))
    now = await board.now("example")
    assert not now.online
    assert now.time == LAST
    assert now.outdoor is not None and now.outdoor.temperature == 18.0


async def test_a_station_with_no_recent_report_has_nothing_to_show(reader: MemoryReader) -> None:
    board = Dashboard(reader, clock=lambda: NOW + timedelta(days=8))
    now = await board.now("example")
    assert (now.time, now.online, now.outdoor, now.rooms, now.summary) == (
        None,
        False,
        None,
        [],
        "",
    )


async def test_a_station_without_most_sensors_has_none_of_their_sections() -> None:
    rows = [row("station", LAST, {"interval_s": 60.0})]
    info = StationInfo("example")
    board = Dashboard(MemoryReader(rows, {"example": info}), clock=lambda: NOW)
    now = await board.now("example")
    assert (now.outdoor, now.wind, now.rain, now.pressure, now.sun) == (None,) * 5
    assert now.timezone == "UTC"
    assert now.summary == ""


async def test_a_trend_needs_nearly_three_hours_of_pressure(reader: MemoryReader) -> None:
    reader.rows = [
        r for r in reader.rows if not (r.table == "pressure" and r.timestamp < LAST.timestamp())
    ]
    reader.rows.append(row("pressure", LAST - timedelta(hours=2), {"sea_hpa": 1015.0}))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.pressure is not None and now.pressure.trend is None
    assert "Pressure" not in now.summary


async def test_a_trend_falls_back_to_relative_pressure_without_an_altitude(
    reader: MemoryReader,
) -> None:
    for i, r in enumerate(reader.rows):
        if r.table == "pressure":
            fields = {k: v for k, v in r.fields.items() if k != "sea_hpa"}
            reader.rows[i] = row("pressure", datetime.fromtimestamp(r.timestamp, UTC), fields)
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.pressure is not None and now.pressure.sea_level is None
    assert now.pressure.trend is not None and now.pressure.trend.change == -1.0


async def test_the_gauge_that_reported_last_is_shown(reader: MemoryReader) -> None:
    reader.rows.append(row("rain", LAST - timedelta(minutes=2), {"rate_mm_h": 0.0}, gauge="piezo"))
    reader.rows.append(row("rain", LAST, {"rate_mm_h": 0.0, "daily_mm": 0.0}, gauge="piezo"))
    rain = (await Dashboard(reader, clock=lambda: NOW).now("example")).rain
    assert rain is not None and (rain.gauge, rain.raining) == ("piezo", False)


async def test_a_calm_wind_has_no_direction_in_the_summary(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table != "wind"]
    reader.rows.append(row("wind", LAST, {"speed_kmh": 0.5, "dir_deg": 90.0}))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert "Calm." in now.summary


async def test_sun_times_need_coordinates(reader: MemoryReader) -> None:
    reader.infos["example"] = StationInfo("example", timezone="Europe/Lisbon")
    sun = (await Dashboard(reader, clock=lambda: NOW).now("example")).sun
    assert sun is not None and sun.sunrise is None and sun.radiation == 450.0
    reader.rows = [r for r in reader.rows if r.table != "solar"]
    assert (await Dashboard(reader, clock=lambda: NOW).now("example")).sun is None


async def test_polar_night_has_no_sunrise(reader: MemoryReader) -> None:
    reader.infos["example"] = StationInfo("example", latitude=78.2, longitude=15.6, timezone="UTC")
    winter = datetime(2026, 12, 21, 12, tzinfo=UTC)
    reader.rows.append(row("station", winter, {"interval_s": 60.0}))
    sun = (await Dashboard(reader, clock=lambda: winter).now("example")).sun
    assert sun is not None and (sun.polar, sun.sunrise, sun.daylight_s) == ("night", None, 0)


async def test_an_unknown_time_zone_counts_as_utc(reader: MemoryReader) -> None:
    reader.infos["example"] = StationInfo("example", timezone="Mars/Olympus")
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.timezone == "Mars/Olympus"
    assert now.outdoor is not None and now.outdoor.low is not None
    assert now.outdoor.low.value == 9.5


async def test_now_is_cached_for_every_visitor(board: Dashboard, reader: MemoryReader) -> None:
    await board.now("example")
    asked = len(reader.calls)
    await board.now("example", {"temperature": "f"})
    assert len(reader.calls) == asked


async def test_series_in_buckets_aligned_to_the_stations_midnight(board: Dashboard) -> None:
    found = await board.series("example", ["outdoor.temperature", "wind.direction"], "24h")
    assert (found.range, found.step_s, found.end) == ("24h", 300, NOW)
    assert found.start == NOW - RANGES["24h"].duration
    temperature, direction = found.series
    assert (temperature.metric, temperature.sensor, temperature.name) == (
        "outdoor.temperature",
        "outdoor",
        "Garden",
    )
    assert temperature.unit == "c"
    assert set(temperature.values) == {"mean", "min", "max"}
    assert temperature.values["max"][-1] == 18.0
    assert all((t - int(MIDNIGHT.timestamp())) % 300 == 0 for t in temperature.t)
    assert direction.sensor is None and direction.name is None
    assert direction.values["circular"][-1] == 135.0


async def test_daily_buckets_start_at_local_midnight(board: Dashboard) -> None:
    found = await board.series("example", ["outdoor.temperature"], "1y")
    assert found.series[0].t[-1] == int(MIDNIGHT.timestamp())
    assert found.series[0].values["min"] == [9.5]


async def test_room_series_cover_rooms_only(board: Dashboard) -> None:
    found = await board.series("example", ["rooms.temperature", "rooms.dew_point"], "24h")
    assert [(s.metric, s.sensor, s.name) for s in found.series] == [
        ("rooms.temperature", "indoor", "Lounge"),
        ("rooms.temperature", "ch1", "Bathroom"),
        ("rooms.dew_point", "ch1", "Bathroom"),
        ("rooms.dew_point", "indoor", "Lounge"),
    ]


async def test_series_are_converted(board: Dashboard) -> None:
    found = await board.series("example", ["wind.gust", "rain.rate"], "7d", {"wind": "kn"})
    gust, rain = found.series
    assert gust.unit == "kn" and gust.values["max"][-1] == 13.5
    assert (rain.sensor, rain.unit) == ("bucket", "mm_h")


async def test_a_group_without_the_metric_has_no_series(reader: MemoryReader) -> None:
    reader.rows.append(row("derived", LAST, {"unchanged_s": 0.0}, sensor="ch2", name="ch2"))
    board = Dashboard(reader, clock=lambda: NOW)
    found = await board.series("example", ["rooms.dew_point"], "30d")
    assert [s.sensor for s in found.series] == ["ch1", "indoor"]


async def test_series_ask_once_per_table(board: Dashboard, reader: MemoryReader) -> None:
    await board.series("example", ["outdoor.temperature", "outdoor.humidity"], "24h")
    assert [c for c in reader.calls if c[0] == "buckets"] == [("buckets", "example", "outdoor")]


async def test_extremes_of_today(board: Dashboard) -> None:
    found = await board.extremes("example", "today")
    assert (found.start, found.end) == (MIDNIGHT, NOW)
    by = {(e.metric, e.sensor): e for e in found.extremes}
    temperature = by[("outdoor.temperature", "outdoor")]
    assert temperature.min is not None and temperature.max is not None
    assert (temperature.min.value, temperature.max.value) == (9.5, 21.0)
    gust = by[("wind.gust", None)]
    assert gust.min is None and gust.max is not None and gust.max.value == 52.0
    assert ("rooms.temperature", "ch1") in by
    assert ("outdoor.temperature", "bgt") not in by
    assert not any(e.metric == "wind.direction" for e in found.extremes)


@pytest.mark.parametrize(
    ("period", "start"),
    [
        ("month", datetime(2026, 9, 30, 23, tzinfo=UTC)),
        ("year", datetime(2026, 1, 1, tzinfo=UTC)),
    ],
)
async def test_extremes_of_a_month_or_year(board: Dashboard, period: str, start: datetime) -> None:
    found = await board.extremes("example", period, {"temperature": "f"})
    assert found.start == start
    assert found.units.temperature == "f"
    temperature = next(e for e in found.extremes if e.metric == "outdoor.temperature")
    assert temperature.max is not None and temperature.max.value == 69.8


async def test_stations_and_their_settings(board: Dashboard) -> None:
    (station,) = await board.stations()
    assert (station.id, station.latitude, station.timezone) == ("example", 38.72, "Europe/Lisbon")


async def test_only_the_configured_stations_are_shown(reader: MemoryReader) -> None:
    reader.infos["other"] = StationInfo("other")
    board = Dashboard(reader, stations=["other"], clock=lambda: NOW)
    assert await board.station_names() == ["other"]
    with pytest.raises(UnknownStation):
        await board.now("example")


async def test_an_unknown_station_is_refused(board: Dashboard) -> None:
    with pytest.raises(UnknownStation):
        await board.series("nowhere", ["outdoor.temperature"], "24h")


async def test_a_station_whose_settings_vanished_is_unknown(reader: MemoryReader) -> None:
    class Forgetful(MemoryReader):
        async def station_info(self, station: str) -> StationInfo | None:
            return None

    board = Dashboard(Forgetful(readings(), {"example": INFO}), clock=lambda: NOW)
    with pytest.raises(UnknownStation):
        await board.extremes("example", "today")


async def test_a_read_failure_propagates_and_is_not_cached(reader: MemoryReader) -> None:
    board = Dashboard(reader, clock=lambda: NOW)
    reader.failure = "the token was not accepted"
    with pytest.raises(ReadError):
        await board.stations()
    reader.failure = None
    assert [s.id for s in await board.stations()] == ["example"]


def test_meta_lists_metrics_units_ranges_and_periods(board: Dashboard) -> None:
    meta = board.meta()
    assert meta.title == "Test weather"
    metrics = {m.id: m for m in meta.metrics}
    assert metrics["outdoor.temperature"].quantity == "temperature"
    assert metrics["solar.radiation"].quantity is None
    assert metrics["solar.radiation"].unit == "wm2"
    assert metrics["rooms.humidity"].per_sensor and not metrics["wind.gust"].per_sensor
    assert [c.code for c in meta.units["pressure"]] == ["hpa", "inhg", "mmhg"]
    assert meta.symbols["mm_h"] == "mm/h"
    assert meta.ranges == ["24h", "7d", "30d", "1y"]
    assert meta.periods == ["today", "month", "year"]


async def test_a_room_without_an_outdoor_comparison_has_no_advice(reader: MemoryReader) -> None:
    reader.rows.append(row("channel", LAST, {"temp_c": 19.0, "humidity_pct": 66.0}, sensor="ch2"))
    rooms = (await Dashboard(reader, clock=lambda: NOW).now("example")).rooms
    assert [(r.sensor, r.name, r.airing) for r in rooms[2:]] == [("ch2", "ch2", None)]


async def test_feels_like_without_wind_is_the_temperature(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table != "wind"]
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.wind is None
    assert now.outdoor is not None and now.outdoor.feels_like == 18.0


async def test_a_gauge_without_a_metric_has_no_extremes_for_it(reader: MemoryReader) -> None:
    reader.rows.append(row("rain", LAST, {"rate_mm_h": 0.0}, gauge="piezo"))
    found = await Dashboard(reader, clock=lambda: NOW).extremes("example", "today")
    rain = [(e.metric, e.sensor) for e in found.extremes if e.metric.startswith("rain.")]
    assert rain == [("rain.rate", "bucket"), ("rain.rate", "piezo"), ("rain.daily", "bucket")]


async def test_an_unnamed_room_keeps_its_identifier(reader: MemoryReader) -> None:
    reader.rows.append(row("channel", LAST, {"temp_c": 19.0}, sensor="ch2", name="ch2"))
    reader.rows.append(row("channel", LAST, {"temp_c": 19.0}, sensor="ch3", name="Attic"))
    rooms = (await Dashboard(reader, clock=lambda: NOW).now("example")).rooms
    assert [r.name for r in rooms[2:]] == ["ch2", "Attic"]

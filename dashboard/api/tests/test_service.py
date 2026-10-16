"""The answers, built from the example station's readings in memory."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import ReadError
from ecowitt.core.units import Units
from ecowitt.dashboard import models
from ecowitt.dashboard.i18n import LANGUAGES
from ecowitt.dashboard.service import RANGES, Dashboard, UnknownStation
from ecowitt.dashboard.weather import Tendency

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
    assert now.pressure.trend.code is Tendency.FALLING
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


async def test_a_dry_night_does_not_flag_the_rain_gauge_or_light_sensor(
    reader: MemoryReader,
) -> None:
    for sensor in ("rain", "solar", "wind"):
        reader.rows.append(
            row("derived", LAST, {"unchanged_s": 20000.0}, sensor=sensor, name=sensor)
        )
    sensors = {
        s.sensor: s for s in (await Dashboard(reader, clock=lambda: NOW).now("example")).sensors
    }
    assert [sensors[s].updating for s in ("rain", "solar", "wind")] == [True, True, True]
    assert sensors["rain"].unchanged_s == 20000.0
    assert sensors["ch1"].updating is False, "a room still is"


async def test_the_summary_says_it_in_one_line(board: Dashboard) -> None:
    now = await board.now("example")
    assert now.summary == "18 °C. Gentle breeze from the SE. Raining, 2.4 mm/h. Pressure falling."
    Code = models.SummaryCode
    assert [(p.code, p.text) for p in now.summary_parts] == [
        (Code.TEMPERATURE, "18 °C"),
        (Code.WIND, "Gentle breeze from the SE"),
        (Code.RAIN, "Raining, 2.4 mm/h"),
        (Code.PRESSURE, "Pressure falling"),
    ]


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
    reader.rows = [r for r in reader.rows if r.table not in {"wind", "wind_10m"}]
    reader.rows.append(row("wind", LAST, {"speed_kmh": 0.5, "dir_deg": 90.0}))
    reader.rows.append(row("wind_10m", LAST, {"speed_kmh": 0.5, "source": "sensor"}))
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
    assert meta.ranges == ["1h", "3h", "6h", "12h", "24h", "7d", "30d", "1y"]
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


async def test_the_house_is_told_which_rooms_to_air(board: Dashboard) -> None:
    airing = (await board.now("example")).airing
    assert airing is not None
    assert (airing.advice, airing.rooms) == ("open", ["Bathroom"])
    assert (airing.humidity, airing.humidity_after, airing.dew_point_difference) == (
        65.0,
        54.0,
        1.1,
    ), "the stored medians, rounded as shown"


async def test_humid_outside_air_keeps_the_windows_closed(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table not in {"ventilation", "house"}]
    house = {"humidity_pct": 65.0, "predicted_humidity_pct": 72.0, "dewpoint_delta_c": -0.75}
    reader.rows.append(row("house", LAST, house))
    for sensor, delta, after in (("indoor", -2.0, 70.0), ("ch1", 0.5, 74.0)):
        reader.rows.append(
            row(
                "ventilation",
                LAST,
                {"dewpoint_delta_c": delta, "predicted_humidity_pct": after},
                sensor=sensor,
            )
        )
    now = await Dashboard(reader, clock=lambda: NOW).now("example", {"temperature": "f"})
    assert now.airing is not None
    assert (now.airing.advice, now.airing.rooms, now.airing.humidity_after) == (
        "keep_closed",
        [],
        72.0,
    )
    assert now.airing.dew_point_difference == -1.4, "-0.75 °C as a Fahrenheit difference"


async def test_no_outdoor_comparison_means_no_house_advice(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table not in {"ventilation", "house"}]
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is None
    assert all(room.airing is None for room in now.rooms)


async def test_the_house_is_judged_by_the_stored_medians(reader: MemoryReader) -> None:
    """The collector's row decides the house's advice, with no room of its own to air."""
    reader.rows = [r for r in reader.rows if r.table not in {"ventilation", "house"}]
    house = {"humidity_pct": 66.0, "predicted_humidity_pct": 74.0, "dewpoint_delta_c": -1.0}
    reader.rows.append(row("house", LAST, house))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None
    assert (now.airing.advice, now.airing.rooms, now.airing.humidity) == ("keep_closed", [], 66.0)


async def test_a_house_without_a_dew_point_difference_has_no_advice(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table != "house"]
    reader.rows.append(row("house", LAST, {"humidity_pct": 65.0, "predicted_humidity_pct": 53.5}))
    assert (await Dashboard(reader, clock=lambda: NOW).now("example")).airing is None


def windows_open(
    reader: MemoryReader,
    humidity: tuple[float, float] = (66.0, 66.0),
    not_aired: range = range(0),
    vent_delta: float = 0.1,
    unit: str = "c",
) -> None:
    """Two hours of house rows a minute apart up to the latest report, aired but for the minutes
    before it in `not_aired`, the rooms' humidity moving evenly from one end of `humidity` to the
    other; every room's air already close to the outdoor air. Temperatures are stored in `unit`."""
    reader.rows = [r for r in reader.rows if r.table not in {"house", "ventilation"}]
    first, last = humidity
    delta = f"dewpoint_delta_{unit}"
    for i in range(121):
        ago = 120 - i
        fields: dict[str, object] = {
            "aired": ago not in not_aired,
            "humidity_pct": round(first + (last - first) * i / 120, 1),
        }
        if ago == 0:
            fields |= {"predicted_humidity_pct": last, delta: vent_delta}
        reader.rows.append(row("house", LAST - timedelta(minutes=ago), fields))
    for sensor in ("indoor", "ch1"):
        vent = {delta: vent_delta, "predicted_humidity_pct": last}
        reader.rows.append(row("ventilation", LAST, vent, sensor=sensor))


def outdoor_dew_points(
    reader: MemoryReader,
    earlier: float,
    recent: float,
    middle: float | None = None,
    latest: float | None = None,
    unit: str = "c",
) -> None:
    """The outdoor dew point at `earlier` from 70 to 50 minutes before the latest report,
    `middle` (else `earlier`) until 10 minutes before it, then `recent`, and `latest` (else
    `recent`) in the latest report itself; stored in `unit`."""
    reader.rows = [
        r
        for r in reader.rows
        if not (r.table == "derived" and dict(r.tags).get("sensor") == "outdoor")
    ]
    for ago in range(70):
        if ago == 0 and latest is not None:
            value = latest
        elif ago < 10:
            value = recent
        elif ago < 50:
            value = earlier if middle is None else middle
        else:
            value = earlier
        fields = {f"dewpoint_{unit}": value}
        at = LAST - timedelta(minutes=ago)
        reader.rows.append(row("derived", at, fields, sensor="outdoor", name="out"))


async def test_open_windows_and_rooms_getting_damper_say_close(reader: MemoryReader) -> None:
    windows_open(reader, humidity=(65.0, 70.0))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "close"
    assert now.airing.windows_open
    assert now.notices["airing"].level == "warning"


async def test_open_windows_and_a_rising_outdoor_dew_point_say_close(reader: MemoryReader) -> None:
    """The last ten minutes against the hour before: the time between does not count."""
    windows_open(reader)
    outdoor_dew_points(reader, earlier=14.0, middle=13.0, recent=14.8)
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "close"


async def test_one_odd_report_is_not_a_rising_dew_point(reader: MemoryReader) -> None:
    """The latest report counts as one of the last ten minutes' readings, not as a step of its
    own: 14 °C for nine minutes and 16 °C once is 14.2 °C."""
    windows_open(reader)
    outdoor_dew_points(reader, earlier=14.0, recent=14.0, latest=16.0)
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "aired"


async def test_the_dew_point_rise_is_judged_in_celsius() -> None:
    """A station storing °F: a 0.9 °F rise is 0.5 °C, short of the threshold."""
    from ecowitt.core.units import Units

    info = StationInfo("example", units=Units(temperature="f"))
    reader = MemoryReader([row("station", LAST, {"interval_s": 60.0})], {"example": info})
    windows_open(reader, unit="f")
    outdoor_dew_points(reader, earlier=57.2, recent=58.1, unit="f")
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "aired"


async def test_open_windows_in_steady_air_read_as_aired(reader: MemoryReader) -> None:
    windows_open(reader, humidity=(64.0, 66.0))
    outdoor_dew_points(reader, earlier=14.0, recent=14.5)
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "aired"
    assert "airing" not in now.notices


async def test_a_dew_point_without_an_hour_behind_it_is_no_trend(reader: MemoryReader) -> None:
    windows_open(reader)
    outdoor_dew_points(reader, earlier=10.0, recent=14.0)
    since = (LAST - timedelta(minutes=45)).timestamp()
    reader.rows = [r for r in reader.rows if r.table != "derived" or r.timestamp > since]
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "aired"


async def test_windows_open_only_lately_do_not_count_yet(reader: MemoryReader) -> None:
    """Aired for most of two hours but only 25 of the last 40 minutes: the windows may have been
    closed, so they do not count as open."""
    windows_open(reader, humidity=(65.0, 70.0), not_aired=range(15, 30))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "no_need"
    assert not now.airing.windows_open


async def test_a_house_without_its_recent_rows_is_judged_as_closed(reader: MemoryReader) -> None:
    """The example's one house row has no aired flag: nothing says the windows are open."""
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.advice == "open"
    assert not now.airing.windows_open


async def test_open_windows_still_show_while_a_room_would_be_dried(reader: MemoryReader) -> None:
    """Good time to air, with the windows already open: the advice and the mark both stand."""
    windows_open(reader, vent_delta=3.0)
    reader.rows.append(row("indoor", LAST, {"temp_c": 21.0, "humidity_pct": 70.0}, sensor="indoor"))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None
    assert (now.airing.advice, now.airing.windows_open) == ("open", True)


async def test_a_room_without_a_prediction_still_counts(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table not in {"ventilation", "house"}]
    reader.rows.append(row("ventilation", LAST, {"dewpoint_delta_c": -1.0}, sensor="indoor"))
    reader.rows.append(row("house", LAST, {"humidity_pct": 55.0, "dewpoint_delta_c": -1.0}))
    now = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert now.airing is not None and now.airing.humidity_after is None


async def test_the_words_are_in_the_language_asked_for(board: Dashboard) -> None:
    portuguese = LANGUAGES["pt-PT"]
    now = await board.now("example", language=portuguese)

    assert [p.text for p in now.summary_parts] == [
        "18 °C",
        "Vento bonançoso de SE",
        "A chover, 2,4 mm/h",
        "Pressão a descer",
    ]
    assert now.wind is not None and (now.wind.description, now.wind.compass) == (
        "Vento bonançoso",
        "SE",
    )
    assert now.pressure is not None and now.pressure.trend is not None
    assert now.pressure.trend.tendency == "a descer"
    assert now.notices["rooms"].text == "Húmido: Bathroom."
    names = {s.sensor: s.name for s in now.sensors}
    assert names["pressure"] == "Barómetro", "a sensor nobody named takes its kind's name"


async def test_every_answer_names_an_unnamed_sensor_in_the_language_asked_for() -> None:
    """The outdoor sensor written under its own id, as one nobody has named is."""
    rows = [
        dataclasses.replace(
            r, tags=tuple((k, "outdoor" if v == "Garden" else v) for k, v in r.tags)
        )
        for r in readings()
    ]
    info = dataclasses.replace(INFO, sensors={})
    board = Dashboard(MemoryReader(rows, {"example": info}), clock=lambda: NOW)
    portuguese = LANGUAGES["pt-PT"]

    now = await board.now("example", language=portuguese)
    series = await board.series("example", ["outdoor.temperature"], "24h", language=portuguese)
    extremes = await board.extremes("example", "today", language=portuguese)

    assert {s.name for s in now.sensors if s.sensor == "outdoor"} == {"Exterior"}
    assert {s.name for s in series.series} == {"Exterior"}
    assert {e.name for e in extremes.extremes if e.sensor == "outdoor"} == {"Exterior"}


async def test_notices_point_at_what_deserves_attention(board: Dashboard) -> None:
    now = await board.now("example")
    assert set(now.notices) == {"airing", "rooms", "sensors"}
    assert now.notices["airing"].level == "good"
    assert now.notices["rooms"].text == "Damp: Bathroom."
    assert now.notices["sensors"].level == "warning"
    assert [r.flags for r in now.rooms] == [[], ["damp"]]


async def test_weather_worth_a_warning_is_flagged(reader: MemoryReader) -> None:
    later = LAST + timedelta(seconds=30)
    reader.rows += [
        row("station", later, {"interval_s": 60.0}),
        row("outdoor", later, {"temp_c": 5.0, "humidity_pct": 95.0}, sensor="outdoor"),
        row("wind", later, {"speed_kmh": 40.0, "gust_kmh": 61.0, "dir_deg": 0.0}),
        row("wind_10m", later, {"speed_kmh": 40.0, "gust_kmh": 61.0, "source": "sensor"}),
        row("rain", later, {"rate_mm_h": 10.5}, gauge="bucket"),
        # 1015 hPa at the start of the three hours, 1011.5 at their end: 3.5 hPa down.
        row("pressure", later - timedelta(hours=3), {"sea_hpa": 1015.0}),
        row("pressure", later, {"sea_hpa": 1011.5}),
        row("solar", later, {"radiation_wm2": 900.0, "uv_index": 8.0}),
        row(
            "channel",
            later,
            {"temp_c": 7.0, "humidity_pct": 25.0},
            sensor="ch1",
            name="ch1",
            channel="1",
        ),
    ]
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert {card: n.text for card, n in notices.items() if card not in {"sensors", "airing"}} == {
        "outdoor": "Cold: frost is possible on clear nights. "
        "Very humid outside: fog and condensation likely.",
        "wind": "Strong gusts.",
        "rain": "Heavy rain.",
        "pressure": "Falling fast: a front or a storm is likely.",
        "sun": "Very high UV: seek shade at midday.",
        "rooms": "Cold: Bathroom. Dry: Bathroom.",
    }
    Code = models.NoticeCode
    assert {card: [i.code for i in n.items] for card, n in notices.items()} == {
        "outdoor": [Code.COLD, Code.HUMID_AIR],
        "wind": [Code.STRONG_GUSTS],
        "rain": [Code.HEAVY_RAIN],
        "pressure": [Code.PRESSURE_FALLING_FAST],
        "sun": [Code.UV_VERY_HIGH],
        "rooms": [Code.ROOM_FLAG, Code.ROOM_FLAG],
        "sensors": [],
    }
    assert [(i.flag, i.rooms) for i in notices["rooms"].items] == [
        ("cold", ["Bathroom"]),
        ("dry", ["Bathroom"]),
    ]


@pytest.mark.parametrize(("minutes", "flagged"), [(9, True), (11, False)])
async def test_a_gust_or_downpour_counts_for_ten_minutes(
    reader: MemoryReader, minutes: int, flagged: bool
) -> None:
    """As the Strong wind and Heavy rain rules count them: the latest report alone would leave
    a gusty spell marked only on the reports that caught a gust."""
    earlier = LAST - timedelta(minutes=minutes)
    reader.rows += [
        row("wind", earlier, {"speed_kmh": 40.0, "gust_kmh": 61.0, "dir_deg": 0.0}),
        row("wind_10m", earlier, {"speed_kmh": 40.0, "gust_kmh": 61.0, "source": "sensor"}),
        row("rain", earlier, {"rate_mm_h": 10.5}, gauge="piezo"),
    ]
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert ("wind" in notices, "rain" in notices) == (flagged, flagged)


async def test_gusts_are_judged_in_metric_whatever_is_stored(reader: MemoryReader) -> None:
    """38 mph is 61 km/h, over the 60 km/h line; 0.42 in/h is 10.7 mm/h, over 10 mm/h."""
    reader.infos["example"] = dataclasses.replace(
        reader.infos["example"], units=Units(wind="mph", rain="in")
    )
    reader.rows += [
        row("wind", LAST, {"gust_mph": 38.0}),
        row("rain", LAST, {"rate_in_h": 0.42}, gauge="bucket"),
    ]
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert notices["wind"].text == "Strong gusts."
    assert notices["rain"].text == "Heavy rain."


@pytest.mark.parametrize(
    ("temp", "humidity", "text"),
    [
        (31.0, 60.0, "Heat: take care outdoors."),
        (20.0, 25.0, "Very dry air: fire risk."),
        (5.1, 94.0, None),
    ],
)
async def test_heat_is_judged_by_what_it_feels_like_and_air_by_its_humidity(
    reader: MemoryReader, temp: float, humidity: float, text: str | None
) -> None:
    later = LAST + timedelta(seconds=30)
    reader.rows += [
        row("station", later, {"interval_s": 60.0}),
        row("outdoor", later, {"temp_c": temp, "humidity_pct": humidity}, sensor="outdoor"),
    ]
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert (notices["outdoor"].text if "outdoor" in notices else None) == text


async def test_a_calm_dry_day_has_no_weather_notices(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table not in {"pressure", "ventilation", "house"}]
    reader.rows.append(row("pressure", LAST, {"rel_hpa": 1012.0}))
    for i, r in enumerate(reader.rows):
        if r.table == "outdoor" and dict(r.tags).get("sensor") == "outdoor":
            reader.rows[i] = row(
                "outdoor", datetime.fromtimestamp(r.timestamp, UTC), {"temp_c": 18.0}
            )
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert set(notices) == {"rooms", "sensors"}


async def test_closed_windows_are_a_warning(reader: MemoryReader) -> None:
    reader.rows = [r for r in reader.rows if r.table not in {"ventilation", "house"}]
    # Airing would take the house from 55% to 70%: damp, and damper.
    vent = {"dewpoint_delta_c": -2.0, "predicted_humidity_pct": 70.0}
    reader.rows.append(row("ventilation", LAST, vent, sensor="indoor"))
    reader.rows.append(row("house", LAST, {"humidity_pct": 55.0, **vent}))
    notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
    assert notices["airing"].level == "warning"


@pytest.mark.parametrize(("name", "step"), [("1h", 60), ("3h", 60), ("6h", 60), ("12h", 120)])
async def test_short_ranges_keep_every_report(board: Dashboard, name: str, step: int) -> None:
    """A minute apart, the station's own pace, up to six hours; two minutes for twelve."""
    found = await board.series("example", ["outdoor.temperature"], name)

    assert (found.range, found.step_s, found.end) == (name, step, NOW)
    assert found.start == NOW - RANGES[name].duration
    # The last reading, a minute before NOW, falls in every one of them.
    assert found.series[0].values["max"][-1] == 18.0

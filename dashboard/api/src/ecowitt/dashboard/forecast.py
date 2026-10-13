"""The forecast the collector stores, read back: the newest for each hour and day, and what
the dashboard draws from it -- the forecast section, and the cards' warnings of what is coming.

Each stored row is tagged with its `lead`, how far ahead it was made, so the newest forecast for
any hour is the row with the smallest lead. Only the station's current weather model counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
from typing import Protocol

from ecowitt.core import weathermodel
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import Point, Reader
from ecowitt.core.units import Kind, field_name
from ecowitt.dashboard import models, weather

#: How far ahead the hours run.
HOURS = 24
#: A forecast older than this is not shown: the collector has stopped fetching.
STALE_AFTER = timedelta(hours=12)
#: How far ahead the cards look for what is coming.
WARN_WITHIN = timedelta(hours=24)
#: Rain is expected in an hour with at least this chance of it, or this much of it.
RAIN_LIKELY_PCT = 60.0
RAIN_LIKELY_MM = 0.5
#: How far ahead rain is announced: beyond a few hours it is the forecast's business, not a card's.
RAIN_WITHIN = timedelta(hours=6)
#: Frost is possible once the air is forecast to reach this, in °C: the ground cools below it.
FROST_C = 2.0
#: How far ahead a drier spell for airing is looked for.
AIRING_WITHIN = timedelta(hours=12)


@dataclass(frozen=True)
class Stored:
    """A station's newest forecast, in its stored units: by hour and by day, oldest first."""

    hours: list[Point] = field(default_factory=list)
    days: list[Point] = field(default_factory=list)
    issued: datetime | None = None


async def read(
    reader: Reader, station: str, info: StationInfo, zone: tzinfo, now: datetime
) -> Stored:
    """The newest forecast from the station's model for the coming hours, and for the days from
    today in the station's time."""
    if info.weather_model is None:
        return Stored()
    hour = now.replace(minute=0, second=0, microsecond=0)
    hourly = _fields(weathermodel.FORECAST_HOURLY, info)
    daily = _fields(weathermodel.FORECAST_DAILY, info)
    hours = await reader.points(
        station, weathermodel.FORECAST_TABLE, hourly, start=hour, end=hour + timedelta(hours=HOURS)
    )
    days = await reader.points(
        station,
        weathermodel.FORECAST_DAILY_TABLE,
        daily,
        start=datetime.combine(now.astimezone(zone).date(), time(), zone),
        end=now + timedelta(days=weathermodel.FORECAST_DAYS),
    )
    newest_hours = _newest(hours, info.weather_model)
    issued = max((_issued(p) for p in newest_hours), default=None)
    if issued is None or now - issued > STALE_AFTER:
        return Stored()
    return Stored(newest_hours[:HOURS], _newest(days, info.weather_model), issued)


def _fields(variables: dict[str, tuple[str, Kind]], info: StationInfo) -> list[str]:
    return [field_name(base, kind, info.units) for base, kind in variables.values()]


def _newest(points: list[Point], model: str) -> list[Point]:
    """For each time, the row made nearest to it -- the smallest lead -- from `model`."""
    best: dict[datetime, Point] = {}
    for point in points:
        if point.tags.get("model") != model:
            continue
        kept = best.get(point.time)
        if kept is None or _lead(point) < _lead(kept):
            best[point.time] = point
    return [best[t] for t in sorted(best)]


def _lead(point: Point) -> int:
    try:
        return int(point.tags.get("lead", ""))
    except ValueError:
        return 1 << 30


def _issued(point: Point) -> datetime:
    """When an hourly row's forecast was made: its hour, less its lead."""
    return point.time - timedelta(hours=_lead(point))


class Values(Protocol):
    """What converts a stored value: to the requested units, or to metric to compare with."""

    def out(self, kind: Kind, value: object) -> float | None:
        """A stored value in the requested units, rounded."""

    def metric(self, kind: Kind, value: object) -> float | None:
        """A stored value in metric units."""


def answer(
    stored: Stored, values: Values, info: StationInfo
) -> tuple[list[models.ForecastHour], list[models.ForecastDay]]:
    """The forecast section: the hours from the one under way, and the days from today."""
    units = info.units
    T, S = Kind.TEMPERATURE, Kind.SPEED

    def f(base: str, kind: Kind) -> str:
        return field_name(base, kind, units)

    hours = []
    for p in stored.hours:
        v = p.values
        code = _code(v.get("weather_code"))
        direction = values.metric(Kind.ANGLE, v.get(f("dir", Kind.ANGLE)))
        hours.append(
            models.ForecastHour(
                time=p.time,
                temperature=values.out(T, v.get(f("temp", T))),
                humidity=values.out(Kind.HUMIDITY, v.get(f("humidity", Kind.HUMIDITY))),
                dew_point=values.out(T, v.get(f("dewpoint", T))),
                precipitation=values.out(Kind.RAIN, v.get(f("precip_1h", Kind.RAIN))),
                precipitation_probability=values.out(
                    Kind.PERCENT, v.get(f("precip_probability", Kind.PERCENT))
                ),
                weather_code=code,
                description=None if code is None else weathermodel.describe(code),
                is_day=v.get("is_day") if isinstance(v.get("is_day"), bool) else None,
                wind_speed=values.out(S, v.get(f("speed", S))),
                wind_gust=values.out(S, v.get(f("gust", S))),
                wind_direction=None if direction is None else round(direction),
                compass=None if direction is None else weather.compass(direction),
            )
        )
    days = []
    for p in stored.days:
        v = p.values
        code = _code(v.get("weather_code"))
        direction = values.metric(Kind.ANGLE, v.get(f("dir", Kind.ANGLE)))
        days.append(
            models.ForecastDay(
                date=p.time,
                weather_code=code,
                description=None if code is None else weathermodel.describe(code),
                temperature_max=values.out(T, v.get(f("temp_max", T))),
                temperature_min=values.out(T, v.get(f("temp_min", T))),
                precipitation=values.out(Kind.RAIN, v.get(f("precip", Kind.RAIN))),
                precipitation_probability=values.out(
                    Kind.PERCENT, v.get(f("precip_probability", Kind.PERCENT))
                ),
                wind_speed_max=values.out(S, v.get(f("speed_max", S))),
                wind_gust_max=values.out(S, v.get(f("gust_max", S))),
                wind_direction=None if direction is None else round(direction),
                compass=None if direction is None else weather.compass(direction),
                uv_index_max=values.out(Kind.UV_INDEX, v.get(f("uv_index_max", Kind.UV_INDEX))),
            )
        )
    return hours, days


def _code(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


@dataclass(frozen=True)
class Coming:
    """The first coming hour that matches, and the value there, in metric units."""

    time: datetime
    value: float


def rain(stored: Stored, values: Values, info: StationInfo, now: datetime) -> Coming | None:
    """The first hour within RAIN_WITHIN with rain likely: its chance (or amount) of it."""
    chance = field_name("precip_probability", Kind.PERCENT, info.units)
    amount = field_name("precip_1h", Kind.RAIN, info.units)
    for p in _within(stored.hours, now, RAIN_WITHIN):
        pct = values.metric(Kind.PERCENT, p.values.get(chance))
        mm = values.metric(Kind.RAIN, p.values.get(amount))
        if (pct is not None and pct >= RAIN_LIKELY_PCT) or (
            mm is not None and mm >= RAIN_LIKELY_MM
        ):
            return Coming(p.time, pct if pct is not None else 100.0)
    return None


def extreme(
    stored: Stored,
    values: Values,
    info: StationInfo,
    now: datetime,
    base: str,
    kind: Kind,
    *,
    lowest: bool,
) -> Coming | None:
    """The lowest or highest forecast value of a field within WARN_WITHIN, and when."""
    name = field_name(base, kind, info.units)
    found = [
        Coming(p.time, v)
        for p in _within(stored.hours, now, WARN_WITHIN)
        if (v := values.metric(kind, p.values.get(name))) is not None
    ]
    if not found:
        return None
    pick = min if lowest else max
    return pick(found, key=lambda c: c.value)


def drier_from(
    stored: Stored, values: Values, info: StationInfo, now: datetime, room_dew_points: list[float]
) -> datetime | None:
    """The first hour within AIRING_WITHIN whose forecast dew point is low enough to dry one of
    the damp rooms whose dew points are given (in °C), by the Good time to air rule's margin."""
    if not room_dew_points:
        return None
    name = field_name("dewpoint", Kind.TEMPERATURE, info.units)
    wettest = max(room_dew_points)
    for p in _within(stored.hours, now, AIRING_WITHIN):
        outdoor = values.metric(Kind.TEMPERATURE, p.values.get(name))
        if outdoor is not None and wettest - outdoor > weather.AIRING_DEWPOINT_DELTA_C:
            return p.time
    return None


def _within(points: list[Point], now: datetime, span: timedelta) -> list[Point]:
    """The hours still to come within `span`, the one under way included."""
    start = now.replace(minute=0, second=0, microsecond=0)
    return [p for p in points if start <= p.time <= now + span]

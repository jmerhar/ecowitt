"""The API's answers, built from what a `Reader` returns.

What is read from the database is cached in the units the station stores, per station and
question, so every visitor shares one set of queries; each answer is then converted to the units
its request asked for. Calculations -- feels-like, airing, the pressure trend -- work in metric.
"""

from __future__ import annotations

import asyncio
import dataclasses
import zoneinfo
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo

from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import Buckets, Extreme, Extremes, Reader, Span
from ecowitt.core.units import Kind, Units, convert, field_name
from ecowitt.dashboard import models, weather
from ecowitt.dashboard.cache import TtlCache
from ecowitt.dashboard.catalogue import (
    CHOICES,
    METRICS,
    ROOM_SENSOR,
    SYMBOLS,
    Metric,
    Sides,
    rounded,
    unit,
)
from ecowitt.dashboard.sun import sun_times

#: The units calculations are made in.
METRIC = Units()


@dataclass(frozen=True)
class Range:
    """A chart's span and the width of its buckets."""

    duration: timedelta
    step: timedelta
    #: How long its answer is reused.
    ttl: float


RANGES = {
    "24h": Range(timedelta(hours=24), timedelta(minutes=5), 60),
    "7d": Range(timedelta(days=7), timedelta(minutes=30), 300),
    "30d": Range(timedelta(days=30), timedelta(hours=2), 900),
    "1y": Range(timedelta(days=365), timedelta(days=1), 3600),
}
#: Periods extremes are given for, and how long each answer is reused.
PERIODS = {"today": 60.0, "month": 600.0, "year": 1800.0}

NOW_TTL = 30.0
STATIONS_TTL = 300.0
#: How far back a station's latest report is looked for.
LATEST_WITHIN = timedelta(days=7)
#: How much of the time before its latest report a station's current values are taken from.
CURRENT_WINDOW = timedelta(minutes=15)
PRESSURE_TREND = timedelta(hours=3)
#: A trend needs readings from nearly the whole of its three hours.
PRESSURE_TREND_COVERAGE = timedelta(hours=2, minutes=50)
#: A station is online while its latest report is younger than this many upload intervals...
ONLINE_INTERVALS = 3
#: ...or than this, whichever is longer.
ONLINE_AT_LEAST = timedelta(minutes=5)


#: Names for the sensors a console has one of, which nobody names on the setup page.
SENSOR_NAMES = {
    "indoor": "Indoor",
    "outdoor": "Outdoor",
    "pressure": "Barometer",
    "rain": "Rain gauge",
    "solar": "Light sensor",
    "wind": "Wind sensor",
}


class UnknownStation(LookupError):
    """No station of that name is shown here."""


@dataclass(frozen=True)
class _Latest:
    """Everything /now reads for a station, in its stored units."""

    report: Span | None = None
    outdoor: Span | None = None
    derived: list[Span] = field(default_factory=list)
    wind: Span | None = None
    rain: list[Span] = field(default_factory=list)
    pressure: Span | None = None
    solar: Span | None = None
    rooms: list[Span] = field(default_factory=list)
    ventilation: list[Span] = field(default_factory=list)
    battery: list[Span] = field(default_factory=list)
    temperature_today: Extremes | None = None
    wind_today: Extremes | None = None
    #: When it was read.
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class _Bucketed:
    """A range's buckets per metric, in stored units."""

    start: datetime
    end: datetime
    groups: dict[str, list[Buckets]]


@dataclass(frozen=True)
class _Ranged:
    """A period's extremes per metric, in stored units."""

    start: datetime
    end: datetime
    groups: dict[str, list[Extremes]]


class _Values:
    """Converts a station's stored values for one answer."""

    def __init__(self, stored: Units, target: Units) -> None:
        self.stored = stored
        self.target = target

    def metric(self, kind: Kind, value: object) -> float | None:
        """A stored value in metric units, for calculating with."""
        if not isinstance(value, int | float) or isinstance(value, bool):
            return None
        return convert(kind, float(value), self.stored, METRIC)

    def out(self, kind: Kind, value: object) -> float | None:
        """A stored value in the requested units, rounded."""
        metric = self.metric(kind, value)
        return None if metric is None else self.from_metric(kind, metric)

    def from_metric(self, kind: Kind, value: float) -> float:
        """A metric value in the requested units, rounded."""
        return rounded(convert(kind, value, METRIC, self.target), unit(kind, self.target))

    def at(self, kind: Kind, extreme: Extreme) -> models.At:
        """An extreme in the requested units."""
        metric = convert(kind, extreme.value, self.stored, METRIC)
        return models.At(value=self.from_metric(kind, metric), time=extreme.time)


class Dashboard:
    """Answers about the stations a Reader can see.

    Each answer takes the units a request chose (`{"wind": "mph"}`) and gives every other
    quantity in the units the station stores.
    """

    def __init__(
        self,
        reader: Reader,
        *,
        title: str = "Weather",
        stations: Collection[str] = (),
        cache: TtlCache | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.reader = reader
        self.title = title
        self.allowed = frozenset(stations)
        self.cache = cache or TtlCache()
        self.clock = clock

    async def station_names(self) -> list[str]:
        """The stations shown: every one that published its settings, or the configured ones."""
        names = await self.cache.get(("stations",), STATIONS_TTL, self.reader.stations)
        return [name for name in names if not self.allowed or name in self.allowed]

    async def info(self, station: str) -> StationInfo:
        """A shown station's settings. Raises UnknownStation for any other name."""
        if station not in await self.station_names():
            raise UnknownStation(station)
        info = await self.cache.get(
            ("info", station), STATIONS_TTL, lambda: self.reader.station_info(station)
        )
        if info is None:
            raise UnknownStation(station)
        return info

    async def stations(self) -> list[models.Station]:
        """Every shown station with its settings."""
        found = []
        for name in await self.station_names():
            info = await self.info(name)
            found.append(
                models.Station(
                    id=name,
                    latitude=info.latitude,
                    longitude=info.longitude,
                    altitude_m=info.altitude_m,
                    timezone=info.timezone or "UTC",
                    units=_units(info.units),
                )
            )
        return found

    def meta(self) -> models.Meta:
        """The metrics, units, ranges and periods there are."""
        return models.Meta(
            title=self.title,
            metrics=[
                models.MetricInfo(
                    id=m.id,
                    label=m.label,
                    quantity=m.quantity,
                    unit=None if m.quantity else unit(m.kind, METRIC),
                    aggregates=[a.value for a in m.aggregates],
                    extremes=m.extremes.value,
                    per_sensor=m.per_sensor,
                )
                for m in METRICS.values()
            ],
            units={
                quantity: [models.UnitChoice(code=code, symbol=SYMBOLS[code]) for code in codes]
                for quantity, codes in CHOICES.items()
            },
            symbols=SYMBOLS,
            ranges=list(RANGES),
            periods=list(PERIODS),
        )

    async def now(self, station: str, choice: Mapping[str, str] | None = None) -> models.Now:
        """A station at a glance."""
        info = await self.info(station)
        latest = await self.cache.get(
            ("now", station), NOW_TTL, lambda: self._latest(station, info)
        )
        values = _Values(info.units, _target(info.units, choice))
        zone = _zone(info)
        answer = models.Now(
            station=station,
            time=latest.report.last_time if latest.report else None,
            online=_online(latest),
            timezone=info.timezone or "UTC",
            units=_units(values.target),
            summary="",
        )
        if latest.report is None:
            return answer
        stored = info.units
        answer.outdoor = _outdoor(latest, values, stored)
        answer.wind = _wind(latest, values, stored)
        answer.rain = _rain(latest, values, stored)
        answer.pressure = _pressure(latest, values, stored)
        answer.sun = _sun(latest, values, stored, info, zone)
        answer.rooms = _rooms(latest, values, stored, info)
        answer.sensors = _health(latest, info)
        answer.summary = _summary(answer, values.target)
        return answer

    async def series(
        self,
        station: str,
        metrics: list[str],
        range_name: str,
        choice: Mapping[str, str] | None = None,
    ) -> models.SeriesOut:
        """Metrics over a range, in buckets aligned to the station's midnight."""
        info = await self.info(station)
        chosen = [METRICS[m] for m in dict.fromkeys(metrics)]
        span = RANGES[range_name]
        key = ("series", station, range_name, tuple(m.id for m in chosen))
        found = await self.cache.get(
            key, span.ttl, lambda: self._bucketed(station, info, chosen, span)
        )
        values = _Values(info.units, _target(info.units, choice))
        series = []
        for metric in chosen:
            for group in found.groups.get(metric.id, []):
                columns = {
                    aggregate.value: [
                        None if v is None else values.out(metric.kind, v)
                        for v in group.values.get((metric.field(info.units), aggregate), [])
                    ]
                    for aggregate in metric.aggregates
                }
                if not any(v is not None for column in columns.values() for v in column):
                    continue
                sensor = _group(group.tags)
                series.append(
                    models.Series(
                        metric=metric.id,
                        sensor=sensor,
                        name=_name(info, group.tags, group.name),
                        unit=unit(metric.kind, values.target),
                        t=[int(t.timestamp()) for t in group.times],
                        values=columns,
                    )
                )
        return models.SeriesOut(
            station=station,
            range=range_name,
            step_s=int(span.step.total_seconds()),
            start=found.start,
            end=found.end,
            units=_units(values.target),
            series=series,
        )

    async def extremes(
        self, station: str, period: str, choice: Mapping[str, str] | None = None
    ) -> models.ExtremesOut:
        """The extremes of today, this month or this year, in the station's time."""
        info = await self.info(station)
        found = await self.cache.get(
            ("extremes", station, period),
            PERIODS[period],
            lambda: self._ranged(station, info, period),
        )
        values = _Values(info.units, _target(info.units, choice))
        entries = []
        for metric in METRICS.values():
            for group in found.groups.get(metric.id, []):
                name = metric.field(info.units)
                if name not in group.maximum:
                    continue
                entries.append(
                    models.Extreme(
                        metric=metric.id,
                        sensor=_group(group.tags),
                        name=_name(info, group.tags, group.name),
                        unit=unit(metric.kind, values.target),
                        min=values.at(metric.kind, group.minimum[name])
                        if metric.extremes is Sides.BOTH
                        else None,
                        max=values.at(metric.kind, group.maximum[name]),
                    )
                )
        return models.ExtremesOut(
            station=station,
            period=period,
            start=found.start,
            end=found.end,
            units=_units(values.target),
            extremes=entries,
        )

    async def _latest(self, station: str, info: StationInfo) -> _Latest:
        """Read everything /now needs, in parallel once the latest report is known."""
        now = self.clock()
        reports = await self.reader.span(
            station, "station", ["interval_s"], start=now - LATEST_WITHIN, end=now
        )
        if not reports:
            return _Latest(at=now)
        report = reports[0]
        end = report.last_time
        start = end - CURRENT_WINDOW
        units = info.units
        midnight = _midnight(now, _zone(info))

        def f(base: str, kind: Kind) -> str:
            return field_name(base, kind, units)

        def span(
            table: str, *fields: str, since: datetime = start, sensors: list[str] | None = None
        ) -> Awaitable[list[Span]]:
            return self.reader.span(station, table, fields, start=since, end=end, sensors=sensors)

        T, H, P, R, S = Kind.TEMPERATURE, Kind.HUMIDITY, Kind.PRESSURE, Kind.RAIN, Kind.SPEED
        D = Kind.TEMPERATURE_DELTA
        rain_fields = [f(b, R) for b in ("event", "hourly", "daily", "last24h", "weekly")]
        rain_fields += [f(b, R) for b in ("monthly", "yearly")] + [f("rate", Kind.RAIN_RATE)]
        (
            outdoor, derived, wind, rain, pressure, solar, indoor, channel, ventilation,
            battery, temperature_today, wind_today,
        ) = await asyncio.gather(
            span("outdoor", f("temp", T), f("humidity", H), sensors=["outdoor"]),
            span("derived", f("dewpoint", T), "unchanged_s"),
            span("wind", f("speed", S), f("gust", S), f("dir", Kind.ANGLE)),
            span("rain", *rain_fields),
            span("pressure", f("sea", P), f("abs", P), f("rel", P), since=end - PRESSURE_TREND),
            span("solar", f("radiation", Kind.IRRADIANCE), "uv_index"),
            span("indoor", f("temp", T), f("humidity", H)),
            span("channel", f("temp", T), f("humidity", H)),
            span("ventilation", f("dewpoint_delta", D), f("predicted_humidity", H)),
            span("battery", "low"),
            self.reader.extremes(
                station, "outdoor", [f("temp", T)], start=midnight, end=now, sensors=["outdoor"]
            ),
            self.reader.extremes(station, "wind", [f("gust", S)], start=midnight, end=now),
        )  # fmt: skip
        return _Latest(
            report=report,
            outdoor=_first(outdoor),
            derived=derived,
            wind=_first(wind),
            rain=rain,
            pressure=_first(pressure),
            solar=_first(solar),
            rooms=[s for s in indoor + channel if s.sensor and ROOM_SENSOR.fullmatch(s.sensor)],
            ventilation=ventilation,
            battery=battery,
            temperature_today=_first(temperature_today),
            wind_today=_first(wind_today),
            at=now,
        )

    async def _bucketed(
        self, station: str, info: StationInfo, metrics: list[Metric], span: Range
    ) -> _Bucketed:
        """Read each metric's buckets, one query per table and sensor filter."""
        end = self.clock()
        start = end - span.duration
        origin = _midnight(start, _zone(info))
        queries = _by_table(metrics)

        async def ask(
            table: str, sensors: tuple[str, ...] | None, chosen: list[Metric]
        ) -> list[Buckets]:
            pairs = [(m.field(info.units), a) for m in chosen for a in m.aggregates]
            return await self.reader.buckets(
                station, table, pairs, start=start, end=end, step=span.step, origin=origin,
                sensors=sensors,
            )  # fmt: skip

        answers = await asyncio.gather(*(ask(*q) for q in queries))
        groups: dict[str, list[Buckets]] = {}
        for (_, _, chosen), found in zip(queries, answers, strict=True):
            for metric in chosen:
                groups.setdefault(metric.id, []).extend(g for g in found if metric.covers(g.sensor))
        return _Bucketed(start, end, groups)

    async def _ranged(self, station: str, info: StationInfo, period: str) -> _Ranged:
        """Read the period's extremes of every metric that has them."""
        end = self.clock()
        zone = _zone(info)
        local = end.astimezone(zone)
        day = local.date()
        first = {"today": day, "month": day.replace(day=1), "year": date(day.year, 1, 1)}[period]
        start = _midnight_of(first, zone)
        queries = _by_table([m for m in METRICS.values() if m.extremes is not Sides.NONE])

        async def ask(
            table: str, sensors: tuple[str, ...] | None, chosen: list[Metric]
        ) -> list[Extremes]:
            fields = [m.field(info.units) for m in chosen]
            return await self.reader.extremes(
                station, table, fields, start=start, end=end, sensors=sensors
            )

        answers = await asyncio.gather(*(ask(*q) for q in queries))
        groups: dict[str, list[Extremes]] = {}
        for (_, _, chosen), found in zip(queries, answers, strict=True):
            for metric in chosen:
                groups.setdefault(metric.id, []).extend(g for g in found if metric.covers(g.sensor))
        return _Ranged(start, end, groups)


def _by_table(
    metrics: Iterable[Metric],
) -> list[tuple[str, tuple[str, ...] | None, list[Metric]]]:
    """Metrics grouped into one query per table and sensor filter."""
    grouped: dict[tuple[str, tuple[str, ...] | None], list[Metric]] = {}
    for metric in metrics:
        sensors = metric.sensors()
        for table in metric.tables:
            grouped.setdefault((table, tuple(sensors) if sensors else None), []).append(metric)
    return [(table, sensors, chosen) for (table, sensors), chosen in grouped.items()]


def _outdoor(latest: _Latest, values: _Values, stored: Units) -> models.Outdoor | None:
    """The outdoor section."""
    if latest.outdoor is None:
        return None
    last = latest.outdoor.last
    T, H = Kind.TEMPERATURE, Kind.HUMIDITY
    temp = values.metric(T, last.get(field_name("temp", T, stored)))
    humidity = values.metric(H, last.get(field_name("humidity", H, stored)))
    dew = next(
        (
            s.last.get(field_name("dewpoint", T, stored))
            for s in latest.derived
            if s.sensor == "outdoor"
        ),
        None,
    )
    speed = None
    if latest.wind is not None:
        speed = values.metric(
            Kind.SPEED, latest.wind.last.get(field_name("speed", Kind.SPEED, stored))
        )
    feels = weather.feels_like(temp, humidity, speed) if temp is not None else None
    today = latest.temperature_today
    name = field_name("temp", T, stored)
    return models.Outdoor(
        temperature=None if temp is None else values.from_metric(T, temp),
        humidity=None if humidity is None else values.from_metric(H, humidity),
        dew_point=values.out(T, dew),
        feels_like=None if feels is None else values.from_metric(T, feels),
        high=values.at(T, today.maximum[name]) if today else None,
        low=values.at(T, today.minimum[name]) if today else None,
    )


def _wind(latest: _Latest, values: _Values, stored: Units) -> models.Wind | None:
    """The wind section."""
    if latest.wind is None:
        return None
    S = Kind.SPEED
    last = latest.wind.last
    speed = values.metric(S, last.get(field_name("speed", S, stored)))
    direction = values.metric(Kind.ANGLE, last.get("dir_deg"))
    force = None if speed is None else weather.beaufort(speed)
    today = latest.wind_today
    return models.Wind(
        speed=None if speed is None else values.from_metric(S, speed),
        gust=values.out(S, last.get(field_name("gust", S, stored))),
        direction=None if direction is None else round(direction),
        compass=None if direction is None else weather.compass(direction),
        beaufort=force,
        description=None if force is None else weather.BEAUFORT_NAMES[force],
        max_gust_today=values.at(S, today.maximum[field_name("gust", S, stored)])
        if today
        else None,
    )


def _rain(latest: _Latest, values: _Values, stored: Units) -> models.Rain | None:
    """The rain section, from the gauge that reported last (the piezo one on a tie)."""
    if not latest.rain:
        return None
    gauge = max(latest.rain, key=lambda s: (s.last_time, s.tags.get("gauge") == "piezo"))
    last = gauge.last
    R = Kind.RAIN

    def total(base: str) -> float | None:
        return values.out(R, last.get(field_name(base, R, stored)))

    rate = values.out(Kind.RAIN_RATE, last.get(field_name("rate", Kind.RAIN_RATE, stored)))
    return models.Rain(
        gauge=gauge.tags.get("gauge"),
        rate=rate,
        event=total("event"),
        hourly=total("hourly"),
        daily=total("daily"),
        last_24h=total("last24h"),
        weekly=total("weekly"),
        monthly=total("monthly"),
        yearly=total("yearly"),
        raining=bool(rate),
    )


def _pressure(latest: _Latest, values: _Values, stored: Units) -> models.Pressure | None:
    """The pressure section, with the trend when the last three hours are covered."""
    span = latest.pressure
    if span is None:
        return None
    P = Kind.PRESSURE
    sea, absolute, relative = (field_name(b, P, stored) for b in ("sea", "abs", "rel"))
    reference = sea if sea in span.last else relative
    trend = None
    first, last = (
        values.metric(P, span.first.get(reference)),
        values.metric(P, span.last.get(reference)),
    )
    if (
        first is not None
        and last is not None
        and span.last_time - span.first_time >= PRESSURE_TREND_COVERAGE
    ):
        change = last - first
        trend = models.PressureTrend(
            change=values.from_metric(P, change),
            hours=round((span.last_time - span.first_time).total_seconds() / 3600, 1),
            tendency=weather.tendency(change),
        )
    return models.Pressure(
        sea_level=values.out(P, span.last.get(sea)),
        absolute=values.out(P, span.last.get(absolute)),
        relative=values.out(P, span.last.get(relative)),
        trend=trend,
    )


def _sun(
    latest: _Latest, values: _Values, stored: Units, info: StationInfo, zone: tzinfo
) -> models.Sun | None:
    """Today's sun times where the station is, and the latest light readings."""
    light = latest.solar.last if latest.solar else {}
    answer = models.Sun(
        radiation=values.out(
            Kind.IRRADIANCE, light.get(field_name("radiation", Kind.IRRADIANCE, stored))
        ),
        uv_index=values.out(Kind.UV_INDEX, light.get("uv_index")),
    )
    if info.latitude is not None and info.longitude is not None:
        times = sun_times(latest.at.astimezone(zone).date(), info.latitude, info.longitude)
        answer.sunrise, answer.noon, answer.sunset = times.sunrise, times.noon, times.sunset
        answer.daylight_s = int(times.daylight.total_seconds())
        answer.polar = times.polar
    elif latest.solar is None:
        return None
    return answer


def _rooms(latest: _Latest, values: _Values, stored: Units, info: StationInfo) -> list[models.Room]:
    """Each room, indoor sensor first, with its airing advice."""
    T, H = Kind.TEMPERATURE, Kind.HUMIDITY
    dew_points = {s.sensor: s.last.get(field_name("dewpoint", T, stored)) for s in latest.derived}
    vents = {s.sensor: s.last for s in latest.ventilation}
    rooms = []
    for span in sorted(latest.rooms, key=lambda s: _natural(s.sensor or "")):
        sensor = span.sensor or ""
        humidity = values.metric(H, span.last.get(field_name("humidity", H, stored)))
        vent = vents.get(sensor, {})
        delta = values.metric(
            Kind.TEMPERATURE_DELTA,
            vent.get(field_name("dewpoint_delta", Kind.TEMPERATURE_DELTA, stored)),
        )
        advice = None
        if delta is not None and humidity is not None:
            advice = models.AiringAdvice(
                advice=weather.airing(humidity, delta).value,
                humidity_after=values.out(H, vent.get(field_name("predicted_humidity", H, stored))),
                dew_point_difference=values.from_metric(Kind.TEMPERATURE_DELTA, delta),
            )
        rooms.append(
            models.Room(
                sensor=sensor,
                name=_name(info, span.tags, span.name) or sensor,
                temperature=values.out(T, span.last.get(field_name("temp", T, stored))),
                humidity=None if humidity is None else values.from_metric(H, humidity),
                dew_point=values.out(T, dew_points.get(sensor)),
                airing=advice,
            )
        )
    return rooms


def _health(latest: _Latest, info: StationInfo) -> list[models.SensorHealth]:
    """Every sensor that reports staleness or a battery, in natural order."""
    unchanged = {s.sensor: s for s in latest.derived if s.sensor and "unchanged_s" in s.last}
    batteries = {s.sensor: s for s in latest.battery if s.sensor and "low" in s.last}
    found = []
    for sensor in sorted(unchanged.keys() | batteries.keys(), key=_natural):
        span = unchanged.get(sensor) or batteries[sensor]
        value = unchanged[sensor].last["unchanged_s"] if sensor in unchanged else None
        seconds = float(value) if isinstance(value, int | float) else None
        low = batteries[sensor].last["low"] if sensor in batteries else None
        found.append(
            models.SensorHealth(
                sensor=sensor,
                name=_name(info, span.tags, span.name) or sensor,
                battery_low=None if low is None else bool(low),
                unchanged_s=seconds,
                updating=seconds is None or seconds < weather.STALE_AFTER_S,
            )
        )
    return found


def _summary(now: models.Now, units: Units) -> str:
    """One line: temperature and feels-like, wind, rain, and the pressure trend."""
    parts = []
    outdoor = now.outdoor
    if outdoor is not None and outdoor.temperature is not None:
        symbol = SYMBOLS[unit(Kind.TEMPERATURE, units)]
        text = f"{outdoor.temperature:g} {symbol}"
        if outdoor.feels_like is not None and abs(outdoor.feels_like - outdoor.temperature) >= 1:
            text += f", feels like {round(outdoor.feels_like):g} {symbol}"
        parts.append(text)
    wind = now.wind
    if wind is not None and wind.beaufort is not None:
        if wind.beaufort == 0 or wind.compass is None:
            parts.append(wind.description or "")
        else:
            parts.append(f"{wind.description} from the {wind.compass}")
    rain = now.rain
    if rain is not None and rain.raining and rain.rate is not None:
        parts.append(f"Raining, {rain.rate:g} {SYMBOLS[unit(Kind.RAIN_RATE, units)]}")
    if now.pressure is not None and now.pressure.trend is not None:
        parts.append(f"Pressure {now.pressure.trend.tendency}")
    return "".join(f"{part}. " for part in parts).strip()


def _online(latest: _Latest) -> bool:
    """Whether the latest report is recent enough for the station to count as reporting."""
    if latest.report is None:
        return False
    interval = latest.report.last.get("interval_s")
    seconds = float(interval) if isinstance(interval, int | float) else 0.0
    grace = max(timedelta(seconds=seconds * ONLINE_INTERVALS), ONLINE_AT_LEAST)
    return latest.at - latest.report.last_time <= grace


def _first[T](found: list[T]) -> T | None:
    """The one answer of a table without groups, if there was one."""
    return found[0] if found else None


def _group(tags: dict[str, str]) -> str | None:
    """The sensor or rain gauge a group is."""
    return tags.get("sensor") or tags.get("gauge")


def _name(info: StationInfo, tags: dict[str, str], written: str | None) -> str | None:
    """A sensor's current name: the station's settings, then its newest rows, then a default.

    A sensor nobody named is written under its own identifier, which is no name at all.
    """
    sensor = tags.get("sensor")
    if sensor is None:
        return None
    if info.sensors.get(sensor):
        return info.sensors[sensor]
    if written and written != sensor:
        return written
    return SENSOR_NAMES.get(sensor, sensor)


def _natural(sensor: str) -> tuple[int, int, str]:
    """Indoor, then outdoor, then channels by number, then anything else."""
    if sensor == "indoor":
        return (0, 0, "")
    if sensor == "outdoor":
        return (1, 0, "")
    if sensor.startswith("ch") and sensor[2:].isdigit():
        return (2, int(sensor[2:]), "")
    return (3, 0, sensor)


def _target(stored: Units, choice: Mapping[str, str] | None) -> Units:
    """The units to answer in: the station's own, with the request's choices swapped in."""
    return dataclasses.replace(stored, **(choice or {}))


def _units(units: Units) -> models.UnitsOut:
    """Units as the API states them."""
    return models.UnitsOut(
        temperature=units.temperature,
        pressure=units.pressure,
        rain=units.rain,
        wind=units.wind,
        distance=units.distance,
    )


def _zone(info: StationInfo) -> tzinfo:
    """The station's time zone, UTC if it has none or one this system does not know."""
    try:
        return zoneinfo.ZoneInfo(info.timezone) if info.timezone else UTC
    except zoneinfo.ZoneInfoNotFoundError, ValueError:
        return UTC


def _midnight(moment: datetime, zone: tzinfo) -> datetime:
    """The start of `moment`'s day in `zone`, in UTC."""
    return _midnight_of(moment.astimezone(zone).date(), zone)


def _midnight_of(day: date, zone: tzinfo) -> datetime:
    """The start of `day` in `zone`, in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)

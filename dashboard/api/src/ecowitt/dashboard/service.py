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
from importlib.metadata import version as package_version

from ecowitt.core import weathermodel, windheight
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import Buckets, Extreme, Extremes, Reader, Span
from ecowitt.core.units import SYMBOLS, Kind, Units, convert, field_name
from ecowitt.dashboard import forecast, messages, models, weather
from ecowitt.dashboard.cache import TtlCache
from ecowitt.dashboard.catalogue import (
    CHOICES,
    METRICS,
    ROOM_SENSOR,
    Metric,
    Sides,
    rounded,
    unit,
)
from ecowitt.dashboard.i18n import ENGLISH, Language
from ecowitt.dashboard.sun import sun_times

#: The units calculations are made in.
METRIC = Units()
#: The table of wind estimated at 10 m, which the wind answers lead with.
TEN = windheight.TABLE


@dataclass(frozen=True)
class Range:
    """A chart's span and the width of its buckets."""

    duration: timedelta
    step: timedelta
    #: How long its answer is reused.
    ttl: float


#: A station reports about once a minute, so the shortest ranges keep every report.
RANGES = {
    "1h": Range(timedelta(hours=1), timedelta(minutes=1), 30),
    "3h": Range(timedelta(hours=3), timedelta(minutes=1), 30),
    "6h": Range(timedelta(hours=6), timedelta(minutes=1), 30),
    "12h": Range(timedelta(hours=12), timedelta(minutes=2), 60),
    "24h": Range(timedelta(hours=24), timedelta(minutes=5), 60),
    "7d": Range(timedelta(days=7), timedelta(minutes=30), 300),
    "30d": Range(timedelta(days=30), timedelta(hours=2), 900),
    "1y": Range(timedelta(days=365), timedelta(days=1), 3600),
}
#: Periods extremes are given for, and how long each answer is reused.
PERIODS = {"today": 60.0, "month": 600.0, "year": 1800.0}

NOW_TTL = 30.0
#: The release running, from the installed package's metadata.
VERSION = package_version("ecowitt-dashboard")
#: The collector fetches a forecast hourly, so a few minutes' reuse loses nothing.
FORECAST_TTL = 300.0
STATIONS_TTL = 300.0
#: How far back a station's latest report is looked for.
LATEST_WITHIN = timedelta(days=7)
#: How much of the time before its latest report a station's current values are taken from.
CURRENT_WINDOW = timedelta(minutes=15)
#: How far back the strongest gust and heaviest rain are taken for the wind and rain notices: the
#: Strong wind and Heavy rain alert rules' window, so a gusty spell stays marked between gusts.
GUSTS_WITHIN = timedelta(minutes=10)
PRESSURE_TREND = timedelta(hours=3)
#: A trend needs readings from nearly the whole of its three hours.
PRESSURE_TREND_COVERAGE = timedelta(hours=2, minutes=50)
#: A station is online while its latest report is younger than this many upload intervals...
ONLINE_INTERVALS = 3
#: ...or than this, whichever is longer.
ONLINE_AT_LEAST = timedelta(minutes=5)
#: The weather model's sky is shown while its newest values are younger than this: the model
#: writes every 15 minutes, so older means the collector has stopped fetching.
SKY_FRESH = timedelta(hours=1)


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
    #: The house's median room against the outdoor air, as the collector stores it.
    house: Span | None = None
    battery: list[Span] = field(default_factory=list)
    temperature_today: Extremes | None = None
    wind_today: Extremes | None = None
    #: The wind estimated at 10 m (`windheight`): latest values, today's and recent gusts.
    wind_10m: Span | None = None
    wind_10m_today: Extremes | None = None
    recent_wind_10m: Extremes | None = None
    #: The strongest gust and each gauge's heaviest rain rate within GUSTS_WITHIN of the report.
    recent_wind: Extremes | None = None
    recent_rain: list[Extremes] = field(default_factory=list)
    #: The station's weather model's newest sky, if it has a model and the values are fresh.
    sky: Span | None = None
    #: When it was read.
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class _Bucketed:
    """A range's buckets per metric, in stored units."""

    start: datetime
    end: datetime
    groups: dict[str, list[Buckets]]
    #: The weather model's buckets per metric, when they were asked for.
    model: dict[str, Buckets] = field(default_factory=dict)


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

    async def stations(self, language: Language = ENGLISH) -> list[models.Station]:
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
                    weather_model=_weather_model(info, language),
                    wind_factor=info.wind_factor,
                )
            )
        return found

    def meta(self, language: Language = ENGLISH) -> models.Meta:
        """The metrics, units, ranges and periods there are."""
        return models.Meta(
            title=self.title,
            version=VERSION,
            metrics=[
                models.MetricInfo(
                    id=m.id,
                    label=messages.metric(language, m.label),
                    quantity=m.quantity,
                    unit=None if m.quantity else unit(m.kind, METRIC),
                    aggregates=[a.value for a in m.aggregates],
                    extremes=m.extremes.value,
                    per_sensor=m.per_sensor,
                    model=m.model_base is not None,
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

    async def now(
        self, station: str, choice: Mapping[str, str] | None = None, language: Language = ENGLISH
    ) -> models.Now:
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
        answer.wind = _wind(latest, values, stored, info, language)
        answer.rain = _rain(latest, values, stored)
        answer.pressure = _pressure(latest, values, stored, language)
        answer.sun = _sun(latest, values, stored, info, zone)
        air = _room_air(latest, values, stored, info, language)
        answer.airing = _house(latest, air, values, stored)
        answer.rooms = _rooms(latest, values, stored, info, air, language)
        answer.sensors = _health(latest, info, language)
        answer.notices = _notices(latest, values, stored, answer, language)
        coming = await self._stored_forecast(station, info)
        _forecast_notices(answer, coming, values, info, zone, self.clock(), language)
        if answer.airing is not None and answer.airing.advice != "open":
            damp = [r for r in air if r.humidity >= weather.AIRING_HUMIDITY_PCT]
            answer.airing.drier_from = forecast.drier_from(
                coming, values, info, self.clock(), [r.delta for r in damp]
            )
        answer.sky = _sky(latest, stored, language)
        answer.summary_parts = _summary(answer, values.target, language)
        answer.summary = "".join(f"{part.text}. " for part in answer.summary_parts).strip()
        return answer

    async def forecast(
        self, station: str, choice: Mapping[str, str] | None = None, language: Language = ENGLISH
    ) -> models.ForecastOut:
        """The station's latest forecast: the next 24 hours and the days its model reaches."""
        info = await self.info(station)
        stored = await self._stored_forecast(station, info)
        values = _Values(info.units, _target(info.units, choice))
        hours, days = forecast.answer(stored, values, info, language)
        return models.ForecastOut(
            station=station,
            model=_weather_model(info, language),
            issued=stored.issued,
            units=_units(values.target),
            hours=hours,
            days=days,
        )

    async def _stored_forecast(self, station: str, info: StationInfo) -> forecast.Stored:
        """The station's newest stored forecast, shared by /now and /forecast."""
        return await self.cache.get(
            ("forecast", station),
            FORECAST_TTL,
            lambda: forecast.read(self.reader, station, info, _zone(info), self.clock()),
        )

    async def series(
        self,
        station: str,
        metrics: list[str],
        range_name: str,
        choice: Mapping[str, str] | None = None,
        *,
        model: bool = False,
        language: Language = ENGLISH,
    ) -> models.SeriesOut:
        """Metrics over a range, in buckets aligned to the station's midnight.

        With `model`, each metric the station's weather model has also comes as the model's
        series, marked `source: model`.
        """
        info = await self.info(station)
        chosen = [METRICS[m] for m in dict.fromkeys(metrics)]
        span = RANGES[range_name]
        model = model and info.weather_model is not None
        key = ("series", station, range_name, tuple(m.id for m in chosen), model)
        found = await self.cache.get(
            key, span.ttl, lambda: self._bucketed(station, info, chosen, span, model=model)
        )
        values = _Values(info.units, _target(info.units, choice))
        series = []
        for metric in chosen:
            for group in found.groups.get(metric.id, []):
                columns = _columns(metric, group, metric.field(info.units), values)
                if columns is not None:
                    series.append(
                        models.Series(
                            metric=metric.id,
                            sensor=_group(group.tags),
                            name=_name(info, group.tags, group.name, language),
                            unit=unit(metric.kind, values.target),
                            t=[int(t.timestamp()) for t in group.times],
                            values=columns,
                        )
                    )
            buckets = found.model.get(metric.id)
            name = metric.model_field(info.units)
            columns = (
                None if buckets is None or name is None else _columns(metric, buckets, name, values)
            )
            if buckets is not None and columns is not None:
                series.append(
                    models.Series(
                        metric=metric.id,
                        sensor=None,
                        name=None,
                        unit=unit(metric.kind, values.target),
                        source="model",
                        t=[int(t.timestamp()) for t in buckets.times],
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
        self,
        station: str,
        period: str,
        choice: Mapping[str, str] | None = None,
        language: Language = ENGLISH,
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
                        name=_name(info, group.tags, group.name, language),
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
        recent = end - GUSTS_WITHIN
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
        rate = f("rate", Kind.RAIN_RATE)
        rain_fields += [f(b, R) for b in ("monthly", "yearly")] + [rate]
        (
            outdoor, derived, wind, rain, pressure, solar, indoor, channel, ventilation, house,
            battery, temperature_today, wind_today, sky, recent_wind, recent_rain,
            wind_10m, wind_10m_today, recent_wind_10m,
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
            span("house", f("humidity", H), f("predicted_humidity", H), f("dewpoint_delta", D)),
            span("battery", "low"),
            self.reader.extremes(
                station, "outdoor", [f("temp", T)], start=midnight, end=now, sensors=["outdoor"]
            ),
            self.reader.extremes(station, "wind", [f("gust", S)], start=midnight, end=now),
            self._sky(station, info, now),
            self.reader.extremes(station, "wind", [f("gust", S)], start=recent, end=end),
            self.reader.extremes(station, "rain", [rate], start=recent, end=end),
            span(TEN, f("speed", S), f("gust", S), "source"),
            self.reader.extremes(station, TEN, [f("gust", S)], start=midnight, end=now),
            self.reader.extremes(station, TEN, [f("gust", S)], start=recent, end=end),
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
            house=_first(house),
            battery=battery,
            temperature_today=_first(temperature_today),
            wind_today=_first(wind_today),
            recent_wind=_first(recent_wind),
            recent_rain=recent_rain,
            wind_10m=_first(wind_10m),
            wind_10m_today=_first(wind_10m_today),
            recent_wind_10m=_first(recent_wind_10m),
            sky=sky,
            at=now,
        )

    async def _sky(self, station: str, info: StationInfo, now: datetime) -> Span | None:
        """The newest sky from the station's weather model, if it has one and it is fresh."""
        if info.weather_model is None:
            return None
        cloud = field_name("cloud_cover", Kind.PERCENT, info.units)
        found = await self.reader.span(
            station,
            weathermodel.TABLE,
            ["weather_code", "is_day", cloud],
            start=now - SKY_FRESH,
            end=now,
        )
        return next((s for s in found if s.tags.get("model") == info.weather_model), None)

    async def _bucketed(
        self,
        station: str,
        info: StationInfo,
        metrics: list[Metric],
        span: Range,
        *,
        model: bool = False,
    ) -> _Bucketed:
        """Read each metric's buckets, one query per table and sensor filter, and with `model`
        one more of the `model` table for the station's current weather model."""
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

        async def ask_model() -> dict[str, Buckets]:
            modelled = [m for m in metrics if m.model_base is not None]
            if not model or not modelled:
                return {}
            pairs = [(m.model_field(info.units), a) for m in modelled for a in m.aggregates]
            found = await self.reader.buckets(
                station, weathermodel.TABLE, pairs, start=start, end=end, step=span.step,
                origin=origin,
            )  # type: ignore[arg-type]  # fmt: skip
            current = next((g for g in found if g.tags.get("model") == info.weather_model), None)
            return {} if current is None else {m.id: current for m in modelled}

        *answers, modelled = await asyncio.gather(*(ask(*q) for q in queries), ask_model())
        groups: dict[str, list[Buckets]] = {}
        for (_, _, chosen), found in zip(queries, answers, strict=True):
            for metric in chosen:
                groups.setdefault(metric.id, []).extend(g for g in found if metric.covers(g.sensor))
        return _Bucketed(start, end, groups, modelled)

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


def _wind(
    latest: _Latest, values: _Values, stored: Units, info: StationInfo, language: Language
) -> models.Wind | None:
    """The wind section: led by the estimate at 10 m, with what the sensor measured beside it.

    A station whose 10 m estimate has not been written for the latest report -- one running a
    collector without it -- leads with the measured wind.
    """
    if latest.wind is None:
        return None
    S = Kind.SPEED
    speed_field, gust_field = field_name("speed", S, stored), field_name("gust", S, stored)
    measured = latest.wind.last
    ten = latest.wind_10m.last if latest.wind_10m else {}
    lead = ten if speed_field in ten else measured
    speed = values.metric(S, lead.get(speed_field))
    direction = values.metric(Kind.ANGLE, measured.get("dir_deg"))
    force = None if speed is None else weather.beaufort(speed)
    today = latest.wind_10m_today if lead is ten else latest.wind_today
    measured_today = latest.wind_today
    source = ten.get("source") if lead is ten else None
    measured_speed = values.metric(S, measured.get(speed_field))
    measured_force = None if measured_speed is None else weather.beaufort(measured_speed)
    return models.Wind(
        speed=None if speed is None else values.from_metric(S, speed),
        gust=values.out(S, lead.get(gust_field)),
        direction=None if direction is None else round(direction),
        compass=None if direction is None else messages.compass(language, direction),
        beaufort=force,
        description=None if force is None else messages.beaufort(language, force),
        max_gust_today=values.at(S, today.maximum[gust_field])
        if today and gust_field in today.maximum
        else None,
        source=source if isinstance(source, str) else None,
        height_factor=info.wind_factor,
        measured_speed=values.out(S, measured.get(speed_field)),
        measured_gust=values.out(S, measured.get(gust_field)),
        measured_max_gust_today=values.at(S, measured_today.maximum[gust_field])
        if measured_today and gust_field in measured_today.maximum
        else None,
        measured_beaufort=measured_force,
        measured_description=None
        if measured_force is None
        else messages.beaufort(language, measured_force),
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


def _pressure_change(latest: _Latest, values: _Values, stored: Units) -> float | None:
    """How far pressure has moved over the last three hours, in hPa; None unless they are
    nearly all covered. Sea-level pressure where there is an altitude, relative otherwise."""
    span = latest.pressure
    if span is None or span.last_time - span.first_time < PRESSURE_TREND_COVERAGE:
        return None
    P = Kind.PRESSURE
    sea, relative = field_name("sea", P, stored), field_name("rel", P, stored)
    reference = sea if sea in span.last else relative
    first = values.metric(P, span.first.get(reference))
    last = values.metric(P, span.last.get(reference))
    return None if first is None or last is None else last - first


def _pressure(
    latest: _Latest, values: _Values, stored: Units, language: Language
) -> models.Pressure | None:
    """The pressure section, with the trend when the last three hours are covered."""
    span = latest.pressure
    if span is None:
        return None
    P = Kind.PRESSURE
    change = _pressure_change(latest, values, stored)
    trend = None
    if change is not None:
        tendency = weather.tendency(change)
        trend = models.PressureTrend(
            change=values.from_metric(P, change),
            hours=round((span.last_time - span.first_time).total_seconds() / 3600, 1),
            code=tendency,
            tendency=messages.tendency(language, tendency),
        )
    return models.Pressure(
        sea_level=values.out(P, span.last.get(field_name("sea", P, stored))),
        absolute=values.out(P, span.last.get(field_name("abs", P, stored))),
        relative=values.out(P, span.last.get(field_name("rel", P, stored))),
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


@dataclass(frozen=True)
class _RoomAir:
    """What airing one room would do, in metric units."""

    sensor: str
    name: str
    humidity: float
    delta: float
    after: float | None


def _room_air(
    latest: _Latest, values: _Values, stored: Units, info: StationInfo, language: Language
) -> list[_RoomAir]:
    """Each room with both its humidity and a comparison with the outdoor air."""
    H, D = Kind.HUMIDITY, Kind.TEMPERATURE_DELTA
    vents = {s.sensor: s.last for s in latest.ventilation}
    found = []
    for span in latest.rooms:
        sensor = span.sensor or ""
        vent = vents.get(sensor, {})
        humidity = values.metric(H, span.last.get(field_name("humidity", H, stored)))
        delta = values.metric(D, vent.get(field_name("dewpoint_delta", D, stored)))
        if humidity is None or delta is None:
            continue
        after = values.metric(H, vent.get(field_name("predicted_humidity", H, stored)))
        name = _name(info, span.tags, span.name, language) or sensor
        found.append(_RoomAir(sensor, name, humidity, delta, after))
    return found


def _house(
    latest: _Latest, air: list[_RoomAir], values: _Values, stored: Units
) -> models.HouseAiring | None:
    """The whole house's airing advice, from the collector's medians and each room's advice."""
    if latest.house is None:
        return None
    H, D = Kind.HUMIDITY, Kind.TEMPERATURE_DELTA
    row = latest.house.last
    humidity = values.metric(H, row.get(field_name("humidity", H, stored)))
    delta = values.metric(D, row.get(field_name("dewpoint_delta", D, stored)))
    if humidity is None or delta is None:
        return None
    after = values.metric(H, row.get(field_name("predicted_humidity", H, stored)))
    advice = weather.house_airing([(r.humidity, r.delta, r.after) for r in air], humidity, after)
    return models.HouseAiring(
        advice=advice.value,
        rooms=[
            r.name
            for r in air
            if weather.airing(r.humidity, r.delta, r.after) is weather.Airing.OPEN
        ],
        humidity=values.from_metric(H, humidity),
        humidity_after=None if after is None else values.from_metric(H, after),
        dew_point_difference=values.from_metric(D, delta),
    )


def _rooms(
    latest: _Latest,
    values: _Values,
    stored: Units,
    info: StationInfo,
    air: list[_RoomAir],
    language: Language,
) -> list[models.Room]:
    """Each room, indoor sensor first, with its airing advice."""
    T, H = Kind.TEMPERATURE, Kind.HUMIDITY
    dew_points = {s.sensor: s.last.get(field_name("dewpoint", T, stored)) for s in latest.derived}
    by_sensor = {r.sensor: r for r in air}
    rooms = []
    for span in sorted(latest.rooms, key=lambda s: _natural(s.sensor or "")):
        sensor = span.sensor or ""
        room = by_sensor.get(sensor)
        advice = None
        if room is not None:
            advice = models.AiringAdvice(
                advice=weather.airing(room.humidity, room.delta, room.after).value,
                humidity_after=None if room.after is None else values.from_metric(H, room.after),
                dew_point_difference=values.from_metric(Kind.TEMPERATURE_DELTA, room.delta),
            )
        temp = values.metric(T, span.last.get(field_name("temp", T, stored)))
        humidity = values.metric(H, span.last.get(field_name("humidity", H, stored)))
        rooms.append(
            models.Room(
                sensor=sensor,
                name=_name(info, span.tags, span.name, language) or sensor,
                temperature=None if temp is None else values.from_metric(T, temp),
                humidity=None if humidity is None else values.from_metric(H, humidity),
                dew_point=values.out(T, dew_points.get(sensor)),
                airing=advice,
                flags=weather.room_flags(temp, humidity),
            )
        )
    return rooms


def _health(latest: _Latest, info: StationInfo, language: Language) -> list[models.SensorHealth]:
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
                name=_name(info, span.tags, span.name, language) or sensor,
                battery_low=None if low is None else bool(low),
                unchanged_s=seconds,
                updating=not _judged(sensor) or seconds is None or seconds < weather.STALE_AFTER_S,
            )
        )
    return found


def _judged(sensor: str) -> bool:
    """Whether a sensor's unchanged readings mean it has stopped, as Sensor not updating judges.

    Temperature and humidity always drift. Rain totals hold still through a dry week and light
    through every night, and their sensors report with the outdoor one -- which is judged, so a
    silent array still shows.
    """
    return sensor == "outdoor" or ROOM_SENSOR.fullmatch(sensor) is not None


def _notices(
    latest: _Latest, values: _Values, stored: Units, now: models.Now, language: Language
) -> dict[str, models.Notice]:
    """What deserves attention, card by card, judged in metric units."""
    found: dict[str, models.Notice] = {}

    def warn(card: str, *codes: models.NoticeCode) -> None:
        found[card] = models.Notice(level="warning")
        for code in codes:
            _say(found[card], models.NoticeItem(code=code, text=messages.notice(language, code)))

    if latest.outdoor is not None:
        T, H = Kind.TEMPERATURE, Kind.HUMIDITY
        temp = values.metric(T, latest.outdoor.last.get(field_name("temp", T, stored)))
        humidity = values.metric(H, latest.outdoor.last.get(field_name("humidity", H, stored)))
        speed = None
        if latest.wind is not None:
            speed = values.metric(
                Kind.SPEED, latest.wind.last.get(field_name("speed", Kind.SPEED, stored))
            )
        codes = []
        if temp is not None and temp <= weather.COLD_C:
            codes.append(models.NoticeCode.COLD)
        elif temp is not None and weather.feels_like(temp, humidity, speed) >= weather.HEAT_FEELS_C:
            codes.append(models.NoticeCode.HEAT)
        if humidity is not None and humidity >= weather.HUMID_AIR_PCT:
            codes.append(models.NoticeCode.HUMID_AIR)
        elif humidity is not None and humidity <= weather.DRY_AIR_PCT:
            codes.append(models.NoticeCode.DRY_AIR)
        if codes:
            warn("outdoor", *codes)

    def strongest(groups: list[Extremes], base: str, kind: Kind) -> float:
        """The highest of the groups' maxima of a field, in metric units; 0 without one."""
        name = field_name(base, kind, stored)
        found = [g.maximum[name].value for g in groups if name in g.maximum]
        return convert(kind, max(found), stored, METRIC) if found else 0.0

    # The 10 m gust, the height the threshold is meant for; the measured one without it.
    recent = latest.recent_wind_10m or latest.recent_wind
    if strongest([recent] if recent else [], "gust", Kind.SPEED) > weather.STRONG_GUST_KMH:
        warn("wind", models.NoticeCode.STRONG_GUSTS)
    if strongest(latest.recent_rain, "rate", Kind.RAIN_RATE) > weather.HEAVY_RAIN_MM_H:
        warn("rain", models.NoticeCode.HEAVY_RAIN)
    change = _pressure_change(latest, values, stored)
    if change is not None and -change > weather.FAST_FALL_HPA:
        warn("pressure", models.NoticeCode.PRESSURE_FALLING_FAST)
    if latest.solar is not None:
        uv = values.metric(Kind.UV_INDEX, latest.solar.last.get("uv_index"))
        if uv is not None and uv >= weather.UV_VERY_HIGH:
            warn("sun", models.NoticeCode.UV_VERY_HIGH)
    if now.airing is not None and now.airing.advice == "open":
        found["airing"] = models.Notice(level="good")
    elif now.airing is not None and now.airing.advice == "keep_closed":
        warn("airing")
    flagged: dict[str, list[str]] = {}
    for room in now.rooms:
        for flag in room.flags:
            flagged.setdefault(flag, []).append(room.name)
    if flagged:
        warn("rooms")
        for flag, names in flagged.items():
            text = messages.notice(
                language,
                models.NoticeCode.ROOM_FLAG,
                flag=messages.room_flag(language, flag),
                rooms=", ".join(names),
            )
            item = models.NoticeItem(
                code=models.NoticeCode.ROOM_FLAG, flag=flag, rooms=names, text=text
            )
            _say(found["rooms"], item)
    if any(s.battery_low or not s.updating for s in now.sensors):
        warn("sensors")
    return found


def _columns(
    metric: Metric, buckets: Buckets, name: str, values: _Values
) -> dict[str, list[float | None]] | None:
    """A metric's columns from one group's buckets, converted; None when it has no value."""
    columns = {
        aggregate.value: [
            None if v is None else values.out(metric.kind, v)
            for v in buckets.values.get((name, aggregate), [])
        ]
        for aggregate in metric.aggregates
    }
    if not any(v is not None for column in columns.values() for v in column):
        return None
    return columns


def _forecast_notices(
    now: models.Now,
    coming: forecast.Stored,
    values: _Values,
    info: StationInfo,
    zone: tzinfo,
    at: datetime,
    language: Language,
) -> None:
    """Add to the cards' notices what the forecast says is coming within the day.

    Rain on the rain card while it is dry; frost or heat on the outdoor card; strong gusts on the
    wind card while they are not blowing already. Times are in the station's time.
    """
    target = values.target
    today = at.astimezone(zone).date()

    def say(
        card: str,
        code: models.NoticeCode,
        time: datetime,
        kind: Kind | None = None,
        value: float | None = None,
    ) -> None:
        """Add a forecast item to a card's notice: what is coming, when, and how much."""
        item = models.NoticeItem(code=code, time=time, text="")
        if code in messages.NOTICES_AT:
            params = {}
            if kind is not None and value is not None:
                item.value, item.unit = values.from_metric(kind, value), unit(kind, target)
                params["value"] = f"{language.number(item.value)} {SYMBOLS[item.unit]}"
            local = time.astimezone(zone)
            item.text = messages.notice_at(language, code, local, local.date() != today, **params)
        else:
            item.text = messages.notice(language, code)
        _say(now.notices.setdefault(card, models.Notice(level="warning")), item)

    raining = now.rain is not None and now.rain.raining
    rain = forecast.rain(coming, values, info, at)
    if rain is not None and not raining:
        soon = rain.time <= at
        say("rain", models.NoticeCode.RAIN_SOON if soon else models.NoticeCode.RAIN_FROM, rain.time)
    low = forecast.extreme(coming, values, info, at, "temp", Kind.TEMPERATURE, lowest=True)
    if low is not None and low.value <= forecast.FROST_C:
        # The forecast's frost is more precise than the present reading's hint of it.
        outdoor = now.notices.get("outdoor")
        if outdoor is not None:
            outdoor.items = [i for i in outdoor.items if i.code is not models.NoticeCode.COLD]
            outdoor.text = _line(outdoor.items)
        say("outdoor", models.NoticeCode.FROST_FORECAST, low.time, Kind.TEMPERATURE, low.value)
    high = forecast.extreme(coming, values, info, at, "temp", Kind.TEMPERATURE, lowest=False)
    if high is not None and high.value >= weather.HEAT_FEELS_C:
        say("outdoor", models.NoticeCode.HEAT_FORECAST, high.time, Kind.TEMPERATURE, high.value)
    gust = forecast.extreme(coming, values, info, at, "gust", Kind.SPEED, lowest=False)
    if gust is not None and gust.value > weather.STRONG_GUST_KMH and "wind" not in now.notices:
        say("wind", models.NoticeCode.GUSTS_FORECAST, gust.time, Kind.SPEED, gust.value)


def _say(notice: models.Notice, item: models.NoticeItem) -> None:
    """Add an item to a notice, and its words to the notice's line."""
    notice.items.append(item)
    notice.text = _line(notice.items)


def _line(items: list[models.NoticeItem]) -> str:
    """Items' words in one line."""
    return " ".join(i.text for i in items)


def _sky(latest: _Latest, stored: Units, language: Language) -> models.Sky | None:
    """The sky from the weather model's newest values, or None without a weather code."""
    span = latest.sky
    code = span.last.get("weather_code") if span else None
    if span is None or isinstance(code, bool) or not isinstance(code, int | float):
        return None
    is_day = span.last.get("is_day")
    cloud = span.last.get(field_name("cloud_cover", Kind.PERCENT, stored))
    return models.Sky(
        code=int(code),
        description=messages.sky(language, int(code)),
        is_day=is_day if isinstance(is_day, bool) else None,
        cloud_cover=float(cloud) if isinstance(cloud, int | float) else None,
        time=span.last_time,
    )


def _weather_model(info: StationInfo, language: Language) -> models.WeatherModel | None:
    """The station's weather model, named, or None when it has none."""
    if info.weather_model is None:
        return None
    label = messages.model(language, info.weather_model)
    return models.WeatherModel(id=info.weather_model, label=label)


def _summary(now: models.Now, units: Units, language: Language) -> list[models.SummaryPart]:
    """One line, part by part: the sky, temperature and feels-like, wind, rain, and the pressure
    trend."""
    Code = models.SummaryCode
    parts = []
    if now.sky is not None:
        parts.append(models.SummaryPart(code=Code.SKY, text=now.sky.description))
    outdoor = now.outdoor
    if outdoor is not None and outdoor.temperature is not None:
        symbol = SYMBOLS[unit(Kind.TEMPERATURE, units)]
        text = f"{language.number(outdoor.temperature)} {symbol}"
        if outdoor.feels_like is not None and abs(outdoor.feels_like - outdoor.temperature) >= 1:
            feels = f"{language.number(round(outdoor.feels_like))} {symbol}"
            text = messages.summary(language, "feels_like", temperature=text, feels=feels)
        parts.append(models.SummaryPart(code=Code.TEMPERATURE, text=text))
    wind = now.wind
    if wind is not None and wind.beaufort is not None:
        text = wind.description or ""
        if wind.beaufort != 0 and wind.compass is not None:
            text = messages.summary(language, "wind_from", description=text, compass=wind.compass)
        parts.append(models.SummaryPart(code=Code.WIND, text=text))
    rain = now.rain
    if rain is not None and rain.raining and rain.rate is not None:
        rate = f"{language.number(rain.rate)} {SYMBOLS[unit(Kind.RAIN_RATE, units)]}"
        text = messages.summary(language, "raining", rate=rate)
        parts.append(models.SummaryPart(code=Code.RAIN, text=text))
    if now.pressure is not None and now.pressure.trend is not None:
        text = messages.summary(language, "pressure", tendency=now.pressure.trend.tendency)
        parts.append(models.SummaryPart(code=Code.PRESSURE, text=text))
    return parts


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


def _name(
    info: StationInfo, tags: dict[str, str], written: str | None, language: Language
) -> str | None:
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
    return messages.sensor(language, sensor)


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

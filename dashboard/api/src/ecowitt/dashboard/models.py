"""The API's answers, as the OpenAPI document publishes them for any client to build against.

Values are in the units the request asked for (each answer says which in `units`), rounded to
what is worth showing. Times are UTC; a station's `timezone` says where its day begins.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UnitsOut(BaseModel):
    """The unit each convertible quantity is given in, as a code /meta lists symbols for."""

    temperature: str
    pressure: str
    rain: str
    wind: str
    distance: str


class Station(BaseModel):
    """A station and its published settings."""

    id: str
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    timezone: str
    #: The units the station stores, which answers default to.
    units: UnitsOut


class At(BaseModel):
    """A value and when it was reached."""

    value: float
    time: datetime


class Outdoor(BaseModel):
    """The outdoor sensor's latest reading, with what follows from it and today's range."""

    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    feels_like: float | None = None
    high: At | None = None
    low: At | None = None


class Wind(BaseModel):
    """The latest wind, and today's strongest gust."""

    speed: float | None = None
    gust: float | None = None
    #: Degrees the wind blows from, clockwise from north.
    direction: float | None = None
    compass: str | None = None
    beaufort: int | None = None
    description: str | None = None
    max_gust_today: At | None = None


class Rain(BaseModel):
    """One gauge's latest totals, as the console keeps them."""

    gauge: str | None = None
    rate: float | None = None
    event: float | None = None
    hourly: float | None = None
    daily: float | None = None
    last_24h: float | None = None
    weekly: float | None = None
    monthly: float | None = None
    yearly: float | None = None
    raining: bool = False


class PressureTrend(BaseModel):
    """How pressure has changed over the last three hours."""

    change: float
    hours: float
    #: In the Met Office's words: steady, rising slowly, falling quickly...
    tendency: str


class Pressure(BaseModel):
    """The latest pressure readings."""

    sea_level: float | None = None
    absolute: float | None = None
    relative: float | None = None
    trend: PressureTrend | None = None


class Sun(BaseModel):
    """Today's sun at the station, and the latest light readings."""

    radiation: float | None = None
    uv_index: float | None = None
    sunrise: datetime | None = None
    noon: datetime | None = None
    sunset: datetime | None = None
    daylight_s: int | None = None
    #: "day" when the sun does not set today, "night" when it does not rise.
    polar: str | None = None


class AiringAdvice(BaseModel):
    """Whether opening this room's windows would dry it."""

    #: open, keep_closed or no_need.
    advice: str
    #: The room's humidity once its air had been replaced by outdoor air at room temperature.
    humidity_after: float | None = None
    #: How far the room's dew point is above the outdoor one.
    dew_point_difference: float


class Room(BaseModel):
    """One room's latest reading."""

    sensor: str
    name: str
    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    airing: AiringAdvice | None = None


class SensorHealth(BaseModel):
    """Whether a sensor is reporting, and its battery."""

    sensor: str
    name: str
    battery_low: bool | None = None
    #: How long its values have gone unchanged.
    unchanged_s: float | None = None
    updating: bool = True


class Now(BaseModel):
    """A station at a glance."""

    station: str
    #: The station's latest report, or None if it has sent none for a week.
    time: datetime | None
    online: bool
    timezone: str
    units: UnitsOut
    #: One line in words: temperature, wind, rain and the pressure trend.
    summary: str
    outdoor: Outdoor | None = None
    wind: Wind | None = None
    rain: Rain | None = None
    pressure: Pressure | None = None
    sun: Sun | None = None
    rooms: list[Room] = Field(default_factory=list)
    sensors: list[SensorHealth] = Field(default_factory=list)


class Series(BaseModel):
    """One metric of one sensor in time buckets."""

    metric: str
    #: The sensor, or rain gauge, the values are from; None for a station-wide metric.
    sensor: str | None
    name: str | None
    unit: str
    #: Each bucket's start, in Unix seconds.
    t: list[int]
    #: Per aggregate the metric has (mean, min, max, circular), one value per bucket.
    values: dict[str, list[float | None]]


class SeriesOut(BaseModel):
    """Metrics over a range, bucketed."""

    station: str
    range: str
    step_s: int
    start: datetime
    end: datetime
    units: UnitsOut
    series: list[Series]


class Extreme(BaseModel):
    """One metric's extremes for one sensor."""

    metric: str
    sensor: str | None
    name: str | None
    unit: str
    min: At | None = None
    max: At | None = None


class ExtremesOut(BaseModel):
    """The extremes of a period: today, this month or this year, in the station's time."""

    station: str
    period: str
    start: datetime
    end: datetime
    units: UnitsOut
    extremes: list[Extreme]


class MetricInfo(BaseModel):
    """A metric /series and /extremes serve."""

    id: str
    label: str
    #: The unit preference that converts it, or None when it has one fixed unit.
    quantity: str | None
    #: Its fixed unit, when it has no quantity.
    unit: str | None
    aggregates: list[str]
    #: none, max or both.
    extremes: str
    per_sensor: bool


class UnitChoice(BaseModel):
    """A unit a quantity can be asked for in."""

    code: str
    symbol: str


class Meta(BaseModel):
    """What the API offers."""

    title: str
    metrics: list[MetricInfo]
    units: dict[str, list[UnitChoice]]
    #: The symbol for every unit code a value can come in.
    symbols: dict[str, str]
    ranges: list[str]
    periods: list[str]

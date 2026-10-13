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


class WeatherModel(BaseModel):
    """The weather model stored beside a station's readings."""

    #: Open-Meteo's name for it, as `best_match`.
    id: str
    #: In words, as "Best for this location".
    label: str


class Station(BaseModel):
    """A station and its published settings."""

    id: str
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    timezone: str
    #: The units the station stores, which answers default to.
    units: UnitsOut
    #: The weather model whose values /series can add, or None when the station has none.
    weather_model: WeatherModel | None = None
    #: What its measured wind is multiplied by to estimate it at 10 m; 1 with no correction.
    wind_factor: float = 1.0


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
    """The latest wind and today's strongest gust, estimated at the standard 10 m, with what the
    sensor measured beside them."""

    speed: float | None = None
    gust: float | None = None
    #: Degrees the wind blows from, clockwise from north.
    direction: float | None = None
    compass: str | None = None
    beaufort: int | None = None
    description: str | None = None
    max_gust_today: At | None = None
    #: Where the 10 m figures came from: sensor (measured, scaled by height_factor) or model (the
    #: weather model's, while the cups were too slow to turn); None when they are the measured
    #: wind itself.
    source: str | None = None
    #: What measured wind is multiplied by for the estimate; 1 with no correction set.
    height_factor: float = 1.0
    measured_speed: float | None = None
    measured_gust: float | None = None
    measured_max_gust_today: At | None = None


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


class Sky(BaseModel):
    """The sky at the station, from its weather model: what a station cannot measure."""

    #: The WMO weather code, and the same in words: "Overcast", "Light rain"...
    code: int
    description: str
    #: Whether it is day at the station, by the model; None when the model did not say.
    is_day: bool | None = None
    cloud_cover: float | None = None
    #: When the model's values are for.
    time: datetime


class AiringAdvice(BaseModel):
    """Whether opening this room's windows would dry it."""

    #: open, keep_closed or no_need.
    advice: str
    #: The room's humidity once its air had been replaced by outdoor air at room temperature.
    humidity_after: float | None = None
    #: How far the room's dew point is above the outdoor one.
    dew_point_difference: float


class Notice(BaseModel):
    """Something on a card that deserves attention."""

    #: warning, or good for news worth acting on (a good time to air).
    level: str
    #: What it is, in a few words; empty when the card says it already.
    text: str = ""


class HouseAiring(BaseModel):
    """Whether opening the windows would dry the house."""

    #: open, keep_closed or no_need.
    advice: str
    #: The rooms airing would dry, when the advice is to open.
    rooms: list[str] = Field(default_factory=list)
    #: The median room's humidity now, and once its air had been replaced by outdoor air.
    humidity: float
    humidity_after: float | None = None
    #: How far the median room's dew point is above the outdoor one.
    dew_point_difference: float


class Room(BaseModel):
    """One room's latest reading."""

    sensor: str
    name: str
    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    airing: AiringAdvice | None = None
    #: What is wrong with it: cold, hot, damp or dry.
    flags: list[str] = Field(default_factory=list)


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
    #: One line in words: the sky, temperature, wind, rain and the pressure trend.
    summary: str
    #: The sky from the weather model, when the station has one and its values are recent.
    sky: Sky | None = None
    outdoor: Outdoor | None = None
    wind: Wind | None = None
    rain: Rain | None = None
    pressure: Pressure | None = None
    sun: Sun | None = None
    airing: HouseAiring | None = None
    rooms: list[Room] = Field(default_factory=list)
    #: What deserves attention, by card: outdoor, wind, rain, pressure, sun, airing, rooms,
    #: sensors. A card missing from it is unremarkable.
    notices: dict[str, Notice] = Field(default_factory=dict)
    sensors: list[SensorHealth] = Field(default_factory=list)


class Series(BaseModel):
    """One metric of one sensor in time buckets."""

    metric: str
    #: The sensor, or rain gauge, the values are from; None for a station-wide metric.
    sensor: str | None
    name: str | None
    unit: str
    #: station, or model for the weather model's values for the same metric.
    source: str = "station"
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
    #: Whether the weather model has it, so /series can add the model's series.
    model: bool = False


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

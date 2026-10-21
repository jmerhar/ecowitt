"""Quantities the console does not send but the data is hard to use without.

Every sensor reporting both temperature and humidity -- indoor, outdoor, each channel, the air
quality combo -- gets its dew point, absolute humidity, mixing ratio and vapour pressure
deficit. Every indoor one also gets a comparison with the outdoor air, which is what answers
whether opening a window would dry that room, and the indoor ones together say whether the house
as a whole is being aired. Pressure is reduced to sea level from the
operator's altitude, and the console's own relative pressure is checked against it. Wind is
estimated at the standard 10 m from the anemometer's height (`windheight`).

Derivations are computed afresh for every report, never taken from fields the console may also
send: a console's dew point uses its own formula, and mixing the two in one series would put a
step in the data wherever the source changed.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Hashable, Iterable

from ecowitt.collector.ingest.staleness import StalenessTracker
from ecowitt.core import psychro, windheight
from ecowitt.core.preferences import Preferences
from ecowitt.core.readings import Reading
from ecowitt.core.units import Kind

#: Tables whose readings are not a sensor's measurements, and so do not count towards whether
#: that sensor has gone quiet: a battery voltage drifts on its own, and the console's uptime
#: changes on every report.
NOT_MEASUREMENTS = frozenset({"battery", "station", "unmapped"})


def derive(
    readings: Iterable[Reading],
    preferences: Preferences,
    tracker: StalenessTracker,
    *,
    station: str,
    timestamp: int,
    model_wind: windheight.ModelWind | None = None,
) -> list[Reading]:
    """Return the derived readings for one report's parsed readings.

    `model_wind` is the station's weather model's latest wind, which stands in for the 10 m
    estimate while the cups have stalled, unless the station's preferences turn that off.
    """
    readings = list(readings)
    climate = _climate(readings)
    pressure = {r.field: float(r.value) for r in readings if r.table == "pressure"}

    derived: list[Reading] = []
    for sensor, (temp, humidity) in climate.items():
        derived += _moisture(sensor, temp, humidity, pressure.get("abs"))

    outdoor = climate.get("outdoor")
    if outdoor is not None:
        indoors = {sensor: values for sensor, values in climate.items() if sensor != "outdoor"}
        in_rooms = {r.sensor for r in readings if r.table in ROOM_TABLES}
        rooms = {sensor: values for sensor, values in indoors.items() if sensor in in_rooms}
        derived += _ventilation(indoors, outdoor, _house_dewpoint(rooms))
        derived += _house(rooms, outdoor)

    if preferences.altitude_m is not None and "abs" in pressure:
        derived += _sea_level(pressure, preferences.altitude_m, climate)

    model = model_wind if preferences.wind_model_fallback else None
    derived += wind_10m(readings, preferences.wind_factor, model, timestamp)
    derived += _staleness(readings, tracker, station, timestamp)
    return derived


#: The wind fields estimated at 10 m, each under the same name in `wind_10m`. The day's strongest
#: gust is not among them: estimating a gust needs the wind it rose from (see wind_10m), which the
#: report does not give for that moment, and the day's strongest is the highest of the estimates.
WIND_FIELDS = ("speed", "gust", "speed_avg10m")


def wind_10m(
    readings: list[Reading],
    wind_factor: float,
    model: windheight.ModelWind | None,
    timestamp: int,
) -> list[Reading]:
    """The report's wind estimated at 10 m, and where the estimate came from.

    From the sensor: the speeds scaled by the height factor, and the gust by how far it rose above
    the speed, added to the scaled speed. Near the ground the turbulence that makes gusts barely
    changes with height while the mean wind grows, so a gust rises above the mean by about as much
    at 10 m as at the sensor; scaling the whole gust would scale the turbulence too, which a
    sheltered, low anemometer has plenty of. While the cups have stalled and the weather model
    has a recent value, the estimate is the model's, since scaling a stalled reading only scales
    zero.
    """
    wind = {
        r.field: float(r.value)
        for r in readings
        if r.table == "wind" and r.field in WIND_FIELDS and r.kind is Kind.SPEED
    }
    if "speed" not in wind:
        return []
    values = {field: value * wind_factor for field, value in wind.items()}
    if "gust" in wind:
        values["gust"] = values["speed"] + max(0.0, wind["gust"] - wind["speed"])
    source = "sensor"
    usable = model is not None and abs(timestamp - model.timestamp) <= windheight.MODEL_WITHIN_S
    if wind["speed"] < windheight.STALL_MS and usable:
        source = "model"
        values["speed"] = model.speed_ms  # type: ignore[union-attr]
        if "speed_avg10m" in values:
            values["speed_avg10m"] = model.speed_ms  # type: ignore[union-attr]
        if model.gust_ms is not None:  # type: ignore[union-attr]
            values["gust"] = model.gust_ms  # type: ignore[union-attr]
    table = windheight.TABLE
    return [
        *(Reading(table, field, Kind.SPEED, value) for field, value in values.items()),
        Reading(table, "source", Kind.TEXT, source),
    ]


#: The air temperatures derivations are made from, in °C: a margin beyond the lowest and highest
#: ever recorded.
PLAUSIBLE_TEMP_C = (-95.0, 75.0)


def _climate(readings: list[Reading]) -> dict[str, tuple[float, float]]:
    """Temperature and humidity for every sensor that reported both, with usable values.

    Humidity outside (0, 100] is dropped rather than derived from: zero makes the dew point's
    logarithm undefined, and either end means a faulty sensor whose derivations would only
    mislead. Temperature outside the range air on Earth reaches is dropped for the same reason,
    and because the formulas overflow or divide by zero far enough beyond it.
    """
    temps: dict[str, float] = {}
    humidities: dict[str, float] = {}
    for r in readings:
        if r.sensor is None or r.table in NOT_MEASUREMENTS:
            continue
        if r.field == "temp" and r.kind is Kind.TEMPERATURE:
            temps[r.sensor] = float(r.value)
        elif r.field == "humidity" and r.kind is Kind.HUMIDITY:
            humidities[r.sensor] = float(r.value)
    return {
        sensor: (temps[sensor], humidity)
        for sensor, humidity in humidities.items()
        if sensor in temps
        and 0 < humidity <= 100
        and PLAUSIBLE_TEMP_C[0] <= temps[sensor] <= PLAUSIBLE_TEMP_C[1]
    }


def _moisture(
    sensor: str, temp: float, humidity: float, pressure_hpa: float | None
) -> list[Reading]:
    """Dew point, absolute humidity, mixing ratio and vapour pressure deficit for one sensor."""
    values = [
        ("dewpoint", Kind.TEMPERATURE, psychro.dew_point(temp, humidity)),
        ("abs_humidity", Kind.ABSOLUTE_HUMIDITY, psychro.absolute_humidity(temp, humidity)),
        ("vpd", Kind.PRESSURE, psychro.vapour_pressure_deficit(temp, humidity)),
    ]
    if pressure_hpa is not None:
        ratio = psychro.mixing_ratio(temp, humidity, pressure_hpa)
        values.append(("mixing_ratio", Kind.MIXING_RATIO, ratio))
    return [_per_sensor("derived", sensor, field, kind, value) for field, kind, value in values]


#: The tables whose sensors are the house's rooms, as the dashboard and Grafana count them. The
#: air quality combo also reads humidity, but shares a room another sensor already covers.
ROOM_TABLES = frozenset({"indoor", "channel"})
#: The fewest rooms whose agreement says anything about the house: two can agree by chance.
HOUSE_MIN_ROOMS = 3
#: The house reads as aired when at least this share of its rooms have a dew point within
#: AIRED_DEWPOINT_C of the outdoor one -- not all: a kitchen in use or an occupied bedroom keeps
#: some moisture of its own with the windows open...
AIRED_SHARE = 2 / 3
#: ...the rooms' median dew point is within this of the outdoor dew point too...
AIRED_DEWPOINT_C = 0.7
#: ...and their median temperature within this of the outdoor temperature.
AIRED_TEMP_C = 2.5


def _house_dewpoint(rooms: dict[str, tuple[float, float]]) -> float | None:
    """The rooms' median dew point, when there are enough rooms for it to describe the house."""
    if len(rooms) < HOUSE_MIN_ROOMS:
        return None
    return statistics.median(psychro.dew_point(t, h) for t, h in rooms.values())


def _ventilation(
    sensors: dict[str, tuple[float, float]], outdoor: tuple[float, float], house: float | None
) -> list[Reading]:
    """What exchanging each room's air for the outdoor air would do, and how close it is now.

    A positive dew-point difference means the outdoor air is drier, so ventilating removes
    moisture. The predicted humidity is what the room would read once its air had been replaced
    and brought back to its present temperature -- the number that says whether it is worth it.
    The temperature difference, and the dew point's difference from the house's median, say how
    far the room has already gone towards the outdoor air and away from the other rooms, which
    is what a room aired on its own looks like.
    """
    outdoor_temp, outdoor_humidity = outdoor
    outdoor_dewpoint = psychro.dew_point(outdoor_temp, outdoor_humidity)
    outdoor_vapour = psychro.vapour_pressure(outdoor_temp, outdoor_humidity)
    dewpoints = {sensor: psychro.dew_point(t, h) for sensor, (t, h) in sensors.items()}

    readings = []
    for sensor, (temp, _) in sensors.items():
        values = [
            ("dewpoint_delta", Kind.TEMPERATURE_DELTA, dewpoints[sensor] - outdoor_dewpoint),
            ("predicted_humidity", Kind.HUMIDITY, psychro.humidity_at(outdoor_vapour, temp)),
            ("temp_delta", Kind.TEMPERATURE_DELTA, temp - outdoor_temp),
        ]
        if house is not None:
            values.append(
                ("house_dewpoint_delta", Kind.TEMPERATURE_DELTA, dewpoints[sensor] - house)
            )
        readings += [_per_sensor("ventilation", sensor, f, k, v) for f, k, v in values]
    return readings


def _house(rooms: dict[str, tuple[float, float]], outdoor: tuple[float, float]) -> list[Reading]:
    """The house's median room against the outdoor air, and whether the house is being aired.

    The medians -- humidity now and after airing, dew point and temperature against outdoors --
    are what the dashboard and the alert rules judge the house by. Whether it is aired, the share
    of rooms sharing the outdoor air that decides it, and how far apart the rooms' dew points lie
    need HOUSE_MIN_ROOMS rooms.

    A closed house keeps a moisture level per room -- a bathroom after a shower, a bedroom
    overnight -- and, with people living in it, sits above the outdoor dew point. Air flowing
    through open windows makes most rooms one body of air with the outdoors: their dew points
    converge on the outdoor one, while a room in use may keep a little moisture of its own. The
    temperature condition keeps out a still night, when a closed, warmer house can meet the
    outdoor dew point by chance. A single room aired behind a closed door leaves the others as
    they were, so it does not count here; its own `ventilation` row shows it.
    """
    if not rooms:
        return []
    outdoor_vapour = psychro.vapour_pressure(*outdoor)
    dewpoints = [psychro.dew_point(t, h) for t, h in rooms.values()]
    outdoor_dewpoint = psychro.dew_point(*outdoor)
    dewpoint_delta = statistics.median(dewpoints) - outdoor_dewpoint
    temp_delta = statistics.median(t for t, _ in rooms.values()) - outdoor[0]
    readings = [
        Reading("house", "rooms", Kind.COUNT, float(len(rooms))),
        Reading(
            "house", "humidity", Kind.HUMIDITY, statistics.median(h for _, h in rooms.values())
        ),
        Reading(
            "house",
            "predicted_humidity",
            Kind.HUMIDITY,
            statistics.median(psychro.humidity_at(outdoor_vapour, t) for t, _ in rooms.values()),
        ),
        Reading("house", "dewpoint_delta", Kind.TEMPERATURE_DELTA, dewpoint_delta),
        Reading("house", "temp_delta", Kind.TEMPERATURE_DELTA, temp_delta),
    ]
    if len(rooms) >= HOUSE_MIN_ROOMS:
        spread = max(dewpoints) - min(dewpoints)
        near = sum(1 for d in dewpoints if abs(d - outdoor_dewpoint) <= AIRED_DEWPOINT_C)
        share = near / len(dewpoints)
        aired = (
            share >= AIRED_SHARE
            and abs(dewpoint_delta) <= AIRED_DEWPOINT_C
            and abs(temp_delta) <= AIRED_TEMP_C
        )
        readings += [
            Reading("house", "dewpoint_spread", Kind.TEMPERATURE_DELTA, spread),
            Reading("house", "outdoor_share", Kind.PERCENT, 100.0 * share),
            Reading("house", "aired", Kind.FLAG, aired),
        ]
    return readings


def _sea_level(
    pressure: dict[str, float], altitude_m: float, climate: dict[str, tuple[float, float]]
) -> list[Reading]:
    """Sea-level pressure, and the error in the console's own relative-pressure offset.

    The reduction depends on the temperature of the air column below the station -- by about
    0.1 hPa per degree at 250 m -- so it uses the outdoor sensor when there is one and the
    standard atmosphere otherwise, and stores which. Indoor temperature is deliberately not a
    fallback: a heated house reads 21 °C all winter, which says nothing about the air outside.

    The calibration error is measured against a reduction at the standard atmosphere's
    temperature instead, whatever the outdoor sensor says. A console's offset is a constant,
    so the best it can do is match a constant-temperature reduction; comparing it with the
    temperature-dependent one would show a seasonal swing of a few hectopascals that no
    offset could remove, and a warning built on it would come and go with the weather.
    """
    standard = psychro.standard_temperature(altitude_m)
    if "outdoor" in climate:
        source, temp = "outdoor", climate["outdoor"][0]
    else:
        source, temp = "standard", standard

    sea = psychro.sea_level_pressure(pressure["abs"], altitude_m, temp)
    values: list[Reading] = [
        Reading("pressure", "sea", Kind.PRESSURE, sea, sensor="pressure"),
        Reading("pressure", "sea_temp_source", Kind.TEXT, source, sensor="pressure"),
    ]
    if "rel" in pressure:
        reference = psychro.sea_level_pressure(pressure["abs"], altitude_m, standard)
        error = pressure["rel"] - reference
        values.append(Reading("pressure", "rel_error", Kind.PRESSURE, error, sensor="pressure"))
    return values


def _staleness(
    readings: list[Reading], tracker: StalenessTracker, station: str, timestamp: int
) -> list[Reading]:
    """Seconds each sensor's measurements have gone unchanged."""
    by_sensor: dict[str, list[Hashable]] = defaultdict(list)
    for r in readings:
        if r.sensor is not None and r.table not in NOT_MEASUREMENTS:
            by_sensor[r.sensor].append((r.table, r.field, r.tags, r.value))
    return [
        _per_sensor(
            "derived",
            sensor,
            "unchanged",
            Kind.DURATION,
            float(tracker.observe((station, sensor), _signature(values), timestamp)),
        )
        for sensor, values in sorted(by_sensor.items())
    ]


def _signature(values: list[Hashable]) -> tuple[Hashable, ...]:
    """An order-independent fingerprint of a sensor's values.

    Sorted by representation rather than by value, because a payload may carry two spellings
    of one field -- `tempinf` and `indoortempf` -- and comparing a float with a string would
    raise.
    """
    return tuple(sorted(values, key=repr))


def _per_sensor(table: str, sensor: str, field: str, kind: Kind, value: float) -> Reading:
    """A derived reading for the sensor it describes; its tags are added when written."""
    return Reading(table, field, kind, value, sensor=sensor)

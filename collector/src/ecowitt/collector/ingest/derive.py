"""Quantities the console does not send but the data is hard to use without.

Every sensor reporting both temperature and humidity -- indoor, outdoor, each channel, the air
quality combo -- gets its dew point, absolute humidity, mixing ratio and vapour pressure
deficit. Every indoor one also gets a comparison with the outdoor air, which is what answers
whether opening a window would dry that room. Pressure is reduced to sea level from the
operator's altitude, and the console's own relative pressure is checked against it.

Derivations are computed afresh for every report, never taken from fields the console may also
send: a console's dew point uses its own formula, and mixing the two in one series would put a
step in the data wherever the source changed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable

from ecowitt.collector import psychro
from ecowitt.collector.ingest.staleness import StalenessTracker
from ecowitt.collector.preferences import Preferences
from ecowitt.collector.readings import Reading
from ecowitt.collector.units import Kind

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
) -> list[Reading]:
    """Return the derived readings for one report's parsed readings."""
    readings = list(readings)
    climate = _climate(readings)
    pressure = {r.field: float(r.value) for r in readings if r.table == "pressure"}

    derived: list[Reading] = []
    for sensor, (temp, humidity) in climate.items():
        derived += _moisture(sensor, temp, humidity, pressure.get("abs"))

    outdoor = climate.get("outdoor")
    if outdoor is not None:
        for sensor, (temp, humidity) in climate.items():
            if sensor != "outdoor":
                derived += _ventilation(sensor, temp, humidity, *outdoor)

    if preferences.altitude_m is not None and "abs" in pressure:
        derived += _sea_level(pressure, preferences.altitude_m, climate)

    derived += _staleness(readings, tracker, station, timestamp)
    return derived


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


def _ventilation(
    sensor: str, temp: float, humidity: float, outdoor_temp: float, outdoor_humidity: float
) -> list[Reading]:
    """What exchanging this room's air for the outdoor air would do to its humidity.

    A positive dew-point difference means the outdoor air is drier, so ventilating removes
    moisture. The predicted humidity is what the room would read once its air had been replaced
    and brought back to its present temperature -- the number that says whether it is worth it.
    """
    delta = psychro.dew_point(temp, humidity) - psychro.dew_point(outdoor_temp, outdoor_humidity)
    outdoor_vapour = psychro.vapour_pressure(outdoor_temp, outdoor_humidity)
    predicted = psychro.humidity_at(outdoor_vapour, temp)
    return [
        _per_sensor("ventilation", sensor, "dewpoint_delta", Kind.TEMPERATURE_DELTA, delta),
        _per_sensor("ventilation", sensor, "predicted_humidity", Kind.HUMIDITY, predicted),
    ]


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

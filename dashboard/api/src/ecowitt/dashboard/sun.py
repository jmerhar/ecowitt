"""Sunrise, solar noon and sunset for a place and a day, from NOAA's solar calculator.

The equations are those of NOAA's spreadsheet calculator (after Meeus), evaluated once at the
day's approximate solar noon, which keeps them within a minute or so of an almanac at the
latitudes people live at. Sunrise and sunset are when the sun's upper edge crosses the horizon,
allowing for refraction: a centre 0.833° below it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

#: The sun's centre below the horizon at sunrise and sunset: refraction plus its radius.
HORIZON_DEG = 90.833
#: Julian day at the start of 1 January of year 1 (proleptic Gregorian), in date.toordinal terms.
JULIAN_OFFSET = 1721424.5


@dataclass(frozen=True)
class SunTimes:
    """One local day's sun, in UTC. Sunrise and sunset are None in polar day or night."""

    noon: datetime
    sunrise: datetime | None
    sunset: datetime | None
    #: "day" when the sun never sets, "night" when it never rises, None otherwise.
    polar: str | None = None

    @property
    def daylight(self) -> timedelta:
        """How long the sun is up."""
        if self.sunrise is not None and self.sunset is not None:
            return self.sunset - self.sunrise
        return timedelta(days=1) if self.polar == "day" else timedelta(0)


def sun_times(day: date, latitude: float, longitude: float) -> SunTimes:
    """The sun on `day` at a place, east longitudes positive. `day` is the place's own date."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    # The place's solar noon falls about four minutes earlier per degree east of Greenwich.
    approximate_noon = 720 - 4 * longitude
    julian_day = day.toordinal() + JULIAN_OFFSET + approximate_noon / 1440
    declination, equation_of_time = _solar(julian_day)

    noon_minutes = 720 - 4 * longitude - equation_of_time
    noon = midnight + timedelta(minutes=noon_minutes)
    lat = math.radians(latitude)
    cosine = math.cos(math.radians(HORIZON_DEG)) / (
        math.cos(lat) * math.cos(declination)
    ) - math.tan(lat) * math.tan(declination)
    if cosine > 1:
        return SunTimes(noon, None, None, "night")
    if cosine < -1:
        return SunTimes(noon, None, None, "day")
    half_day = 4 * math.degrees(math.acos(cosine))
    return SunTimes(
        noon,
        midnight + timedelta(minutes=noon_minutes - half_day),
        midnight + timedelta(minutes=noon_minutes + half_day),
    )


def _solar(julian_day: float) -> tuple[float, float]:
    """The sun's declination (radians) and the equation of time (minutes) at a Julian day."""
    t = (julian_day - 2451545) / 36525
    mean_longitude = math.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    anomaly = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (
        math.sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * anomaly) * (0.019993 - 0.000101 * t)
        + math.sin(3 * anomaly) * 0.000289
    )
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = math.radians(
        math.degrees(mean_longitude) + centre - 0.00569 - 0.00478 * math.sin(omega)
    )
    mean_obliquity = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliquity = math.radians(mean_obliquity + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(apparent))
    y = math.tan(obliquity / 2) ** 2
    equation = (
        y * math.sin(2 * mean_longitude)
        - 2 * eccentricity * math.sin(anomaly)
        + 4 * eccentricity * y * math.sin(anomaly) * math.cos(2 * mean_longitude)
        - 0.5 * y * y * math.sin(4 * mean_longitude)
        - 1.25 * eccentricity * eccentricity * math.sin(2 * anomaly)
    )
    return declination, 4 * math.degrees(equation)

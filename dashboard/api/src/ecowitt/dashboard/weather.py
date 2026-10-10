"""What the readings mean to someone looking at them: words and judgements, from metric values.

Every function takes metric units (°C, km/h, hPa, %) and is pure, so each is tested against
published tables rather than against this code.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from enum import Enum

COMPASS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)  # fmt: skip

#: The Beaufort scale: the lowest speed of each force from 1 to 12, in m/s, and every force's
#: name. Speeds are the WMO's, rounded to a tenth.
BEAUFORT_FROM_MS = (0.5, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)
BEAUFORT_NAMES = (
    "Calm",
    "Light air",
    "Light breeze",
    "Gentle breeze",
    "Moderate breeze",
    "Fresh breeze",
    "Strong breeze",
    "Near gale",
    "Gale",
    "Strong gale",
    "Storm",
    "Violent storm",
    "Hurricane force",
)

#: A room is worth airing when the outdoor air's dew point is this much lower than the room's...
AIRING_DEWPOINT_DELTA_C = 2.0
#: ...and the room is at least this humid. The Good time to air alert rule in
#: grafana/alerts.json uses the same two numbers.
AIRING_HUMIDITY_PCT = 65.0
#: A room this humid whose dew point is less than this much above the outdoor one gains nothing
#: from airing: the air brought in holds about as much moisture as the air it replaces. The
#: Close the windows alert rule applies it to the house as a whole.
CLOSING_DEWPOINT_DELTA_C = 1.0

#: A sensor whose values have not changed for this long is reported as not updating, as the
#: Sensor not updating alert rule does.
STALE_AFTER_S = 3 * 3600


def compass(degrees: float) -> str:
    """The 16-point compass direction a wind blowing from `degrees` comes from."""
    return COMPASS[round(degrees % 360 / 22.5) % 16]


def beaufort(speed_kmh: float) -> int:
    """The Beaufort force of a wind speed."""
    return bisect_right(BEAUFORT_FROM_MS, speed_kmh / 3.6)


def wind_chill(temp_c: float, speed_kmh: float) -> float:
    """The North American wind chill index (2001), for 10 m wind speeds."""
    power = speed_kmh**0.16
    return 13.12 + 0.6215 * temp_c - 11.37 * power + 0.3965 * temp_c * power


def heat_index(temp_c: float, humidity_pct: float) -> float:
    """The US National Weather Service heat index: Rothfusz's regression and its adjustments."""
    t = temp_c * 9 / 5 + 32
    rh = humidity_pct
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:
        return (simple - 32) * 5 / 9
    index = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )
    if rh < 13 and 80 <= t <= 112:
        index -= (13 - rh) / 4 * math.sqrt((17 - abs(t - 95)) / 17)
    elif rh > 85 and 80 <= t <= 87:
        index += (rh - 85) / 10 * (87 - t) / 5
    return (index - 32) * 5 / 9


def feels_like(temp_c: float, humidity_pct: float | None, speed_kmh: float | None) -> float:
    """What the air feels like, the way the US National Weather Service reports it.

    Wind chill when it is 10 °C or colder with wind of at least 4.8 km/h; the heat index when it
    is 26.7 °C (80 °F) or warmer; otherwise the air temperature itself.
    """
    if temp_c <= 10 and speed_kmh is not None and speed_kmh >= 4.8:
        return wind_chill(temp_c, speed_kmh)
    if temp_c >= 26.7 and humidity_pct is not None:
        return max(temp_c, heat_index(temp_c, humidity_pct))
    return temp_c


def tendency(change_hpa: float) -> str:
    """The words for a three-hour pressure change, in the Met Office's terms."""
    size = abs(change_hpa)
    if size < 0.1:
        return "steady"
    direction = "rising" if change_hpa > 0 else "falling"
    if size <= 1.5:
        return f"{direction} slowly"
    if size <= 3.5:
        return direction
    if size <= 6.0:
        return f"{direction} quickly"
    return f"{direction} very rapidly"


class Airing(Enum):
    """Whether opening a room's windows would make it drier."""

    #: Damp, and the outdoor air is markedly drier: airing would help.
    OPEN = "open"
    #: Damp, and the outdoor air holds about as much moisture as the room's, or more: airing
    #: would not dry it.
    KEEP_CLOSED = "keep_closed"
    #: Neither: dry enough already, or too little difference to matter.
    NO_NEED = "no_need"


def airing(humidity_pct: float, dewpoint_delta_c: float) -> Airing:
    """Advice for one room, from its humidity and how far its dew point is above outdoors'."""
    if humidity_pct < AIRING_HUMIDITY_PCT:
        return Airing.NO_NEED
    if dewpoint_delta_c > AIRING_DEWPOINT_DELTA_C:
        return Airing.OPEN
    if dewpoint_delta_c < CLOSING_DEWPOINT_DELTA_C:
        return Airing.KEEP_CLOSED
    return Airing.NO_NEED

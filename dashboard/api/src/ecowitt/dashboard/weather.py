"""What the readings mean to someone looking at them: words and judgements, from metric values.

Every function takes metric units (°C, km/h, hPa, %) and is pure, so each is tested against
published tables rather than against this code.
"""

from __future__ import annotations

import math
import statistics
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
#: Airing is advised against only when it would do harm: leave a room at least
#: AIRING_HUMIDITY_PCT humid and this many points damper than it is. Humidity sensors are good to
#: a few points, and the humidity after airing adds the outdoor sensor's error to the room's, so
#: a smaller difference says nothing. The Close the windows alert rule applies the same to the
#: house's median room, and the page treats a smaller change either way as none.
DAMPER_BY_PCT = 5.0

# What deserves a visitor's attention. Each threshold with an alert rule in grafana/alerts.json is
# that rule's, and a test holds them together.
#: Strong wind: a gust above this, in km/h.
STRONG_GUST_KMH = 60.0
#: Heavy rain: a rate above this, in mm/h.
HEAVY_RAIN_MM_H = 10.0
#: Pressure falling fast: more than this many hPa in three hours.
FAST_FALL_HPA = 3.0
#: A room too cold or too hot, in °C.
ROOM_COLD_C = 8.0
ROOM_HOT_C = 32.0
#: A damp room, in % humidity: the Damp room rule's level, though not its six hours.
ROOM_DAMP_PCT = 70.0
#: A room dry enough to be uncomfortable, in %.
ROOM_DRY_PCT = 30.0
#: Cold enough outdoors for frost on a clear night, in °C: the ground cools below the air, so frost
#: forms while the air at sensor height is still a few degrees above zero.
COLD_C = 5.0
#: Outdoor air humid enough for fog and condensation, or dry enough for fire risk, in %.
HUMID_AIR_PCT = 95.0
DRY_AIR_PCT = 25.0
#: Heat: a feels-like temperature at or above the US National Weather Service's "extreme
#: caution" level for the heat index (90 °F), in °C.
HEAT_FEELS_C = 32.0
#: The WHO's "very high" UV index.
UV_VERY_HIGH = 8.0

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


def airing(humidity_pct: float, dewpoint_delta_c: float, after_pct: float | None) -> Airing:
    """Advice for one room, from its humidity, how far its dew point is above outdoors', and
    the humidity it would settle at once aired (None when that is unknown)."""
    if humidity_pct >= AIRING_HUMIDITY_PCT and dewpoint_delta_c > AIRING_DEWPOINT_DELTA_C:
        return Airing.OPEN
    if _dampens(humidity_pct, after_pct):
        return Airing.KEEP_CLOSED
    return Airing.NO_NEED


def house_airing(rooms: list[tuple[float, float, float | None]]) -> Airing:
    """Advice for the whole house, from each room's humidity, dew-point difference and humidity
    once aired.

    Air when any room would be dried by it. Keep the windows closed only when airing would leave
    the median room damp and damper than it is: when it would merely not help, or dampen dry
    rooms a little, nothing is lost by opening them.
    """
    if any(airing(*room) is Airing.OPEN for room in rooms):
        return Airing.OPEN
    afters = [after for _, _, after in rooms if after is not None]
    if afters and _dampens(statistics.median(h for h, _, _ in rooms), statistics.median(afters)):
        return Airing.KEEP_CLOSED
    return Airing.NO_NEED


def _dampens(humidity_pct: float, after_pct: float | None) -> bool:
    """Whether airing would leave a room damp, and damper than it is."""
    return (
        after_pct is not None
        and after_pct >= AIRING_HUMIDITY_PCT
        and after_pct >= humidity_pct + DAMPER_BY_PCT
    )


def room_flags(temp_c: float | None, humidity_pct: float | None) -> list[str]:
    """What is wrong with a room, if anything: cold, hot, damp or dry."""
    flags = []
    if temp_c is not None and temp_c < ROOM_COLD_C:
        flags.append("cold")
    if temp_c is not None and temp_c > ROOM_HOT_C:
        flags.append("hot")
    if humidity_pct is not None and humidity_pct >= ROOM_DAMP_PCT:
        flags.append("damp")
    if humidity_pct is not None and humidity_pct <= ROOM_DRY_PCT:
        flags.append("dry")
    return flags

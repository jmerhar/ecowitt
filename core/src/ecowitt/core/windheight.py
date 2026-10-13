"""Wind as it would be measured at the standard 10 m, from an anemometer mounted lower.

Wind slows towards the ground, by how much depending on how rough the surroundings are. Forecasts,
weather models and official stations all give wind at 10 m above open ground, so a garden
anemometer at 2 m reads perhaps half of it. The collector stores an estimate at 10 m beside every
measured wind (the `wind_10m` table), and the dashboards lead with it.

The estimate scales the measured wind by the neutral logarithmic wind profile,
ln(10 / z0) / ln(h / z0), where h is the anemometer's height and z0 the roughness length of its
surroundings. That holds in a breeze and in daylight, when the air is well mixed. In still nights
the air near the ground decouples from the wind above, and cups below their starting speed stop
turning altogether: no factor recovers wind the sensor never felt. So while the cups have
stalled, and the station has a weather model, the estimate is the model's 10 m wind instead, and
the row says so in `source`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TABLE = "wind_10m"
REFERENCE_HEIGHT_M = 10.0

#: Below this measured speed, in m/s, cup anemometers stop turning: a reading under it says the
#: wind was too light to measure, not that there was none.
STALL_MS = 1.0

#: How long a weather model's wind stands in for stalled cups: its values are 15 minutes apart.
MODEL_WITHIN_S = 30 * 60

#: A station's choice that applies no correction.
NONE = "none"


@dataclass(frozen=True)
class Surroundings:
    """A kind of surroundings, in words, and its roughness length in metres."""

    label: str
    roughness_m: float


SURROUNDINGS: dict[str, Surroundings] = {
    "open": Surroundings("Open: fields, open lawn, or a rooftop with nothing higher nearby", 0.1),
    "gardens": Surroundings("Gardens: hedges, scattered houses and trees", 0.3),
    "sheltered": Surroundings("Sheltered: buildings and trees close by", 0.5),
}

#: The heights an anemometer may be given as, in metres: above every roughness length here, so
#: the profile's logarithm stays positive.
MIN_HEIGHT_M = 1.0
MAX_HEIGHT_M = 200.0


def factor(height_m: float | None, surroundings: str) -> float:
    """What measured wind is multiplied by to estimate it at 10 m; 1 with no correction chosen."""
    kind = SURROUNDINGS.get(surroundings)
    if kind is None or height_m is None:
        return 1.0
    z0 = kind.roughness_m
    return math.log(REFERENCE_HEIGHT_M / z0) / math.log(height_m / z0)


@dataclass(frozen=True)
class ModelWind:
    """A weather model's 10 m wind at one time, in m/s."""

    timestamp: int
    speed_ms: float
    gust_ms: float | None

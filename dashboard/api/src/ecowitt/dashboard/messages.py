"""The words the API puts beside its codes: every message a notice, the summary or a pressure
trend can say, in one place, so that each code is worded once."""

from __future__ import annotations

from ecowitt.dashboard.models import NoticeCode
from ecowitt.dashboard.weather import Tendency

#: Each notice, with `{value}` and `{time}` where it names them.
NOTICES: dict[NoticeCode, str] = {
    NoticeCode.COLD: "Cold: frost is possible on clear nights.",
    NoticeCode.HEAT: "Heat: take care outdoors.",
    NoticeCode.HUMID_AIR: "Very humid outside: fog and condensation likely.",
    NoticeCode.DRY_AIR: "Very dry air: fire risk.",
    NoticeCode.STRONG_GUSTS: "Strong gusts.",
    NoticeCode.HEAVY_RAIN: "Heavy rain.",
    NoticeCode.PRESSURE_FALLING_FAST: "Falling fast: a front or a storm is likely.",
    NoticeCode.UV_VERY_HIGH: "Very high UV: seek shade at midday.",
    NoticeCode.RAIN_SOON: "Rain likely within the hour.",
    NoticeCode.RAIN_FROM: "Rain likely from {time}.",
    NoticeCode.FROST_FORECAST: "Down to {value} at {time}: frost possible.",
    NoticeCode.HEAT_FORECAST: "Up to {value} at {time}.",
    NoticeCode.GUSTS_FORECAST: "Gusts to {value} at {time}.",
    NoticeCode.ROOM_FLAG: "{flag}: {rooms}.",
}

#: A room's flags, as a room_flag notice names them.
ROOM_FLAGS = {"cold": "Cold", "hot": "Hot", "damp": "Damp", "dry": "Dry"}

#: A time in a notice: later today, or tomorrow, since a notice looks a day ahead at most.
TODAY = "{clock}"
TOMORROW = "tomorrow {clock}"

TENDENCIES: dict[Tendency, str] = {
    Tendency.STEADY: "steady",
    Tendency.RISING_SLOWLY: "rising slowly",
    Tendency.RISING: "rising",
    Tendency.RISING_QUICKLY: "rising quickly",
    Tendency.RISING_VERY_RAPIDLY: "rising very rapidly",
    Tendency.FALLING_SLOWLY: "falling slowly",
    Tendency.FALLING: "falling",
    Tendency.FALLING_QUICKLY: "falling quickly",
    Tendency.FALLING_VERY_RAPIDLY: "falling very rapidly",
}

#: The summary's parts. Each ends without a full stop; the summary adds them.
FEELS_LIKE = "{temperature}, feels like {feels}"
WIND_FROM = "{description} from the {compass}"
RAINING = "Raining, {rate}"
PRESSURE = "Pressure {tendency}"


def notice(code: NoticeCode, **params: str) -> str:
    """A notice in words, its named values already formatted; any it does not name are left
    out."""
    return NOTICES[code].format(**params)

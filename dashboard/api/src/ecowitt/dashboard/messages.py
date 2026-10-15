"""The words the API puts beside its codes, in the language an answer is in.

Every message is written here, or in the table it describes, in English. The gettext template the
catalogues are kept against is built from these tables (`template`), so a message added to one
of them is a message the catalogues must translate.
"""

from __future__ import annotations

from datetime import datetime

from babel.messages.catalog import Catalog

from ecowitt.core import weathermodel
from ecowitt.dashboard import weather
from ecowitt.dashboard.catalogue import METRICS
from ecowitt.dashboard.i18n import Language
from ecowitt.dashboard.models import NoticeCode
from ecowitt.dashboard.weather import Tendency

#: Each notice that names no time, with `{flag}` and `{rooms}` where it names them.
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
    NoticeCode.ROOM_FLAG: "{flag}: {rooms}.",
}

#: Each notice that names a time of day, `{clock}`, later today and tomorrow (a notice looks a day
#: ahead at most), with `{value}` where it names one.
NOTICES_AT: dict[NoticeCode, tuple[str, str]] = {
    NoticeCode.RAIN_FROM: ("Rain likely from {clock}.", "Rain likely from tomorrow {clock}."),
    NoticeCode.FROST_FORECAST: (
        "Down to {value} at {clock}: frost possible.",
        "Down to {value} at tomorrow {clock}: frost possible.",
    ),
    NoticeCode.HEAT_FORECAST: ("Up to {value} at {clock}.", "Up to {value} at tomorrow {clock}."),
    NoticeCode.GUSTS_FORECAST: (
        "Gusts to {value} at {clock}.",
        "Gusts to {value} at tomorrow {clock}.",
    ),
}

#: A room's flags, as a room_flag notice names them.
ROOM_FLAGS = {"cold": "Cold", "hot": "Hot", "damp": "Damp", "dry": "Dry"}

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
SUMMARY = {
    "feels_like": "{temperature}, feels like {feels}",
    "wind_from": "{description} from the {compass}",
    "raining": "Raining, {rate}",
    "pressure": "Pressure {tendency}",
}

#: Names for the sensors a console has one of, which nobody names on the setup page.
SENSOR_NAMES = {
    "indoor": "Indoor",
    "outdoor": "Outdoor",
    "pressure": "Barometer",
    "rain": "Rain gauge",
    "solar": "Light sensor",
    "wind": "Wind sensor",
}

#: A weather code the table does not know.
UNKNOWN_SKY = "Weather code {code}"

#: What the page is, as a home screen's install dialog describes it.
APP_DESCRIPTION = "Current conditions and history from the weather station"

# Each table's gettext context: the same English word can need different translations in two of
# them, and the context tells a translator what the message is.
NOTICE, ROOM_FLAG, TENDENCY, SUMMARY_PART = "notice", "room flag", "pressure tendency", "summary"
APP = "home-screen app"
COMPASS, BEAUFORT, SKY, MODEL, METRIC, SENSOR = (
    "compass point",
    "Beaufort force",
    "sky",
    "weather model",
    "chart metric",
    "sensor",
)

#: What a translator is told about a message naming a time of day.
AT_HOUR = (
    "{clock} is a time of day, 00:00 to 23:59. The plural forms are chosen by its hour, for a "
    "language whose words agree with it."
)


def notice(language: Language, code: NoticeCode, **params: str) -> str:
    """A notice that names no time, its values already formatted; any it does not name are
    left out."""
    return language.text(NOTICE, NOTICES[code]).format(**params)


def notice_at(
    language: Language, code: NoticeCode, local: datetime, tomorrow: bool, **params: str
) -> str:
    """A notice that names a time of day, `local` in the station's time."""
    message = NOTICES_AT[code][1 if tomorrow else 0]
    words = language.text_at_hour(NOTICE, message, local.hour)
    return words.format(clock=f"{local:%H:%M}", **params)


def room_flag(language: Language, flag: str) -> str:
    """A room's flag, as a notice names it."""
    return language.text(ROOM_FLAG, ROOM_FLAGS[flag])


def tendency(language: Language, value: Tendency) -> str:
    """A pressure tendency in words."""
    return language.text(TENDENCY, TENDENCIES[value])


def summary(language: Language, part: str, **params: str) -> str:
    """One of the summary's composed parts."""
    return language.text(SUMMARY_PART, SUMMARY[part]).format(**params)


def compass(language: Language, degrees: float) -> str:
    """The compass point a wind blowing from `degrees` comes from, as this language writes it."""
    return language.text(COMPASS, weather.compass(degrees))


def beaufort(language: Language, force: int) -> str:
    """A Beaufort force's name."""
    return language.text(BEAUFORT, weather.BEAUFORT_NAMES[force])


def sky(language: Language, code: int) -> str:
    """A WMO weather code in words, or its number for one the table does not know."""
    known = weathermodel.WEATHER_CODES.get(code)
    if known is None:
        return language.text(SKY, UNKNOWN_SKY).format(code=code)
    return language.text(SKY, known)


def model(language: Language, model_id: str) -> str:
    """A weather model's name, or its id for one the setup form does not offer."""
    label = weathermodel.MODELS.get(model_id)
    return model_id if label is None else language.text(MODEL, label)


def metric(language: Language, label: str) -> str:
    """A chart metric's label."""
    return language.text(METRIC, label)


def sensor(language: Language, sensor_id: str) -> str:
    """A sensor's name when nobody has named it: its kind's, or its id."""
    name = SENSOR_NAMES.get(sensor_id)
    return sensor_id if name is None else language.text(SENSOR, name)


def app_description(language: Language) -> str:
    """The page's description, for its web app manifest."""
    return language.text(APP, APP_DESCRIPTION)


def template() -> Catalog:
    """The gettext template: every message above, with its context."""
    catalog = Catalog(domain="messages", project="Ecowitt Server dashboard")
    tables: list[tuple[str, list[str]]] = [
        (NOTICE, list(NOTICES.values())),
        (ROOM_FLAG, list(ROOM_FLAGS.values())),
        (TENDENCY, list(TENDENCIES.values())),
        (SUMMARY_PART, list(SUMMARY.values())),
        (COMPASS, list(weather.COMPASS)),
        (BEAUFORT, list(weather.BEAUFORT_NAMES)),
        (SKY, [*weathermodel.WEATHER_CODES.values(), UNKNOWN_SKY]),
        (MODEL, list(weathermodel.MODELS.values())),
        (METRIC, list(dict.fromkeys(m.label for m in METRICS.values()))),
        (SENSOR, list(SENSOR_NAMES.values())),
        (APP, [APP_DESCRIPTION]),
    ]
    # Babel marks a message with placeholders python-brace-format itself, so gettext's tools
    # check that a translation keeps them.
    for context, messages in tables:
        for message in messages:
            catalog.add(message, context=context)
    for pair in NOTICES_AT.values():
        for message in pair:
            catalog.add((message, message), context=NOTICE, auto_comments=[AT_HOUR])
    return catalog

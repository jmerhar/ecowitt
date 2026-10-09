"""Which report field means what: the table every recognised key is stored under.

This is data rather than code so that supporting new hardware is a row, not a branch. The
families and their units follow the field map Home Assistant's `aioecowitt` library maintains,
the most complete public description of what Ecowitt consoles send, plus the Wunderground
protocol names a console uses when configured to speak that instead.

A key matching no row is not dropped: `parse` stores it under the `unmapped` table with its
original name, so a sensor this table has never heard of still produces data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .units import Kind

T = Kind.TEMPERATURE
P = Kind.PRESSURE
RAIN = Kind.RAIN
RATE = Kind.RAIN_RATE
SPEED = Kind.SPEED

#: Channel suffixes. Temperature/humidity channels run 1-8, soil channels 1-16, particulate,
#: leak and depth channels 1-4; the patterns accept any number so that a console with more
#: channels than this table knows about still maps them.
CH = r"(?P<ch>[1-9][0-9]?)"


@dataclass(frozen=True)
class FieldSpec:
    """How one family of report keys is stored.

    `field`, `sensor` and tag values are templates: `{ch}` and any other named group in the
    pattern are filled from the key that matched.
    """

    pattern: re.Pattern[str]
    table: str
    field: str
    kind: Kind
    #: The unit the station sends, for kinds that convert; None for the rest.
    unit: str | None = None
    sensor: str | None = None
    tags: tuple[tuple[str, str], ...] = ()


def spec(
    pattern: str,
    table: str,
    field: str,
    kind: Kind,
    unit: str | None = None,
    *,
    sensor: str | None = None,
    tags: tuple[tuple[str, str], ...] = (),
) -> FieldSpec:
    """Build a FieldSpec, adding a `channel` tag whenever the pattern captures one."""
    compiled = re.compile(pattern)
    if "ch" in compiled.groupindex:
        tags = (("channel", "{ch}"), *tags)
    return FieldSpec(compiled, table, field, kind, unit, sensor, tags)


def temperature(
    stem: str, table: str, field: str, *, sensor: str | None, bare_is_fahrenheit: bool = False
) -> list[FieldSpec]:
    """Both spellings of a temperature: Fahrenheit and Celsius.

    Most families mark Fahrenheit with an `f` suffix (`tempf`, `tempc`). A few newer ones --
    `wbgt`, `tf_co2`, `tf_chN` -- send Fahrenheit under the bare stem and only Celsius with a
    suffix, which `bare_is_fahrenheit` selects. Getting this wrong does not fail: the real key
    simply matches nothing and is stored as unmapped, so the known-keys test is what guards it.
    """
    fahrenheit = stem if bare_is_fahrenheit else stem + "f"
    return [
        spec(fahrenheit, table, field, T, "f", sensor=sensor),
        spec(stem + "c", table, field, T, "c", sensor=sensor),
    ]


def battery(pattern: str, kind: Kind, sensor: str) -> FieldSpec:
    """A battery reading, stored per sensor in the `battery` table.

    Encodings differ by sensor family -- a 0/1 low flag, a voltage, or a 0-5 level -- so each
    family names its own, and the field says which it is. `sensor` is the identifier the
    sensor's measurements carry, so a battery row joins with its readings and takes the same
    display name. Built without `spec` because the `sensor` tag already says which channel.
    """
    field = {Kind.FLAG: "low", Kind.VOLTAGE: "voltage", Kind.LEVEL: "level"}[kind]
    return FieldSpec(re.compile(pattern), "battery", field, kind, sensor=sensor)


RAIN_PERIODS = r"(?P<period>event|hourly|daily|weekly|monthly|yearly|total|last24h)"
#: The piezo gauge abbreviates each period to its initial: `erain_piezo` is the event total.
PIEZO_PERIODS = {
    "e": "event",
    "h": "hourly",
    "d": "daily",
    "w": "weekly",
    "m": "monthly",
    "y": "yearly",
}

BUCKET = (("gauge", "bucket"),)
PIEZO = (("gauge", "piezo"),)

SPECS: list[FieldSpec] = [
    # Indoor: the console's own sensor, or the WH25/WN32P that replaces it.
    *temperature("tempin", "indoor", "temp", sensor="indoor"),
    *temperature("dewpointin", "indoor", "dewpoint", sensor="indoor"),
    spec("humidityin", "indoor", "humidity", Kind.HUMIDITY, sensor="indoor"),
    spec("co2in", "indoor", "co2", Kind.CO2, sensor="indoor"),
    spec("co2in_24h", "indoor", "co2_24h", Kind.CO2, sensor="indoor"),
    # Wunderground protocol spellings.
    spec("indoortempf", "indoor", "temp", T, "f", sensor="indoor"),
    spec("indoorhumidity", "indoor", "humidity", Kind.HUMIDITY, sensor="indoor"),
    # Outdoor thermo-hygrometer.
    *temperature("temp", "outdoor", "temp", sensor="outdoor"),
    *temperature("dewpoint", "outdoor", "dewpoint", sensor="outdoor"),
    *temperature("tempfeels", "outdoor", "feels_like", sensor="outdoor"),
    *temperature("windchill", "outdoor", "wind_chill", sensor="outdoor"),
    spec("humidity", "outdoor", "humidity", Kind.HUMIDITY, sensor="outdoor"),
    spec("dewptf", "outdoor", "dewpoint", T, "f", sensor="outdoor"),
    spec("vpd", "outdoor", "vpd", P, "inhg", sensor="outdoor"),
    # Heat-stress sensor (WN38): black globe and wet-bulb globe temperature.
    *temperature("bgt", "outdoor", "black_globe", sensor="bgt", bare_is_fahrenheit=True),
    *temperature("wbgt", "outdoor", "wbgt", sensor="bgt", bare_is_fahrenheit=True),
    # Pressure. The barometer sits in the console or the indoor sensor.
    spec("baromrelin", "pressure", "rel", P, "inhg", sensor="pressure"),
    spec("baromabsin", "pressure", "abs", P, "inhg", sensor="pressure"),
    spec("baromrelhpa", "pressure", "rel", P, "hpa", sensor="pressure"),
    spec("baromabshpa", "pressure", "abs", P, "hpa", sensor="pressure"),
    # Wunderground defines `baromin` as sea-level pressure. Some devices send station pressure
    # under it instead; the calibration check on the status page is what exposes that.
    spec("baromin", "pressure", "rel", P, "inhg", sensor="pressure"),
    # Wind.
    spec("windspeedmph", "wind", "speed", SPEED, "mph", sensor="wind"),
    spec("windspeedkmh", "wind", "speed", SPEED, "kmh", sensor="wind"),
    spec("windgustmph", "wind", "gust", SPEED, "mph", sensor="wind"),
    spec("windgustkmh", "wind", "gust", SPEED, "kmh", sensor="wind"),
    spec("maxdailygust", "wind", "max_daily_gust", SPEED, "mph", sensor="wind"),
    spec("maxdailygustkmh", "wind", "max_daily_gust", SPEED, "kmh", sensor="wind"),
    spec("windspdmph_avg10m", "wind", "speed_avg10m", SPEED, "mph", sensor="wind"),
    spec("windspdkmh_avg10m", "wind", "speed_avg10m", SPEED, "kmh", sensor="wind"),
    spec("winddir", "wind", "dir", Kind.ANGLE, sensor="wind"),
    spec("winddir_avg10m", "wind", "dir_avg10m", Kind.ANGLE, sensor="wind"),
    # Rain: tipping-bucket gauge.
    spec("rainratein", "rain", "rate", RATE, "in", sensor="rain", tags=BUCKET),
    spec("rainratemm", "rain", "rate", RATE, "mm", sensor="rain", tags=BUCKET),
    spec(RAIN_PERIODS + "rainin", "rain", "{period}", RAIN, "in", sensor="rain", tags=BUCKET),
    spec(RAIN_PERIODS + "rainmm", "rain", "{period}", RAIN, "mm", sensor="rain", tags=BUCKET),
    # Wunderground's `rainin` is the rain over the past hour.
    spec("rainin", "rain", "hourly", RAIN, "in", sensor="rain", tags=BUCKET),
    # Rain: piezoelectric gauge (WS90 and its relatives).
    spec("rrain_piezo", "rain", "rate", RATE, "in", sensor="piezo", tags=PIEZO),
    spec("rrain_piezomm", "rain", "rate", RATE, "mm", sensor="piezo", tags=PIEZO),
    *[
        spec(f"{p}rain_piezo{suffix}", "rain", period, RAIN, unit, sensor="piezo", tags=PIEZO)
        for p, period in PIEZO_PERIODS.items()
        for suffix, unit in (("", "in"), ("mm", "mm"))
    ],
    spec("last24hrain_piezo", "rain", "last24h", RAIN, "in", sensor="piezo", tags=PIEZO),
    spec("last24hrain_piezomm", "rain", "last24h", RAIN, "mm", sensor="piezo", tags=PIEZO),
    spec("srain_piezo", "rain", "raining", Kind.FLAG, sensor="piezo", tags=PIEZO),
    # Solar and UV.
    spec("solarradiation", "solar", "radiation", Kind.IRRADIANCE, sensor="solar"),
    spec("solarradiation_lux", "solar", "illuminance", Kind.ILLUMINANCE, sensor="solar"),
    spec("uv", "solar", "uv_index", Kind.UV_INDEX, sensor="solar"),
    spec("UV", "solar", "uv_index", Kind.UV_INDEX, sensor="solar"),
    # Temperature/humidity channels (WH31, WN31).
    *temperature("temp" + CH, "channel", "temp", sensor="ch{ch}"),
    *temperature("dewpoint" + CH, "channel", "dewpoint", sensor="ch{ch}"),
    spec("humidity" + CH, "channel", "humidity", Kind.HUMIDITY, sensor="ch{ch}"),
    # Soil moisture (WH51).
    spec("soilmoisture" + CH, "soil", "moisture", Kind.HUMIDITY, sensor="soil{ch}"),
    spec("soilad" + CH, "soil", "moisture_raw", Kind.COUNT, sensor="soil{ch}"),
    # Soil moisture, conductivity and temperature (WH52).
    spec("soil_ec_hum" + CH, "soil_ec", "moisture", Kind.HUMIDITY, sensor="soil_ec{ch}"),
    spec("soil_ec_hum_ad" + CH, "soil_ec", "moisture_raw", Kind.COUNT, sensor="soil_ec{ch}"),
    spec("soil_ec" + CH, "soil_ec", "ec", Kind.CONDUCTIVITY, sensor="soil_ec{ch}"),
    spec("soil_ec_ad" + CH, "soil_ec", "ec_raw", Kind.COUNT, sensor="soil_ec{ch}"),
    *temperature(
        "soil_ec_temp" + CH, "soil_ec", "temp", sensor="soil_ec{ch}", bare_is_fahrenheit=True
    ),
    # Particulate matter (WH41, WH43).
    spec("pm25_ch" + CH, "pm", "pm25", Kind.PARTICULATE, sensor="pm{ch}"),
    spec("pm25_avg_24h_ch" + CH, "pm", "pm25_24h", Kind.PARTICULATE, sensor="pm{ch}"),
    # Air quality combo (WH45, WH46): temperature, humidity, particulates and CO2.
    *temperature("tf_co2", "air", "temp", sensor="air", bare_is_fahrenheit=True),
    spec("humi_co2", "air", "humidity", Kind.HUMIDITY, sensor="air"),
    *[
        spec(f"{pm}_co2", "air", pm, Kind.PARTICULATE, sensor="air")
        for pm in ("pm1", "pm4", "pm25", "pm10")
    ],
    *[
        spec(f"{pm}_24h_co2", "air", f"{pm}_24h", Kind.PARTICULATE, sensor="air")
        for pm in ("pm1", "pm4", "pm25", "pm10")
    ],
    spec("co2", "air", "co2", Kind.CO2, sensor="air"),
    spec("co2_24h", "air", "co2_24h", Kind.CO2, sensor="air"),
    # Lightning (WH57).
    spec("lightning", "lightning", "distance", Kind.DISTANCE, "km", sensor="lightning"),
    spec("lightning_mi", "lightning", "distance", Kind.DISTANCE, "mi", sensor="lightning"),
    spec("lightning_num", "lightning", "strikes", Kind.COUNT, sensor="lightning"),
    spec("lightning_time", "lightning", "last_strike", Kind.UNIX_TIME, sensor="lightning"),
    # Leak (WH55).
    spec("leak_ch" + CH, "leak", "leak", Kind.FLAG, sensor="leak{ch}"),
    # Temperature probe (WN34).
    *temperature("tf_ch" + CH, "probe", "temp", sensor="probe{ch}", bare_is_fahrenheit=True),
    # Leaf wetness (WN35).
    spec("leafwetness_ch" + CH, "leaf", "wetness", Kind.PERCENT, sensor="leaf{ch}"),
    # Laser distance (LDS01).
    spec("depth_ch" + CH, "depth", "depth", Kind.LENGTH, sensor="depth{ch}"),
    spec("thi_ch" + CH, "depth", "history_index", Kind.LENGTH, sensor="depth{ch}"),
    spec("air_ch" + CH, "depth", "air_gap", Kind.LENGTH, sensor="depth{ch}"),
    spec("ldsheat_ch" + CH, "depth", "heater_count", Kind.COUNT, sensor="depth{ch}"),
    # Batteries.
    battery("batt" + CH, Kind.FLAG, "ch{ch}"),
    # A battery takes the identifier of the readings it powers, so it shows beside them and
    # shares their name. The WH25 and WN32P are indoor sensors that take over from the console's
    # own; the WH26 is the plain outdoor thermo-hygrometer, and the WH65 (the WS69 array), WS80
    # and WS90 are arrays whose outdoor temperature and humidity come from the same unit.
    battery("wh25batt", Kind.FLAG, "indoor"),
    battery("wh26batt", Kind.FLAG, "outdoor"),
    battery("wh65batt", Kind.FLAG, "outdoor"),
    battery("wh80batt", Kind.VOLTAGE, "outdoor"),
    battery("wh90batt", Kind.VOLTAGE, "outdoor"),
    battery("wh57batt", Kind.LEVEL, "wh57"),
    battery("co2_batt", Kind.LEVEL, "air"),
    battery("pm25batt" + CH, Kind.LEVEL, "pm{ch}"),
    battery("leakbatt" + CH, Kind.LEVEL, "leak{ch}"),
    *[
        battery(f"{device}batt", Kind.VOLTAGE, device)
        for device in ("wh40", "wh68", "wh85", "bgt", "wn20")
    ],
    battery("console_batt", Kind.VOLTAGE, "console"),
    battery("soilbatt" + CH, Kind.VOLTAGE, "soil{ch}"),
    battery("soil_ec_batt" + CH, Kind.VOLTAGE, "soil_ec{ch}"),
    battery("tf_batt" + CH, Kind.VOLTAGE, "probe{ch}"),
    battery("leaf_batt" + CH, Kind.VOLTAGE, "leaf{ch}"),
    battery("ldsbatt" + CH, Kind.VOLTAGE, "depth{ch}"),
    # The WS85 and WS90 run from a solar-charged supercapacitor rather than a battery.
    spec("ws85cap_volt", "battery", "capacitor", Kind.VOLTAGE, sensor="ws85"),
    spec("ws90cap_volt", "battery", "capacitor", Kind.VOLTAGE, sensor="ws90"),
    # The console itself.
    spec("stationtype", "station", "stationtype", Kind.TEXT),
    spec("model", "station", "model", Kind.TEXT),
    spec("freq", "station", "freq", Kind.TEXT),
    spec("softwaretype", "station", "softwaretype", Kind.TEXT),
    spec("runtime", "station", "runtime", Kind.DURATION),
    spec("interval", "station", "interval", Kind.DURATION),
    spec("heap", "station", "heap", Kind.BYTES),
]

#: Tables whose rows describe one sensor a person might name -- a room, a soil bed, a tank.
#: Each row carries the stable `sensor` identifier, which is what joins a room's readings
#: across tables, and its display `name`.
NAMED_TABLES = frozenset(
    {
        "indoor",
        "outdoor",
        "battery",
        "channel",
        "soil",
        "soil_ec",
        "pm",
        "air",
        "leak",
        "probe",
        "leaf",
        "depth",
        "derived",
        "ventilation",
    }
)

#: Keys that are consumed or discarded rather than stored. PASSKEY and PASSWORD are
#: credentials; `dateutc` becomes the timestamp; the rest are Wunderground protocol plumbing
#: that describes the request rather than the weather.
NOT_STORED = frozenset(
    {"PASSKEY", "PASSWORD", "ID", "dateutc", "action", "realtime", "rtfreq", "updateraw"}
)


def match(key: str) -> tuple[FieldSpec, dict[str, str]] | None:
    """Find the spec a report key belongs to, with the values its pattern captured."""
    for candidate in SPECS:
        found = candidate.pattern.fullmatch(key)
        if found:
            return candidate, found.groupdict()
    return None

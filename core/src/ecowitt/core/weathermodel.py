"""A weather model's view of each station's location, as the collector stores it.

The collector fetches Open-Meteo's 15-minute values for every station with coordinates and
writes them to the `model` table beside the station's own readings, so the two can be compared
and the model can supply what a station does not measure (cloud cover, the weather code).

Rows are tagged `station`, `source` (`open_meteo`) and `model` (the model asked for), so
choosing another model starts new series rather than putting a step in the old ones. Field names
follow the station's tables -- `temp_c`, `speed_kmh`, `dir_deg` -- in the operator's units, and
each row's time is when its values are valid, not when they were fetched.
"""

from __future__ import annotations

from ecowitt.core.units import Kind

TABLE = "model"
SOURCE = "open_meteo"

#: Open-Meteo's name for each variable stored, and the base field and kind it is stored as.
#: Precipitation is the total of the 15 minutes ending at the row's time; radiation is their
#: mean; everything else is the value at that time.
VARIABLES: dict[str, tuple[str, Kind]] = {
    "temperature_2m": ("temp", Kind.TEMPERATURE),
    "relative_humidity_2m": ("humidity", Kind.HUMIDITY),
    "dew_point_2m": ("dewpoint", Kind.TEMPERATURE),
    "wind_speed_10m": ("speed", Kind.SPEED),
    "wind_gusts_10m": ("gust", Kind.SPEED),
    "wind_direction_10m": ("dir", Kind.ANGLE),
    "surface_pressure": ("abs", Kind.PRESSURE),
    "pressure_msl": ("sea", Kind.PRESSURE),
    "precipitation": ("precip_15m", Kind.RAIN),
    "shortwave_radiation": ("radiation", Kind.IRRADIANCE),
    "uv_index": ("uv_index", Kind.UV_INDEX),
    "cloud_cover": ("cloud_cover", Kind.PERCENT),
    "weather_code": ("weather_code", Kind.CODE),
    "is_day": ("is_day", Kind.FLAG),
}

#: A station's choice that turns the model off, and the default for a station with coordinates.
OFF = "off"
DEFAULT_MODEL = "best_match"

#: The models a setup form offers, by Open-Meteo's name. Any other model Open-Meteo serves can be
#: named in the configuration file by hand.
MODELS: dict[str, str] = {
    "best_match": "Best for this location",
    "icon_seamless": "ICON (DWD, Germany)",
    "ecmwf_ifs": "ECMWF IFS (Europe's centre)",
    "meteofrance_seamless": "ARPEGE and AROME (Météo-France)",
    "gfs_seamless": "GFS (NOAA, United States)",
    "ukmo_seamless": "Unified Model (UK Met Office)",
}

#: The WMO weather codes Open-Meteo uses, in words.
WEATHER_CODES: dict[int, str] = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Light snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def describe(code: int) -> str:
    """A weather code in words, or the number itself for one the table does not know."""
    return WEATHER_CODES.get(code, f"Weather code {code}")


#: The weather model's forecast for each station, hour by hour and day by day. A row's time is the
#: hour or local day it forecasts; its `lead` tag says how far ahead it was made (hours, or days),
#: so each fetch replaces the previous one's row for the same lead, and forecasts made at every
#: distance ahead are kept to be compared with what the station then measured.
FORECAST_TABLE = "forecast"
FORECAST_DAILY_TABLE = "forecast_daily"
FORECAST_DAYS = 7

#: Open-Meteo's hourly forecast variables, and the base field and kind each is stored as.
#: Precipitation is the hour's total, ending at the row's time.
FORECAST_HOURLY: dict[str, tuple[str, Kind]] = {
    "temperature_2m": ("temp", Kind.TEMPERATURE),
    "relative_humidity_2m": ("humidity", Kind.HUMIDITY),
    "dew_point_2m": ("dewpoint", Kind.TEMPERATURE),
    "precipitation": ("precip_1h", Kind.RAIN),
    "precipitation_probability": ("precip_probability", Kind.PERCENT),
    "weather_code": ("weather_code", Kind.CODE),
    "wind_speed_10m": ("speed", Kind.SPEED),
    "wind_gusts_10m": ("gust", Kind.SPEED),
    "wind_direction_10m": ("dir", Kind.ANGLE),
    "cloud_cover": ("cloud_cover", Kind.PERCENT),
    "uv_index": ("uv_index", Kind.UV_INDEX),
    "is_day": ("is_day", Kind.FLAG),
}

#: Open-Meteo's daily forecast variables, for the station's local days.
FORECAST_DAILY: dict[str, tuple[str, Kind]] = {
    "weather_code": ("weather_code", Kind.CODE),
    "temperature_2m_max": ("temp_max", Kind.TEMPERATURE),
    "temperature_2m_min": ("temp_min", Kind.TEMPERATURE),
    "precipitation_sum": ("precip", Kind.RAIN),
    "precipitation_probability_max": ("precip_probability", Kind.PERCENT),
    "wind_speed_10m_max": ("speed_max", Kind.SPEED),
    "wind_gusts_10m_max": ("gust_max", Kind.SPEED),
    "wind_direction_10m_dominant": ("dir", Kind.ANGLE),
    "uv_index_max": ("uv_index_max", Kind.UV_INDEX),
}

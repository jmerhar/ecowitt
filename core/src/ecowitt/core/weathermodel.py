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

"""Facts about a location from public services: its elevation, and a weather model's values.

Both are asked only about stations whose coordinates the operator has entered, because the
coordinates are sent to them. Every failure -- no network, a rate limit, an answer of the wrong
shape -- returns None: a lookup is a convenience, and nothing depends on it succeeding.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2

from ecowitt.core import weathermodel
from ecowitt.core.readings import Value
from ecowitt.core.units import Kind

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Elevation:
    """A ground elevation and the service that gave it."""

    metres: float
    source: str


async def elevation(
    client: httpx2.AsyncClient,
    latitude: float,
    longitude: float,
    *,
    opentopodata_url: str,
    open_elevation_url: str,
) -> Elevation | None:
    """Ground elevation at a point, from OpenTopoData, or Open-Elevation if that fails.

    Ground, not barometer: a console upstairs sits a few metres higher, which matters little --
    about 0.4 hPa per storey -- but is worth adding by hand.
    """
    location = f"{latitude},{longitude}"
    data = await _get_json(client, opentopodata_url, {"locations": location})
    metres = _first(data, "results", "elevation")
    if metres is not None:
        return Elevation(metres, "OpenTopoData (SRTM 30 m)")
    data = await _get_json(client, open_elevation_url, {"locations": location})
    metres = _first(data, "results", "elevation")
    if metres is not None:
        return Elevation(metres, "Open-Elevation")
    return None


@dataclass(frozen=True)
class ModelSample:
    """A weather model's values at one time, by Open-Meteo's variable names.

    Measurements are floats, a weather code an int and a flag a bool; a variable the model
    left out at that time is absent.
    """

    timestamp: int
    values: dict[str, Value]


async def weather_model(
    client: httpx2.AsyncClient,
    latitude: float,
    longitude: float,
    altitude_m: float | None,
    *,
    start: int,
    end: int,
    model: str,
    open_meteo_url: str,
) -> list[ModelSample] | None:
    """A weather model's 15-minute values at a point, from `start` to `end` (Unix seconds).

    Given the station's altitude, Open-Meteo adjusts its grid cell's temperature and pressure to
    that height, which is what makes them comparable with the station's. Outside the regions
    with a native 15-minute model it interpolates hourly values, in the same shape.
    """
    params: dict[str, str] = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "models": model,
        "minutely_15": ",".join(weathermodel.VARIABLES),
        "start_minutely_15": _quarter(start),
        "end_minutely_15": _quarter(end),
        "wind_speed_unit": "ms",
        "timeformat": "unixtime",
    }
    if altitude_m is not None:
        params["elevation"] = str(altitude_m)
    data = await _get_json(client, open_meteo_url, params)
    block = data.get("minutely_15") if isinstance(data, dict) else None
    times = block.get("time") if isinstance(block, dict) else None
    if not isinstance(times, list):
        return None
    columns = {
        name: column
        for name in weathermodel.VARIABLES
        if isinstance(column := block.get(name), list) and len(column) == len(times)
    }
    samples = []
    for index, timestamp in enumerate(times):
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            return None
        values = {
            name: value
            for name, column in columns.items()
            if (value := _typed(weathermodel.VARIABLES[name][1], column[index])) is not None
        }
        if values:
            samples.append(ModelSample(timestamp, values))
    return samples


def _quarter(timestamp: int) -> str:
    """A time as Open-Meteo's 15-minute parameters take it: UTC, to the minute."""
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M")


def _typed(kind: Kind, value: Any) -> Value | None:
    """A model value as its kind is stored, or None for a missing or malformed one."""
    number = _finite(value)
    if number is None:
        return None
    if kind is Kind.FLAG:
        return bool(number)
    if kind is Kind.CODE:
        return int(number)
    return number


async def _get_json(client: httpx2.AsyncClient, url: str, params: dict[str, str]) -> Any:
    """GET a URL and parse its JSON, or return None on any failure."""
    try:
        response = await client.get(url, params=params, timeout=TIMEOUT_SECONDS)
    except httpx2.RequestError as exc:
        logger.warning("lookup at %s failed: %s", url, exc)
        return None
    if not response.is_success:
        logger.warning("lookup at %s failed: HTTP %d", url, response.status_code)
        return None
    try:
        return response.json()
    except ValueError:
        logger.warning("lookup at %s returned something that is not JSON", url)
        return None


def _first(data: Any, list_key: str, value_key: str) -> float | None:
    """`data[list_key][0][value_key]` as a finite float, or None for any other shape."""
    if not isinstance(data, dict):
        return None
    items = data.get(list_key)
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    return _finite(items[0].get(value_key))


def _finite(value: Any) -> float | None:
    """A finite number as a float, or None. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None

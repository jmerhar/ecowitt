"""Facts about a location from public services: its elevation, and the weather model's pressure.

Both are asked only about stations whose coordinates the operator has entered, because the
coordinates are sent to them. Every failure -- no network, a rate limit, an answer of the wrong
shape -- returns None: a lookup is a convenience, and nothing depends on it succeeding.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import httpx2

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


async def surface_pressure(
    client: httpx2.AsyncClient,
    latitude: float,
    longitude: float,
    altitude_m: float | None,
    *,
    open_meteo_url: str,
) -> float | None:
    """A weather model's current surface pressure at a point, in hPa.

    Given the station's altitude, Open-Meteo corrects its grid cell's pressure to that height,
    which is what makes the value comparable with the console's absolute reading.
    """
    params: dict[str, str] = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "current": "surface_pressure",
    }
    if altitude_m is not None:
        params["elevation"] = str(altitude_m)
    data = await _get_json(client, open_meteo_url, params)
    current = data.get("current") if isinstance(data, dict) else None
    value = current.get("surface_pressure") if isinstance(current, dict) else None
    return _finite(value)


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

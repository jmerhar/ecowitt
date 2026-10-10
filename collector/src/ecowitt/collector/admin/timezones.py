"""Time zones: which one a pair of coordinates falls in, and whether a name is one.

The lookup is offline (tzfpy carries the zone boundaries), so it sends the coordinates nowhere.
"""

from __future__ import annotations

import zoneinfo

import tzfpy


def is_zone(name: str) -> bool:
    """Whether `name` is an IANA zone this system knows, such as `Europe/Lisbon`."""
    try:
        zoneinfo.ZoneInfo(name)
    except zoneinfo.ZoneInfoNotFoundError, ValueError:
        return False
    return True


def zone_at(latitude: float | None, longitude: float | None) -> str | None:
    """The zone the point falls in, or None without both coordinates.

    Over open sea tzfpy answers with a nautical zone (`Etc/GMT+1`), which is still a zone, so
    a station on a ship gets one too.
    """
    if latitude is None or longitude is None:
        return None
    name = tzfpy.get_tz(longitude, latitude)
    return name if name and is_zone(name) else None


def all_zones() -> list[str]:
    """Every zone name, sorted, for the setup page to offer."""
    return sorted(zoneinfo.available_timezones())

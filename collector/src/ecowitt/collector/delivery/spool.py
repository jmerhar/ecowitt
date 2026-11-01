"""Reports waiting for InfluxDB, kept on disk so an outage or a restart loses none of them.

jigkit's spool, which keeps each report's rows as one file and replays them oldest first,
bounded by size, with refused reports kept apart for inspection. Files of line protocol that an
older version spooled (`.lp`) are still listed, so they reach delivery, which cannot read them as
rows and sets them aside rather than leaving them unseen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jigkit.spool import Spool as _Spool
from jigkit.spool import SpoolStats

__all__ = ["LEGACY_SUFFIX", "Spool", "SpoolStats"]

#: Line protocol an older version spooled.
LEGACY_SUFFIX = ".lp"


class Spool(_Spool):
    """jigkit's spool, also listing the line protocol files an older version left behind."""

    def __init__(self, directory: Path, max_bytes: int, **kwargs: Any) -> None:
        super().__init__(directory, max_bytes, extra_suffixes=(LEGACY_SUFFIX,), **kwargs)

"""Reading back what was stored: the questions a store answers, and the shapes of the answers.

The questions are generic -- a table, some fields, a time window -- so a dashboard asks them the
same way of any database that implements `Reader`. Rows are grouped by their tags (`sensor`,
`gauge`, ...) other than `station` and `name`, and each group reports the newest `name` it was
written with: renaming a room starts a new `name` but keeps its `sensor`.

A field the table does not have is left out of the answer rather than failing the question: a
station without a rain gauge has no rain fields, and a unit preference changed today has no
history under its new field name.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from ecowitt.core.readings import Value
from ecowitt.core.stationinfo import StationInfo


class ReadError(Exception):
    """The database could not answer: unreachable, refusing the token, or failing the query."""


class Aggregate(Enum):
    """How a field's values in one bucket become one value."""

    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    #: The mean of an angle in degrees, taken as a vector so 350° and 10° average to 0°, not 180°.
    CIRCULAR = "circular"


class _Group:
    """What every answer shares: the group's tags."""

    tags: dict[str, str]

    @property
    def sensor(self) -> str | None:
        """The group's `sensor` tag, if its table has one."""
        return self.tags.get("sensor")


@dataclass(frozen=True)
class Span(_Group):
    """One group's first and last values in a window, each field's earliest and latest non-null."""

    tags: dict[str, str]
    name: str | None
    first_time: datetime
    last_time: datetime
    first: dict[str, Value] = field(default_factory=dict)
    last: dict[str, Value] = field(default_factory=dict)


@dataclass(frozen=True)
class Extreme:
    """A lowest or highest value, and the first time it was reached."""

    value: float
    time: datetime


@dataclass(frozen=True)
class Extremes(_Group):
    """One group's lowest and highest value of each field in a window."""

    tags: dict[str, str]
    name: str | None
    minimum: dict[str, Extreme] = field(default_factory=dict)
    maximum: dict[str, Extreme] = field(default_factory=dict)


@dataclass(frozen=True)
class Buckets(_Group):
    """One group's values in equal time buckets: the bucket starts, and per (field, aggregate) the
    value of each bucket, None where the field had none."""

    tags: dict[str, str]
    name: str | None
    times: list[datetime] = field(default_factory=list)
    values: dict[tuple[str, Aggregate], list[float | None]] = field(default_factory=dict)


class Reader(Protocol):
    """A database readings can be read back from."""

    async def check_read(self) -> str | None:
        """Whether this store would answer a query: None, or the reason not."""

    async def stations(self) -> list[str]:
        """Every station that has published its settings, sorted."""

    async def station_info(self, station: str) -> StationInfo | None:
        """A station's newest published settings, or None if it has published none."""

    async def span(
        self,
        station: str,
        table: str,
        fields: Collection[str],
        *,
        start: datetime,
        end: datetime,
        sensors: Collection[str] | None = None,
    ) -> list[Span]:
        """Each group's first and last values between `start` and `end` (inclusive).

        `sensors`, when given, keeps only rows whose `sensor` tag is one of them; a table
        without that tag is not filtered.
        """

    async def extremes(
        self,
        station: str,
        table: str,
        fields: Collection[str],
        *,
        start: datetime,
        end: datetime,
        sensors: Collection[str] | None = None,
    ) -> list[Extremes]:
        """Each group's lowest and highest values between `start` and `end`."""

    async def buckets(
        self,
        station: str,
        table: str,
        aggregates: Sequence[tuple[str, Aggregate]],
        *,
        start: datetime,
        end: datetime,
        step: timedelta,
        origin: datetime,
        sensors: Collection[str] | None = None,
    ) -> list[Buckets]:
        """Each group's values in buckets of `step`, aligned to `origin`; empty buckets left out."""

    async def aclose(self) -> None:
        """Release connections."""

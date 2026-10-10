"""A Reader over rows held in memory, answering as InfluxDB 3's SQL does.

Groups are a table's tags other than station and name; a group's name is its newest row's; a
field no row of the table has is left out, and a table with none of the requested fields
answers nothing.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta

from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.base import Row
from ecowitt.core.store.query import Aggregate, Buckets, Extreme, Extremes, ReadError, Span


class MemoryReader:
    """Answers from `rows` and the stations' `infos`."""

    def __init__(self, rows: list[Row], infos: dict[str, StationInfo]) -> None:
        self.rows = rows
        self.infos = infos
        self.calls: list[tuple[str, str, str]] = []
        self.failure: str | None = None
        self.closed = False

    async def check_read(self) -> str | None:
        return self.failure

    async def stations(self) -> list[str]:
        self._fail()
        return sorted(self.infos)

    async def station_info(self, station: str) -> StationInfo | None:
        self._fail()
        return self.infos.get(station)

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
        found = []
        for tags, rows in self._groups("span", station, table, fields, start, end, sensors):
            first = {}
            last = {}
            for name in fields:
                values = [r.fields[name] for r in rows if r.fields.get(name) is not None]
                if values:
                    first[name], last[name] = values[0], values[-1]
            found.append(
                Span(
                    tags, _name(rows), _at(rows[0].timestamp), _at(rows[-1].timestamp), first, last
                )
            )
        return found

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
        found = []
        for tags, rows in self._groups("extremes", station, table, fields, start, end, sensors):
            lows, highs = {}, {}
            for name in fields:
                values = [
                    (float(r.fields[name]), r.timestamp)
                    for r in rows
                    if _number(r.fields.get(name))
                ]
                if values:
                    low = min(values, key=lambda v: (v[0], v[1]))
                    high = min(values, key=lambda v: (-v[0], v[1]))
                    lows[name] = Extreme(low[0], _at(low[1]))
                    highs[name] = Extreme(high[0], _at(high[1]))
            if lows:
                found.append(Extremes(tags, _name(rows), lows, highs))
        return found

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
        wanted = list(dict.fromkeys(aggregates))
        fields = [name for name, _ in wanted]
        found = []
        for tags, rows in self._groups("buckets", station, table, fields, start, end, sensors):
            present = self._columns(table)
            pairs = [pair for pair in wanted if pair[0] in present]
            by_bucket: dict[datetime, list[Row]] = {}
            size = step.total_seconds()
            for row in rows:
                offset = (_at(row.timestamp) - origin).total_seconds() // size
                by_bucket.setdefault(origin + timedelta(seconds=offset * size), []).append(row)
            times = sorted(by_bucket)
            values = {pair: [_aggregate(pair, by_bucket[t]) for t in times] for pair in pairs}
            found.append(Buckets(tags, _name(rows), times, values))
        return found

    async def aclose(self) -> None:
        self.closed = True

    def _fail(self) -> None:
        if self.failure:
            raise ReadError(self.failure)

    def _columns(self, table: str) -> set[str]:
        return {name for row in self.rows if row.table == table for name in row.fields}

    def _groups(
        self,
        call: str,
        station: str,
        table: str,
        fields: Collection[str],
        start: datetime,
        end: datetime,
        sensors: Collection[str] | None,
    ) -> list[tuple[dict[str, str], list[Row]]]:
        self._fail()
        self.calls.append((call, station, table))
        if not set(fields) & self._columns(table):
            return []
        groups: dict[tuple[tuple[str, str], ...], list[Row]] = {}
        for row in sorted(self.rows, key=lambda r: r.timestamp):
            tags = dict(row.tags)
            if row.table != table or tags.get("station") != station:
                continue
            if not start <= _at(row.timestamp) <= end:
                continue
            if sensors is not None and "sensor" in tags and tags["sensor"] not in sensors:
                continue
            key = tuple(sorted((k, v) for k, v in tags.items() if k not in {"station", "name"}))
            groups.setdefault(key, []).append(row)
        return [(dict(key), rows) for key, rows in sorted(groups.items())]


def _aggregate(pair: tuple[str, Aggregate], rows: list[Row]) -> float | None:
    name, aggregate = pair
    values = [float(r.fields[name]) for r in rows if _number(r.fields.get(name))]
    if not values:
        return None
    match aggregate:
        case Aggregate.MEAN:
            return statistics.fmean(values)
        case Aggregate.MIN:
            return min(values)
        case Aggregate.MAX:
            return max(values)
    sin = statistics.fmean(math.sin(math.radians(v)) for v in values)
    cos = statistics.fmean(math.cos(math.radians(v)) for v in values)
    return math.degrees(math.atan2(sin, cos)) % 360


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _name(rows: list[Row]) -> str | None:
    return dict(rows[-1].tags).get("name")


def _at(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)

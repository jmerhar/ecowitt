"""InfluxDB 3: the weather questions the dashboard asks, on jigkit's InfluxDB 3 sink.

jigkit writes the rows and runs the SQL. The queries here name tables and fields from the
caller, so each one is checked against the database's own catalogue and quoted; values -- the
station and sensor names -- travel as query parameters, never inside the SQL text.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Any

from jigkit.influx.sink import IDENTIFIER, Influx3Sink, TableInfo, parse_time, sql_timestamp

from ecowitt.core.readings import Value
from ecowitt.core.stationinfo import TABLE as STATION_INFO
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.query import (
    Aggregate,
    Buckets,
    Extreme,
    Extremes,
    Point,
    Span,
    increases,
)

#: Tags that are not part of a group: every query is for one station, and `name` is a label
#: that changes when a sensor is renamed.
NOT_GROUPS = frozenset({"station", "name"})


def _groups(info: TableInfo) -> list[str]:
    """The tags a table's rows are grouped by, sorted."""
    return sorted(set(info.tags) - NOT_GROUPS)


class Influx3Store(Influx3Sink):
    """Writes to, and reads from, an InfluxDB 3 database, answering the dashboard's questions."""

    async def stations(self) -> list[str]:
        """Every station that has published its settings, sorted."""
        rows = await self.rows(f"SELECT DISTINCT station FROM {STATION_INFO} ORDER BY station")
        return [row["station"] for row in rows if row.get("station")]

    async def station_info(self, station: str) -> StationInfo | None:
        """A station's newest `station_info` row."""
        rows = await self.rows(
            f"SELECT * FROM {STATION_INFO} WHERE station = $station ORDER BY time DESC LIMIT 1",
            {"station": station},
        )
        if not rows:
            return None
        values = {k: v for k, v in rows[0].items() if k not in {"station", "time"}}
        return StationInfo.from_fields(station, values)

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
        """Each group's first and last values in the window."""
        info = await self.table(table)
        present = _present(fields, info.columns)
        if not present:
            return []
        select = ["min(time) AS first_time", "max(time) AS last_time"]
        for i, name in enumerate(present):
            select.append(f'first_value("{name}" IGNORE NULLS ORDER BY time) AS first_{i}')
            select.append(f'last_value("{name}" IGNORE NULLS ORDER BY time) AS last_{i}')
        rows = await self._grouped(table, info, select, station, start, end, sensors)
        return [
            Span(
                tags=_tags(row, info),
                name=row.get("name"),
                first_time=parse_time(row["first_time"]),
                last_time=parse_time(row["last_time"]),
                first=_values(row, "first", present),
                last=_values(row, "last", present),
            )
            for row in rows
            if row.get("last_time")
        ]

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
        """Each group's lowest and highest values in the window, with when each was first seen."""
        info = await self.table(table)
        present = _present(fields, info.columns)
        if not present:
            return []
        select = []
        for i, name in enumerate(present):
            select += [
                f'min("{name}") AS min_{i}',
                f'first_value(time ORDER BY "{name}" ASC NULLS LAST, time) AS min_{i}_at',
                f'max("{name}") AS max_{i}',
                f'first_value(time ORDER BY "{name}" DESC NULLS LAST, time) AS max_{i}_at',
            ]
        rows = await self._grouped(table, info, select, station, start, end, sensors)
        found = []
        for row in rows:
            lows, highs = {}, {}
            for i, name in enumerate(present):
                if row.get(f"min_{i}") is not None:
                    lows[name] = Extreme(float(row[f"min_{i}"]), parse_time(row[f"min_{i}_at"]))
                    highs[name] = Extreme(float(row[f"max_{i}"]), parse_time(row[f"max_{i}_at"]))
            if lows:
                found.append(Extremes(_tags(row, info), row.get("name"), lows, highs))
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
        """Each group's values in buckets of `step` aligned to `origin`."""
        info = await self.table(table)
        present = set(_present([name for name, _ in aggregates], info.columns))
        wanted = list(dict.fromkeys(key for key in aggregates if key[0] in present))
        if not wanted:
            return []
        seconds = int(step.total_seconds())
        if seconds <= 0:
            raise ValueError(f"a bucket must last at least a second, not {step}")
        bucket = f"date_bin(INTERVAL '{seconds} seconds', time, {sql_timestamp(origin)})"
        select = [f"{bucket} AS bucket"]
        for i, (name, aggregate) in enumerate(wanted):
            if aggregate is Aggregate.INCREASE:
                # Each bucket's highest and lowest, from which `increases` works out the rise.
                select.append(f"{_aggregate(name, Aggregate.MAX)} AS value_{i}")
                select.append(f"{_aggregate(name, Aggregate.MIN)} AS low_{i}")
            else:
                select.append(f"{_aggregate(name, aggregate)} AS value_{i}")
        rows = await self._grouped(
            table, info, select, station, start, end, sensors, extra_group="bucket"
        )
        groups: dict[tuple[tuple[str, str], ...], Buckets] = {}
        names: dict[tuple[tuple[str, str], ...], str | None] = {}
        lows: dict[tuple[tuple[str, str], ...], dict[int, list[float | None]]] = {}
        for row in rows:
            tags = _tags(row, info)
            key = tuple(sorted(tags.items()))
            if key not in groups:
                groups[key] = Buckets(tags, None, [], {pair: [] for pair in wanted})
            # Rows arrive in time order, so the last bucket's name is the newest.
            names[key] = row.get("name") or names.get(key)
            groups[key].times.append(parse_time(row["bucket"]))
            for i, pair in enumerate(wanted):
                value = row.get(f"value_{i}")
                if value is not None and pair[1] is Aggregate.CIRCULAR:
                    value = value % 360.0
                groups[key].values[pair].append(None if value is None else float(value))
                if pair[1] is Aggregate.INCREASE:
                    low = row.get(f"low_{i}")
                    lows.setdefault(key, {}).setdefault(i, []).append(
                        None if low is None else float(low)
                    )
        for key, group in groups.items():
            for i, low in lows.get(key, {}).items():
                pair = wanted[i]
                group.values[pair] = increases(group.times, group.values[pair], low, step)
        return [
            Buckets(group.tags, names[key], group.times, group.values)
            for key, group in groups.items()
        ]

    async def points(
        self,
        station: str | None,
        table: str,
        fields: Collection[str],
        *,
        start: datetime,
        end: datetime,
    ) -> list[Point]:
        """Every row in the window, oldest first; rows with none of the fields are left out."""
        info = await self.table(table)
        present = _present(fields, info.columns)
        if not present:
            return []
        tags = [t for t in info.tags if t != "station" or station is None]
        columns = ", ".join(
            ["time", *tags, *(f'"{name}" AS value_{i}' for i, name in enumerate(present))]
        )
        any_field = " OR ".join(f'"{name}" IS NOT NULL' for name in present)
        scope = "" if station is None else "station = $station AND "
        sql = (
            f'SELECT {columns} FROM "{table}" WHERE {scope}'
            f"time >= {sql_timestamp(start)} AND time <= {sql_timestamp(end)} "
            f"AND ({any_field}) ORDER BY time"
        )
        rows = await self.rows(sql, {} if station is None else {"station": station})
        return [
            Point(
                time=parse_time(row["time"]),
                tags={t: str(row[t]) for t in tags if row.get(t) is not None},
                values=_values(row, "value", present),
            )
            for row in rows
        ]

    async def _grouped(
        self,
        table: str,
        info: TableInfo,
        select: list[str],
        station: str,
        start: datetime,
        end: datetime,
        sensors: Collection[str] | None,
        *,
        extra_group: str | None = None,
    ) -> list[dict[str, Any]]:
        """One aggregate query over a station's rows in a window, grouped by the table's tags."""
        params: dict[str, str] = {"station": station}
        where = [
            "station = $station",
            f"time >= {sql_timestamp(start)}",
            f"time <= {sql_timestamp(end)}",
        ]
        group = _groups(info)
        if group:
            select = [*group, *select]
            if "name" in info.tags:
                select.append("last_value(name ORDER BY time) AS name")
        if sensors is not None and "sensor" in info.tags:
            if not sensors:
                return []
            names = []
            for i, sensor in enumerate(sorted(sensors)):
                params[f"s{i}"] = sensor
                names.append(f"$s{i}")
            where.append(f"sensor IN ({', '.join(names)})")
        if extra_group:
            group.append(extra_group)
        sql = f'SELECT {", ".join(select)} FROM "{table}" WHERE {" AND ".join(where)}'
        if group:
            sql += f" GROUP BY {', '.join(group)} ORDER BY {', '.join(group)}"
        return await self.rows(sql, params)


def _present(fields: Collection[str], columns: frozenset[str]) -> list[str]:
    """The requested fields the table has, in order, refusing anything that is not a name."""
    for name in fields:
        if not IDENTIFIER.fullmatch(name) or name in {"time", "station", "sensor", "name"}:
            raise ValueError(f"not a field name: {name!r}")
    return [name for name in dict.fromkeys(fields) if name in columns]


def _tags(row: dict[str, Any], info: TableInfo) -> dict[str, str]:
    """A result row's group: its value of each tag the query grouped by."""
    return {tag: row[tag] for tag in _groups(info) if row.get(tag) is not None}


def _aggregate(name: str, aggregate: Aggregate) -> str:
    """The SQL that reduces one field's values in a bucket."""
    match aggregate:
        case Aggregate.MEAN:
            return f'avg("{name}")'
        case Aggregate.MIN:
            return f'min("{name}")'
        case Aggregate.MAX:
            return f'max("{name}")'
    # Aggregate.CIRCULAR
    return f'degrees(atan2(avg(sin(radians("{name}"))), avg(cos(radians("{name}")))))'


def _values(row: dict[str, Any], prefix: str, present: list[str]) -> dict[str, Value]:
    """The non-null `<prefix>_<i>` columns of a row, by field name."""
    return {
        name: row[f"{prefix}_{i}"]
        for i, name in enumerate(present)
        if row.get(f"{prefix}_{i}") is not None
    }

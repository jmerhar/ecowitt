"""InfluxDB 3: line protocol to /api/v3/write_lp, SQL to /api/v3/query_sql, with a bearer token.

Queries name tables and fields from the caller, so each one is checked against the database's
own catalogue (`information_schema.columns`) and quoted; values -- the station and sensor names
-- travel as query parameters, never inside the SQL text.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2

from ecowitt.core.readings import Value
from ecowitt.core.stationinfo import TABLE as STATION_INFO
from ecowitt.core.stationinfo import StationInfo
from ecowitt.core.store.influx import (
    CHECK_TIMEOUT_SECONDS,
    ERROR_EXCERPT,
    TIMEOUT_SECONDS,
    InfluxStore,
)
from ecowitt.core.store.query import Aggregate, Buckets, Extreme, Extremes, ReadError, Span

logger = logging.getLogger(__name__)

#: How long the list of tables and their columns is trusted. A field written for the first time
#: is invisible to queries for at most this long.
COLUMNS_TTL_SECONDS = 300.0

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


#: Tags that are not part of a group: every query is for one station, and `name` is a label
#: that changes when a sensor is renamed.
NOT_GROUPS = frozenset({"station", "name"})


class _Missing(Exception):
    """The query named a table the database does not have."""


@dataclass(frozen=True)
class _Table:
    """A table's columns, and which of them are tags."""

    columns: frozenset[str] = frozenset()
    tags: tuple[str, ...] = ()

    @property
    def groups(self) -> list[str]:
        """The tags rows are grouped by, sorted."""
        return sorted(set(self.tags) - NOT_GROUPS)


class Influx3Store(InfluxStore):
    """Writes to, and reads from, an InfluxDB 3 database."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tables: dict[str, _Table] = {}
        self._columns_at = -math.inf

    def _write_endpoint(self) -> tuple[str, dict[str, str], str]:
        # Second precision, which is what the line protocol encoder writes.
        return "/api/v3/write_lp", {"db": self.database, "precision": "second"}, "Bearer"

    async def check_read(self) -> str | None:
        """Whether a query would be answered, found by running a trivial one."""
        if not self.configured:
            return "no database is configured"
        try:
            await self._query("SELECT 1", timeout=CHECK_TIMEOUT_SECONDS)
        except ReadError as exc:
            return str(exc)
        return None

    async def stations(self) -> list[str]:
        """Every station that has published its settings, sorted."""
        rows = await self._rows(f"SELECT DISTINCT station FROM {STATION_INFO} ORDER BY station")
        return [row["station"] for row in rows if row.get("station")]

    async def station_info(self, station: str) -> StationInfo | None:
        """A station's newest `station_info` row."""
        rows = await self._rows(
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
        info = await self._table(table)
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
                first_time=_time(row["first_time"]),
                last_time=_time(row["last_time"]),
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
        info = await self._table(table)
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
                    lows[name] = Extreme(float(row[f"min_{i}"]), _time(row[f"min_{i}_at"]))
                    highs[name] = Extreme(float(row[f"max_{i}"]), _time(row[f"max_{i}_at"]))
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
        info = await self._table(table)
        present = set(_present([name for name, _ in aggregates], info.columns))
        wanted = list(dict.fromkeys(key for key in aggregates if key[0] in present))
        if not wanted:
            return []
        seconds = int(step.total_seconds())
        if seconds <= 0:
            raise ValueError(f"a bucket must last at least a second, not {step}")
        bucket = f"date_bin(INTERVAL '{seconds} seconds', time, {_timestamp(origin)})"
        select = [f"{bucket} AS bucket"]
        for i, (name, aggregate) in enumerate(wanted):
            select.append(f"{_aggregate(name, aggregate)} AS value_{i}")
        rows = await self._grouped(
            table, info, select, station, start, end, sensors, extra_group="bucket"
        )
        groups: dict[tuple[tuple[str, str], ...], Buckets] = {}
        names: dict[tuple[tuple[str, str], ...], str | None] = {}
        for row in rows:
            tags = _tags(row, info)
            key = tuple(sorted(tags.items()))
            if key not in groups:
                groups[key] = Buckets(tags, None, [], {pair: [] for pair in wanted})
            # Rows arrive in time order, so the last bucket's name is the newest.
            names[key] = row.get("name") or names.get(key)
            groups[key].times.append(_time(row["bucket"]))
            for i, pair in enumerate(wanted):
                value = row.get(f"value_{i}")
                if value is not None and pair[1] is Aggregate.CIRCULAR:
                    value = value % 360.0
                groups[key].values[pair].append(None if value is None else float(value))
        return [
            Buckets(group.tags, names[key], group.times, group.values)
            for key, group in groups.items()
        ]

    async def _grouped(
        self,
        table: str,
        info: _Table,
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
            f"time >= {_timestamp(start)}",
            f"time <= {_timestamp(end)}",
        ]
        group = info.groups
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
        return await self._rows(sql, params)

    async def _table(self, table: str) -> _Table:
        """The columns of `table`, none if it does not exist; the catalogue is cached briefly.

        InfluxDB 3 stores tags as dictionary-encoded strings, which is how they are told apart
        from fields.
        """
        if not IDENTIFIER.fullmatch(table):
            raise ValueError(f"not a table name: {table!r}")
        now = time.monotonic()
        if now - self._columns_at > COLUMNS_TTL_SECONDS:
            rows = await self._rows(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'iox'"
            )
            columns: dict[str, set[str]] = {}
            tags: dict[str, list[str]] = {}
            for row in rows:
                columns.setdefault(row["table_name"], set()).add(row["column_name"])
                if str(row.get("data_type", "")).startswith("Dictionary"):
                    tags.setdefault(row["table_name"], []).append(row["column_name"])
            self._tables = {
                name: _Table(frozenset(names), tuple(tags.get(name, ())))
                for name, names in columns.items()
            }
            self._columns_at = now
        return self._tables.get(table, _Table())

    async def _rows(self, sql: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """The rows a query returns, or none if it names a table that does not exist."""
        try:
            return await self._query(sql, params)
        except _Missing:
            return []

    async def _query(
        self, sql: str, params: dict[str, str] | None = None, *, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        """POST one SQL query, returning its rows as dicts with null columns left out."""
        if not self.configured:
            raise ReadError("no database is configured")
        body: dict[str, object] = {"db": self.database, "q": sql, "format": "json"}
        if params:
            body["params"] = params
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = await self._client.post(
                self.url + "/api/v3/query_sql",
                json=body,
                headers=headers,
                timeout=timeout or TIMEOUT_SECONDS,
            )
        except httpx2.RequestError as exc:
            raise ReadError(f"cannot connect ({type(exc).__name__})") from exc
        status = response.status_code
        if status == 200:
            rows = response.json()
            if not isinstance(rows, list):
                raise ReadError("InfluxDB answered with something other than rows")
            return rows
        text = response.text[:ERROR_EXCERPT]
        if status == 400 and re.search(r"table '[^']*' not found", text):
            raise _Missing(text)
        logger.error("query to InfluxDB failed: HTTP %s: %s", status, text)
        reasons = {
            401: "the token was not accepted",
            403: "the token may not read that database",
            404: "no such database",
        }
        raise ReadError(reasons.get(status, f"InfluxDB answered HTTP {status}"))


def _present(fields: Collection[str], columns: frozenset[str]) -> list[str]:
    """The requested fields the table has, in order, refusing anything that is not a name."""
    for name in fields:
        if not IDENTIFIER.fullmatch(name) or name in {"time", "station", "sensor", "name"}:
            raise ValueError(f"not a field name: {name!r}")
    return [name for name in dict.fromkeys(fields) if name in columns]


def _tags(row: dict[str, Any], info: _Table) -> dict[str, str]:
    """A result row's group: its value of each tag the query grouped by."""
    return {tag: row[tag] for tag in info.groups if row.get(tag) is not None}


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


def _timestamp(moment: datetime) -> str:
    """A SQL timestamp literal for an aware datetime, in UTC to the second."""
    if moment.tzinfo is None:
        raise ValueError("a query's times must carry a time zone")
    return f"TIMESTAMP '{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}'"


def _time(text: str) -> datetime:
    """A UTC datetime from InfluxDB's timestamps, which have no zone and up to nanoseconds."""
    whole, _, fraction = text.partition(".")
    moment = datetime.fromisoformat(whole).replace(tzinfo=UTC)
    if fraction:
        moment += timedelta(microseconds=int(fraction[:6].ljust(6, "0")))
    return moment

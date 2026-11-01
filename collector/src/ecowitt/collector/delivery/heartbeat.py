"""Tell a monitoring service that a station's readings are reaching InfluxDB.

jigkit's heartbeat calls a push monitor's URL after delivered writes, at most once per interval.
What is particular to the collector is which writes count: only a station's own readings, not
the rows the collector writes itself, so the monitor notices a console that has stopped
uploading even while the collector keeps writing its own tables.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx2
from jigkit.heartbeat import Heartbeat as _Heartbeat

from ecowitt.collector.state import State
from ecowitt.core import stationinfo, weathermodel, windheight
from ecowitt.core.store.base import Row

#: Tables the collector writes itself rather than from a station's report.
#: The 10 m wind is one: a live report writes it beside the station's readings, which beat, and a
#: recompute writes it alone, which must not.
OWN_TABLES = frozenset(
    {
        stationinfo.TABLE,
        weathermodel.TABLE,
        weathermodel.FORECAST_TABLE,
        weathermodel.FORECAST_DAILY_TABLE,
        windheight.TABLE,
    }
)


class Heartbeat(_Heartbeat):
    """Calls a URL after a station's readings are written, counting each call in `state`."""

    def __init__(
        self,
        client: httpx2.AsyncClient,
        url: str,
        *,
        interval_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        state: State | None = None,
    ) -> None:
        if state is not None:
            state.heartbeat_configured = True
        super().__init__(
            client,
            url,
            interval_seconds=interval_seconds,
            sleep=sleep,
            on_result=state.record_heartbeat if state is not None else lambda _: None,
        )

    def written(self, rows: list[Row]) -> None:
        """Beat if a write carried a station's readings.

        The collector writes rows of its own as well -- station settings, the weather model and
        its forecast -- and those must not keep the monitor happy while the console has stopped
        uploading.
        """
        if any(row.table not in OWN_TABLES for row in rows):
            self.beat()

"""What the admin tests share: an admin app over a configuration file, driven like a browser."""

from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt.collector.admin import app as admin
from ecowitt.collector.admin.calibration import CalibrationMonitor
from ecowitt.collector.admin.configstore import ConfigStore
from ecowitt.collector.config import Settings
from ecowitt.collector.ingest.handler import StationHandler
from ecowitt.collector.ingest.pending import PendingStations
from ecowitt.collector.state import State
from ecowitt.core.store.base import Row
from ecowitt.core.store.lineprotocol import encode

from ..conftest import FIXTURE_PASSKEY, payload

ORIGIN = {"Origin": "http://localhost"}


class Sink:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def submit(self, rows: list[Row]) -> None:
        self.bodies.append(encode(rows))


@dataclass
class Rig:
    client: TestClient
    store: ConfigStore
    handler: StationHandler
    pending: PendingStations
    calibration: CalibrationMonitor
    context: admin.AdminContext

    @property
    def csrf(self) -> str:
        return admin.auth.csrf_token(self.context.secret)

    def post(
        self,
        path: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ):
        body = urllib.parse.urlencode({"csrf": self.csrf, **data})
        hdrs = {"Content-Type": "application/x-www-form-urlencoded", **ORIGIN, **(headers or {})}
        if auth:
            hdrs["Authorization"] = (
                "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            )
        return self.client.post(path, content=body, headers=hdrs)

    async def report(self, passkey: str = FIXTURE_PASSKEY) -> bool:
        fields = dict(urllib.parse.parse_qsl(payload("hp2551_indoor"), keep_blank_values=True))
        return await self.handler.handle(fields | {"PASSKEY": passkey}, "192.0.2.9")


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    settings = Settings(
        data_dir=tmp_path,
        opentopodata_url="http://127.0.0.1:1/x",
        open_elevation_url="http://127.0.0.1:1/y",
    )
    store = ConfigStore(settings.config_file)
    pending, calibration = PendingStations(), CalibrationMonitor()
    handler = StationHandler(store.stations, Sink(), pending=pending, calibration=calibration)
    store.subscribe(lambda stations: setattr(handler, "config", stations))
    context = admin.AdminContext(
        settings,
        State(),
        secret=b"s" * 32,
        store=store,
        handler=handler,
        pending=pending,
        calibration=calibration,
    )
    with TestClient(
        base_url="http://localhost", app=admin.build_app(context), follow_redirects=False
    ) as client:
        yield Rig(client, store, handler, pending, calibration, context)

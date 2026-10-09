"""Fixtures shared by the suite."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt import admin, ingest
from ecowitt.config import Settings
from ecowitt.state import State

FIXTURES = Path(__file__).parent / "fixtures"

#: The PASSKEY in the fixtures is a placeholder. A real one is the MD5 of a station's MAC and
#: authenticates its reports, so no repository should hold one.
FIXTURE_PASSKEY = "0123456789ABCDEF0123456789ABCDEF"


def payload(name: str) -> str:
    """Return a recorded console payload, exactly as the station sends it."""
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a throwaway data directory."""
    return Settings(data_dir=tmp_path, influx_url="http://influx.invalid:8181")


@pytest.fixture
def state() -> State:
    """Fresh runtime state."""
    return State()


class RecordingHandler:
    """A report handler whose verdict each test chooses."""

    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.reports: list[dict[str, str]] = []
        self.sources: list[str] = []

    async def handle(self, fields: Mapping[str, str], source: str) -> bool:
        """Record the report and return the configured verdict."""
        self.reports.append(dict(fields))
        self.sources.append(source)
        return self.accept


@pytest.fixture
def handler() -> RecordingHandler:
    """A handler that accepts everything and remembers what it got."""
    return RecordingHandler()


@pytest.fixture
def ingest_client(
    settings: Settings, state: State, handler: RecordingHandler
) -> Iterator[TestClient]:
    """A client for the public listener, behaving the way a weather station does.

    `follow_redirects=False` is the whole point of this fixture. The Ecowitt uploader ignores
    a 3xx -- it closes the connection and re-sends the identical request on its next interval,
    for ever -- so a test client that quietly followed one would report success for a server
    the real console cannot talk to. An HTTP-to-HTTPS redirect on a reverse proxy is the usual
    way a deployment ends up there.
    """
    app = ingest.build_app(settings, state, handler)
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def admin_client(settings: Settings, state: State) -> Iterator[TestClient]:
    """A client for the admin listener."""
    with TestClient(admin.build_app(settings, state), follow_redirects=False) as client:
        yield client

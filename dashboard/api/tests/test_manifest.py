"""Adding the page to a home screen: the manifest, and the icons it and the page name."""

from __future__ import annotations

import re
import struct
from pathlib import Path

from fastapi.testclient import TestClient

from ecowitt.dashboard.app import _manifest, build_app
from ecowitt.dashboard.settings import Settings

from .conftest import REPO
from .memory import MemoryReader

WEB = REPO / "dashboard/web"


def png(path: Path) -> tuple[int, int, int]:
    """A PNG's width, height and colour type, from its header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height, _, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def test_the_manifest_is_named_for_the_site_and_opens_as_an_app(client: TestClient) -> None:
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/manifest+json"
    found = response.json()
    assert (found["name"], found["short_name"]) == ("Test weather", "Test weather")
    assert (found["start_url"], found["scope"], found["display"]) == ("/", "/", "standalone")
    purposes = {(i["sizes"], i["purpose"]) for i in found["icons"]}
    # What Chrome asks of an installable app: a 192 and a 512 icon, and one it may crop.
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= purposes


def test_the_page_can_ask_for_an_app_that_opens_full_screen(client: TestClient) -> None:
    found = client.get("/manifest.webmanifest", params={"display": "fullscreen"}).json()

    assert (found["start_url"], found["display"]) == ("/", "fullscreen")
    assert client.get("/manifest.webmanifest", params={"display": "minimal-ui"}).status_code == 422


def test_there_is_no_manifest_before_setup(settings: Settings, reader: MemoryReader) -> None:
    """Until setup is done the page is the setup form, which is no app to install."""
    with TestClient(build_app(settings, make_reader=lambda *_: reader)) as fresh:
        assert fresh.get("/manifest.webmanifest").status_code == 404


def test_every_icon_named_exists_at_its_size_and_is_opaque() -> None:
    """A home screen fills a transparent icon with a colour of its own, so none may have alpha."""
    named = [(i["src"], i["sizes"]) for i in _manifest("x")["icons"]]  # type: ignore[union-attr]
    page = (WEB / "index.html").read_text(encoding="utf-8")
    touch = re.search(r'rel="apple-touch-icon" href="([^"]+)"', page)
    assert touch is not None
    # iOS asks for 180 px.
    named.append((touch.group(1), "180x180"))
    for src, sizes in named:
        width, height, colour = png(WEB / "public" / src.lstrip("/"))
        assert f"{width}x{height}" == sizes, src
        # Colour types 4 and 6 carry alpha.
        assert colour not in (4, 6), src


def test_the_manifest_is_described_in_the_browsers_language(client: TestClient) -> None:
    english = client.get("/manifest.webmanifest")
    portuguese = client.get("/manifest.webmanifest", headers={"Accept-Language": "pt-PT,pt"})

    assert (
        english.json()["description"] == "Current conditions and history from the weather station"
    )
    assert (portuguese.json()["lang"], portuguese.json()["description"]) == (
        "pt-PT",
        "Condições atuais e histórico da estação meteorológica",
    )
    assert portuguese.headers["content-language"] == "pt-PT"
    assert portuguese.headers["vary"] == "Accept-Language"


def test_the_page_links_the_manifest() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")

    assert '<link rel="manifest" href="/manifest.webmanifest" />' in page

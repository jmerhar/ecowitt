"""The container's health probe, against a real server."""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from ecowitt.dashboard import healthcheck
from ecowitt.dashboard.settings import Settings


@pytest.fixture
def server() -> Iterator[tuple[http.server.HTTPServer, list[int]]]:
    """A server answering /healthz with the status at the head of its list."""
    statuses = [200]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(statuses[0])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_: object) -> None:
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, statuses
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.mark.parametrize(("status", "code"), [(200, 0), (204, 1), (503, 1)])
def test_only_a_200_is_healthy(
    server: tuple[http.server.HTTPServer, list[int]], tmp_path: Path, status: int, code: int
) -> None:
    httpd, statuses = server
    statuses[0] = status
    settings = Settings(data_dir=tmp_path, port=httpd.server_address[1])
    assert healthcheck.main(settings) == code


def test_nothing_listening_is_unhealthy(tmp_path: Path) -> None:
    assert healthcheck.main(Settings(data_dir=tmp_path, port=1)) == 1


def test_the_default_settings_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "1")
    assert healthcheck.main() == 1

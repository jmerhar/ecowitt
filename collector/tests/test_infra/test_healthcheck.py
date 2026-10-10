"""The container's health probe."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from ecowitt.collector import healthcheck


class _Response(io.BytesIO):
    """Enough of an HTTP response for urlopen's context-manager use."""

    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@pytest.fixture(autouse=True)
def _settings_cache_cleared() -> None:
    """Settings are cached process-wide, and each test here builds its own."""
    healthcheck.get_settings.cache_clear()


def test_healthy_when_both_listeners_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A serving process exits zero."""
    monkeypatch.setattr(
        healthcheck.urllib.request, "urlopen", lambda *_a, **_k: _Response({"status": "ok"})
    )

    assert healthcheck.main() == 0


def test_unhealthy_while_still_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process with one listener bound is not healthy."""
    monkeypatch.setattr(
        healthcheck.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response({"status": "starting", "ingest_serving": False}),
    )

    assert healthcheck.main() == 1


def test_unhealthy_on_a_2xx_that_is_not_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 204 is not an answer to a health question."""
    monkeypatch.setattr(
        healthcheck.urllib.request, "urlopen", lambda *_a, **_k: _Response({}, status=204)
    )

    assert healthcheck.main() == 1


def test_unhealthy_when_nothing_is_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused connection is the normal failure, and must not raise."""

    def refuse(*_: object, **__: object) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", refuse)

    assert healthcheck.main() == 1


def test_unhealthy_on_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 500 from the admin listener is unhealthy, and its response is closed."""

    def fail(*_: object, **__: object) -> None:
        raise urllib.error.HTTPError("u", 500, "boom", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", fail)

    assert healthcheck.main() == 1


def test_probes_the_configured_admin_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving the admin port moves the probe with it."""
    monkeypatch.setenv("ADMIN_PORT", "9999")
    healthcheck.get_settings.cache_clear()
    seen: list[str] = []

    def record(url: str, **_: object) -> _Response:
        seen.append(url)
        return _Response({"status": "ok"})

    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", record)

    assert healthcheck.main() == 0
    assert seen == ["http://127.0.0.1:9999/healthz"]

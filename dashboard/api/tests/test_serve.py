"""Starting the server."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from ecowitt.dashboard import serve
from ecowitt.dashboard.settings import Settings


def test_main_serves_with_the_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ran: dict[str, Any] = {}
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kwargs: ran.update(kwargs, app=app))
    serve.main(Settings(data_dir=tmp_path, port=9999, forwarded_allow_ips="10.0.0.1"))
    assert (ran["port"], ran["proxy_headers"], ran["forwarded_allow_ips"]) == (
        9999,
        True,
        "10.0.0.1",
    )
    assert ran["app"].state.site.dashboard is None


def test_the_app_can_be_built_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logging.getLogger("httpx2").setLevel(logging.NOTSET)
    app = serve.from_environment()
    assert app.state.site.dashboard is None
    assert logging.getLogger("httpx2").level == logging.WARNING


def test_chatty_libraries_are_quieted() -> None:
    serve.configure_logging("DEBUG")
    assert logging.getLogger("httpx2").level == logging.WARNING


def test_the_config_file_lives_in_the_data_directory(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path).config_path == tmp_path / "dashboard.yaml"

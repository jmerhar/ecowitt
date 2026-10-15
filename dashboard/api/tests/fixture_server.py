"""The dashboard over the tests' example station, for a browser to load: the real app and built
pages, reading the in-memory day of readings at its fixed moment.

    python -m tests.fixture_server WEB_DIR [PORT]   (from dashboard/api)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import uvicorn

from ecowitt.dashboard.app import build_app
from ecowitt.dashboard.settings import Settings

from .conftest import CONFIG, INFO, NOW, readings
from .memory import MemoryReader


def main(argv: list[str]) -> None:
    """Serve WEB_DIR and the API on every interface at PORT (default 2553) until stopped."""
    web_dir = Path(argv[0]).resolve()
    port = int(argv[1]) if len(argv) > 1 else 2553
    with tempfile.TemporaryDirectory() as data:
        settings = Settings(data_dir=Path(data), web_dir=web_dir, rate=1000.0, burst=1000)
        settings.config_path.write_text(CONFIG, encoding="utf-8")
        reader = MemoryReader(readings(), {"example": INFO})
        app = build_app(settings, make_reader=lambda *_: reader)
        app.state.site.dashboard.clock = lambda: NOW
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")  # noqa: S104


if __name__ == "__main__":
    main(sys.argv[1:])

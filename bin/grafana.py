#!/usr/bin/env python3
"""Write grafana/weather.json and grafana/alerts.json: the templates rendered for the default units.

    .venv/bin/python bin/grafana.py [--root DIR]

The templates in collector/src/ecowitt/collector/grafana/ are the source; these two files are
what someone importing the dashboard or loading the rules by hand downloads, and what the
collector's Grafana page renders for other units. Run it after changing a template; a test fails
until the files match. `--root DIR` writes into a checkout other than this one, as the test does.
It needs the virtualenv's interpreter, which has the collector installed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ecowitt.collector.grafana import render
from ecowitt.core.units import Units

#: Each file, by its path in the repository, and how it is rendered.
FILES = {"grafana/weather.json": render.dashboard, "grafana/alerts.json": render.alerts}


def main(argv: list[str] | None = None) -> None:
    """Render both files into the checkout."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args(argv).root
    for path, document in FILES.items():
        (root / path).write_text(render.dumps(document(Units())), encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

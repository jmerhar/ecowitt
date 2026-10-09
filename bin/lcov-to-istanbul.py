#!/usr/bin/env python3
"""Turn an lcov report into the istanbul files the shared coverage tooling reads.

Node's built-in test coverage writes lcov and nothing else, while the summary, the gate and the
coverage site read istanbul's `coverage-summary.json` and publish an `html` directory. This
writes both from the lcov, so the page scripts are measured without installing a coverage tool:

    lcov-to-istanbul.py <lcov.info> <output-dir>

writes `<output-dir>/coverage-summary.json` and `<output-dir>/html/index.html`. The lcov is left
where it is, which is where Codecov looks for it.

Statements are reported as lines: lcov does not count them separately, and the tooling reads only
lines and branches.
"""

from __future__ import annotations

import html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

USAGE = "usage: lcov-to-istanbul.py <lcov.info> <output-dir>"


@dataclass
class FileCoverage:
    """One source file's counts from an lcov record."""

    path: str
    lines_found: int = 0
    lines_hit: int = 0
    branches_found: int = 0
    branches_hit: int = 0
    functions_found: int = 0
    functions_hit: int = 0
    uncovered_lines: list[int] = field(default_factory=list)


def parse(text: str) -> list[FileCoverage]:
    """Read every `SF` ... `end_of_record` block. Unknown lines are ignored, as lcov allows."""
    files: list[FileCoverage] = []
    current: FileCoverage | None = None
    counters = {
        "LF": "lines_found",
        "LH": "lines_hit",
        "BRF": "branches_found",
        "BRH": "branches_hit",
        "FNF": "functions_found",
        "FNH": "functions_hit",
    }
    for raw in text.splitlines():
        line = raw.strip()
        tag, _, value = line.partition(":")
        if tag == "SF":
            current = FileCoverage(value)
        elif current is None:
            continue
        elif tag in counters:
            setattr(current, counters[tag], int(value))
        elif tag == "DA":
            number, hits = value.split(",")[:2]
            if int(hits) == 0:
                current.uncovered_lines.append(int(number))
        elif line == "end_of_record":
            files.append(current)
            current = None
    return files


def _metric(covered: int, total: int) -> dict[str, float | int]:
    """One istanbul counter. An empty one is 100%: nothing went unexercised."""
    pct = round(covered / total * 100, 2) if total else 100
    return {"total": total, "covered": covered, "skipped": 0, "pct": pct}


def _summary(files: list[FileCoverage]) -> dict[str, dict[str, float | int]]:
    """Istanbul's four counters for a set of files."""
    lines = _metric(sum(f.lines_hit for f in files), sum(f.lines_found for f in files))
    return {
        "lines": lines,
        "statements": dict(lines),
        "functions": _metric(
            sum(f.functions_hit for f in files), sum(f.functions_found for f in files)
        ),
        "branches": _metric(
            sum(f.branches_hit for f in files), sum(f.branches_found for f in files)
        ),
    }


def istanbul_summary(files: list[FileCoverage]) -> dict[str, object]:
    """The `coverage-summary.json` document: a `total`, then one entry per file."""
    return {"total": _summary(files), **{f.path: _summary([f]) for f in files}}


def html_report(files: list[FileCoverage]) -> str:
    """A one-page report: each file's percentages and the lines no test reached."""
    rows = []
    for f in [*files, None]:
        name = "All files" if f is None else f.path
        counts = _summary(files if f is None else [f])
        missing = "" if f is None else ", ".join(map(str, f.uncovered_lines))
        rows.append(
            f"<tr><td>{html.escape(name)}</td>"
            + "".join(f"<td>{counts[k]['pct']}%</td>" for k in ("lines", "branches", "functions"))
            + f"<td>{html.escape(missing)}</td></tr>"
        )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page script coverage</title>'
        "<style>body{font:15px system-ui,sans-serif;margin:2rem}td,th{padding:.3rem .8rem;"
        "text-align:left;border-bottom:1px solid #ddd}</style><h1>Page script coverage</h1>"
        "<table><tr><th>File</th><th>Lines</th><th>Branches</th><th>Functions</th>"
        "<th>Uncovered lines</th></tr>" + "".join(rows) + "</table></html>\n"
    )


def main(argv: list[str]) -> int:
    """Convert one lcov file, refusing an empty one rather than reporting 100% of nothing."""
    if len(argv) != 3:
        print(USAGE, file=sys.stderr)
        return 2
    lcov, out = Path(argv[1]), Path(argv[2])
    files = parse(lcov.read_text(encoding="utf-8"))
    if not files:
        print(f"{lcov}: no coverage records; did any test load the scripts?", file=sys.stderr)
        return 1
    (out / "html").mkdir(parents=True, exist_ok=True)
    (out / "coverage-summary.json").write_text(json.dumps(istanbul_summary(files), indent=2) + "\n")
    (out / "html" / "index.html").write_text(html_report(files), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

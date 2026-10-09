"""bin/lcov-to-istanbul.py: Node's lcov into the files the shared coverage tooling reads."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[3] / "bin" / "lcov-to-istanbul.py"

LCOV = """TN:
SF:backend/src/ecowitt/static/a.js
FN:1,f
FNDA:1,f
FNF:2
FNH:1
DA:1,1
DA:2,0
DA:3,4
DA:7,0
BRDA:2,0,0,1
BRF:4
BRH:3
LF:4
LH:2
end_of_record
SF:backend/src/ecowitt/static/b<x>.js
FNF:0
FNH:0
BRF:0
BRH:0
LF:6
LH:6
end_of_record
"""


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lcov_to_istanbul", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: dataclasses looks the defining module up in sys.modules while it builds
    # a class, and a module loaded by path is not there otherwise.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_records_are_read_with_their_uncovered_lines(tool: ModuleType) -> None:
    a, b = tool.parse(LCOV)

    assert (a.path, a.lines_found, a.lines_hit, a.branches_found, a.branches_hit) == (
        "backend/src/ecowitt/static/a.js",
        4,
        2,
        4,
        3,
    )
    assert (a.functions_found, a.functions_hit, a.uncovered_lines) == (2, 1, [2, 7])
    assert b.uncovered_lines == []


def test_lines_outside_a_record_are_ignored(tool: ModuleType) -> None:
    assert tool.parse("TN:\nLF:9\nDA:1,0\n") == []


def test_the_summary_is_istanbuls_shape_with_totals_and_files(tool: ModuleType) -> None:
    summary = tool.istanbul_summary(tool.parse(LCOV))

    assert summary["total"]["lines"] == {"total": 10, "covered": 8, "skipped": 0, "pct": 80.0}
    assert summary["total"]["branches"] == {"total": 4, "covered": 3, "skipped": 0, "pct": 75.0}
    assert summary["total"]["statements"] == summary["total"]["lines"]
    assert summary["backend/src/ecowitt/static/a.js"]["functions"]["pct"] == 50.0
    # A file with nothing to measure counts as fully covered, not as 0% or a division error.
    assert summary["backend/src/ecowitt/static/b<x>.js"]["branches"]["pct"] == 100


def test_the_summary_is_what_the_shared_tooling_parses(tool: ModuleType) -> None:
    """The istanbul parser reads `total.lines` and `total.branches` covered and total counts."""
    total = tool.istanbul_summary(tool.parse(LCOV))["total"]

    assert (total["lines"]["covered"], total["lines"]["total"]) == (8, 10)
    assert (total["branches"]["covered"], total["branches"]["total"]) == (3, 4)


def test_the_html_lists_files_and_uncovered_lines_escaped(tool: ModuleType) -> None:
    page = tool.html_report(tool.parse(LCOV))

    assert "<td>All files</td><td>80.0%</td><td>75.0%</td><td>50.0%</td>" in page
    assert "<td>2, 7</td>" in page
    assert "b&lt;x&gt;.js" in page and "b<x>.js" not in page


def test_main_writes_both_files(tool: ModuleType, tmp_path: Path) -> None:
    lcov = tmp_path / "lcov.info"
    lcov.write_text(LCOV)

    assert tool.main(["lcov-to-istanbul.py", str(lcov), str(tmp_path / "out")]) == 0

    summary = json.loads((tmp_path / "out" / "coverage-summary.json").read_text())
    assert summary["total"]["lines"]["pct"] == 80.0
    assert (tmp_path / "out" / "html" / "index.html").read_text().startswith("<!doctype html>")


def test_an_empty_report_is_refused_not_reported_as_full(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """100% of nothing would pass any gate while measuring nothing."""
    lcov = tmp_path / "lcov.info"
    lcov.write_text("TN:\n")

    assert tool.main(["lcov-to-istanbul.py", str(lcov), str(tmp_path / "out")]) == 1
    assert "no coverage records" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_wrong_arguments_print_usage(tool: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert tool.main(["lcov-to-istanbul.py"]) == 2
    assert "lcov-to-istanbul.py <lcov.info> <output-dir>" in capsys.readouterr().err

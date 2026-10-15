"""The dashboard image's build context: what .dockerignore lets in must be enough to build the
pages, or the image fails to build only in CI, after the change is pushed."""

from __future__ import annotations

import json
import re

from .conftest import REPO

WEB = "dashboard/web/"


def allowed() -> list[str]:
    """The paths under dashboard/web that .dockerignore lets in, relative to it."""
    lines = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [line.removeprefix(f"!{WEB}") for line in lines if line.startswith(f"!{WEB}")]


def admitted(path: str, paths: list[str]) -> bool:
    """Whether a path is one of `paths`, or inside one of its directories."""
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in paths)


def test_every_local_module_the_build_config_imports_is_let_in() -> None:
    config = (REPO / WEB / "vite.config.ts").read_text(encoding="utf-8")
    local = re.findall(r'from "\./([^"]+)"', config)
    assert local, "vite.config.ts imports no local module: has the pattern gone stale?"
    paths = allowed()
    missing = [path for path in local if not admitted(path, paths)]
    assert not missing, f"add these to .dockerignore's allowlist: {missing}"


def test_every_file_the_message_compiler_reads_is_let_in() -> None:
    """Paraglide's plugin reads its project's settings and the message files they name, rather
    than importing them, so the check above cannot see them."""
    options = (REPO / WEB / "build/paraglide.ts").read_text(encoding="utf-8")
    project = re.search(r'project: "\./([^"]+)"', options)
    assert project, "build/paraglide.ts names no project: has the pattern gone stale?"
    settings = f"{project.group(1)}/settings.json"
    pattern = json.loads((REPO / WEB / settings).read_text(encoding="utf-8"))[
        "plugin.inlang.messageFormat"
    ]["pathPattern"]
    messages = pattern.removeprefix("./").split("{locale}")[0]
    paths = allowed()
    missing = [path for path in (settings, f"{messages}en.json") if not admitted(path, paths)]
    assert not missing, f"add these to .dockerignore's allowlist: {missing}"


def test_admitted_matches_files_and_directories() -> None:
    assert admitted("build/legacy-css.ts", ["build/"])
    assert admitted("vite.config.ts", ["vite.config.ts"])
    assert not admitted("build/legacy-css.ts", ["build"])
    assert not admitted("legacy-browser/check.mjs", ["build/"])

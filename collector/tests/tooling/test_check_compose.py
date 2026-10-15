"""bin/check-compose.sh: each compose file, and each combination of them that is run, validates."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "bin" / "check-compose.sh"

#: Logs its arguments, and fails for the combination named in FAIL_ON.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$LOG"
case "$*" in *"${FAIL_ON:-none}"*) exit 1 ;; esac
"""


def run(tmp_path: Path, **env: str) -> tuple[int, list[str]]:
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log = tmp_path / "log"
    result = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "DOCKER": str(docker), "LOG": str(log), **env},
    )
    return result.returncode, log.read_text().splitlines() if log.exists() else []


def test_every_combination_is_validated(tmp_path: Path) -> None:
    status, calls = run(tmp_path)

    assert status == 0
    assert calls == [
        "compose -f docker-compose.yml config -q",
        "compose -f docker-compose.yml -f docker-compose.build.yml config -q",
    ]


def test_a_file_that_does_not_validate_fails(tmp_path: Path) -> None:
    status, calls = run(tmp_path, FAIL_ON="docker-compose.yml config")

    assert status == 1
    assert len(calls) == 1


def test_every_compose_file_in_the_repository_is_checked() -> None:
    files = {p.name for p in SCRIPT.parents[1].glob("docker-compose*.yml")}
    assert files and all(name in SCRIPT.read_text() for name in files)

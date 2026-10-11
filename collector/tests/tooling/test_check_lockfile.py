"""bin/check-lockfile.sh: a lockfile may resolve packages from the public npm registry only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "bin" / "check-lockfile.sh"
PUBLIC = "https://registry.npmjs.org/"


def lockfile(tmp_path: Path, *resolved: str) -> Path:
    path = tmp_path / "package-lock.json"
    packages = {
        f"node_modules/p{i}": {"version": "1.0.0", "resolved": url}
        for i, url in enumerate(resolved)
    }
    path.write_text(json.dumps({"lockfileVersion": 3, "packages": packages}, indent=2))
    return path


def check(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), str(path)], capture_output=True, text=True, check=False, timeout=30
    )


def test_a_lockfile_on_the_public_registry_passes(tmp_path: Path) -> None:
    result = check(lockfile(tmp_path, f"{PUBLIC}a/-/a-1.0.0.tgz", f"{PUBLIC}@s/b/-/b-2.0.0.tgz"))
    assert result.returncode == 0, result.stderr
    assert "only to the public registry" in result.stdout


def test_any_other_host_fails_and_is_named_without_its_paths(tmp_path: Path) -> None:
    proxied = "https://npm.example.test/artifactory/api/npm/npm/a/-/a-1.0.0.tgz"
    result = check(lockfile(tmp_path, f"{PUBLIC}b/-/b-1.0.0.tgz", proxied, proxied))
    assert result.returncode == 1
    assert "  https://npm.example.test/…" in result.stderr
    assert result.stderr.count("npm.example.test") == 1, "each host is listed once"
    assert "artifactory" not in result.stderr


def test_a_registry_merely_starting_like_the_public_one_fails(tmp_path: Path) -> None:
    result = check(lockfile(tmp_path, "https://registry.npmjs.org.example.test/a/-/a-1.0.0.tgz"))
    assert result.returncode == 1


def test_a_missing_lockfile_fails(tmp_path: Path) -> None:
    result = check(tmp_path / "package-lock.json")
    assert result.returncode == 1
    assert "is missing" in result.stderr


def test_the_repositorys_own_lockfile_passes() -> None:
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr

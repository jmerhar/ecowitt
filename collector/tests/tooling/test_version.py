"""bin/version.py and bin/release.sh: one version in every manifest, released from the changelog."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

BIN = Path(__file__).parents[3] / "bin"
_spec = importlib.util.spec_from_file_location("version", BIN / "version.py")
assert _spec is not None and _spec.loader is not None
version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(version)

CHANGELOG = """# Changelog

Intro.

## Unreleased

### Added

- Something new.

## 1.2.3 — 2026-10-01

### Fixed

- Something old.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout's manifests and changelog, all at 1.2.3."""
    for path in version.PYPROJECTS:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    web = tmp_path / "dashboard/web"
    web.mkdir(parents=True)
    (web / "package.json").write_text(json.dumps({"name": "web", "version": "1.2.3"}, indent=2))
    lock = {
        "name": "web",
        "version": "1.2.3",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web", "version": "1.2.3"},
            "node_modules/dep": {"version": "4.5.6"},
        },
    }
    (web / "package-lock.json").write_text(json.dumps(lock, indent=2))
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    return tmp_path


def run(root: Path, *args: str) -> tuple[int, str, str]:
    out = subprocess.run(
        [str(BIN / "version.py"), "--root", str(root), *args],
        capture_output=True, text=True, check=False, timeout=30,
    )  # fmt: skip
    return out.returncode, out.stdout, out.stderr


def test_agreeing_manifests_pass_and_a_tag_must_name_their_released_version(root: Path) -> None:
    assert run(root, "check") == (0, "every manifest names 1.2.3\n", "")
    assert run(root, "check", "v1.2.3")[0] == 0
    code, _, err = run(root, "check", "v1.2.4")
    assert (code, err) == (1, "the tag is v1.2.4, but the manifests name 1.2.3\n")


def test_a_manifest_out_of_step_is_named(root: Path) -> None:
    pyproject = root / "collector/pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace("1.2.3", "1.2.4"))

    code, _, err = run(root, "check")

    assert code == 1
    assert "collector/pyproject.toml: 1.2.4" in err and "core/pyproject.toml: 1.2.3" in err


def test_a_manifest_without_a_version_is_refused(root: Path) -> None:
    (root / "core/pyproject.toml").write_text('[project]\nname = "x"\n')

    assert run(root, "check")[2] == "core/pyproject.toml names no version where one is expected\n"


def test_setting_a_version_writes_every_manifest_and_dates_the_changelog(root: Path) -> None:
    version.set_version(root, "1.3.0", date(2026, 10, 14))

    assert set(version.versions(root).values()) == {"1.3.0"}
    lock = json.loads((root / "dashboard/web/package-lock.json").read_text())
    assert lock["packages"]["node_modules/dep"]["version"] == "4.5.6", "dependencies untouched"
    text = (root / "CHANGELOG.md").read_text()
    assert "## Unreleased" not in text
    assert "## 1.3.0 — 2026-10-14\n\n### Added\n\n- Something new.\n\n## 1.2.3" in text
    assert run(root, "notes", "1.3.0") == (0, "### Added\n\n- Something new.\n", "")
    assert run(root, "check", "v1.3.0")[0] == 0


@pytest.mark.parametrize(
    ("change", "wanted", "problem"),
    [
        (None, "1.3", "1.3 is not a version like 1.2.3"),
        (("## Unreleased\n", "## Later\n"), "1.3.0", "has no '## Unreleased' section"),
        (("- Something new.\n", ""), "1.3.0", "'## Unreleased' section is empty"),
        (None, "1.2.3", "already has a section for 1.2.3"),
    ],
)
def test_a_release_that_cannot_be_cut_changes_nothing(
    root: Path, change: tuple[str, str] | None, wanted: str, problem: str
) -> None:
    changelog = root / "CHANGELOG.md"
    if change:
        changelog.write_text(CHANGELOG.replace(*change))
    before = changelog.read_text()

    code, _, err = run(root, "set", wanted)

    assert code == 1 and problem in err
    assert changelog.read_text() == before
    assert set(version.versions(root).values()) == {"1.2.3"}


def test_notes_need_a_dated_section(root: Path) -> None:
    assert run(root, "notes", "9.9.9")[2] == "CHANGELOG.md has no dated section for 9.9.9\n"
    code, _, err = run(root, "check", "v1.2.3")
    assert code == 0, err
    (root / "CHANGELOG.md").write_text(CHANGELOG.replace("## 1.2.3 — 2026-10-01", "## 1.2.3"))
    assert run(root, "check", "v1.2.3")[0] == 1


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=30
    ).stdout


@pytest.fixture
def repo(root: Path) -> Path:
    """`root` as a git repository on main, with the release scripts, signing off."""
    (root / "bin").mkdir()
    for script in ("release.sh", "version.py"):
        shutil.copy2(BIN / script, root / "bin" / script)
    git(root, "init", "--quiet", "--initial-branch=main")
    for key, value in (("user.name", "T"), ("user.email", "t@example.test"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("user.signingkey", "")):  # fmt: skip
        git(root, "config", key, value)
    git(root, "add", ".")
    git(root, "commit", "--quiet", "--message", "start")
    return root


def release(repo: Path, wanted: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "bin/release.sh"), wanted], capture_output=True, text=True, check=False,
        timeout=60,
    )  # fmt: skip


def test_a_release_is_committed_and_tagged_with_its_notes(repo: Path) -> None:
    result = release(repo, "1.3.0")

    assert result.returncode == 0, result.stderr
    assert "git push origin main v1.3.0" in result.stdout
    assert git(repo, "log", "-1", "--format=%s") == "chore(release): 1.3.0\n"
    # The headings survive: git strips lines starting with # from a message unless told not to.
    assert git(repo, "tag", "-l", "--format=%(contents)", "v1.3.0").rstrip() == (
        "Ecowitt Server 1.3.0\n\n### Added\n\n- Something new."
    )
    assert git(repo, "status", "--porcelain") == ""


def test_a_release_needs_a_clean_main(repo: Path) -> None:
    (repo / "stray.txt").write_text("x")
    assert "working tree has changes" in release(repo, "1.3.0").stderr
    (repo / "stray.txt").unlink()
    git(repo, "switch", "--quiet", "--create", "other")
    assert "cut from main" in release(repo, "1.3.0").stderr
    assert git(repo, "tag") == ""

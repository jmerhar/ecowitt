#!/usr/bin/env python3
"""The release version, which every project's manifest and CHANGELOG.md carry.

    version.py check [TAG]   every manifest names the same version, and docker-compose.yml pins
                             its images to that version's major; with a tag (v1.2.3), that the
                             manifests name that version and CHANGELOG.md has its section
    version.py set X.Y.Z     write X.Y.Z into every manifest and its major into docker-compose.yml,
                             and date CHANGELOG.md's Unreleased section as X.Y.Z's
    version.py notes X.Y.Z   print X.Y.Z's section of CHANGELOG.md, without its heading

`--root DIR` reads and writes a checkout other than this one, as the tests do.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

PYPROJECTS = ("core/pyproject.toml", "collector/pyproject.toml", "dashboard/api/pyproject.toml")
PACKAGE = "dashboard/web/package.json"
LOCK = "dashboard/web/package-lock.json"
CHANGELOG = "CHANGELOG.md"
#: The shipped compose file follows a major version, so an install gets every release that needs
#: nothing done on upgrading, and no other.
COMPOSE = "docker-compose.yml"
COMPOSE_IMAGE = re.compile(r"(?m)^(    image: ghcr\.io/jmerhar/ecowitt(?:-dashboard)?:)(\S+)$")
SEMVER = re.compile(r"\d+\.\d+\.\d+")
UNRELEASED = "## Unreleased"

#: Each manifest's own version: a pyproject's `version`, package.json's, and the lockfile's
#: top-level one and its root package's (the dependencies' versions are left alone).
PATTERNS = {
    **{p: [re.compile(r'(?m)^(version = ")([^"]*)(")$')] for p in PYPROJECTS},
    PACKAGE: [re.compile(r'(?m)^(  "version": ")([^"]*)(")')],
    LOCK: [
        re.compile(r'(?m)^(  "version": ")([^"]*)(")'),
        re.compile(r'(?m)^(    "": \{\n      "name": "[^"]*",\n      "version": ")([^"]*)(")'),
    ],
}


class VersionError(Exception):
    """What stops a check or a release, said to the person running it."""


def versions(root: Path) -> dict[str, str]:
    """Every manifest's version, by where it was found."""
    found = {}
    for path, patterns in PATTERNS.items():
        text = (root / path).read_text(encoding="utf-8")
        for n, pattern in enumerate(patterns):
            match = pattern.search(text)
            if match is None:
                raise VersionError(f"{path} names no version where one is expected")
            found[f"{path}#{n}" if n else path] = match.group(2)
    return found


def check(root: Path, tag: str | None) -> str:
    """The version every manifest agrees on; with `tag`, also that it is the tag's, released."""
    found = versions(root)
    if len(set(found.values())) != 1:
        listed = "\n".join(f"  {where}: {v}" for where, v in found.items())
        raise VersionError(f"the manifests name different versions:\n{listed}")
    version = next(iter(found.values()))
    major = version.split(".")[0]
    pins = COMPOSE_IMAGE.findall((root / COMPOSE).read_text(encoding="utf-8"))
    if not pins:
        raise VersionError(f"{COMPOSE} names no ecowitt image")
    for image, pin in pins:
        if pin != major:
            raise VersionError(
                f"{COMPOSE} pins {image.split()[1]}{pin}, not {major} as {version} is"
            )
    if tag is not None:
        if tag != f"v{version}":
            raise VersionError(f"the tag is {tag}, but the manifests name {version}")
        notes(root, version)
    return version


def set_version(root: Path, version: str, today: date) -> None:
    """Write `version` into every manifest and date the Unreleased changelog section as it."""
    if not SEMVER.fullmatch(version):
        raise VersionError(f"{version} is not a version like 1.2.3")
    changelog = root / CHANGELOG
    text = changelog.read_text(encoding="utf-8")
    if UNRELEASED not in text.splitlines():
        raise VersionError(f"{CHANGELOG} has no '{UNRELEASED}' section to release")
    if not any(
        line.strip() and not line.startswith("#")
        for line in _section(text, UNRELEASED).splitlines()
    ):
        raise VersionError(f"{CHANGELOG}'s '{UNRELEASED}' section is empty")
    if re.search(rf"(?m)^## {re.escape(version)} ", text):
        raise VersionError(f"{CHANGELOG} already has a section for {version}")
    for path, patterns in PATTERNS.items():
        file = root / path
        content = file.read_text(encoding="utf-8")
        for pattern in patterns:
            content = pattern.sub(rf"\g<1>{version}\g<3>", content, count=1)
        file.write_text(content, encoding="utf-8")
    compose = root / COMPOSE
    major = version.split(".")[0]
    compose.write_text(
        COMPOSE_IMAGE.sub(rf"\g<1>{major}", compose.read_text(encoding="utf-8")), encoding="utf-8"
    )
    heading = f"## {version} — {today.isoformat()}"
    changelog.write_text(text.replace(UNRELEASED, heading, 1), encoding="utf-8")


def notes(root: Path, version: str) -> str:
    """`version`'s changelog section, without its heading."""
    text = (root / CHANGELOG).read_text(encoding="utf-8")
    match = re.search(rf"(?m)^## {re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$", text)
    if match is None:
        raise VersionError(f"{CHANGELOG} has no dated section for {version}")
    return _section(text, match.group(0)).strip() + "\n"


def _section(text: str, heading: str) -> str:
    """The text under `heading`, up to the next section's."""
    after = text.split(heading + "\n", 1)[1] if heading + "\n" in text else ""
    return re.split(r"(?m)^## ", after, maxsplit=1)[0]


def main(argv: list[str] | None = None) -> int:
    """Run one command; a VersionError is reported and exits 1."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("tag", nargs="?")
    commands.add_parser("set").add_argument("version")
    commands.add_parser("notes").add_argument("version")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"every manifest names {check(args.root, args.tag)}")
        elif args.command == "set":
            set_version(args.root, args.version, date.today())
        else:
            sys.stdout.write(notes(args.root, args.version))
    except VersionError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

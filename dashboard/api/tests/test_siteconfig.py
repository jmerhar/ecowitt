"""dashboard.yaml: what it may say, and how it is written once."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ecowitt.dashboard import siteconfig
from ecowitt.dashboard.siteconfig import AlreadyConfigured, ConfigError, SiteConfig

from .conftest import CONFIG


def test_a_complete_file_parses() -> None:
    config = siteconfig.parse(CONFIG)
    assert config.kind == "influx3"
    assert config.connection == {
        "url": "http://db:8181",
        "database": "weather",
        "token": "apiv3_read",
    }
    assert (config.title, config.stations) == ("Test weather", ())


def test_title_and_stations_are_optional() -> None:
    config = siteconfig.parse("store:\n  kind: influx3\n  url: http://db:8181\n")
    assert (config.title, config.stations) == ("Weather", ())


def test_a_written_file_reads_back() -> None:
    config = SiteConfig("influx3", {"url": "http://db:8181"}, "Façade", ("a", "b"))
    assert siteconfig.parse(config.to_yaml()) == config


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("store: [", "not valid YAML"),
        ("- a list", "expected a mapping"),
        ("store: {kind: influx3, url: 'http://db'}\ncolour: red\n", "unknown keys: colour"),
        ("title: x\n", "store must be a mapping with a kind"),
        ("store: {kind: influx3}\n", "URL is required"),
        ("store: {kind: oracle, url: 'http://db'}\n", "unknown kind of database"),
        (
            "store: {kind: influx2, url: 'http://db', org: o}\n",
            "InfluxDB 2.x cannot be read from yet",
        ),
        ("title: ''\nstore: {kind: influx3, url: 'http://db'}\n", "title must be text"),
        ("stations: a\nstore: {kind: influx3, url: 'http://db'}\n", "stations must be a list"),
    ],
)
def test_problems_are_named(text: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=problem):
        siteconfig.parse(text)


def test_a_missing_file_means_not_set_up(tmp_path: Path) -> None:
    assert siteconfig.load(tmp_path / "dashboard.yaml") is None


def test_a_broken_file_names_itself(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.yaml"
    path.write_text("title: x\n")
    with pytest.raises(ConfigError, match=f"{path}: store must be"):
        siteconfig.load(path)


def test_the_file_is_written_once_and_for_its_owner_alone(tmp_path: Path) -> None:
    path = tmp_path / "data" / "dashboard.yaml"
    config = SiteConfig("influx3", {"url": "http://db:8181", "token": "secret"})
    siteconfig.create(path, config)
    assert siteconfig.load(path) == config
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(AlreadyConfigured):
        siteconfig.create(path, SiteConfig("influx3", {"url": "http://other:8181"}))
    assert siteconfig.load(path) == config
    assert sorted(p.name for p in path.parent.iterdir()) == ["dashboard.yaml"]

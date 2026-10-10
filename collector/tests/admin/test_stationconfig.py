"""The configuration file."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecowitt.collector.admin.stationconfig import ConfigError, StationConfig, load
from ecowitt.core.units import Units

GOOD = """
units:
  temperature: f
  wind: ms
stations:
  - name: Home
    passkey: AAAA0000AAAA0000AAAA0000AAAA0000
    altitude_m: 180
    sensors:
      indoor: Lounge
      ch1: Bathroom
  - name: Cabin
    passkey: BBBB1111BBBB1111BBBB1111BBBB1111
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_full_file_loads(tmp_path: Path) -> None:
    config = load(write(tmp_path, GOOD))

    assert config.names == ["Home", "Cabin"]
    home = config.lookup("AAAA0000AAAA0000AAAA0000AAAA0000")
    assert home is not None and home.name == "Home"
    assert home.preferences.altitude_m == 180
    assert home.preferences.name_for("ch1") == "Bathroom"
    assert home.preferences.units == Units(temperature="f", wind="ms")


def test_units_are_shared_and_names_are_per_station(tmp_path: Path) -> None:
    """`ch1` at one house is not `ch1` at another; one database keeps one set of units."""
    config = load(write(tmp_path, GOOD))
    cabin = config.lookup("BBBB1111BBBB1111BBBB1111BBBB1111")

    assert cabin is not None
    assert cabin.preferences.name_for("ch1") == "ch1"
    assert cabin.preferences.altitude_m is None
    assert cabin.preferences.units.temperature == "f"


def test_an_unknown_passkey_belongs_to_nobody(tmp_path: Path) -> None:
    config = load(write(tmp_path, GOOD))

    assert config.lookup("CCCC") is None
    assert config.lookup("") is None


def test_lookup_compares_every_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No early exit, so timing does not reveal which entry matched."""
    config = load(write(tmp_path, GOOD))
    calls: list[str] = []
    import ecowitt.collector.admin.stationconfig as sc

    real = sc.hmac.compare_digest
    monkeypatch.setattr(sc.hmac, "compare_digest", lambda a, b: calls.append("x") or real(a, b))

    config.lookup("AAAA0000AAAA0000AAAA0000AAAA0000")

    assert len(calls) == 2


def test_a_missing_file_accepts_no_one(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The normal state of a fresh install, and it says so."""
    config = load(tmp_path / "absent.yaml")

    assert config == StationConfig()
    assert "no configuration" in caplog.text


def test_an_empty_file_is_an_empty_configuration(tmp_path: Path) -> None:
    assert load(write(tmp_path, "")).names == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("stations: [", "while parsing"),
        ("stattions: []", "stattions"),
        ("units: {temperature: k}", "'c' or 'f'"),
        ("stations: [{name: A}]", "passkey"),
        ("stations: [{name: '', passkey: x}]", "name"),
        ("stations: [{name: A, passkey: x}, {name: A, passkey: y}]", "share a name"),
        ("stations: [{name: A, passkey: x}, {name: B, passkey: x}]", "share a passkey"),
        ("stations: [{name: A, passkey: x, colour: red}]", "colour"),
        ("- just a list", "valid dictionary"),
    ],
)
def test_a_malformed_file_is_refused_with_the_reason(
    tmp_path: Path, text: str, reason: str
) -> None:
    """Running on with no stations would discard every report while looking healthy."""
    with pytest.raises(ConfigError, match=reason):
        load(write(tmp_path, text))


def test_a_station_takes_its_zone_from_its_coordinates() -> None:
    from ecowitt.collector.admin.stationconfig import ConfigDocument, StationEntry, build

    entry = StationEntry(name="Home", passkey="A", latitude=38.72, longitude=-9.14)

    (station,) = build(ConfigDocument(stations=[entry])).stations
    assert station.timezone == "Europe/Lisbon"


def test_a_configured_zone_wins_over_the_coordinates() -> None:
    from ecowitt.collector.admin.stationconfig import ConfigDocument, StationEntry, build

    entry = StationEntry(name="Home", passkey="A", latitude=38.72, longitude=-9.14, timezone="UTC")

    (station,) = build(ConfigDocument(stations=[entry])).stations
    assert station.timezone == "UTC"


def test_without_coordinates_or_a_zone_there_is_none() -> None:
    from ecowitt.collector.admin.stationconfig import ConfigDocument, StationEntry, build

    (station,) = build(ConfigDocument(stations=[StationEntry(name="Home", passkey="A")])).stations
    assert station.timezone is None


def test_an_unknown_zone_name_is_refused() -> None:
    from pydantic import ValidationError

    from ecowitt.collector.admin.stationconfig import StationEntry

    with pytest.raises(ValidationError, match="Europe/Lisbon"):
        StationEntry(name="Home", passkey="A", timezone="Europe/Atlantis")


def test_the_database_connection_is_saved_beside_its_kind(tmp_path: Path) -> None:
    from ecowitt.collector.admin.stationconfig import (
        ConfigDocument,
        StoreEntry,
        load_document,
        save_document,
    )

    entry = StoreEntry(kind="influx2", url="http://influx:8086", org="home", token="t")  # type: ignore[call-arg]
    save_document(tmp_path / "config.yaml", ConfigDocument(store=entry))

    text = (tmp_path / "config.yaml").read_text()
    loaded = load_document(tmp_path / "config.yaml").store
    assert "kind: influx2" in text and "org: home" in text
    assert loaded is not None and loaded.connection == {
        "url": "http://influx:8086",
        "org": "home",
        "token": "t",
    }


@pytest.mark.parametrize(
    ("store", "problem"),
    [
        ("{kind: sqlite}", "unknown kind"),
        ("{kind: influx3}", "URL is required"),
        ("{kind: influx3, url: 'http://x', bucket: y}", "bucket is not a setting"),
    ],
)
def test_a_connection_the_kind_would_not_accept_stops_startup(
    tmp_path: Path, store: str, problem: str
) -> None:
    (tmp_path / "config.yaml").write_text(f"store: {store}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=problem):
        load(tmp_path / "config.yaml")

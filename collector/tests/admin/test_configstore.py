"""Saving and applying configuration changes."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from ecowitt.collector.admin.configstore import ConfigStore
from ecowitt.collector.admin.stationconfig import (
    AdminLogin,
    ConfigDocument,
    StationEntry,
    load_document,
    save_document,
)
from ecowitt.core.units import Units


def entry(name: str = "Home", passkey: str = "AAAA", **kw: object) -> StationEntry:
    return StationEntry(name=name, passkey=passkey, **kw)  # type: ignore[arg-type]


def test_a_document_survives_a_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    document = ConfigDocument(
        units=Units(temperature="f"),
        stations=[
            entry(
                altitude_m=180.0,
                latitude=45.0,
                longitude=7.0,
                sensors={"ch7": "Zoë's room"},
                dismissed={"location": 0.0},
            )
        ],
        admin=AdminLogin(username="admin", password_hash="scrypt$x"),
    )

    save_document(path, document)

    assert load_document(path) == document
    assert "Zoë's room" in path.read_text(encoding="utf-8")


def test_the_saved_file_is_owner_only_and_tidy(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_document(path, ConfigDocument(stations=[entry()]))

    text = path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "sensors" not in text and "dismissed" not in text and "null" not in text
    assert text.startswith("# Ecowitt Server configuration")


def test_a_crash_mid_save_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ecowitt.collector.admin.stationconfig as sc

    path = tmp_path / "config.yaml"
    save_document(path, ConfigDocument(stations=[entry("Old")]))
    monkeypatch.setattr(sc.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk gone")))

    with pytest.raises(OSError):
        save_document(path, ConfigDocument(stations=[entry("New")]))

    assert load_document(path).stations[0].name == "Old"


def test_replace_saves_then_applies_and_notifies(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    seen: list[list[str]] = []
    store.subscribe(lambda stations: seen.append(stations.names))

    store.replace(ConfigDocument(stations=[entry()]))

    assert seen == [[], ["Home"]]
    assert store.stations.lookup("AAAA") is not None
    assert load_document(store.path).stations[0].name == "Home"


def test_an_invalid_document_changes_nothing(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.replace(ConfigDocument(stations=[entry()]))
    bad = ConfigDocument.model_construct(
        units=Units(), stations=[entry("A", "K"), entry("B", "K")], admin=None
    )

    with pytest.raises(ValidationError):
        store.replace(bad)

    assert store.stations.names == ["Home"]
    assert load_document(store.path).stations[0].name == "Home"


def test_a_document_that_cannot_be_saved_is_not_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ecowitt.collector.admin.configstore as cs

    store = ConfigStore(tmp_path / "config.yaml")
    monkeypatch.setattr(cs, "save_document", lambda *_: (_ for _ in ()).throw(OSError("read-only")))

    with pytest.raises(OSError):
        store.replace(ConfigDocument(stations=[entry()]))

    assert store.stations.names == []


@pytest.mark.parametrize(
    ("field", "value"), [("latitude", 91), ("latitude", -91), ("longitude", 181)]
)
def test_impossible_coordinates_are_refused(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        entry(**{field: value})


def test_station_lookup_by_name(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.yaml")
    store.replace(ConfigDocument(stations=[entry(latitude=1.0, longitude=2.0)]))

    assert store.document.station("Home") is not None
    assert store.document.station("Nope") is None
    assert store.stations.get("Home").located  # type: ignore[union-attr]
    assert store.stations.get("Nope") is None

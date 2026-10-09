"""Settings resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecowitt.config import Settings


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("/data/report/", ("/data/report", "/data/report/")),
        ("/data/report", ("/data/report", "/data/report/")),
        ("data/report", ("/data/report", "/data/report/")),
        ("/", ("/",)),
    ],
)
def test_both_slash_spellings_are_derived(configured: str, expected: tuple[str, ...]) -> None:
    """However the path is written, both spellings are served and the leading slash is added."""
    assert Settings(ingest_path=configured).ingest_paths == expected


def test_a_token_file_supplies_the_token(tmp_path: Path) -> None:
    """A Docker secret keeps the value out of the compose file."""
    token_file = tmp_path / "token"
    token_file.write_text("apiv3_from-a-file\n", encoding="utf-8")

    settings = Settings(influx_token_file=token_file)

    assert settings.influx_token == "apiv3_from-a-file"


def test_an_unreadable_token_file_is_an_error(tmp_path: Path) -> None:
    """Naming a file excludes the alternatives, so a missing one must not fall back.

    Falling back to the empty default would surface much later, as an authentication failure
    against InfluxDB, with nothing pointing at the real cause.
    """
    with pytest.raises(Exception, match="No such file"):
        Settings(influx_token_file=tmp_path / "absent")


def test_derived_paths_sit_under_the_data_directory(tmp_path: Path) -> None:
    """Everything mutable lives in one directory, so backing it up is enough."""
    settings = Settings(data_dir=tmp_path)

    assert settings.config_file == tmp_path / "config.yaml"
    assert settings.spool_dir == tmp_path / "spool"


@pytest.mark.parametrize("field", ["influx_token_file", "heartbeat_url_file"])
def test_an_empty_optional_path_is_treated_as_unset(field: str) -> None:
    """Compose passes an unset `${VAR:-}` through as an empty string.

    Resolved as a path that would be `Path(".")`, and reading a credential from the working
    directory fails with IsADirectoryError -- at startup, in a restart loop, which is how this
    surfaced.
    """
    settings = Settings(**{field: ""})

    assert getattr(settings, field) is None


def test_a_heartbeat_url_file_supplies_the_url(tmp_path: Path) -> None:
    """The push URL carries the monitor's token, so a Docker secret can hold it."""
    url_file = tmp_path / "heartbeat"
    url_file.write_text("http://monitor:3001/api/push/token\n", encoding="utf-8")

    settings = Settings(heartbeat_url_file=url_file)

    assert settings.heartbeat_url == "http://monitor:3001/api/push/token"


def test_an_unreadable_heartbeat_url_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Settings(heartbeat_url_file=tmp_path / "absent")


def test_an_empty_token_file_does_not_blank_an_inline_token() -> None:
    """An empty file variable must not displace a token given directly."""
    settings = Settings(influx_token="apiv3_inline", influx_token_file="")

    assert settings.influx_token == "apiv3_inline"


def test_published_and_listening_ports_match_by_default() -> None:
    """Firewalls that see Docker traffic match the container's port, so the two must agree."""
    settings = Settings()

    assert (settings.ingest_port, settings.admin_port) == (2551, 2552)

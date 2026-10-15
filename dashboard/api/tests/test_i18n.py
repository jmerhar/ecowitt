"""The languages the API answers in: their catalogues, and the choice of one for a request."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from ecowitt.dashboard import i18n, messages

from .conftest import REPO

CATALOGUES = sorted(i18n.LOCALE_DIR.glob("*/LC_MESSAGES/messages.po"))


def test_european_portuguese_is_loaded_from_the_package() -> None:
    """The catalogue ships inside the package: one kept anywhere else would leave an installed
    dashboard answering in English without a word of complaint."""
    assert Path(i18n.__file__).parent / "locale" == i18n.LOCALE_DIR
    assert list(i18n.LANGUAGES) == ["en", "pt-PT"]
    assert i18n.LANGUAGES["pt-PT"].text("sky", "Overcast") == "Céu encoberto"


@pytest.mark.parametrize("po", CATALOGUES, ids=lambda po: po.parents[1].name)
def test_every_catalogue_is_current(po: Path) -> None:
    assert i18n.updated(messages.template(), po) == po.read_bytes(), (
        f"{po.parents[1].name} is out of date: run .venv/bin/python bin/messages.py"
    )


@pytest.mark.parametrize("po", CATALOGUES, ids=lambda po: po.parents[1].name)
def test_every_message_is_translated_with_its_placeholders(po: Path) -> None:
    with po.open("rb") as source:
        catalog = read_po(source)
    problems = []
    for message in catalog:
        if not message.id:
            continue
        sources = [message.id] if isinstance(message.id, str) else list(message.id)
        strings = [message.string] if isinstance(message.string, str) else list(message.string)
        wanted = set(re.findall(r"{\w+}", sources[0]))
        for string in strings:
            if not string or message.fuzzy:
                problems.append(f"untranslated: {message.context} / {sources[0]}")
            elif set(re.findall(r"{\w+}", string)) != wanted:
                problems.append(f"placeholders differ: {message.context} / {string}")
            else:
                # The API formats every message, so a stray brace would fail every answer that
                # says it.
                try:
                    string.format(**{name.strip("{}"): "x" for name in wanted})
                except ValueError, IndexError, KeyError:
                    problems.append(f"cannot be formatted: {message.context} / {string}")
    assert problems == []


def test_the_script_starts_and_updates_catalogues(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("messages_script", REPO / "bin" / "messages.py")
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    script.main(["--dir", str(tmp_path), "--add", "nl"])
    po = tmp_path / "nl" / "LC_MESSAGES" / "messages.po"
    first = po.read_bytes()
    script.main(["--dir", str(tmp_path)])

    assert po.read_bytes() == first, "an unchanged catalogue is not rewritten differently"
    assert b'msgctxt "sky"\nmsgid "Overcast"\nmsgstr ""' in first
    assert b"Language-Team: Dutch" in first and b"#, fuzzy" not in first


def test_a_catalogue_keeps_its_translations_and_drops_removed_messages(tmp_path: Path) -> None:
    po = tmp_path / "nl" / "LC_MESSAGES" / "messages.po"
    po.parent.mkdir(parents=True)
    po.write_bytes(i18n.updated(messages.template(), po))
    with po.open("rb") as source:
        catalog = read_po(source)
    catalog.get("Overcast", context="sky").string = "Bewolkt"
    catalog.add("Gone", "Weg", context="sky")
    from babel.messages.pofile import write_po

    with po.open("wb") as target:
        write_po(target, catalog)

    updated = i18n.updated(messages.template(), po).decode()

    assert 'msgid "Overcast"\nmsgstr "Bewolkt"' in updated
    assert "Gone" not in updated


def test_a_fuzzy_translation_is_not_used(tmp_path: Path) -> None:
    po = tmp_path / "nl" / "LC_MESSAGES" / "messages.po"
    po.parent.mkdir(parents=True)
    po.write_text(
        'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
        'msgctxt "sky"\nmsgid "Fog"\nmsgstr "Mist"\n\n'
        '#, fuzzy\nmsgctxt "sky"\nmsgid "Rain"\nmsgstr "Regen?"\n',
        encoding="utf-8",
    )

    dutch = i18n.load(tmp_path)["nl"]

    assert (dutch.text("sky", "Fog"), dutch.text("sky", "Rain")) == ("Mist", "Rain")


@pytest.mark.parametrize(
    ("requested", "header", "tag"),
    [
        (None, None, "en"),
        ("pt-PT", None, "pt-PT"),
        ("PT-pt", None, "pt-PT"),
        ("pt", None, "pt-PT"),
        ("pt-BR", None, "pt-PT"),
        ("en", "pt-PT", "en"),
        ("xx", "pt-PT,en;q=0.5", "pt-PT"),
        (None, "pt-PT,pt;q=0.9,en;q=0.8", "pt-PT"),
        (None, "de, en;q=0.9, pt;q=0.8", "en"),
        (None, "en;q=0.4, pt;q=0.6", "pt-PT"),
        (None, "pt;q=0, en", "en"),
        (None, "pt;q=0, de", "en"),
        (None, "*", "en"),
        (None, "pt;q=high, en;q=0.1", "en"),
        (None, "de, fr", "en"),
        (None, "", "en"),
        ("pt_PT", None, "pt-PT"),
        (None, "en;Q=0.1, pt;q=0.9", "pt-PT"),
        (None, "pt-PT;q=1;level=1", "pt-PT"),
        (None, "pt;q=, en;q=0.5", "en"),
    ],
)
def test_the_language_is_the_one_asked_for_else_accepted_else_english(
    requested: str | None, header: str | None, tag: str
) -> None:
    assert i18n.negotiate(requested, header).tag == tag


def test_equally_preferred_languages_keep_their_order() -> None:
    assert i18n.accepted("pt, en, *;q=0.5, de;q=0.5") == ["pt", "en", "de"]


@pytest.mark.parametrize(
    ("language", "value", "words"),
    [
        ("en", 2.4, "2.4"),
        ("pt-PT", 2.4, "2,4"),
        ("en", 1012.0, "1012"),
        ("pt-PT", -5.0, "-5"),
        ("pt-PT", -0.0, "0"),
    ],
)
def test_numbers_follow_the_language_without_grouping(
    language: str, value: float, words: str
) -> None:
    assert i18n.LANGUAGES[language].number(value) == words


@pytest.mark.parametrize(("hour", "words"), [(0, "às 00:30"), (1, "à 01:30"), (13, "às 13:30")])
def test_a_time_takes_the_article_its_hour_needs(hour: int, words: str) -> None:
    from datetime import datetime

    local = datetime(2026, 10, 10, hour, 30)
    text = messages.notice_at(
        i18n.LANGUAGES["pt-PT"], messages.NoticeCode.GUSTS_FORECAST, local, False, value="72 km/h"
    )
    assert text == f"Rajadas até 72 km/h {words}."

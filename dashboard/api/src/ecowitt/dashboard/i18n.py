"""The languages the API answers in, and the choice of one for a request.

English is the language every message is written in. Each other language is a gettext catalogue,
`locale/<locale>/LC_MESSAGES/messages.po`, which Babel reads and compiles when the module loads, so
no compiled file is kept beside it.
"""

from __future__ import annotations

import gettext
import io
from dataclasses import dataclass
from pathlib import Path

from babel import Locale
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po
from babel.numbers import format_decimal

LOCALE_DIR = Path(__file__).parent / "locale"
DOMAIN = "messages"


@dataclass(frozen=True)
class Language:
    """One language an answer can be in."""

    #: Its BCP 47 tag, as Content-Language gives it: "en", "pt-PT".
    tag: str
    locale: Locale
    translations: gettext.NullTranslations

    def text(self, context: str, message: str) -> str:
        """A message in this language; the message itself where the catalogue lacks it."""
        return self.translations.pgettext(context, message)

    def text_at_hour(self, context: str, message: str, hour: int) -> str:
        """A message that names a time of day, in the form its hour takes: a language whose
        article agrees with the hour ("à 01:00", "às 02:00") has one per plural form."""
        return self.translations.npgettext(context, message, message, hour)

    def number(self, value: float) -> str:
        """A number by this language's rules, without grouping: "2.4", "2,4", "1012"."""
        return format_decimal(value, locale=self.locale, group_separator=False)


#: English, which every message is written in; numbers as in British English.
ENGLISH = Language("en", Locale.parse("en_GB"), gettext.NullTranslations())


def load(directory: Path = LOCALE_DIR) -> dict[str, Language]:
    """Every language there is: English, and one per catalogue in `directory`, by tag."""
    found = {ENGLISH.tag: ENGLISH}
    for po in sorted(directory.glob(f"*/LC_MESSAGES/{DOMAIN}.po")):
        locale = Locale.parse(po.parents[1].name)
        with po.open("rb") as source:
            catalog = read_po(source, locale=locale, domain=DOMAIN)
        compiled = io.BytesIO()
        write_mo(compiled, catalog)
        compiled.seek(0)
        tag = "-".join(part for part in (locale.language, locale.territory) if part)
        found[tag] = Language(tag, locale, gettext.GNUTranslations(compiled))
    return found


LANGUAGES = load()


def updated(template: Catalog, po: Path) -> bytes:
    """A catalogue brought up to date with `template`, as its file would read: new messages
    added untranslated, removed ones dropped, and translations kept. No translation is guessed
    from a similar message, and the file's dates are kept, so an unchanged catalogue reads the
    same."""
    locale = Locale.parse(po.parents[1].name)
    if po.is_file():
        with po.open("rb") as source:
            catalog = read_po(source, locale=locale, domain=DOMAIN)
    else:
        catalog = Catalog(
            locale=locale,
            domain=DOMAIN,
            header_comment=f"# {locale.english_name} for the Ecowitt Server dashboard's API.\n"
            "# Kept up to date with its messages by bin/messages.py.",
            project=template.project,
            version="1",
            msgid_bugs_address="https://github.com/jmerhar/ecowitt/issues",
            last_translator="Ecowitt Server",
            language_team=locale.english_name,
            fuzzy=False,
        )
    template.creation_date = catalog.creation_date
    catalog.update(template, no_fuzzy_matching=True)
    catalog.obsolete.clear()
    written = io.BytesIO()
    write_po(written, catalog, width=96)
    return written.getvalue()


def negotiate(
    requested: str | None,
    accept_language: str | None,
    languages: dict[str, Language] = LANGUAGES,
) -> Language:
    """The language to answer in: the one asked for by name, else the first the client accepts,
    else English. A tag matches its language exactly or, failing that, by its first part, so
    "pt" and "pt-BR" are answered in the Portuguese there is."""
    for tag in ([requested] if requested else []) + accepted(accept_language):
        found = _match(tag, languages)
        if found is not None:
            return found
    return ENGLISH


def accepted(header: str | None) -> list[str]:
    """The languages an Accept-Language header names, most preferred first; none it refuses
    (q=0) and no wildcard."""
    ranked = []
    for position, entry in enumerate((header or "").split(",")):
        tag, _, rest = entry.strip().partition(";")
        weight = 1.0
        if rest.strip().startswith("q="):
            try:
                weight = float(rest.strip()[2:])
            except ValueError:
                continue
        if tag and tag != "*" and weight > 0:
            ranked.append((-weight, position, tag))
    return [tag for _, _, tag in sorted(ranked)]


def _match(tag: str, languages: dict[str, Language]) -> Language | None:
    """The language a tag names, exactly or by its first part; None if there is none."""
    wanted = tag.strip().lower()
    for candidate in languages.values():
        if candidate.tag.lower() == wanted:
            return candidate
    first = wanted.split("-")[0]
    return next((c for c in languages.values() if c.tag.lower().split("-")[0] == first), None)

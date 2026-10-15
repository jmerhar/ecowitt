#!/usr/bin/env python3
"""Bring the dashboard API's gettext catalogues up to date with the messages it says.

    .venv/bin/python bin/messages.py [--add LOCALE] [--dir DIR]

Each catalogue, dashboard/api/src/ecowitt/dashboard/locale/<locale>/LC_MESSAGES/messages.po,
gains the messages added since it was last updated, untranslated, and loses the ones removed.
Run it after changing a message, then translate what it added; a test fails until every
catalogue is current and fully translated. `--add pt_PT` starts a catalogue for a new language.
It needs the virtualenv's interpreter, which has the dashboard installed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ecowitt.dashboard import i18n, messages


def main(argv: list[str] | None = None) -> None:
    """Update every catalogue, and start the one `--add` names."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--add", metavar="LOCALE", help="start a catalogue, as pt_PT")
    parser.add_argument("--dir", type=Path, default=i18n.LOCALE_DIR)
    args = parser.parse_args(argv)
    catalogues = sorted(args.dir.glob(f"*/LC_MESSAGES/{i18n.DOMAIN}.po"))
    if args.add:
        catalogues.append(args.dir / args.add / "LC_MESSAGES" / f"{i18n.DOMAIN}.po")
    for po in dict.fromkeys(catalogues):
        content = i18n.updated(messages.template(), po)
        if po.is_file() and po.read_bytes() == content:
            continue
        po.parent.mkdir(parents=True, exist_ok=True)
        po.write_bytes(content)
        print(f"wrote {po}")


if __name__ == "__main__":
    main()

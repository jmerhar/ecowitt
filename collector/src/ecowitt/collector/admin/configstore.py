"""The configuration as the running process holds it: one document, saved and applied together.

The setup page changes the configuration while reports are arriving. Every change goes
through `replace`, which validates the new document, writes it, and only then swaps it in and
tells whoever depends on it -- so the file on disk and what the process is acting on never
disagree, and a change that cannot be saved is not applied either.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ecowitt.collector.admin.stationconfig import (
    ConfigDocument,
    StationConfig,
    build,
    load_document,
    save_document,
)


class ConfigStore:
    """The current configuration document and its runtime form."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.document = load_document(path)
        self.stations: StationConfig = build(self.document)
        self._listeners: list[Callable[[StationConfig], None]] = []

    def subscribe(self, listener: Callable[[StationConfig], None]) -> None:
        """Call `listener` with the runtime configuration now and after every change."""
        self._listeners.append(listener)
        listener(self.stations)

    def replace(self, document: ConfigDocument) -> None:
        """Validate, save and apply a new document, in that order.

        Raises if the document is invalid or cannot be written, leaving everything as it was.
        """
        validated = ConfigDocument.model_validate(document.model_dump())
        stations = build(validated)
        save_document(self.path, validated)
        self.document, self.stations = validated, stations
        for listener in self._listeners:
            listener(stations)

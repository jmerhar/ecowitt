"""The ecowitt namespace: no project may claim it with an ecowitt/__init__.py.

core, collector and dashboard each ship one part of `ecowitt`. A package-level __init__.py in any
of them would make that project own the whole name, and the others' parts would stop importing
-- which of them depending on install order.
"""

from __future__ import annotations

from pathlib import Path

import ecowitt


def test_ecowitt_is_a_namespace_with_no_init() -> None:
    portions = [Path(p) for p in ecowitt.__path__]

    assert portions
    assert not [p for p in portions if (p / "__init__.py").exists()]
    assert getattr(ecowitt, "__file__", None) is None

"""The Grafana dashboard and alert rules, rendered for the units the collector stores.

The templates beside this module are the two files with every spot that depends on the units
written as a placeholder, ``%{...}`` -- a spelling neither Grafana's ``${variable}`` and
``$__macro`` nor the rules' Go templates (``{{ ... }}``) use:

``%{temp_c}``
    a field, written by its name in the default units; renders as the stored name (``temp_f``).
``%{8 temperature}``
    a number in the default units, converted (``46.4``). ``temperature_delta`` converts a
    difference, which has no offset.
``%{unit speed}``, ``%{symbol speed}``, ``%{decimals pressure}``
    Grafana's display unit, the symbol for prose, and the decimal places worth showing.

A string that is nothing but a number or ``decimals`` placeholder renders as a JSON number, so
a threshold can be written ``"%{60 speed}"`` where Grafana expects ``60``. Rendered for the
default units, the templates are the files in the repository's ``grafana/`` directory.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from ecowitt.core.units import DECIMALS, SYMBOLS, Kind, Units, convert, field_name, from_canonical

TEMPLATES = Path(__file__).parent

#: The quantities a placeholder can name.
KINDS: dict[str, Kind] = {
    "temperature": Kind.TEMPERATURE,
    "temperature_delta": Kind.TEMPERATURE_DELTA,
    "pressure": Kind.PRESSURE,
    "rain": Kind.RAIN,
    "rain_rate": Kind.RAIN_RATE,
    "speed": Kind.SPEED,
}

#: Every field the templates name whose stored name depends on the units, by its default name.
FIELDS: dict[str, tuple[str, Kind]] = {
    "temp_c": ("temp", Kind.TEMPERATURE),
    "dewpoint_c": ("dewpoint", Kind.TEMPERATURE),
    "temp_min_c": ("temp_min", Kind.TEMPERATURE),
    "temp_max_c": ("temp_max", Kind.TEMPERATURE),
    "dewpoint_delta_c": ("dewpoint_delta", Kind.TEMPERATURE_DELTA),
    "sea_hpa": ("sea", Kind.PRESSURE),
    "rel_error_hpa": ("rel_error", Kind.PRESSURE),
    "speed_kmh": ("speed", Kind.SPEED),
    "gust_kmh": ("gust", Kind.SPEED),
    "gust_max_kmh": ("gust_max", Kind.SPEED),
    "rate_mm_h": ("rate", Kind.RAIN_RATE),
    "daily_mm": ("daily", Kind.RAIN),
    "last24h_mm": ("last24h", Kind.RAIN),
    "monthly_mm": ("monthly", Kind.RAIN),
    "precip_1h_mm": ("precip_1h", Kind.RAIN),
    "precip_mm": ("precip", Kind.RAIN),
}

#: Grafana's display unit for each stored unit, by field suffix. Grafana has no millimetres of
#: mercury, and rain reads better as a plain suffix than as its length units.
GRAFANA_UNITS: dict[str, str] = {
    "c": "celsius",
    "f": "fahrenheit",
    "hpa": "pressurehpa",
    "inhg": "pressurehg",
    "mmhg": "suffix: mmHg",
    "mm": "suffix: mm",
    "in": "suffix: in",
    "mm_h": "suffix: mm/h",
    "in_h": "suffix: in/h",
    "kmh": "velocitykmh",
    "ms": "velocityms",
    "mph": "velocitymph",
    "kn": "velocityknot",
}

PLACEHOLDER = re.compile(r"%\{([^}]*)\}")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class UnknownPlaceholder(ValueError):
    """Raised for a placeholder this module cannot render: a typo in a template."""


def dashboard(units: Units) -> dict[str, Any]:
    """The dashboard for a collector storing `units`."""
    return render(_load("weather.template.json"), units)


def alerts(units: Units) -> dict[str, Any]:
    """The alert rules, as a provisioning file, for a collector storing `units`."""
    return render(_load("alerts.template.json"), units)


def dumps(document: dict[str, Any]) -> str:
    """A rendered file as the repository keeps it: two-space indents, UTF-8, a final newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render(node: Any, units: Units) -> Any:
    """A template, or any part of one, with every placeholder replaced for `units`."""
    if isinstance(node, dict):
        return {key: render(value, units) for key, value in node.items()}
    if isinstance(node, list):
        return [render(value, units) for value in node]
    if isinstance(node, str):
        return _render_string(node, units)
    return node


def _render_string(text: str, units: Units) -> Any:
    """A string's placeholders replaced; a lone number placeholder becomes the number itself."""
    whole = PLACEHOLDER.fullmatch(text)
    if whole:
        value = _resolve(whole.group(1), units)
        if not isinstance(value, str):
            return value
    return PLACEHOLDER.sub(lambda m: _text(_resolve(m.group(1), units)), text)


def _resolve(spec: str, units: Units) -> str | int | float:
    """What one placeholder stands for: a field name, a number, a unit, a symbol or decimals."""
    words = spec.split()
    if len(words) == 1:
        if words[0] not in FIELDS:
            raise UnknownPlaceholder(f"no field %{{{spec}}}")
        base, kind = FIELDS[words[0]]
        return field_name(base, kind, units)
    if len(words) != 2 or words[1] not in KINDS:
        raise UnknownPlaceholder(f"cannot render %{{{spec}}}")
    what, kind = words[0], KINDS[words[1]]
    suffix = from_canonical(kind, 0.0, units)[1]
    if what == "unit":
        return GRAFANA_UNITS[suffix]
    if what == "symbol":
        return SYMBOLS[suffix]
    if what == "decimals":
        return DECIMALS.get(suffix, 1)
    if NUMBER.fullmatch(what):
        return _significant(convert(kind, float(what), Units(), units))
    raise UnknownPlaceholder(f"cannot render %{{{spec}}}")


def _significant(value: float) -> int | float:
    """A converted number to three significant figures, whole numbers without a fraction.

    Three figures keep a threshold as exact as the reading it is compared with, and undo the
    float noise a conversion round trip leaves (60 km/h comes back as 60.00000000000001).
    """
    if value == 0:
        return 0
    rounded = round(value, 2 - math.floor(math.log10(abs(value))))
    return int(rounded) if rounded == int(rounded) else rounded


def _text(value: str | int | float) -> str:
    """A resolved placeholder as it reads inside a longer string."""
    return value if isinstance(value, str) else f"{value:g}"


def _load(name: str) -> Any:
    """A template, parsed."""
    return json.loads((TEMPLATES / name).read_text(encoding="utf-8"))

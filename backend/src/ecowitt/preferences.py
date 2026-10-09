"""What the operator has said about their station: units, names and where it is.

Loaded from the configuration file the setup wizard writes; built directly in tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .units import Units


@dataclass(frozen=True)
class Preferences:
    """How readings are named, converted and reduced."""

    units: Units = field(default_factory=Units)
    #: Display names keyed by sensor identifier -- `{"indoor": "Lounge", "ch1": "Bathroom"}`.
    #: Written as the `name` tag. Renaming a sensor therefore starts a new series under the new
    #: name, which is why dashboards should group by the stable `sensor` or `channel` tag and
    #: use `name` only for labels.
    names: Mapping[str, str] = field(default_factory=dict)
    #: Height of the barometer above sea level, in metres. Without it there is no sea-level
    #: pressure and no check of the console's own calibration.
    altitude_m: float | None = None

    def name_for(self, sensor: str) -> str:
        """The display name for a sensor, falling back to its identifier.

        Falling back rather than omitting the tag keeps every row of a named table carrying the
        same tag set, so naming a sensor later is a change of value and not of shape.
        """
        return self.names.get(sensor) or sensor

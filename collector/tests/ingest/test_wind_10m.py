"""Wind estimated at 10 m: scaled from the sensor, or the weather model's while the cups stall."""

from __future__ import annotations

import pytest

from ecowitt.collector.ingest.derive import derive
from ecowitt.collector.ingest.staleness import StalenessTracker
from ecowitt.core.preferences import Preferences
from ecowitt.core.readings import Reading
from ecowitt.core.units import Kind
from ecowitt.core.windheight import ModelWind

NOW = 1791720000


def wind(speed: float, gust: float = 5.0, **more: float) -> list[Reading]:
    """A report's wind readings, in m/s."""
    fields = {"speed": speed, "gust": gust, **more}
    return [Reading("wind", f, Kind.SPEED, v, sensor="wind") for f, v in fields.items()]


def estimate(
    readings: list[Reading],
    factor: float = 2.0,
    model: ModelWind | None = None,
    fallback: bool = True,
) -> dict[str, object]:
    derived = derive(
        readings,
        Preferences(wind_factor=factor, wind_model_fallback=fallback),
        StalenessTracker(),
        station="Home",
        timestamp=NOW,
        model_wind=model,
    )
    return {r.field: r.value for r in derived if r.table == "wind_10m"}


def test_the_sensors_wind_scaled_by_the_factor() -> None:
    """The speeds are doubled; the gust rose 3 m/s above the speed, and does so at 10 m too. The
    day's strongest gust has no estimate: the highest of the gusts' estimates is that."""
    found = estimate(wind(3.0, 6.0, speed_avg10m=2.5, max_daily_gust=9.0))

    assert found == {"speed": 6.0, "gust": 9.0, "speed_avg10m": 5.0, "source": "sensor"}


def test_a_gust_reported_below_the_speed_is_the_speed() -> None:
    """Measured over different spans, a gust can read below the speed; it is never less wind."""
    assert estimate(wind(3.0, 2.5))["gust"] == 6.0


def test_with_no_correction_the_estimate_is_the_measurement() -> None:
    assert estimate(wind(3.0), factor=1.0)["speed"] == 3.0


def test_stalled_cups_take_the_models_wind() -> None:
    model = ModelWind(NOW - 600, 4.2, 9.1)

    found = estimate(wind(0.4, 1.0, speed_avg10m=0.2, max_daily_gust=8.0), model=model)

    assert found == {"speed": 4.2, "gust": 9.1, "speed_avg10m": 4.2, "source": "model"}


def test_turning_cups_keep_the_sensor_however_light() -> None:
    assert estimate(wind(1.0), model=ModelWind(NOW, 4.2, 9.1))["source"] == "sensor"


def test_without_a_model_gust_the_sensors_gust_stays() -> None:
    found = estimate(wind(0.0, 0.5), model=ModelWind(NOW, 4.2, None))

    # And a report without a 10-minute average gets none from the model.
    assert found == {"speed": 4.2, "gust": 0.5, "source": "model"}


@pytest.mark.parametrize(
    "model", [None, ModelWind(NOW - 1801, 4.2, 9.1), ModelWind(NOW + 1801, 4.2, 9.1)]
)
def test_stalled_cups_with_no_recent_model_stay_the_sensors(model: ModelWind | None) -> None:
    """A model value more than half an hour from the report says nothing about it."""
    found = estimate(wind(0.0), model=model)

    assert (found["speed"], found["source"]) == (0.0, "sensor")


def test_no_wind_speed_no_estimate() -> None:
    assert estimate([Reading("wind", "dir", Kind.ANGLE, 90.0, sensor="wind")]) == {}


def test_with_the_fallback_off_stalled_cups_stay_the_sensors() -> None:
    found = estimate(wind(0.4, 1.0), model=ModelWind(NOW, 4.2, 9.1), fallback=False)

    assert found == {"speed": 0.8, "gust": 1.4, "source": "sensor"}

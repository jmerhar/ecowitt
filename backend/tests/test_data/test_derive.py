"""Derived quantities: moisture, ventilation, sea-level pressure and staleness."""

from __future__ import annotations

import pytest

from ecowitt import psychro
from ecowitt.derive import derive
from ecowitt.preferences import Preferences
from ecowitt.readings import Reading
from ecowitt.staleness import StalenessTracker
from ecowitt.units import Kind

T, H = Kind.TEMPERATURE, Kind.HUMIDITY


def climate(sensor: str, temp: float, humidity: float, table: str = "channel") -> list[Reading]:
    """A sensor's temperature and humidity readings."""
    return [
        Reading(table, "temp", T, temp, sensor=sensor),
        Reading(table, "humidity", H, humidity, sensor=sensor),
    ]


def run(
    readings: list[Reading], prefs: Preferences | None = None, timestamp: int = 1000
) -> list[Reading]:
    return derive(
        readings, prefs or Preferences(), StalenessTracker(), station="s", timestamp=timestamp
    )


def values(readings: list[Reading], table: str, sensor: str) -> dict[str, object]:
    return {r.field: r.value for r in readings if r.table == table and r.sensor == sensor}


def test_moisture_quantities_for_every_sensor_with_both_readings() -> None:
    """Each temperature/humidity pair gets the four moisture quantities."""
    readings = [
        *climate("ch1", 20.0, 50.0),
        Reading("pressure", "abs", Kind.PRESSURE, 1013.25, sensor="pressure"),
    ]

    got = values(run(readings), "derived", "ch1")

    assert got["dewpoint"] == pytest.approx(psychro.dew_point(20.0, 50.0))
    assert got["abs_humidity"] == pytest.approx(psychro.absolute_humidity(20.0, 50.0))
    assert got["vpd"] == pytest.approx(psychro.vapour_pressure_deficit(20.0, 50.0))
    assert got["mixing_ratio"] == pytest.approx(psychro.mixing_ratio(20.0, 50.0, 1013.25))


def test_mixing_ratio_needs_a_pressure() -> None:
    """Without the barometer there is no mixing ratio; the rest still derive."""
    got = values(run(climate("ch1", 20.0, 50.0)), "derived", "ch1")

    assert "mixing_ratio" not in got
    assert "dewpoint" in got


def test_a_sensor_with_only_one_reading_gets_no_moisture() -> None:
    """A temperature probe has no humidity, so nothing to derive from."""
    got = values(run([Reading("probe", "temp", T, 20.0, sensor="probe1")]), "derived", "probe1")

    assert set(got) == {"unchanged"}


@pytest.mark.parametrize("humidity", [0.0, -3.0, 100.5, 250.0])
def test_impossible_humidity_is_not_derived_from(humidity: float) -> None:
    """Zero makes the dew point undefined; either end means a faulty sensor."""
    got = values(run(climate("ch1", 20.0, humidity)), "derived", "ch1")

    assert "dewpoint" not in got


def test_ventilation_compares_each_indoor_sensor_with_outdoor() -> None:
    """Drier outdoor air gives a positive delta and a lower predicted humidity."""
    readings = [*climate("outdoor", 10.0, 70.0, "outdoor"), *climate("ch1", 21.0, 65.0)]

    got = values(run(readings), "ventilation", "ch1")

    assert got["dewpoint_delta"] == pytest.approx(
        psychro.dew_point(21.0, 65.0) - psychro.dew_point(10.0, 70.0)
    )
    assert got["dewpoint_delta"] > 0
    assert got["predicted_humidity"] < 65.0
    assert not values(run(readings), "ventilation", "outdoor")


def test_humid_outdoor_air_gives_a_negative_delta() -> None:
    """A muggy afternoon: opening the window would make the room damper."""
    readings = [*climate("outdoor", 28.0, 85.0, "outdoor"), *climate("ch1", 24.0, 55.0)]

    got = values(run(readings), "ventilation", "ch1")

    assert got["dewpoint_delta"] < 0
    assert got["predicted_humidity"] == 100.0


def test_no_ventilation_without_an_outdoor_sensor() -> None:
    """Until the outdoor sensor reports, there is nothing to compare with."""
    assert not [r for r in run(climate("ch1", 21.0, 60.0)) if r.table == "ventilation"]


class TestSeaLevel:
    """Sea-level reduction and the console calibration error."""

    abs_hpa = 1009.0

    def readings(self, *, rel: float | None = None, outdoor: float | None = None) -> list[Reading]:
        out = [Reading("pressure", "abs", Kind.PRESSURE, self.abs_hpa, sensor="pressure")]
        if rel is not None:
            out.append(Reading("pressure", "rel", Kind.PRESSURE, rel, sensor="pressure"))
        if outdoor is not None:
            out += climate("outdoor", outdoor, 70.0, "outdoor")
        return out

    def test_nothing_without_an_altitude(self) -> None:
        got = values(run(self.readings(rel=1009.0)), "pressure", "pressure")

        assert got == {}

    def test_uses_outdoor_temperature_when_present(self) -> None:
        got = values(
            run(self.readings(outdoor=5.0), Preferences(altitude_m=180)), "pressure", "pressure"
        )

        assert got["sea_temp_source"] == "outdoor"
        assert got["sea"] == pytest.approx(psychro.sea_level_pressure(self.abs_hpa, 180, 5.0))

    def test_falls_back_to_the_standard_atmosphere_not_indoor(self) -> None:
        """A heated room says nothing about the air column outside."""
        readings = [*self.readings(), *climate("indoor", 22.0, 50.0, "indoor")]

        got = values(run(readings, Preferences(altitude_m=180)), "pressure", "pressure")

        assert got["sea_temp_source"] == "standard"
        expected = psychro.sea_level_pressure(self.abs_hpa, 180, psychro.standard_temperature(180))
        assert got["sea"] == pytest.approx(expected)

    def test_an_uncalibrated_console_shows_its_offset_as_the_error(self) -> None:
        """REL equal to ABS at 180 m is about 22 hPa low."""
        got = values(
            run(self.readings(rel=self.abs_hpa), Preferences(altitude_m=180)),
            "pressure",
            "pressure",
        )

        assert got["rel_error"] == pytest.approx(-21.8, abs=0.5)

    def test_a_calibrated_console_shows_no_error_in_any_season(self) -> None:
        """The error is measured at a constant temperature, so it does not swing with the weather.

        A console offset set correctly is a constant; if the reference moved with the outdoor
        temperature, the same correct console would show an error in winter and another in
        summer.
        """
        reference = psychro.sea_level_pressure(self.abs_hpa, 180, psychro.standard_temperature(180))
        prefs = Preferences(altitude_m=180)

        for outdoor in (-5.0, 15.0, 38.0):
            got = values(
                run(self.readings(rel=reference, outdoor=outdoor), prefs), "pressure", "pressure"
            )
            assert got["rel_error"] == pytest.approx(0.0, abs=1e-9)

    def test_no_error_without_a_relative_reading(self) -> None:
        got = values(run(self.readings(), Preferences(altitude_m=180)), "pressure", "pressure")

        assert "rel_error" not in got
        assert "sea" in got


class TestStaleness:
    """Seconds each sensor's measurements have gone unchanged."""

    def test_counts_up_while_unchanged_and_resets_on_change(self) -> None:
        tracker = StalenessTracker()

        def unchanged(temp: float, at: int) -> float:
            out = derive(
                climate("ch1", temp, 60.0), Preferences(), tracker, station="s", timestamp=at
            )
            return values(out, "derived", "ch1")["unchanged"]  # type: ignore[return-value]

        assert unchanged(20.0, 1000) == 0
        assert unchanged(20.0, 1010) == 10
        assert unchanged(20.0, 1060) == 60
        assert unchanged(20.1, 1070) == 0
        assert unchanged(20.1, 1080) == 10

    def test_batteries_and_console_metadata_do_not_count(self) -> None:
        """A drifting battery voltage must not make a dead sensor look alive."""
        tracker = StalenessTracker()
        base = climate("ch1", 20.0, 60.0)

        derive(
            [*base, Reading("battery", "voltage", Kind.VOLTAGE, 1.5, sensor="ch1")],
            Preferences(),
            tracker,
            station="s",
            timestamp=0,
        )
        out = derive(
            [*base, Reading("battery", "voltage", Kind.VOLTAGE, 1.4, sensor="ch1")],
            Preferences(),
            tracker,
            station="s",
            timestamp=60,
        )

        assert values(out, "derived", "ch1")["unchanged"] == 60

    def test_stations_are_tracked_separately(self) -> None:
        """Two stations' `ch1` are different sensors."""
        tracker = StalenessTracker()
        derive(climate("ch1", 20.0, 60.0), Preferences(), tracker, station="a", timestamp=0)

        out = derive(climate("ch1", 20.0, 60.0), Preferences(), tracker, station="b", timestamp=60)

        assert values(out, "derived", "ch1")["unchanged"] == 0

    def test_duplicate_spellings_of_differing_types_do_not_raise(self) -> None:
        """Signatures sort by representation, so mixed types in one sensor are fine."""
        readings = [
            Reading("indoor", "temp", T, 20.0, sensor="indoor"),
            Reading("indoor", "temp", Kind.TEXT, "20", sensor="indoor"),
        ]

        assert values(run(readings), "derived", "indoor")["unchanged"] == 0

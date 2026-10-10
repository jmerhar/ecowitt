"""The pressure calibration checks."""

from __future__ import annotations

import pytest

from ecowitt.collector.admin.calibration import (
    REFERENCE_MAX_AGE_SECONDS,
    STEP_HPA,
    STEP_WINDOW_SECONDS,
    CalibrationMonitor,
)
from ecowitt.collector.admin.stationconfig import Station
from ecowitt.collector.preferences import Preferences
from ecowitt.collector.readings import Reading
from ecowitt.collector.units import Kind


def station(altitude: float | None = 180.0, dismissed: dict[str, float] | None = None) -> Station:
    return Station("Home", Preferences(altitude_m=altitude), "K", dismissed=dismissed or {})


def pressure(abs_hpa: float, rel_error: float | None = None) -> list[Reading]:
    out = [Reading("pressure", "abs", Kind.PRESSURE, abs_hpa, sensor="pressure")]
    if rel_error is not None:
        out.append(Reading("pressure", "rel_error", Kind.PRESSURE, rel_error, sensor="pressure"))
    return out


def kinds(monitor: CalibrationMonitor, st: Station, now: int = 10_000) -> list[str]:
    return [w.kind for w in monitor.warnings(st, now)]


def feed(monitor: CalibrationMonitor, values: list[tuple[int, float, float | None]]) -> None:
    for ts, abs_hpa, rel_error in values:
        monitor.observe("Home", ts, pressure(abs_hpa, rel_error))


class TestLocation:
    def test_a_station_without_altitude_is_told_to_set_one(self) -> None:
        assert kinds(CalibrationMonitor(), station(altitude=None)) == ["location"]

    def test_with_an_altitude_there_is_nothing_to_say(self) -> None:
        assert kinds(CalibrationMonitor(), station()) == []


class TestRelative:
    def test_an_uncalibrated_console_is_reported_with_both_forms_of_the_fix(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.0, -14.0) for t in range(5)])

        (warning,) = monitor.warnings(station(), 10_000)

        assert warning.kind == "relative_offset"
        assert warning.correction_hpa == pytest.approx(14.0)
        # Altitude-based consoles, like the HP2551, are told the altitude to enter -- the
        # instruction itself, since "180 m" also appears in the description of the error...
        assert "'Altitude for REL'" in warning.detail
        assert "set it to 180 m" in warning.detail
        # ...and offset-based ones the hPa and inHg to change it by.
        assert "+14.0 hPa" in warning.detail and "+0.41 inHg" in warning.detail
        assert "Leave the absolute calibration alone" in warning.detail

    def test_a_calibrated_console_raises_nothing(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.0, 0.4) for t in range(5)])

        assert kinds(monitor, station()) == []

    def test_one_odd_reading_does_not_raise_it(self) -> None:
        """Judged on the median, so a single outlier is ignored."""
        monitor = CalibrationMonitor()
        feed(
            monitor, [(0, 1009.0, 0.2), (60, 1009.0, 0.1), (120, 1009.0, -9.0), (180, 1009.0, 0.3)]
        )

        assert kinds(monitor, station()) == []

    def test_too_few_reports_to_judge(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.0, -14.0), (60, 1009.0, -14.0)])

        assert kinds(monitor, station()) == []

    def test_no_relative_check_without_an_altitude(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.0, -14.0) for t in range(5)])

        assert kinds(monitor, station(altitude=None)) == ["location"]


class TestAbsoluteStep:
    def test_a_jump_no_weather_can_produce_is_reported(self) -> None:
        """An ABS Barometer setting raised by 24 hPa between two reports."""
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.8, -14.0), (60, 1009.8, -14.0), (120, 1033.7, -14.3)])

        warning = next(w for w in monitor.warnings(station(), 200) if w.kind == "absolute_step")

        assert warning.correction_hpa == pytest.approx(-23.9)
        assert warning.since == 120
        assert "ABS Barometer" in warning.detail
        assert "not here" in warning.detail  # sea level is set elsewhere

    def test_the_relative_check_alone_could_not_have_seen_it(self) -> None:
        """An absolute offset moves relative pressure and its reduction together."""
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.8, 0.1), (60, 1009.8, 0.1), (120, 1033.7, 0.1), (180, 1033.7, 0.1)])

        assert "relative_offset" not in kinds(monitor, station(), 200)
        assert "absolute_step" in kinds(monitor, station(), 200)

    def test_a_step_that_is_put_back_raises_nothing(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.8, None), (60, 1033.7, None), (120, 1009.9, None)])

        assert kinds(monitor, station(), 200) == []

    def test_normal_weather_raises_nothing(self) -> None:
        """A deep low falling a few hPa an hour, reported each minute."""
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1010.0 - t * 0.08, None) for t in range(120)])

        assert kinds(monitor, station(), 120 * 60) == []

    def test_a_large_change_after_a_long_silence_is_not_a_step(self) -> None:
        """After hours without a report, a big difference may be real weather."""
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.0, None), (STEP_WINDOW_SECONDS + 1, 1009.0 + STEP_HPA + 2, None)])

        assert kinds(monitor, station(), STEP_WINDOW_SECONDS + 10) == []

    def test_the_step_threshold_is_exclusive(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1000.0, None), (60, 1000.0 + STEP_HPA, None)])

        assert kinds(monitor, station(), 100) == []

    def test_old_steps_are_forgotten_after_a_week(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1009.8, None), (60, 1033.7, None)])
        week = 7 * 86400
        feed(monitor, [(week + 120, 1033.7, None)])

        assert kinds(monitor, station(), week + 200) == []


class TestStepAndReferenceTogether:
    """A step judged by whether the absolute reading agrees with the model afterwards."""

    def test_a_step_that_brings_absolute_pressure_right_is_a_correction(self) -> None:
        """After a restart, the step that put a mistake right is the only one remembered."""
        monitor = CalibrationMonitor()
        feed(
            monitor,
            [(0, 1033.8, None), (60, 1033.8, None), (120, 1009.9, None), (180, 1009.8, None)],
        )
        monitor.set_reference("Home", 150, 1009.3)

        assert kinds(monitor, station(), 200) == []

    def test_a_step_that_takes_it_away_from_the_model_is_reported_twice_over(self) -> None:
        monitor = CalibrationMonitor()
        feed(
            monitor,
            [(0, 1009.8, None), (60, 1009.8, None), (120, 1033.7, None), (180, 1033.8, None)],
        )
        monitor.set_reference("Home", 150, 1009.3)

        assert kinds(monitor, station(), 200) == ["absolute_step", "absolute_reference"]

    def test_only_readings_since_the_step_are_judged(self) -> None:
        """The mistake before a correction must not make the correction look wrong."""
        monitor = CalibrationMonitor()
        feed(
            monitor,
            [(0, 1033.8, None), (60, 1033.8, None), (90, 1033.8, None), (120, 1009.9, None)],
        )
        monitor.set_reference("Home", 100, 1009.3)

        assert kinds(monitor, station(), 200) == []

    def test_seeing_a_step_asks_for_a_fresh_reference(self) -> None:
        asked: list[bool] = []
        monitor = CalibrationMonitor(on_step=lambda: asked.append(True))

        feed(monitor, [(0, 1009.8, None), (60, 1009.9, None)])
        assert asked == []
        feed(monitor, [(120, 1033.7, None)])
        assert asked == [True]


class TestReference:
    def test_an_absolute_reading_far_from_the_model_is_reported(self) -> None:
        """Catches an absolute error that was always there, which a step check cannot."""
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1033.7, None) for t in range(10)])
        monitor.set_reference("Home", 300, 1009.3)

        warning = next(
            w for w in monitor.warnings(station(), 600) if w.kind == "absolute_reference"
        )

        assert warning.correction_hpa == pytest.approx(-24.4)
        assert "1009.3 hPa" in warning.detail

    def test_agreement_within_the_threshold_raises_nothing(self) -> None:
        """A good barometer reads within a hectopascal of the model."""
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.9, None) for t in range(10)])
        monitor.set_reference("Home", 300, 1009.3)

        assert kinds(monitor, station(), 600) == []

    def test_a_stale_model_value_is_not_used(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1033.7, None) for t in range(10)])
        monitor.set_reference("Home", 300, 1009.3)

        assert kinds(monitor, station(), 300 + REFERENCE_MAX_AGE_SECONDS + 1) == []

    def test_no_readings_near_the_model_time_means_no_comparison(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(0, 1033.7, None)])
        monitor.set_reference("Home", 7200, 1009.3)

        assert kinds(monitor, station(), 7300) == []


class TestDismissal:
    def test_a_dismissed_warning_stays_hidden_at_its_value(self) -> None:
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.0, -14.0) for t in range(5)])

        assert kinds(monitor, station(dismissed={"relative_offset": 14.2})) == []

    def test_it_returns_when_the_error_moves(self) -> None:
        """A further change of calibration is news, even if the last one was acknowledged."""
        monitor = CalibrationMonitor()
        feed(monitor, [(t * 60, 1009.0, -14.0) for t in range(5)])

        assert kinds(monitor, station(dismissed={"relative_offset": 10.0})) == ["relative_offset"]

    def test_a_warning_without_a_number_is_hidden_once_dismissed(self) -> None:
        assert (
            kinds(CalibrationMonitor(), station(altitude=None, dismissed={"location": 0.0})) == []
        )


def test_non_pressure_and_non_numeric_readings_are_ignored() -> None:
    monitor = CalibrationMonitor()
    monitor.observe("Home", 0, [Reading("indoor", "temp", Kind.TEMPERATURE, 20.0, sensor="indoor")])
    monitor.observe("Home", 60, [Reading("pressure", "sea_temp_source", Kind.TEXT, "standard")])

    assert kinds(monitor, station()) == []


def test_stations_are_tracked_separately() -> None:
    monitor = CalibrationMonitor()
    monitor.observe("Other", 0, pressure(1009.8))
    monitor.observe("Other", 60, pressure(1033.7))

    assert kinds(monitor, station(), 100) == []

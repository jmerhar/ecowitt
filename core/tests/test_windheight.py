"""The factor that estimates wind at 10 m from a lower anemometer."""

from __future__ import annotations

import math

import pytest

from ecowitt.core import windheight


@pytest.mark.parametrize(
    ("height", "surroundings", "expected"),
    [
        # ln(10 / z0) / ln(2 / z0) for each roughness length.
        (2.0, "open", math.log(100) / math.log(20)),
        (2.0, "gardens", math.log(10 / 0.3) / math.log(2 / 0.3)),
        (2.0, "sheltered", math.log(20) / math.log(4)),
        (10.0, "sheltered", 1.0),
    ],
)
def test_the_logarithmic_profile(height: float, surroundings: str, expected: float) -> None:
    assert windheight.factor(height, surroundings) == pytest.approx(expected)


def test_the_factors_the_setup_page_offers_at_2_m() -> None:
    """Rounded as the page shows them."""
    factors = {k: round(windheight.factor(2.0, k), 2) for k in windheight.SURROUNDINGS}

    assert factors == {"open": 1.54, "gardens": 1.85, "sheltered": 2.16}


def test_higher_than_10_m_scales_down() -> None:
    assert windheight.factor(20.0, "open") < 1.0


def test_no_correction_without_a_height_or_with_none_chosen() -> None:
    assert windheight.factor(None, "sheltered") == 1.0
    assert windheight.factor(2.0, windheight.NONE) == 1.0


def test_every_allowed_height_is_above_every_roughness_length() -> None:
    """Below z0 the logarithm turns negative, and at z0 the factor divides by zero."""
    assert all(s.roughness_m < windheight.MIN_HEIGHT_M for s in windheight.SURROUNDINGS.values())

"""Fixtures shared by core's tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ecowitt.core.testing import StubInflux, serving


@pytest.fixture
async def influx() -> AsyncIterator[StubInflux]:
    """A stand-in InfluxDB for the length of one test."""
    async with serving(StubInflux()) as stub:
        yield stub

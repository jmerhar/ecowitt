"""A stand-in HTTP server for tests, from jigkit: a real server recording every request.

It stands in for InfluxDB and for the public lookup services. ``StubInflux`` is jigkit's
``StubServer`` under the name these tests use.
"""

from __future__ import annotations

from jigkit.testing.http import Received, StubServer, serving

StubInflux = StubServer

__all__ = ["Received", "StubInflux", "serving"]

"""The cache: reuse for a while, one computation for concurrent requests, failures not kept."""

from __future__ import annotations

import asyncio

import pytest

from ecowitt.dashboard.cache import TtlCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_a_result_is_reused_until_it_expires() -> None:
    clock = Clock()
    cache = TtlCache(clock=clock)
    calls = []

    async def compute() -> int:
        calls.append(1)
        return len(calls)

    assert await cache.get("k", 10, compute) == 1
    clock.now = 9.9
    assert await cache.get("k", 10, compute) == 1
    clock.now = 10.1
    assert await cache.get("k", 10, compute) == 2


async def test_concurrent_requests_share_one_computation() -> None:
    cache = TtlCache()
    started = 0
    release = asyncio.Event()

    async def compute() -> str:
        nonlocal started
        started += 1
        await release.wait()
        return "done"

    waiting = [asyncio.create_task(cache.get("k", 10, compute)) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(*waiting) == ["done"] * 5
    assert started == 1


async def test_a_failure_is_not_kept() -> None:
    cache = TtlCache()
    attempts = []

    async def compute() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database down")
        return "fine"

    with pytest.raises(RuntimeError):
        await cache.get("k", 10, compute)
    assert await cache.get("k", 10, compute) == "fine"


async def test_a_visitor_leaving_does_not_cancel_the_computation_for_others() -> None:
    cache = TtlCache()
    release = asyncio.Event()

    async def compute() -> str:
        await release.wait()
        return "done"

    first = asyncio.create_task(cache.get("k", 10, compute))
    await asyncio.sleep(0)
    second = asyncio.create_task(cache.get("k", 10, compute))
    await asyncio.sleep(0)
    first.cancel()
    release.set()
    assert await second == "done"
    with pytest.raises(asyncio.CancelledError):
        await first


async def test_the_oldest_entries_are_dropped_beyond_the_limit() -> None:
    cache = TtlCache(max_entries=2)
    calls = []

    async def compute() -> int:
        calls.append(1)
        return len(calls)

    for key in ("a", "b", "c"):
        await cache.get(key, 10, compute)
    assert await cache.get("c", 10, compute) == 3
    assert await cache.get("a", 10, compute) == 4


async def test_an_evicted_failure_is_still_retrieved() -> None:
    cache = TtlCache(max_entries=1)
    release = asyncio.Event()

    async def fail() -> None:
        await release.wait()
        raise RuntimeError("nobody is listening")

    async def fine() -> str:
        return "ok"

    failing = asyncio.create_task(cache.get("a", 10, fail))
    await asyncio.sleep(0)
    assert await cache.get("b", 10, fine) == "ok"
    release.set()
    with pytest.raises(RuntimeError):
        await failing


async def test_clear_forgets_everything() -> None:
    cache = TtlCache()
    calls = []

    async def compute() -> int:
        calls.append(1)
        return len(calls)

    await cache.get("k", 10, compute)
    cache.clear()
    assert await cache.get("k", 10, compute) == 2

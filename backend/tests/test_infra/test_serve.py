"""Wiring of the two listeners."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import uvicorn

from ecowitt import serve
from ecowitt.config import Settings
from ecowitt.ingest import LoggingHandler
from ecowitt.state import State


def test_build_binds_each_listener_to_its_own_port() -> None:
    """The two listeners are separate servers on separate ports."""
    settings = Settings(ingest_port=9100, admin_port=9101)

    ingest_listener, admin_listener = serve.build(settings, LoggingHandler(), State())

    assert ingest_listener.config.port == 9100
    assert admin_listener.config.port == 9101


def test_the_public_listener_hides_its_software_and_logs_no_request_lines() -> None:
    """The open port neither names uvicorn nor copies the ingest path into a log."""
    ingest_listener, admin_listener = serve.build(Settings(), LoggingHandler(), State())

    assert ingest_listener.config.server_header is False
    assert ingest_listener.config.access_log is False
    # The admin listener keeps its access log: it is not internet-facing and the lines are
    # useful.
    assert admin_listener.config.access_log is True


def test_a_listener_leaves_process_signal_handlers_alone() -> None:
    """Serving must not repoint SIGTERM, so one handler can stop both listeners."""
    listener, _ = serve.build(Settings(), LoggingHandler(), State())
    before = signal.getsignal(signal.SIGTERM)

    with listener.capture_signals():
        during = signal.getsignal(signal.SIGTERM)

    assert during is before


def test_a_plain_uvicorn_server_would_have_claimed_them() -> None:
    """The upstream behaviour the override exists for.

    `uvicorn.Server.serve` points SIGTERM at its own handler, and `signal.signal` keeps one
    handler per signal -- so two unmodified servers in one process would leave only the
    second able to stop. This fails if uvicorn renames or drops the hook, which is the way
    the override would otherwise become dead code without anything noticing.
    """
    plain = uvicorn.Server(uvicorn.Config(app=_noop_app))
    before = signal.getsignal(signal.SIGTERM)

    with plain.capture_signals():
        during = signal.getsignal(signal.SIGTERM)

    assert during is not before
    assert during == plain.handle_exit
    # Restored on the way out, which is the only reason running this in a test is safe.
    assert signal.getsignal(signal.SIGTERM) is before


def test_stop_all_stops_every_listener() -> None:
    """One signal handler ends both listeners, not just the one that received it."""
    listeners = serve.build(Settings(), LoggingHandler(), State())
    assert not any(listener.should_exit for listener in listeners)

    serve.stop_all(listeners)

    assert all(listener.should_exit for listener in listeners)


async def _noop_app(scope: object, receive: object, send: object) -> None:
    """An ASGI app that is never called; uvicorn.Config only needs something callable."""


def test_missing_admin_authentication_is_announced(caplog: pytest.LogCaptureFixture) -> None:
    """Starting without admin authentication says so, since the publish is then the only gate."""
    with caplog.at_level(logging.WARNING, logger="ecowitt.serve"):
        warned = serve.warn_if_admin_unauthenticated(Settings(admin_port=8001))

    assert warned is True
    assert "no authentication configured" in caplog.text
    assert "8001" in caplog.text


def test_configured_admin_authentication_is_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """With a login configured there is nothing to warn about."""
    htpasswd = tmp_path / "htpasswd"
    htpasswd.write_text("admin:x\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="ecowitt.serve"):
        warned = serve.warn_if_admin_unauthenticated(Settings(htpasswd_file=htpasswd))

    assert warned is False
    assert caplog.text == ""


def test_configure_logging_sets_the_level() -> None:
    """The configured level reaches the root logger."""
    root = logging.getLogger()
    original = root.level
    try:
        serve.configure_logging("warning")
        assert root.level == logging.WARNING
    finally:
        root.setLevel(original)


@contextlib.asynccontextmanager
async def _running(
    monkeypatch: pytest.MonkeyPatch, state: State
) -> AsyncIterator[list[serve._Listener]]:
    """Run the server on kernel-chosen ports, and always shut it down.

    Shutting down through `stop_all` rather than cancelling the task: a cancelled startup
    leaves uvicorn's listening sockets open until the garbage collector reaches them, which
    surfaces as ResourceWarnings from an unrelated test later in the session.
    """
    listeners: list[serve._Listener] = []
    real_build = serve.build

    def capture(*args: object, **kwargs: object) -> tuple[serve._Listener, serve._Listener]:
        built = real_build(*args, **kwargs)  # type: ignore[arg-type]
        listeners.extend(built)
        return built

    monkeypatch.setattr(serve, "build", capture)
    settings = Settings(ingest_port=0, admin_port=0)
    # The state the server will fill in is handed back by patching State's construction,
    # since `run` makes its own.
    monkeypatch.setattr(serve, "State", lambda: state)
    task = asyncio.create_task(serve.run(settings, LoggingHandler()))
    try:
        async with asyncio.timeout(10):
            while not (state.ingest_serving and state.admin_serving):
                await asyncio.sleep(0.05)
        yield listeners
    finally:
        serve.stop_all(listeners)
        async with asyncio.timeout(10):
            await task


async def test_run_serves_on_both_listeners(monkeypatch: pytest.MonkeyPatch) -> None:
    """The startup path: two servers bound, and the state that drives health marked."""
    state = State()

    async with _running(monkeypatch, state) as listeners:
        assert len(listeners) == 2
        assert all(listener.started for listener in listeners)
        assert state.ingest_serving and state.admin_serving
        # Distinct kernel-chosen ports, so the two are genuinely separate sockets.
        bound = {listener.servers[0].sockets[0].getsockname()[1] for listener in listeners}
        assert len(bound) == 2


async def test_the_registered_signal_handler_stops_both_listeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGINT and SIGTERM reach `stop_all` bound to both listeners, and it ends them.

    The callback is invoked rather than the signal delivered: a real SIGTERM in a process that
    had *not* installed the handler would kill the test run instead of failing an assertion.
    """
    registered: dict[int, tuple[object, tuple[object, ...]]] = {}
    loop = asyncio.get_running_loop()
    original = loop.add_signal_handler

    def record(sig: int, callback: object, *args: object) -> None:
        registered[sig] = (callback, args)
        original(sig, lambda: None)

    monkeypatch.setattr(loop, "add_signal_handler", record)
    state = State()

    async with _running(monkeypatch, state) as listeners:
        assert set(registered) == {signal.SIGINT, signal.SIGTERM}
        for callback, args in registered.values():
            assert callback is serve.stop_all
            assert args == (tuple(listeners),)

        # Invoking what was registered must actually stop both, which is the point of
        # overriding uvicorn's own per-server handling.
        callback, args = registered[signal.SIGTERM]
        callback(*args)  # type: ignore[operator]
        assert all(listener.should_exit for listener in listeners)


def test_main_configures_logging_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module entrypoint sets the log level from settings before serving."""
    monkeypatch.setenv("LOG_LEVEL", "warning")
    serve.get_settings.cache_clear()
    ran: list[object] = []
    monkeypatch.setattr(serve.asyncio, "run", lambda coro: ran.append(coro) or coro.close())
    root = logging.getLogger()
    original = root.level
    try:
        serve.main()
    finally:
        root.setLevel(original)
        serve.get_settings.cache_clear()

    assert len(ran) == 1

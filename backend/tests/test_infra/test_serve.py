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


def test_the_admin_listener_warns_when_it_has_no_login(caplog: pytest.LogCaptureFixture) -> None:
    """The publish is then the only gate, so startup says where to publish it."""
    with caplog.at_level(logging.WARNING, logger="ecowitt.serve"):
        assert serve.warn_if_admin_unauthenticated(Settings(admin_port=2552)) is True

    assert "no login" in caplog.text
    assert "2552" in caplog.text


def test_with_a_login_set_there_is_nothing_to_warn_about(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="ecowitt.serve"):
        assert serve.warn_if_admin_unauthenticated(Settings(), login_set=True) is False

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


@pytest.mark.parametrize(
    ("level", "expected"), [("info", logging.WARNING), ("error", logging.ERROR)]
)
def test_per_request_library_logging_is_quieted(level: str, expected: int) -> None:
    """An INFO line per write would be one per report, for ever; warnings still get through."""
    root = logging.getLogger()
    original = root.level
    try:
        serve.configure_logging(level)
        for name in serve.CHATTY_LOGGERS:
            assert logging.getLogger(name).level == expected
    finally:
        root.setLevel(original)
        for name in serve.CHATTY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)


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


@pytest.mark.parametrize("influx_url", ["", "http://127.0.0.1:1"])
async def test_run_without_a_handler_loads_the_configured_stations(
    influx_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The production path: stations from the file, a writer, a warning only with no database."""
    (tmp_path / "config.yaml").write_text(
        "stations: [{name: Home, passkey: AAAA}]\n", encoding="utf-8"
    )
    settings = Settings(data_dir=tmp_path, ingest_port=0, admin_port=0, influx_url=influx_url)
    state = State()
    monkeypatch.setattr(serve, "State", lambda: state)
    closed: list[bool] = []
    real_aclose = serve.InfluxWriter.aclose

    async def track_close(self: serve.InfluxWriter) -> None:
        closed.append(True)
        await real_aclose(self)

    monkeypatch.setattr(serve.InfluxWriter, "aclose", track_close)
    woken: list[bool] = []
    monkeypatch.setattr(serve.ReferenceUpdater, "wake", lambda _self: woken.append(True))
    monitors: list[serve.CalibrationMonitor] = []
    real_monitor = serve.CalibrationMonitor

    def capture_monitor() -> serve.CalibrationMonitor:
        monitors.append(real_monitor())
        return monitors[-1]

    monkeypatch.setattr(serve, "CalibrationMonitor", capture_monitor)
    listeners: list[serve._Listener] = []
    real_build = serve.build

    def capture(*args: object, **kwargs: object) -> tuple[serve._Listener, serve._Listener]:
        built = real_build(*args, **kwargs)  # type: ignore[arg-type]
        listeners.extend(built)
        return built

    monkeypatch.setattr(serve, "build", capture)

    with caplog.at_level(logging.INFO, logger="ecowitt.serve"):
        task = asyncio.create_task(serve.run(settings))
        async with asyncio.timeout(10):
            while not (state.ingest_serving and state.admin_serving):
                await asyncio.sleep(0.05)
        serve.stop_all(listeners)
        async with asyncio.timeout(10):
            await task

    assert "stations: Home" in caplog.text
    assert ("INFLUX_URL is not set" in caplog.text) is (influx_url == "")
    assert closed == [True]
    # The spool and the form-signing secret exist under the data directory, and no background
    # task outlived `run`.
    assert (tmp_path / "spool" / "pending").is_dir()
    assert (tmp_path / "secret.key").is_file()
    names = {t.get_name() for t in asyncio.all_tasks()}
    assert not names & {"spool-replay", "reference-pressure"}
    # Configuration changes and pressure steps both wake the reference refresh; subscribing
    # delivers the first configuration at once.
    assert woken
    assert monitors[0].on_step is not None


async def test_run_refuses_to_start_on_a_malformed_configuration(tmp_path: Path) -> None:
    """Better a container that will not start than one that discards every report.

    Bounded, because the failure this guards against is `run` starting normally -- and a
    server that starts normally serves until stopped, which would hang the suite rather than
    fail it.
    """
    from ecowitt.stationconfig import ConfigError

    (tmp_path / "config.yaml").write_text("stattions: []\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="stattions"):
        async with asyncio.timeout(5):
            await serve.run(Settings(data_dir=tmp_path, ingest_port=0, admin_port=0))


async def test_a_backlog_from_before_a_restart_is_delivered_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the replay loop, reports spooled before a restart would wait for ever."""
    from ecowitt.spool import Spool

    from ..test_store.conftest import StubInflux, serving

    Spool(tmp_path / "spool", 1_000_000).enqueue("indoor,station=Home temp_c=21.0 1791500484")
    (tmp_path / "config.yaml").write_text(
        "stations: [{name: Home, passkey: AAAA}]\n", encoding="utf-8"
    )
    state = State()
    monkeypatch.setattr(serve, "State", lambda: state)
    listeners: list[serve._Listener] = []
    real_build = serve.build

    def capture(*args: object, **kwargs: object) -> tuple[serve._Listener, serve._Listener]:
        built = real_build(*args, **kwargs)  # type: ignore[arg-type]
        listeners.extend(built)
        return built

    monkeypatch.setattr(serve, "build", capture)

    async with serving(StubInflux()) as stub:
        settings = Settings(data_dir=tmp_path, ingest_port=0, admin_port=0, influx_url=stub.url)
        task = asyncio.create_task(serve.run(settings))
        try:
            async with asyncio.timeout(10):
                while not stub.requests:
                    await asyncio.sleep(0.02)
        finally:
            async with asyncio.timeout(10):
                while len(listeners) < 2:
                    await asyncio.sleep(0.02)
            serve.stop_all(listeners)
            async with asyncio.timeout(10):
                await task

    assert stub.requests[0].body == "indoor,station=Home temp_c=21.0 1791500484"
    assert not list((tmp_path / "spool" / "pending").iterdir())

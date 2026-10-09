"""Run both listeners in one process.

One process rather than two containers because the admin listener renders what the ingest
listener has just received, and one event loop rather than two threads because both are
asyncio servers already.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Iterable, Iterator

import uvicorn

from . import admin, ingest, stationconfig
from .config import Settings, get_settings
from .delivery import Delivery
from .handler import StationHandler
from .ingest import ReportHandler
from .spool import Spool
from .state import State
from .writer import InfluxWriter

logger = logging.getLogger(__name__)


class _Listener(uvicorn.Server):
    """A uvicorn server that leaves the process's signal handlers alone."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """Install nothing, so one handler can serve both listeners.

        `uvicorn.Server.serve` wraps itself in this, and the base implementation points
        SIGINT and SIGTERM at its own `handle_exit` with `signal.signal` -- which keeps a
        single handler per signal. With two servers in one process the second would displace
        the first, so a SIGTERM would stop only one of them and the process would hang in
        `asyncio.gather` until something sent SIGKILL. `run` installs one handler that stops
        every listener instead.
        """
        yield

    async def notify_serving(self, state: State, attribute: str) -> None:
        """Set `attribute` on `state` once this listener is accepting connections."""
        while not self.started:
            await asyncio.sleep(0.05)
        setattr(state, attribute, True)


#: Libraries that log every request at INFO. A station reports every few seconds, so at the
#: default level each would add a line per report, for ever; their warnings still get through.
CHATTY_LOGGERS = ("httpx2", "httpcore2")


def configure_logging(level: str) -> None:
    """Send the application's logs to stderr at the configured level."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )
    # From the argument rather than read back from the root logger: basicConfig does nothing
    # when the root logger already has handlers, so the root level is not a reliable echo.
    configured = logging.getLevelNamesMapping()[level.upper()]
    for name in CHATTY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, configured))


def stop_all(listeners: Iterable[_Listener]) -> None:
    """Ask every listener to finish serving."""
    logger.info("shutting down")
    for listener in listeners:
        listener.should_exit = True


def build(
    settings: Settings,
    handler: ReportHandler,
    state: State,
    stations: list[str] | None = None,
    spool: Spool | None = None,
) -> tuple[_Listener, _Listener]:
    """Build the two listeners."""
    ingest_listener = _Listener(
        uvicorn.Config(
            app=ingest.build_app(settings, state, handler),
            host=settings.ingest_host,
            port=settings.ingest_port,
            # No `server: uvicorn` header, so the port does not name its software.
            server_header=False,
            # No access log: this listener answers the open internet, and a request line
            # would copy the ingest path -- which may carry a secret segment -- into the log
            # on every report. The handler logs an accepted report itself.
            access_log=False,
            log_config=None,
        )
    )
    admin_listener = _Listener(
        uvicorn.Config(
            app=admin.build_app(settings, state, stations, spool),
            host=settings.admin_host,
            port=settings.admin_port,
            log_config=None,
        )
    )
    return ingest_listener, admin_listener


def warn_if_admin_unauthenticated(settings: Settings) -> None:
    """Say that the admin listener has no authentication of its own.

    The bind address cannot tell whether that matters. The shipped artefact is a container,
    where a loopback bind is unreachable even through a published port, so the admin listener
    always binds every interface; what keeps it private is where the host publishes it, which
    the process cannot see. So the message states the requirement rather than guessing whether
    it is met.
    """
    logger.warning(
        "the admin interface has no authentication: publish port %d on loopback only, or "
        "behind a reverse proxy that requires a login",
        settings.admin_port,
    )


async def run(settings: Settings | None = None, handler: ReportHandler | None = None) -> None:
    """Serve until a signal arrives.

    Without a handler given, reports are authenticated against the configuration file and
    delivered to InfluxDB, through the spool when it cannot take them. A configuration file
    that exists but cannot be read stops startup with the reason, rather than serving with no
    stations and discarding every report.
    """
    settings = settings or get_settings()
    state = State()
    stations: list[str] = []
    writer: InfluxWriter | None = None
    spool: Spool | None = None
    replay: asyncio.Task[None] | None = None
    if handler is None:
        config = stationconfig.load(settings.config_file)
        writer = InfluxWriter(settings)
        spool = Spool(settings.spool_dir, settings.spool_max_bytes)
        delivery = Delivery(writer, spool, state)
        handler = StationHandler(config, delivery)
        stations = config.names
        logger.info("stations: %s", ", ".join(stations) or "none configured")
        if not writer.configured:
            logger.warning("INFLUX_URL is not set: reports will be spooled until it is")
        replay = asyncio.create_task(delivery.run(), name="spool-replay")
    ingest_listener, admin_listener = build(settings, handler, state, stations, spool)

    warn_if_admin_unauthenticated(settings)

    listeners = (ingest_listener, admin_listener)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_all, listeners)

    logger.info(
        "ingest on %s:%d%s, admin on %s:%d",
        settings.ingest_host,
        settings.ingest_port,
        settings.ingest_path,
        settings.admin_host,
        settings.admin_port,
    )
    try:
        await asyncio.gather(
            ingest_listener.serve(),
            admin_listener.serve(),
            ingest_listener.notify_serving(state, "ingest_serving"),
            admin_listener.notify_serving(state, "admin_serving"),
        )
    finally:
        if replay is not None:
            replay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await replay
        if writer is not None:
            await writer.aclose()


def main() -> None:
    """Configure logging and serve."""
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(run(settings))

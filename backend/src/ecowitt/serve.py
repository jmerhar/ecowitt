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

from . import admin, ingest
from .config import Settings, get_settings
from .ingest import LoggingHandler, ReportHandler
from .state import State

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


def configure_logging(level: str) -> None:
    """Send the application's logs to stderr at the configured level."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )


def stop_all(listeners: Iterable[_Listener]) -> None:
    """Ask every listener to finish serving."""
    logger.info("shutting down")
    for listener in listeners:
        listener.should_exit = True


def build(settings: Settings, handler: ReportHandler, state: State) -> tuple[_Listener, _Listener]:
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
            app=admin.build_app(settings, state),
            host=settings.admin_host,
            port=settings.admin_port,
            log_config=None,
        )
    )
    return ingest_listener, admin_listener


def warn_if_admin_unauthenticated(settings: Settings) -> bool:
    """Say so when the admin listener has no authentication, returning whether it warned.

    The bind address cannot be the signal here. The shipped artefact is a container, where a
    loopback bind is unreachable even through a published port, so the admin listener always
    binds every interface and a warning keyed on that would fire every single start -- which
    is how a warning gets ignored. What is left is the thing the operator controls: whether a
    login is configured at all. Where the port is published is said in the message rather
    than guessed at.
    """
    if settings.htpasswd_file is not None:
        return False
    logger.warning(
        "the admin interface has no authentication configured: publish port %d on loopback "
        "only, or behind a reverse proxy that requires a login",
        settings.admin_port,
    )
    return True


async def run(settings: Settings | None = None, handler: ReportHandler | None = None) -> None:
    """Serve until a signal arrives."""
    settings = settings or get_settings()
    state = State()
    ingest_listener, admin_listener = build(settings, handler or LoggingHandler(), state)

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
    await asyncio.gather(
        ingest_listener.serve(),
        admin_listener.serve(),
        ingest_listener.notify_serving(state, "ingest_serving"),
        admin_listener.notify_serving(state, "admin_serving"),
    )


def main() -> None:
    """Configure logging and serve."""
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(run(settings))

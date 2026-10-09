"""The public listener: one route, and nothing else.

This is the only surface the open internet reaches, so it carries no status page, no API, no
setup wizard and no schema documentation -- not because those are guarded here, but because
they are not mounted here at all. Anything that is absent cannot be exposed by a mistake in a
guard. The admin listener in `admin` holds all of it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import parse_qsl

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from .config import MAX_BODY_BYTES, MAX_BODY_FIELDS, Settings
from .http import BodyTooLarge, read_capped_body
from .state import State

logger = logging.getLogger(__name__)

#: What the Ecowitt cloud answers an upload with. The firmware does not inspect it closely,
#: but it is the reply a station is built to expect, and it reveals nothing about this server.
OK_BODY = {"errcode": "0", "errmsg": "ok"}

#: Never logged. PASSKEY identifies an Ecowitt-protocol station and authenticates its reports;
#: PASSWORD is the Wunderground protocol's equivalent. A log file is the easiest place for a
#: credential to be read from.
REDACTED_FIELDS = frozenset({"PASSKEY", "PASSWORD"})


class ReportHandler(Protocol):
    """What the listener does with a report once it has been read and split into fields."""

    async def handle(self, fields: Mapping[str, str], source: str) -> bool:
        """Process one report, returning whether it was accepted."""


def redact(fields: Mapping[str, str]) -> dict[str, str]:
    """Copy the fields with every credential replaced, safe to log."""
    return {k: ("<redacted>" if k in REDACTED_FIELDS else v) for k, v in fields.items()}


def build_app(settings: Settings, state: State, handler: ReportHandler) -> FastAPI:
    """Build the public application, serving only the configured ingest path."""
    app = FastAPI(
        title="Ecowitt Server ingest",
        # No interactive docs and no schema: they would describe this server to anyone who
        # found the port.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # Starlette's slash redirect answers with a 307, which the Ecowitt uploader does not
        # follow -- it would retry the same request for ever. Both spellings are registered
        # explicitly instead.
        redirect_slashes=False,
    )

    async def report(request: Request) -> Response:
        """Receive one station report."""
        source = request.client.host if request.client else "unknown"

        try:
            body = await read_capped_body(request, MAX_BODY_BYTES)
        except BodyTooLarge:
            logger.warning("report from %s rejected: body over %d bytes", source, MAX_BODY_BYTES)
            state.record_rejected()
            return PlainTextResponse("", status_code=413)

        # The Ecowitt protocol posts form-encoded fields; the Wunderground variant puts the
        # same names in the query string, and both are accepted. parse_qsl is total -- it
        # yields what it can and never raises -- so a malformed body degrades to fewer fields
        # rather than to a 500.
        pairs = parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        pairs += parse_qsl(request.url.query, keep_blank_values=True)
        if len(pairs) > MAX_BODY_FIELDS:
            logger.warning("report from %s rejected: over %d fields", source, MAX_BODY_FIELDS)
            state.record_rejected()
            return PlainTextResponse("", status_code=413)

        if await handler.handle(dict(pairs), source):
            state.record_accepted()
        else:
            state.record_rejected()

        # Always 200, whether or not the report was kept. A station cannot act on a refusal --
        # it has no backlog to retry from -- and a distinguishable error would tell an
        # anonymous caller which PASSKEY guesses were wrong.
        return JSONResponse(OK_BODY)

    for path in settings.ingest_paths:
        app.add_api_route(path, report, methods=["POST", "GET"], include_in_schema=False)

    @app.exception_handler(404)
    async def not_found(_request: Request, _exc: Exception) -> Response:
        """Answer anything that is not the ingest path with an empty 404."""
        return PlainTextResponse("", status_code=404)

    return app


class LoggingHandler:
    """A report handler that only records what it saw.

    Useful on its own for confirming a console can reach this server, and as the stand-in in
    tests that exercise the listener rather than the storage path.
    """

    def __init__(self) -> None:
        self.reports: list[dict[str, str]] = []

    async def handle(self, fields: Mapping[str, str], source: str) -> bool:
        """Record the report and accept it."""
        self.reports.append(dict(fields))
        logger.info("report from %s: %d fields", source, len(fields))
        logger.debug("report from %s: %s", source, redact(fields))
        return True

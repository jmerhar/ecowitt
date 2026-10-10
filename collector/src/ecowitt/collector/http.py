"""Request helpers shared by both listeners."""

from __future__ import annotations

from starlette.requests import Request


class BodyTooLarge(Exception):
    """Raised when a request body exceeds the configured cap."""


async def read_capped_body(request: Request, limit: int) -> bytes:
    """Read a request body, refusing to buffer more than `limit` bytes.

    Streamed rather than read whole, because the ingest listener answers the open internet:
    `await request.body()` would allocate whatever an anonymous caller chose to send before
    anything had a chance to object. A declared Content-Length is checked first so an
    oversized body is refused before any of it is read.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise BodyTooLarge

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise BodyTooLarge
        chunks.append(chunk)
    return b"".join(chunks)

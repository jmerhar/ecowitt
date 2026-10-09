"""A stand-in InfluxDB: a real HTTP server on a kernel-chosen port that records what it gets."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

import pytest


@dataclass
class Received:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: str
    #: What the stand-in answered, so a test can tell stored reports from refused attempts.
    status: int = 0


@dataclass
class StubInflux:
    """Answers every request with `status` and `reply`, and keeps each request."""

    url: str = ""
    status: int = 204
    reply: str = ""
    requests: list[Received] = field(default_factory=list)


@contextlib.asynccontextmanager
async def serving(stub: StubInflux, port: int = 0) -> AsyncIterator[StubInflux]:
    """Run the stand-in on `port` (kernel-chosen when 0) for the duration of the block."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = {k.lower(): v for k, _, v in (line.partition(": ") for line in lines[1:] if line)}
        body = await reader.readexactly(int(headers.get("content-length", "0")))
        parts = urlsplit(target)
        query = dict(parse_qsl(parts.query))
        stub.requests.append(
            Received(method, parts.path, query, headers, body.decode(), stub.status)
        )
        payload = stub.reply.encode()
        response = f"HTTP/1.1 {stub.status} X\r\nContent-Length: {len(payload)}\r\n"
        writer.write(response.encode() + b"Connection: close\r\n\r\n" + payload)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", port)
    stub.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    async with server:
        yield stub
    server.close()
    await server.wait_closed()


@pytest.fixture
async def influx() -> AsyncIterator[StubInflux]:
    async with serving(StubInflux()) as stub:
        yield stub

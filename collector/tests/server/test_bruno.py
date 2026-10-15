"""The Bruno collection's admin requests (bruno/admin): one for every route the admin listener
serves to read, and none for a route it no longer has."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

ADMIN = Path(__file__).parents[3] / "bruno" / "admin"

#: Read routes the collection leaves out, and why.
LEFT_OUT = {
    "/": "the status page, for a browser",
    "/setup": "the setup page, for a browser",
    "/grafana": "the Grafana page, for a browser",
}


def requests() -> set[str]:
    """The path of every admin request, as the admin listener's routes name them."""
    paths = set()
    for path in ADMIN.glob("*.yml"):
        if path.name == "folder.yml":
            continue
        url = re.search(r'^\s*url: "?([^"\s]+)"?$', path.read_text(encoding="utf-8"), re.MULTILINE)
        assert url, f"{path.name} has no url"
        assert url.group(1).startswith("{{admin_url}}/"), (
            f"{path.name} is not under {{{{admin_url}}}}"
        )
        paths.add(url.group(1).removeprefix("{{admin_url}}").split("?")[0])
    return paths


def served(route: str, paths: set[str]) -> set[str]:
    """The requests whose path the route serves: itself, or with its parameter given."""
    pattern = re.sub(r"\\\{\w+\\\}", r"[^/]+", re.escape(route))
    return {p for p in paths if re.fullmatch(pattern, p)}


def test_every_read_route_has_a_request_and_every_request_a_route(
    admin_client: TestClient,
) -> None:
    routes = {
        r.path
        for r in admin_client.app.routes  # type: ignore[attr-defined]
        if isinstance(r, APIRoute) and "GET" in r.methods
    }
    paths = requests()

    assert {r for r in routes - set(LEFT_OUT) if not served(r, paths)} == set(), (
        "add a request for each of these to bruno/admin"
    )
    assert {p for p in paths if not any(served(r, {p}) for r in routes)} == set(), (
        "requests for routes that are gone"
    )


def test_the_routes_left_out_exist(admin_client: TestClient) -> None:
    """A route listed as left out that the listener no longer has is stale, not a gap."""
    routes = {r.path for r in admin_client.app.routes if isinstance(r, APIRoute)}  # type: ignore[attr-defined]
    assert set(LEFT_OUT) <= routes

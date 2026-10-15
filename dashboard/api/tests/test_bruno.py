"""The Bruno collection in bruno/: a request for every route the dashboard serves to read, none
for a route it no longer has, and no host named but the placeholders, since the repository is
published. bin/test-bruno.sh runs the requests themselves."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from .conftest import REPO

BRUNO = REPO / "bruno"

#: The environments the repository keeps; any other is a deployment's own, which .gitignore keeps
#: out of it.
KEPT = {"local.yml", "example.yml"}

#: Read routes the collection leaves out, and why.
LEFT_OUT = {
    "/": "the page itself, for a browser",
    "/docs/oauth2-redirect": "Swagger UI's own callback",
}

#: Routes served beside the API, which its OpenAPI document does not list.
BESIDE_THE_API = {
    "/healthz",
    "/manifest.webmanifest",
    "/setup",
    "/api/v1/openapi.json",
    "/api/v1/docs",
}


def requests(folder: str, base: str) -> set[str]:
    """The path of every request in a folder of the collection, its variables as route
    parameters: `{{station}}` as `{station}`."""
    paths = set()
    for path in (BRUNO / folder).glob("*.yml"):
        if path.name == "folder.yml":
            continue
        url = re.search(r'^\s*url: "?([^"\s]+)"?$', path.read_text(encoding="utf-8"), re.MULTILINE)
        assert url, f"{path.name} has no url"
        assert url.group(1).startswith(base), f"{path.name} is not under {base}"
        route = url.group(1).removeprefix(base).split("?")[0]
        paths.add(re.sub(r"\{\{(\w+)\}\}", r"{\1}", route))
    return paths


def matches(request: str, route: str) -> bool:
    """Whether a request's path is one the route serves: equal, or the route's parameter given."""
    pattern = re.sub(r"\\\{\w+\\\}", r"[^/]+", re.escape(route))
    return re.fullmatch(pattern, request) is not None


def test_every_read_route_has_a_request_and_every_request_a_route(client: TestClient) -> None:
    api = set(client.get("/api/v1/openapi.json").json()["paths"])
    routes = api | BESIDE_THE_API
    base = "{{dashboard_url}}"
    served = requests("dashboard", base) | requests("dashboard-site", base)

    assert routes - served == set(), "add a request for each of these to bruno/"
    stale = {r for r in served if not any(matches(r, route) for route in routes)}
    assert stale == set(), "requests for routes that are gone"


def test_the_routes_left_out_exist(client: TestClient) -> None:
    """A route listed as left out that the app no longer has is a stale entry, not a gap."""
    for route in LEFT_OUT:
        assert client.get(route, follow_redirects=False).status_code != 404, route


def test_matches_a_route_parameter_and_nothing_wider() -> None:
    assert matches("/api/v1/stations/{station}/now", "/api/v1/stations/{station}/now")
    assert matches("/api/v1/stations/Home/now", "/api/v1/stations/{station}/now")
    assert not matches("/api/v1/stations/Home/now/x", "/api/v1/stations/{station}/now")
    assert not matches("/api/v1/stations", "/api/v1/stations/{station}/now")


def test_no_file_names_a_real_host() -> None:
    """Only the project's default ports on this machine and example.com's placeholders: a
    deployment's own environment is kept out of the repository (see .gitignore)."""
    allowed = re.compile(r"^(127\.0\.0\.1|localhost|[\w.-]*example\.com)$")
    for path in BRUNO.rglob("*"):
        if not path.is_file() or path.parent.name == "environments" and path.name not in KEPT:
            continue
        for host in re.findall(r"https?://([^/:\s]+)", path.read_text(encoding="utf-8")):
            assert allowed.match(host), f"{path.relative_to(REPO)} names {host}"


def test_only_the_collections_own_environments_are_kept() -> None:
    assert {p.name for p in (BRUNO / "environments").iterdir()} >= KEPT
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "bruno/environments/*" in ignore

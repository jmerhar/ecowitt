"""The Grafana page and its push: the files for the stored units, and what Grafana is sent."""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx2
import pytest
from pydantic import ValidationError

from ecowitt.collector.admin import grafana
from ecowitt.collector.admin.stationconfig import ConfigDocument, GrafanaEntry, StationEntry
from ecowitt.core.testing import Received, StubInflux, serving
from ecowitt.core.units import Units

from .conftest import Rig

TOKEN = "glsa_test_token_0123456789"
SAVED = {"url": "", "token": TOKEN, "datasource": "influx", "folder": "Weather"}
SOURCE = {"uid": "influx", "name": "Weather DB", "type": "influxdb"}


def grafana_answers(
    *, folders: list[dict[str, str]] | None = None, source: dict[str, str] | None = None
) -> Callable[[str, str], tuple[int, object]]:
    """A Grafana that accepts everything: its answer to each method and path."""

    def answer(method: str, path: str) -> tuple[int, object]:
        if path == "/api/user":
            return 200, {"login": "sa-ecowitt"}
        if path.startswith("/api/datasources/uid/"):
            return (200, source or SOURCE)
        if path == "/api/search":
            return 200, folders or []
        if path == "/api/folders":
            return 200, {"uid": "new-folder", "title": "Weather"}
        if path == "/api/dashboards/db":
            return 200, {"uid": "ecowitt-weather", "status": "success"}
        if path.startswith("/api/v1/provisioning/folder/"):
            return 200, {}
        return 404, {"message": "Not found"}

    return answer


def stub(answer: Callable[[str, str], tuple[int, object]]) -> StubInflux:
    """A stand-in Grafana on the test's loop, answering as `answer` says."""

    def respond(received: Received) -> tuple[int, str]:
        status, body = answer(received.method, received.path)
        return status, body if isinstance(body, str) else json.dumps(body)

    return StubInflux("http://127.0.0.1", respond=respond)


@dataclass
class FakeGrafana:
    """A stand-in Grafana on its own thread, for page tests: TestClient blocks the loop."""

    url: str
    requests: list[tuple[str, str, dict[str, str], object]] = field(default_factory=list)


@contextlib.contextmanager
def fake_grafana(answer: Callable[[str, str], tuple[int, object]]) -> Iterator[FakeGrafana]:
    fake = FakeGrafana("")

    class Handler(http.server.BaseHTTPRequestHandler):
        def _serve(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            path = self.path.split("?", 1)[0]
            fake.requests.append(
                (self.command, path, dict(self.headers), json.loads(raw) if raw else None)
            )
            status, body = answer(self.command, path)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = _serve  # noqa: N815 - the names http.server calls

        def log_message(self, *_: object) -> None:
            """Keep test output quiet."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestFiles:
    def test_the_rule_group_is_the_file_in_the_apis_spelling(self) -> None:
        group = grafana.rule_group(Units(), "influx")
        rules = {r["uid"]: r for r in group["rules"]}

        assert (group["title"], group["interval"]) == ("ecowitt", 60)
        assert rules["ecowitt-gusts"]["keep_firing_for"] == "30m"
        assert all("keepFiringFor" not in r for r in group["rules"])
        assert len(rules) == len(grafana.provisioning(Units())["groups"][0]["rules"])
        steps = [s["datasourceUid"] for r in group["rules"] for s in r["data"]]
        assert set(steps) == {"influx", "__expr__"}

    def test_the_provisioning_file_reads_the_files_data_source_unless_told(self) -> None:
        def sources(doc: dict) -> set[str]:
            return {s["datasourceUid"] for r in doc["groups"][0]["rules"] for s in r["data"]}

        assert sources(grafana.provisioning(Units())) == {"weather", "__expr__"}
        assert sources(grafana.provisioning(Units(), "other")) == {"other", "__expr__"}

    def test_an_unreadable_interval_is_refused(self) -> None:
        with pytest.raises(ValueError, match="duration"):
            grafana._seconds("a minute")

    def test_defaults_fill_what_is_left_empty(self) -> None:
        assert grafana.values_of({"url": " http://g:3000 ", "token": "t", "folder": ""}) == {
            "url": "http://g:3000",
            "token": "t",
            "datasource": "weather",
            "folder": "Weather",
        }


class TestCheck:
    async def test_a_working_token_and_influxdb_source_give_its_name(self) -> None:
        async with serving(stub(grafana_answers())) as s, httpx2.AsyncClient() as client:
            name = await grafana.check(client, {**SAVED, "url": s.url})

        assert name == "Weather DB"
        assert [r.path for r in s.requests] == ["/api/user", "/api/datasources/uid/influx"]
        assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in s.requests)

    @pytest.mark.parametrize(
        ("status", "body", "says"),
        [
            (401, {"message": "invalid API key"}, "it refused the token"),
            (403, {"message": "denied"}, "give its service account the Editor role"),
            (500, {"message": "database locked"}, "it answered 500: database locked"),
            (502, "<html>bad gateway</html>", "it answered 502"),
            (200, "<html>login</html>", "was not Grafana's API"),
        ],
    )
    async def test_each_refusal_is_said_in_words(
        self, status: int, body: object, says: str
    ) -> None:
        async with (
            serving(stub(lambda _method, _path: (status, body))) as s,
            httpx2.AsyncClient() as c,
        ):
            with pytest.raises(grafana.GrafanaError, match=says) as raised:
                await grafana.check(c, {**SAVED, "url": s.url})

        assert TOKEN not in str(raised.value)

    async def test_a_missing_data_source_is_named(self) -> None:
        def answer(method: str, path: str) -> tuple[int, object]:
            return (404, {"message": "nope"}) if "datasources" in path else (200, {})

        async with serving(stub(answer)) as s, httpx2.AsyncClient() as client:
            with pytest.raises(grafana.GrafanaError, match="no data source with uid influx"):
                await grafana.check(client, {**SAVED, "url": s.url})

    async def test_a_data_source_of_another_kind_is_refused(self) -> None:
        answer = grafana_answers(source={"uid": "influx", "type": "prometheus"})
        async with serving(stub(answer)) as s, httpx2.AsyncClient() as client:
            with pytest.raises(grafana.GrafanaError, match="is prometheus, not InfluxDB"):
                await grafana.check(client, {**SAVED, "url": s.url})

    async def test_an_unreachable_grafana_says_so(self) -> None:
        async with httpx2.AsyncClient() as client:
            with pytest.raises(grafana.GrafanaError, match="cannot connect"):
                await grafana.check(client, {**SAVED, "url": "http://127.0.0.1:1"})


class TestPush:
    async def test_a_push_creates_the_folder_then_sends_the_dashboard_and_rules(self) -> None:
        async with serving(stub(grafana_answers())) as s, httpx2.AsyncClient() as client:
            done = await grafana.push(
                client, {**SAVED, "url": s.url}, Units(temperature="f"), "9.9"
            )

        assert done == "Pushed the dashboard and 10 alert rules to the Weather folder."
        steps = [(r.method, r.path) for r in s.requests]
        assert steps == [
            ("GET", "/api/user"),
            ("GET", "/api/datasources/uid/influx"),
            ("GET", "/api/search"),
            ("POST", "/api/folders"),
            ("POST", "/api/dashboards/db"),
            ("PUT", "/api/v1/provisioning/folder/new-folder/rule-groups/ecowitt"),
        ]
        dashboard = json.loads(s.requests[4].body)
        assert (dashboard["folderUid"], dashboard["overwrite"]) == ("new-folder", True)
        assert dashboard["dashboard"]["id"] is None
        assert dashboard["message"] == "Pushed by Ecowitt Server 9.9"
        variable = next(
            v for v in dashboard["dashboard"]["templating"]["list"] if v["type"] == "datasource"
        )
        assert variable["current"] == {"text": "Weather DB", "value": "influx"}
        # Rendered for the units the collector stores.
        assert "temp_f" in json.dumps(dashboard["dashboard"])
        rules = s.requests[5]
        assert rules.headers["x-disable-provenance"] == "true"
        group = json.loads(rules.body)
        assert {r["uid"] for r in group["rules"]} == {
            r["uid"] for r in grafana.provisioning(Units())["groups"][0]["rules"]
        }
        assert "temp_f" in json.dumps(group)

    async def test_a_folder_of_that_name_is_used_rather_than_a_new_one(self) -> None:
        folders = [{"uid": "f-other", "title": "Weather old"}, {"uid": "f-1", "title": "Weather"}]
        async with serving(stub(grafana_answers(folders=folders))) as s, httpx2.AsyncClient() as c:
            await grafana.push(c, {**SAVED, "url": s.url}, Units(), "9.9")

        assert ("POST", "/api/folders") not in [(r.method, r.path) for r in s.requests]
        assert s.requests[-1].path == "/api/v1/provisioning/folder/f-1/rule-groups/ecowitt"


def _connected(rig: Rig, url: str) -> None:
    rig.store.replace(
        ConfigDocument(grafana=GrafanaEntry(url=url, token=TOKEN, datasource="influx"))
    )


class TestPage:
    def test_the_page_offers_both_files_for_the_stored_units(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(units=Units(temperature="f", wind="mph")))

        html = rig.client.get("/grafana").text

        assert '<a href="/grafana" class="here">Grafana</a>' in html
        assert "°F, hPa, mm, mph" in html
        assert "temp_f" in html and "temp_c" not in html
        assert html.count('data-copy="') == 2
        assert '<script src="/static/clipboard.js" defer></script>' in html
        assert "rule-groups/ecowitt" in html
        assert rig.client.get("/static/clipboard.js").status_code == 200

    def test_each_file_downloads_as_json(self, rig: Rig) -> None:
        _connected(rig, "http://127.0.0.1:1")
        for name in ("weather.json", "alerts.json", "rule-group.json"):
            response = rig.client.get(f"/grafana/{name}")
            assert response.status_code == 200
            assert response.headers["content-disposition"] == f'attachment; filename="{name}"'
            assert json.loads(response.text)
        alerts = rig.client.get("/grafana/alerts.json").json()
        steps = {s["datasourceUid"] for r in alerts["groups"][0]["rules"] for s in r["data"]}
        assert steps == {"influx", "__expr__"}
        assert rig.client.get("/grafana/other.json").status_code == 404

    def test_the_token_is_never_shown_or_reported(self, rig: Rig) -> None:
        _connected(rig, "http://user:secret@grafana.example:3000")

        assert TOKEN not in rig.client.get("/grafana").text
        status = rig.client.get("/api/status").json()["grafana"]
        assert status == {
            "configured": True,
            "url": "http://grafana.example:3000",
            "token_set": True,
            "datasource": "influx",
            "folder": "Weather",
        }
        rig.store.replace(ConfigDocument())
        assert rig.client.get("/api/status").json()["grafana"] == {"configured": False}


class TestConnection:
    FORM = {"url": "http://grafana.example:3000", "token": TOKEN, "datasource": "", "folder": ""}

    def test_saving_keeps_the_defaults_and_the_token(self, rig: Rig) -> None:
        response = rig.post("/grafana/connection", {**self.FORM, "action": "save"})

        assert response.status_code == 303
        assert response.headers["location"].startswith("/grafana?message=")
        entry = rig.store.document.grafana
        assert entry is not None and (entry.datasource, entry.folder) == ("weather", "Weather")
        # An empty token on a later save keeps the saved one.
        rig.post(
            "/grafana/connection", {**self.FORM, "token": "", "folder": "Home", "action": "save"}
        )
        entry = rig.store.document.grafana
        assert entry is not None and (entry.token, entry.folder) == (TOKEN, "Home")

    def test_a_bad_address_or_no_token_is_refused_with_the_form_kept(self, rig: Rig) -> None:
        response = rig.post("/grafana/connection", {**self.FORM, "url": "grafana", "token": ""})

        assert response.status_code == 400
        assert "URL must start with http://" in response.text
        assert "Service-account token is required" in response.text
        assert 'value="grafana"' in response.text
        assert rig.store.document.grafana is None

    def test_testing_reports_what_grafana_said_and_saves_nothing(self, rig: Rig) -> None:
        with fake_grafana(grafana_answers()) as fake:
            ok = rig.post("/grafana/connection", {**self.FORM, "url": fake.url, "action": "test"})
        with fake_grafana(lambda _method, _path: (401, {"message": "invalid"})) as fake:
            refused = rig.post(
                "/grafana/connection", {**self.FORM, "url": fake.url, "action": "test"}
            )

        assert ok.status_code == 200 and "Weather DB is an InfluxDB data source" in ok.text
        assert (
            refused.status_code == 400 and "Grafana refused: it refused the token." in refused.text
        )
        assert rig.store.document.grafana is None

    def test_removing_forgets_the_connection(self, rig: Rig) -> None:
        _connected(rig, "http://grafana.example:3000")

        response = rig.post("/grafana/connection", {"action": "clear"})

        assert response.status_code == 303
        assert rig.store.document.grafana is None


class TestPushPage:
    def test_a_push_sends_everything_and_says_what_was_done(self, rig: Rig) -> None:
        with fake_grafana(grafana_answers()) as fake:
            _connected(rig, fake.url)
            response = rig.post("/grafana/push", {})

        assert response.status_code == 303
        assert "Pushed+the+dashboard+and+10+alert+rules" in response.headers["location"]
        assert [(m, p) for m, p, _, _ in fake.requests][-1] == (
            "PUT",
            "/api/v1/provisioning/folder/new-folder/rule-groups/ecowitt",
        )

    def test_a_refused_push_is_shown(self, rig: Rig) -> None:
        with fake_grafana(lambda _method, _path: (403, {"message": "forbidden"})) as fake:
            _connected(rig, fake.url)
            response = rig.post("/grafana/push", {})

        assert response.status_code == 400
        assert "give its service account the Editor role" in response.text

    def test_without_a_connection_there_is_nothing_to_push_to(self, rig: Rig) -> None:
        response = rig.post("/grafana/push", {})

        assert response.status_code == 400
        assert "Save a Grafana connection first." in response.text

    def test_a_push_from_another_site_sends_nothing(self, rig: Rig) -> None:
        with fake_grafana(grafana_answers()) as fake:
            _connected(rig, fake.url)
            response = rig.post("/grafana/push", {}, headers={"Origin": "https://evil.example"})

        assert response.status_code == 403
        assert fake.requests == []

    def test_the_shared_client_is_used_when_there_is_one(self, rig: Rig) -> None:
        with fake_grafana(grafana_answers()) as fake:
            _connected(rig, fake.url)
            rig.context.http = httpx2.AsyncClient()
            response = rig.post("/grafana/push", {})

        assert response.status_code == 303
        assert fake.requests


def test_a_saved_connection_needs_station_free_documents_too() -> None:
    """The Grafana entry sits beside stations without disturbing them."""
    document = ConfigDocument(
        stations=[StationEntry(name="Home", passkey="K")],
        grafana=GrafanaEntry(url="http://g:3000", token="t"),
    )

    assert document.grafana is not None and document.station("Home") is not None


def test_a_hand_edited_connection_is_checked_like_the_form() -> None:
    with pytest.raises(ValidationError, match="URL must start with http"):
        ConfigDocument.model_validate({"grafana": {"url": "grafana:3000", "token": "t"}})

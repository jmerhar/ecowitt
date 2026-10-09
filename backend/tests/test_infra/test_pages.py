"""The status and setup pages, through the admin app with a real store and handler."""

from __future__ import annotations

import base64
import contextlib
import http.server
import json
import re
import threading
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt import admin
from ecowitt.calibration import CalibrationMonitor
from ecowitt.config import Settings
from ecowitt.configstore import ConfigStore
from ecowitt.handler import StationHandler
from ecowitt.pending import PendingStations, fingerprint
from ecowitt.state import State
from ecowitt.stationconfig import ConfigDocument, StationEntry, load_document

from ..conftest import FIXTURE_PASSKEY, payload

ORIGIN = {"Origin": "http://testserver"}


class Sink:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def submit(self, body: str) -> None:
        self.bodies.append(body)


@dataclass
class Rig:
    client: TestClient
    store: ConfigStore
    handler: StationHandler
    pending: PendingStations
    calibration: CalibrationMonitor
    context: admin.AdminContext

    @property
    def csrf(self) -> str:
        return admin.auth.csrf_token(self.context.secret)

    def post(
        self,
        path: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ):
        body = urllib.parse.urlencode({"csrf": self.csrf, **data})
        hdrs = {"Content-Type": "application/x-www-form-urlencoded", **ORIGIN, **(headers or {})}
        if auth:
            hdrs["Authorization"] = (
                "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            )
        return self.client.post(path, content=body, headers=hdrs)

    async def report(self, passkey: str = FIXTURE_PASSKEY) -> bool:
        fields = dict(urllib.parse.parse_qsl(payload("hp2551_indoor"), keep_blank_values=True))
        return await self.handler.handle(fields | {"PASSKEY": passkey}, "192.0.2.9")


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    settings = Settings(
        data_dir=tmp_path,
        opentopodata_url="http://127.0.0.1:1/x",
        open_elevation_url="http://127.0.0.1:1/y",
    )
    store = ConfigStore(settings.config_file)
    pending, calibration = PendingStations(), CalibrationMonitor()
    handler = StationHandler(store.stations, Sink(), pending=pending, calibration=calibration)
    store.subscribe(lambda stations: setattr(handler, "config", stations))
    context = admin.AdminContext(
        settings,
        State(),
        secret=b"s" * 32,
        store=store,
        handler=handler,
        pending=pending,
        calibration=calibration,
    )
    with TestClient(admin.build_app(context), follow_redirects=False) as client:
        yield Rig(client, store, handler, pending, calibration, context)


@contextlib.contextmanager
def json_server(reply: object) -> Iterator[str]:
    """Serve one JSON answer from its own thread.

    Its own thread because TestClient blocks the test's event loop while a request runs, so a
    stand-in on that loop could never answer the lookup the request makes.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            """Keep test output quiet."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def adopt(rig: Rig, name: str = "Home") -> None:
    response = rig.post("/setup/station", {"adopt": fingerprint(FIXTURE_PASSKEY), "name": name})
    assert response.status_code == 303, response.text


class TestFirstRun:
    def test_an_empty_install_says_what_to_do(self, rig: Rig) -> None:
        page = rig.client.get("/").text

        assert "No station is configured yet" in page
        assert "Customized" in page

    async def test_a_reporting_station_is_offered_without_its_passkey(self, rig: Rig) -> None:
        assert await rig.report() is False

        status = rig.client.get("/").text
        setup = rig.client.get("/setup").text

        assert "1 station is reporting" in status
        assert "HP2551AE_Pro_V2.1.4" in setup
        assert fingerprint(FIXTURE_PASSKEY) in setup
        assert FIXTURE_PASSKEY not in setup and FIXTURE_PASSKEY not in status

    async def test_adopting_stores_the_passkey_and_accepts_the_next_report(self, rig: Rig) -> None:
        await rig.report()

        adopt(rig)

        assert load_document(rig.store.path).stations[0].passkey == FIXTURE_PASSKEY
        assert rig.pending.list() == []
        assert await rig.report() is True
        assert "Saved Home." in rig.client.get("/setup?message=Saved+Home.").text

    async def test_a_refused_adoption_leaves_the_station_on_offer(self, rig: Rig) -> None:
        await rig.report()

        response = rig.post("/setup/station", {"adopt": fingerprint(FIXTURE_PASSKEY), "name": ""})

        assert response.status_code == 400
        assert [p.passkey for p in rig.pending.list()] == [FIXTURE_PASSKEY]
        adopt(rig)
        assert rig.pending.list() == []

    def test_adopting_a_station_not_heard_recently_explains(self, rig: Rig) -> None:
        response = rig.post("/setup/station", {"adopt": "000000000000", "name": "Home"})

        assert response.status_code == 400
        assert "has not reported in the last hour" in response.text


class TestCrossSiteForms:
    @pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": ""}])
    @pytest.mark.parametrize(
        ("path", "fields"),
        [
            ("/setup/station", {"name": "Evil", "passkey": "X"}),
            ("/setup/units", {"temperature": "f"}),
            (
                "/setup/admin",
                {"username": "evil", "password": "takeover1", "password_again": "takeover1"},
            ),
            ("/dismiss", {"station": "Home", "kind": "location"}),
        ],
    )
    def test_no_form_from_elsewhere_changes_anything(
        self, rig: Rig, headers: dict[str, str], path: str, fields: dict[str, str]
    ) -> None:
        """Every route that changes anything refuses a cross-site submission."""
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        before = rig.store.path.read_text()

        response = rig.post(path, fields, headers=headers)

        assert response.status_code == 403
        assert rig.store.path.read_text() == before

    def test_a_wrong_token_changes_nothing(self, rig: Rig) -> None:
        response = rig.client.post(
            "/setup/station",
            content="csrf=nope&name=Evil&passkey=X",
            headers={"Content-Type": "application/x-www-form-urlencoded", **ORIGIN},
        )

        assert response.status_code == 403
        assert rig.store.document.stations == []

    def test_an_oversized_form_is_refused(self, rig: Rig) -> None:
        response = rig.post("/setup/station", {"name": "x" * (admin.MAX_FORM_BYTES + 1)})

        assert response.status_code == 413

    def test_every_form_on_every_page_carries_the_token(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        for page in ("/", "/setup"):
            html = rig.client.get(page).text
            forms = html.count('method="post"')
            assert forms and html.count(f'name="csrf" value="{rig.csrf}"') == forms


class TestStations:
    def test_add_by_passkey(self, rig: Rig) -> None:
        assert rig.post("/setup/station", {"name": "Home", "passkey": "ABC"}).status_code == 303

        assert rig.store.stations.lookup("ABC").name == "Home"  # type: ignore[union-attr]

    def test_a_duplicate_name_is_refused_with_the_reason(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        response = rig.post("/setup/station", {"name": "Home", "passkey": "B"})

        assert response.status_code == 400
        assert "share a name" in response.text

    def test_editing_keeps_the_passkey_and_saves_names_and_location(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        response = rig.post(
            "/setup/station",
            {
                "original": "Home",
                "name": "House",
                "latitude": "45,5",
                "longitude": "7.4",
                "altitude_m": "180",
                "sensor_indoor": "Lounge",
                "sensor_ch1": " ",
                "new_sensor_id": "ch2",
                "new_sensor_name": "Study",
                "action": "save",
            },
        )

        assert response.status_code == 303
        (entry,) = rig.store.document.stations
        assert (entry.name, entry.passkey, entry.latitude, entry.longitude, entry.altitude_m) == (
            "House",
            "A",
            45.5,
            7.4,
            180.0,
        )
        assert entry.sensors == {"indoor": "Lounge", "ch2": "Study"}

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"latitude": "north"}, "must be numbers"),
            ({"latitude": "95"}, "latitude"),
            ({"new_sensor_id": "Bad Id", "new_sensor_name": "x"}, "identifier"),
            ({"new_sensor_id": "ch9"}, "identifier"),
            ({"sensor_BAD": "x"}, "look like"),
            ({"name": ""}, "name"),
        ],
    )
    def test_invalid_edits_are_refused_with_the_reason(
        self, rig: Rig, fields: dict[str, str], message: str
    ) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        response = rig.post("/setup/station", {"original": "Home", "name": "Home", **fields})

        assert response.status_code == 400
        assert message in response.text
        assert rig.store.document.stations[0].name == "Home"

    def test_delete(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        assert (
            rig.post("/setup/station", {"original": "Home", "action": "delete"}).status_code == 303
        )
        assert rig.store.document.stations == []
        assert (
            rig.post("/setup/station", {"original": "Home", "action": "delete"}).status_code == 400
        )


class TestElevationLookup:
    def test_the_proposed_altitude_is_shown_not_saved(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})
        with json_server({"results": [{"elevation": 179.6}]}) as url:
            rig.context.settings = rig.context.settings.model_copy(update={"opentopodata_url": url})
            response = rig.post(
                "/setup/station",
                {
                    "original": "Home",
                    "name": "Home",
                    "latitude": "45.8",
                    "longitude": "7.4",
                    "action": "lookup",
                },
            )

        assert response.status_code == 200
        assert "gives 180 m" in response.text
        assert re.search(r'name="altitude_m"[^>]*value="180"', response.text)
        assert rig.store.document.stations[0].altitude_m is None

    async def test_the_shared_client_is_used_when_there_is_one(self, rig: Rig) -> None:
        import httpx2

        rig.post("/setup/station", {"name": "Home", "passkey": "A"})
        async with httpx2.AsyncClient() as client:
            rig.context.http = client
            with json_server({"results": [{"elevation": 42.0}]}) as url:
                rig.context.settings = rig.context.settings.model_copy(
                    update={"opentopodata_url": url}
                )
                response = rig.post(
                    "/setup/station",
                    {
                        "original": "Home",
                        "name": "Home",
                        "latitude": "1",
                        "longitude": "2",
                        "action": "lookup",
                    },
                )

        assert "gives 42 m" in response.text

    def test_without_coordinates_it_asks_for_them(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        response = rig.post(
            "/setup/station", {"original": "Home", "name": "Home", "action": "lookup"}
        )

        assert response.status_code == 400
        assert "Enter both coordinates" in response.text

    async def test_when_the_services_fail_it_says_to_enter_it_by_hand(self, rig: Rig) -> None:
        await rig.report()

        response = rig.post(
            "/setup/station",
            {
                "adopt": fingerprint(FIXTURE_PASSKEY),
                "name": "Home",
                "latitude": "45.8",
                "longitude": "7.4",
                "action": "lookup",
            },
        )

        assert response.status_code == 400
        assert "enter the altitude by hand" in response.text
        # Looking up is not adopting: the station is still offered.
        assert [p.passkey for p in rig.pending.list()] == [FIXTURE_PASSKEY]


class TestUnitsAndLogin:
    def test_units(self, rig: Rig) -> None:
        response = rig.post(
            "/setup/units",
            {"temperature": "f", "pressure": "inhg", "rain": "in", "wind": "ms", "distance": "mi"},
        )

        assert response.status_code == 303
        assert rig.store.document.units.temperature == "f"
        assert rig.post("/setup/units", {"temperature": "k"}).status_code == 400

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            (
                {"username": "", "password": "longenough", "password_again": "longenough"},
                "needs a username",
            ),
            ({"username": "a", "password": "short", "password_again": "short"}, "at least"),
            ({"username": "a", "password": "longenough", "password_again": "different"}, "differ"),
        ],
    )
    def test_a_bad_login_is_refused(self, rig: Rig, fields: dict[str, str], message: str) -> None:
        response = rig.post("/setup/admin", fields)

        assert response.status_code == 400 and message in response.text
        assert rig.store.document.admin is None

    def test_once_set_everything_but_health_needs_it(self, rig: Rig) -> None:
        rig.post(
            "/setup/admin",
            {"username": "admin", "password": "correct-horse", "password_again": "correct-horse"},
        )

        assert rig.client.get("/").status_code == 401
        assert rig.client.get("/api/status").status_code == 401
        assert rig.client.get("/healthz").status_code == 200
        assert rig.client.get("/", auth=("admin", "correct-horse")).status_code == 200
        assert "correct-horse" not in rig.store.path.read_text()

    def test_failed_logins_are_throttled(self, rig: Rig) -> None:
        rig.post(
            "/setup/admin",
            {"username": "admin", "password": "correct-horse", "password_again": "correct-horse"},
        )

        codes = [rig.client.get("/", auth=("admin", f"guess{i}")).status_code for i in range(12)]

        assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]

    def test_the_login_can_be_removed(self, rig: Rig) -> None:
        creds = ("admin", "correct-horse")
        rig.post(
            "/setup/admin",
            {"username": "admin", "password": "correct-horse", "password_again": "correct-horse"},
        )

        assert rig.post("/setup/admin", {"action": "clear"}, auth=creds).status_code == 303
        assert rig.client.get("/").status_code == 200


class TestStatus:
    async def test_a_station_with_readings_and_warnings(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()

        page = rig.client.get("/").text
        readings = rig.client.get("/api/readings").json()["stations"][0]

        assert "<h2>Home</h2>" in page
        assert "Altitude not set" in page
        assert "Pressure: absolute" in page
        assert readings["name"] == "Home"
        assert [s["sensor"] for s in readings["sensors"]][:2] == ["indoor", "ch1"]
        assert readings["sensors"][0]["temp"] == {"value": 23.2222, "unit": "c"}
        assert readings["warnings"][0]["kind"] == "location"
        assert readings["pressure"]["unit"] == "hpa"

    async def test_the_airing_column_answers_whether_to_open_the_windows(self, rig: Rig) -> None:
        """With an outdoor sensor, each room shows which way airing would go."""
        rig.store.replace(
            ConfigDocument(
                stations=[StationEntry(name="Home", passkey="K", sensors={"ch1": "Bathroom"})]
            )
        )
        fields = {
            "PASSKEY": "K",
            "dateutc": "now",
            "tempinf": "71.6",
            "humidityin": "62",
            "tempf": "50.0",
            "humidity": "80",
            "temp1f": "77.0",
            "humidity1": "40",
            "soilmoisture1": "30",
        }
        await rig.handler.handle(fields, "192.0.2.9")

        sensors = {
            s["sensor"]: s for s in rig.client.get("/api/readings").json()["stations"][0]["sensors"]
        }
        page = rig.client.get("/").text

        assert sensors["indoor"]["airing_delta"]["value"] > 0
        assert sensors["ch1"]["airing_humidity"] < 40
        assert "drier outside" in page
        assert "outdoor" in sensors and "airing_delta" not in sensors["outdoor"]
        # A sensor without temperature (the soil probe) is not a row in the climate table.
        assert "soil1" not in sensors

    async def test_a_humid_afternoon_says_damper_outside(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        await rig.handler.handle(
            {
                "PASSKEY": "K",
                "dateutc": "now",
                "tempinf": "75",
                "humidityin": "50",
                "tempf": "86",
                "humidity": "85",
            },
            "192.0.2.9",
        )

        assert "damper outside" in rig.client.get("/").text

    async def test_a_report_without_pressure_shows_no_pressure_line(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        await rig.handler.handle(
            {"PASSKEY": "K", "dateutc": "now", "tempinf": "71.6", "humidityin": "62"}, "192.0.2.9"
        )

        assert rig.client.get("/api/readings").json()["stations"][0]["pressure"] == {}
        assert "Pressure:" not in rig.client.get("/").text

    async def test_a_non_numeric_correction_is_tolerated(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))

        assert (
            rig.post(
                "/dismiss", {"station": "Home", "kind": "location", "correction": "abc"}
            ).status_code
            == 303
        )
        assert rig.store.document.stations[0].dismissed == {"location": 0.0}

    async def test_dismissing_hides_a_warning(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)

        response = rig.post("/dismiss", {"station": "Home", "kind": "location", "correction": ""})

        assert response.status_code == 303 and response.headers["location"].startswith("/?")
        assert "Altitude not set" not in rig.client.get("/").text
        assert rig.post("/dismiss", {"station": "Nope", "kind": "location"}).status_code == 400

    async def test_names_are_escaped(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        rig.post(
            "/setup/station",
            {"original": "Home", "name": "Home", "sensor_ch1": "<script>x</script>"},
        )
        await rig.report()

        page = rig.client.get("/").text

        assert "<script>x</script>" not in page
        assert "&lt;script&gt;x&lt;/script&gt;" in page


def test_without_a_store_nothing_can_be_saved(tmp_path: Path) -> None:
    context = admin.AdminContext(Settings(data_dir=tmp_path), State(), secret=b"s" * 32)
    with TestClient(admin.build_app(context), follow_redirects=False) as client:
        page = client.get("/setup").text
        response = client.post(
            "/setup/station",
            content=urllib.parse.urlencode(
                {"csrf": admin.auth.csrf_token(b"s" * 32), "name": "x", "passkey": "y"}
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded", **ORIGIN},
        )

    assert "nothing here can be saved" in page
    assert response.status_code == 400
    assert "no configuration file" in response.text


def test_a_save_failure_is_shown(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(rig.store, "replace", refuse)

    response = rig.post("/setup/station", {"name": "Home", "passkey": "A"})

    assert response.status_code == 400
    assert "Could not save the configuration: Permission denied" in response.text

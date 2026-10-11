"""The status and setup pages, through the admin app with a real store and handler."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import http.server
import json
import re
import threading
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecowitt.collector.admin import app as admin
from ecowitt.collector.admin.calibration import CalibrationMonitor
from ecowitt.collector.admin.configstore import ConfigStore
from ecowitt.collector.admin.modelfeed import ModelFeed
from ecowitt.collector.admin.stationconfig import ConfigDocument, StationEntry, load_document
from ecowitt.collector.config import Settings
from ecowitt.collector.ingest.handler import StationHandler
from ecowitt.collector.ingest.pending import PendingStations
from ecowitt.collector.state import State
from ecowitt.core.store.base import Row
from ecowitt.core.store.lineprotocol import encode

from ..conftest import FIXTURE_PASSKEY, payload

ORIGIN = {"Origin": "http://localhost"}


class Sink:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def submit(self, rows: list[Row]) -> None:
        self.bodies.append(encode(rows))


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
    with TestClient(
        base_url="http://localhost", app=admin.build_app(context), follow_redirects=False
    ) as client:
        yield Rig(client, store, handler, pending, calibration, context)


@contextlib.contextmanager
def json_server(reply: object, *, status: int = 200, body: str | None = None) -> Iterator[str]:
    """Serve one answer from its own thread: `reply` as JSON, or `body` as it is.

    Its own thread because TestClient blocks the test's event loop while a request runs, so a
    stand-in on that loop could never answer the lookup the request makes.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
            payload = json.dumps(reply).encode() if body is None else body.encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.do_GET()

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


def db(kind: str, **values: str) -> dict[str, str]:
    """A database form: the chosen kind, and that kind's fields under its prefix."""
    return {"kind": kind, **{f"{kind}.{name}": value for name, value in values.items()}}


def use_database(rig: Rig, url: str = "http://127.0.0.1:1") -> None:
    """Save an InfluxDB 3 connection; port 1 refuses, so nothing is ever written."""
    response = rig.post("/setup/database", db("influx3", url=url, token="t0ken"))
    assert response.status_code == 303, response.text


def adopt(rig: Rig, name: str = "Home") -> None:
    response = rig.post(
        "/setup/station", {"adopt": rig.pending.fingerprint(FIXTURE_PASSKEY), "name": name}
    )
    assert response.status_code == 303, response.text


class TestFirstRun:
    def test_an_empty_install_opens_on_the_setup_page(self, rig: Rig) -> None:
        response = rig.client.get("/")

        assert response.status_code == 303
        assert response.headers["location"] == "/setup"
        assert "No database is set up yet" in rig.client.get("/setup").text

    def test_once_anything_is_configured_the_status_page_says_what_to_do(self, rig: Rig) -> None:
        use_database(rig)

        page = rig.client.get("/").text

        assert "No station is configured yet" in page
        assert "Customized" in page

    async def test_a_reporting_station_is_offered_without_its_passkey(self, rig: Rig) -> None:
        use_database(rig)
        assert await rig.report() is False

        status = rig.client.get("/").text
        setup = rig.client.get("/setup").text

        assert "1 station is reporting" in status
        assert "HP2551AE_Pro_V2.1.4" in setup
        assert rig.pending.fingerprint(FIXTURE_PASSKEY) in setup
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

        response = rig.post(
            "/setup/station", {"adopt": rig.pending.fingerprint(FIXTURE_PASSKEY), "name": ""}
        )

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
                {
                    "enabled": "on",
                    "username": "evil",
                    "password": "takeover1",
                    "password_again": "takeover1",
                },
            ),
            ("/dismiss", {"station": "Home", "kind": "location"}),
            ("/setup/database", {"kind": "influx3", "influx3.url": "http://evil.example"}),
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
            ({"altitude_m": "1e308"}, "altitude"),
            ({"timezone": "Europe/Atlantis"}, "not a time zone name"),
            ({"altitude_m": "nan"}, "must be numbers"),
            ({"latitude": "inf"}, "must be numbers"),
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

    def test_a_time_zone_is_saved_and_cleared(self, rig: Rig) -> None:
        rig.post("/setup/station", {"name": "Home", "passkey": "A"})

        rig.post("/setup/station", {"original": "Home", "name": "Home", "timezone": "UTC"})
        assert rig.store.document.stations[0].timezone == "UTC"

        rig.post("/setup/station", {"original": "Home", "name": "Home", "timezone": " "})
        assert rig.store.document.stations[0].timezone is None

    def test_the_zone_from_the_coordinates_is_offered_as_the_placeholder(self, rig: Rig) -> None:
        rig.post(
            "/setup/station",
            {"name": "Home", "passkey": "A", "latitude": "38.72", "longitude": "-9.14"},
        )

        page = rig.client.get("/setup").text

        assert re.search(r'name="timezone"[^>]*placeholder="Europe/Lisbon"', page, re.S)
        assert '<option value="Europe/Lisbon">' in page

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
                "adopt": rig.pending.fingerprint(FIXTURE_PASSKEY),
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


class TestDeviceLocation:
    def test_each_station_form_has_a_location_button_wired_to_its_own_fields(
        self, rig: Rig
    ) -> None:
        """The script finds its inputs by these ids; a button naming a missing one does nothing."""
        rig.store.replace(
            ConfigDocument(
                stations=[StationEntry(name="A", passkey="1"), StationEntry(name="B", passkey="2")]
            )
        )

        page = rig.client.get("/setup").text
        buttons = re.findall(
            r'data-geolocate data-lat="([^"]+)"\s+data-lon="([^"]+)" data-status="([^"]+)"', page
        )

        assert len(buttons) == 2
        assert len(set(buttons)) == 2
        for ids in buttons:
            for element_id in ids:
                assert page.count(f'id="{element_id}"') == 1, element_id
        assert '<script src="/static/geolocate.js" defer></script>' in page

    def test_the_button_does_not_submit_the_form(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="A", passkey="1")]))

        page = rig.client.get("/setup").text

        assert re.search(r'<button class="secondary" type="button" data-geolocate', page)

    def test_the_script_is_served(self, rig: Rig) -> None:
        response = rig.client.get("/static/geolocate.js")

        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "getCurrentPosition" in response.text


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
            ({"username": "a"}, "at least"),
        ],
    )
    def test_a_bad_login_is_refused(self, rig: Rig, fields: dict[str, str], message: str) -> None:
        response = rig.post("/setup/admin", {"enabled": "on", **fields})

        assert response.status_code == 400 and message in response.text
        assert rig.store.document.admin is None

    def test_once_set_everything_but_health_needs_it(self, rig: Rig) -> None:
        rig.post(
            "/setup/admin",
            {
                "enabled": "on",
                "username": "admin",
                "password": "correct-horse",
                "password_again": "correct-horse",
            },
        )

        assert rig.client.get("/setup").status_code == 401
        assert rig.client.get("/api/status").status_code == 401
        assert rig.client.get("/healthz").status_code == 200
        assert rig.client.get("/setup", auth=("admin", "correct-horse")).status_code == 200
        assert "correct-horse" not in rig.store.path.read_text()

    def test_failed_logins_are_throttled(self, rig: Rig) -> None:
        rig.post(
            "/setup/admin",
            {
                "enabled": "on",
                "username": "admin",
                "password": "correct-horse",
                "password_again": "correct-horse",
            },
        )

        codes = [rig.client.get("/", auth=("admin", f"guess{i}")).status_code for i in range(12)]

        assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]

    def test_the_login_can_be_removed(self, rig: Rig) -> None:
        creds = ("admin", "correct-horse")
        rig.post(
            "/setup/admin",
            {
                "enabled": "on",
                "username": "admin",
                "password": "correct-horse",
                "password_again": "correct-horse",
            },
        )

        assert rig.post("/setup/admin", {}, auth=creds).status_code == 303
        assert rig.store.document.admin is None
        assert rig.client.get("/setup").status_code == 200


def with_model(rig: Rig, fields: dict[str, object], *, age: int = 600) -> None:
    """Give the status page a model feed whose latest row for Home holds `fields`."""
    feed = ModelFeed(
        lambda: rig.store.stations,
        Sink(),
        rig.calibration,
        None,  # type: ignore[arg-type] - never fetches
        url="",
        interval_seconds=60,
    )
    station = rig.store.stations.get("Home")
    model = station.weather_model if station else "best_match"
    tags = (("model", model), ("source", "open_meteo"), ("station", "Home"))
    feed.latest["Home"] = Row("model", tags, int(time.time()) - age, fields)
    rig.context.model = feed


def locate(rig: Rig, weather_model: str = "best_match") -> None:
    """Give the adopted station Home coordinates, and a weather model."""
    response = rig.post(
        "/setup/station",
        {
            "original": "Home",
            "name": "Home",
            "latitude": "45.0",
            "longitude": "7.0",
            "weather_model": weather_model,
        },
    )
    assert response.status_code == 303, response.text


class TestWeatherModel:
    async def test_the_model_is_shown_beside_the_stations_readings(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()
        locate(rig)
        own = next(
            p.fields["abs_hpa"] for p in rig.handler.latest["Home"].points if p.table == "pressure"
        )
        with_model(
            rig,
            {
                "temp_c": 18.4,
                "dewpoint_c": 10.0,
                "abs_hpa": own - 1.25,
                "weather_code": 3,
                "cloud_cover_pct": 90.0,
                "precip_15m_mm": 0.2,
                "is_day": True,
            },
        )

        page = rig.client.get("/").text
        view = rig.client.get("/api/readings").json()["stations"][0]["model"]

        assert "<h3>Weather model</h3>" in page
        assert "Best for this location (best_match), from Open-Meteo,\n    for 10 min ago" in page
        assert view["items"] == [
            {"label": "Sky", "text": "Overcast", "difference": None},
            # No outdoor sensor on this console, so the temperature has nothing to compare; nor
            # has the dew point, though the indoor sensor's is stored under the same name.
            {"label": "Temperature", "text": "18.4 °C", "difference": None},
            {"label": "Dew point", "text": "10.0 °C", "difference": None},
            {
                "label": "Absolute pressure",
                "text": f"{own - 1.25:.1f} hPa",
                "difference": "+1.2 hPa",
            },
            {"label": "Cloud cover", "text": "90%", "difference": None},
            {"label": "Precipitation, past 15 min", "text": "0.2 mm", "difference": None},
        ]
        assert "+1.2 hPa" in page

    async def test_a_model_named_by_hand_is_shown_by_its_name(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        locate(rig, "knmi_seamless")
        with_model(rig, {"weather_code": 99})

        page = rig.client.get("/").text

        assert "knmi_seamless, from Open-Meteo" in page
        assert "(knmi_seamless)" not in page
        assert "Thunderstorm with heavy hail" in page

    async def test_without_a_weather_code_there_is_no_sky(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        locate(rig)
        with_model(rig, {"temp_c": 18.4})

        items = rig.client.get("/api/readings").json()["stations"][0]["model"]["items"]

        assert [item["label"] for item in items] == ["Temperature"]

    async def test_no_model_no_box(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        locate(rig, "off")
        with_model(rig, {"temp_c": 18.4})

        assert "<h3>Weather model</h3>" not in rig.client.get("/").text
        assert rig.client.get("/api/readings").json()["stations"][0]["model"] is None

    def test_differences_are_signed_in_the_fields_unit(self) -> None:
        assert admin._difference("temp_c", -0.04) == "-0.0 °C"
        assert admin._difference("humidity_pct", 7.0) == "+7%"
        assert admin._difference("abs_inhg", 0.031) == "+0.03 inHg"
        assert admin._difference("uv_index", 1.25) == "+1.2"
        # A vane reading 10° against a model's 350° is 20° clockwise of it, not 340° anticlockwise.
        assert admin._difference("dir_deg", 10.0 - 350.0) == "+20°"
        assert admin._difference("dir_deg", 350.0 - 10.0) == "-20°"

    async def test_setup_offers_the_models_and_off(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)

        page = rig.client.get("/setup").text

        assert '<option value="best_match" selected>Best for this location</option>' in page
        assert '<option value="ecmwf_ifs" >ECMWF IFS' in page
        assert '<option value="off" >Off</option>' in page
        saved = load_document(rig.context.settings.config_file).stations[0]
        assert saved.weather_model == "best_match"

    async def test_setup_saves_the_choice_and_keeps_one_named_by_hand(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        locate(rig, "knmi_seamless")

        page = rig.client.get("/setup").text
        saved = load_document(rig.context.settings.config_file).stations[0]

        assert saved.weather_model == "knmi_seamless"
        assert '<option value="knmi_seamless" selected>knmi_seamless</option>' in page

    async def test_a_save_without_the_field_keeps_the_choice(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        locate(rig, "off")

        response = rig.post("/setup/station", {"original": "Home", "name": "Home"})

        assert response.status_code == 303
        assert load_document(rig.context.settings.config_file).stations[0].weather_model == "off"

    async def test_a_malformed_model_name_is_refused(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)

        response = rig.post(
            "/setup/station", {"original": "Home", "name": "Home", "weather_model": "Bad name!"}
        )

        assert response.status_code == 400
        saved = load_document(rig.context.settings.config_file).stations[0]
        assert saved.weather_model == "best_match"


class TestStatus:
    async def test_a_station_with_readings_and_warnings(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()

        page = rig.client.get("/").text
        readings = rig.client.get("/api/readings").json()["stations"][0]

        assert "<h2>Home</h2>" in page
        assert "Altitude not set" in page
        assert "Pressure: absolute 1009.0 hPa, relative 1009.0 hPa</p>" in page
        assert readings["name"] == "Home"
        assert [s["sensor"] for s in readings["sensors"]][:2] == ["indoor", "ch1"]
        assert readings["sensors"][0]["temp"] == {"value": 23.2222, "unit": "c"}
        assert readings["warnings"][0]["kind"] == "location"
        # Every value, not just the unit: field names share prefixes (`rel_error_hpa`,
        # `sea_temp_source`), and a prefix match once put "standard" where sea-level pressure goes.
        assert readings["pressure"] == {"abs": 1009.0084, "rel": 1009.0084, "unit": "hpa"}

    async def test_the_pressure_line_shows_every_value_in_the_operators_unit(
        self, rig: Rig
    ) -> None:
        from ecowitt.core.units import Units

        rig.store.replace(
            ConfigDocument(
                units=Units(pressure="inhg"),
                stations=[StationEntry(name="Home", passkey=FIXTURE_PASSKEY, altitude_m=180.0)],
            )
        )
        await rig.report()

        pressure = rig.client.get("/api/readings").json()["stations"][0]["pressure"]

        assert pressure["unit"] == "inhg"
        assert pressure["abs"] == 29.796 and pressure["rel"] == 29.796
        assert isinstance(pressure["sea"], float) and pressure["sea"] > 29.796
        assert isinstance(pressure["rel_error"], float) and pressure["rel_error"] < 0

    async def test_the_climate_table_shows_readings_and_health_not_airing_advice(
        self, rig: Rig
    ) -> None:
        """Whether to air a room is the dashboard's to say; this page shows what arrived."""
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

        assert sensors["ch1"]["temp"] == {"value": 25.0, "unit": "c"}
        assert "dewpoint" in sensors["ch1"] and "unchanged" in sensors["ch1"]
        assert not any("airing" in key for s in sensors.values() for key in s)
        assert "Airing" not in page and "drier outside" not in page
        # A sensor without temperature (the soil probe) is not a row in the climate table.
        assert "soil1" not in sensors

    async def test_a_report_without_pressure_shows_no_pressure_line(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        await rig.handler.handle(
            {"PASSKEY": "K", "dateutc": "now", "tempinf": "71.6", "humidityin": "62"}, "192.0.2.9"
        )

        assert rig.client.get("/api/readings").json()["stations"][0]["pressure"] == {}
        assert "Pressure:" not in rig.client.get("/").text

    @pytest.mark.parametrize("key", ["baromrelin", "baromabsin"])
    async def test_a_report_with_one_pressure_shows_that_one(self, rig: Rig, key: str) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
        await rig.handler.handle({"PASSKEY": "K", "dateutc": "now", key: "29.9"}, "192.0.2.9")

        page = rig.client.get("/")

        assert page.status_code == 200
        assert ("relative 1012" in page.text) is (key == "baromrelin")
        assert ("absolute 1012" in page.text) is (key == "baromabsin")

    def test_a_name_with_quotes_keeps_the_remove_confirmation(self, rig: Rig) -> None:
        """The name is JSON-encoded into the handler, so a quote neither breaks it nor runs."""
        rig.post("/setup/station", {"name": "Ann's x');alert(1);('", "passkey": "A"})

        page = rig.client.get("/setup").text
        (handler,) = re.findall(r"onclick='(return confirm\(.*?\))'", page)

        assert "'" not in handler
        assert handler.startswith('return confirm("Remove Ann\\u0027s x\\u0027);alert(1);(\\u0027?')

    async def test_a_non_numeric_correction_is_tolerated(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))

        assert (
            rig.post(
                "/dismiss", {"station": "Home", "kind": "location", "correction": "abc"}
            ).status_code
            == 303
        )
        assert rig.store.document.stations[0].dismissed == {"location": 0.0}

    async def ws69(self, rig: Rig, **units: str) -> dict[str, object]:
        """The recorded WS69 upload, processed and read back from the API."""
        from ecowitt.core.units import Units

        rig.store.replace(
            ConfigDocument(
                units=Units(**units), stations=[StationEntry(name="Home", passkey=FIXTURE_PASSKEY)]
            )
        )
        fields = dict(urllib.parse.parse_qsl(payload("hp2551_ws69"), keep_blank_values=True))
        await rig.handler.handle(fields | {"dateutc": "now"}, "192.0.2.9")
        return rig.client.get("/api/readings").json()["stations"][0]

    async def test_wind_rain_and_solar_are_shown_with_labels_and_units(self, rig: Rig) -> None:
        station = await self.ws69(rig)

        groups = {
            g["title"]: {i["label"]: i["text"] for i in g["items"]} for g in station["weather"]
        }
        assert groups["Wind"] == {
            "Speed": "8.6 km/h",
            "Gust": "20.2 km/h",
            "Strongest gust today": "27.7 km/h",
            "Direction": "125° SE",
            "Direction, 10-minute average": "137° SE",
        }
        # The running totals all follow from these two.
        assert groups["Rain"] == {"Rate": "0.0 mm/h", "Today": "0.8 mm"}
        assert groups["Solar"] == {"Radiation": "615 W/m²", "UV index": "5"}
        page = rig.client.get("/").text
        assert "Strongest gust today" in page and "125° SE" in page
        # Spaced from the climate table above it rather than butting against its last row.
        assert '<div class="row sections">' in page
        assert ".sections { margin-top:" in page

    async def test_the_weather_follows_the_operators_units(self, rig: Rig) -> None:
        station = await self.ws69(rig, wind="mph", rain="in")

        groups = {
            g["title"]: {i["label"]: i["text"] for i in g["items"]} for g in station["weather"]
        }
        assert groups["Wind"]["Speed"] == "5.4 mph"
        assert groups["Rain"]["Today"] == "0.03 in" and groups["Rain"]["Rate"] == "0.00 in/h"

    async def test_the_outdoor_arrays_battery_shows_on_the_outdoor_row(self, rig: Rig) -> None:
        station = await self.ws69(rig)

        outdoor = next(s for s in station["sensors"] if s["sensor"] == "outdoor")
        assert outdoor["battery_low"] is False
        assert station["batteries"] == []

    async def test_sensors_without_a_section_still_show(self, rig: Rig) -> None:
        """Soil, a piezo gauge, a lone rain gauge's battery: nothing reported is invisible."""
        rig.store.replace(
            ConfigDocument(
                stations=[StationEntry(name="Home", passkey="K", sensors={"soil1": "Herbs"})]
            )
        )
        await rig.handler.handle(
            {
                "PASSKEY": "K",
                "dateutc": "now",
                "tempinf": "70",
                "humidityin": "50",
                "soilmoisture1": "31",
                "soilad1": "212",
                "drain_piezo": "0.12",
                "srain_piezo": "1",
                "wh40batt": "1.38",
                "leakbatt1": "1",
                "pm25batt1": "4",
                "ws90cap_volt": "4.9",
                "batt3": "1",
                "newsensor_mode": "eco",
                "newsensor_level": "3",
            },
            "192.0.2.9",
        )

        station = rig.client.get("/api/readings").json()["stations"][0]
        others = {
            g["title"]: {i["label"]: i["text"] for i in g["items"]} for g in station["others"]
        }
        weather = {
            g["title"]: {i["label"]: i["text"] for i in g["items"]} for g in station["weather"]
        }
        batteries = {b["name"]: (b["state"], b["low"]) for b in station["batteries"]}

        assert others["Soil · Herbs"] == {"moisture": "31%", "moisture raw": "212"}
        # A key this server does not know is named in a notice of its own.
        assert "Unmapped" not in others
        assert station["unmapped"] == ["newsensor_level", "newsensor_mode_text"]
        assert weather["Rain (piezo)"] == {"Raining": "yes", "Today": "3.0 mm"}
        assert batteries == {
            "wh40": ("1.38 V", False),
            "leak1": ("1/5", True),
            "pm1": ("4/5", False),
            "ws90": ("4.90 V", False),
            "ch3": ("low", True),
        }
        page = rig.client.get("/").text
        assert "Soil · Herbs" in page
        assert '<span class="bad">low</span>' in page and '<span class="bad">1/5</span>' in page
        assert "2 unrecognised keys" in page and "newsensor_level, newsensor_mode_text" in page

    async def test_the_health_summary_covers_every_stage(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()
        state = rig.context.state
        state.record_accepted()
        state.record_write(True)
        state.heartbeat_configured = True
        state.record_heartbeat(False)
        state.record_settings(1)
        state.record_model(True)
        state.record_model(False)

        page = rig.client.get("/").text
        status = rig.client.get("/api/status").json()

        assert "<h2>Health</h2>" in page
        assert "1 accepted" in page and "the last 0 s ago" in page
        assert "Database</td>" in page and "not set up" in page
        assert "last accepted never, " in page and "1 failed" in page
        assert "last sent to the database 0 s ago" in page
        assert status["heartbeat"] == {
            "configured": True,
            "seconds_since_last_ok": None,
            "failures": 1,
        }
        assert status["settings"]["published"] == 1
        assert "Open-Meteo: last fetched 0 s ago" in page
        assert '<span class="bad">1 failed since</span>' in page
        assert status["model"] == {
            "seconds_since_last_ok": 0.0,
            "failures": 1,
        }

    async def test_a_quiet_heartbeat_and_settings_say_so(self, rig: Rig) -> None:
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))

        page = rig.client.get("/").text

        assert "not configured" in page and "not sent since this server started" in page
        assert "nothing fetched yet; stations with coordinates are" in page

    async def test_the_console_describes_itself(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()

        station = rig.client.get("/api/readings").json()["stations"][0]
        page = rig.client.get("/").text

        assert station["console"]["model"] == "HP2551AE_Pro_V2.1.4"
        # The recorded report's own clock is days behind the moment the test replays it.
        assert "HP2551AE_Pro_V2.1.4, EasyWeatherPro_V5.2.7; reports every 10 s; clock " in page
        assert re.search(r"clock \d+ days off; 868 MHz, for Europe and the UK\.", page)
        assert station["overdue"] is False

    async def test_every_stored_value_is_listed_under_the_summary(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()

        page = rig.client.get("/").text

        assert "Every value in the latest report, as stored" in page
        assert "interval_s=10.0" in page and "sensor=ch1" in page

    async def test_a_station_that_stopped_reporting_is_called_out(self, rig: Rig) -> None:
        await rig.report()
        adopt(rig)
        await rig.report()
        latest = rig.handler.latest["Home"]
        rig.handler.latest["Home"] = dataclasses.replace(
            latest, received_at=latest.received_at - timedelta(minutes=6)
        )

        page = rig.client.get("/").text

        assert "Home has not reported for 6 min." in page

    def test_a_backlog_and_dropped_reports_are_called_out(self, rig: Rig) -> None:
        class Spool:
            dropped = 2

            def stats(self) -> object:
                return type("Stats", (), {"files": 3, "bytes": 1, "oldest_seconds": 400.0})()

            def rejected_count(self) -> int:
                return 0

        rig.context.spool = Spool()  # type: ignore[assignment]
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))

        page = " ".join(rig.client.get("/").text.split())

        assert "3 reports are waiting for the database, the oldest for 7 min." in page
        assert "2 reports were dropped since this server started" in page
        assert '<span class="bad">3 waiting</span>' in page

    def test_a_short_backlog_is_not_alarming(self, rig: Rig) -> None:
        class Spool:
            dropped = 0

            def stats(self) -> object:
                return type("Stats", (), {"files": 1, "bytes": 1, "oldest_seconds": 30.0})()

            def rejected_count(self) -> int:
                return 0

        rig.context.spool = Spool()  # type: ignore[assignment]
        rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))

        page = rig.client.get("/").text

        assert "waiting for the database" not in page and "dropped" not in page.split("Health")[0]

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
    with TestClient(
        base_url="http://localhost", app=admin.build_app(context), follow_redirects=False
    ) as client:
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


class TestDatabase:
    def test_a_connection_is_saved_and_shown_without_its_token(self, rig: Rig) -> None:
        use_database(rig, "http://influx:8181")

        entry = rig.store.document.store
        page = rig.client.get("/setup").text
        assert entry is not None and entry.connection["token"] == "t0ken"
        assert "Writing to <strong>InfluxDB 3</strong>" in page and "http://influx:8181" in page
        assert "t0ken" not in page
        assert "set; leave empty to keep it" in page

    def test_an_empty_token_keeps_the_saved_one(self, rig: Rig) -> None:
        use_database(rig, "http://influx:8181")

        rig.post("/setup/database", db("influx3", url="http://other:8181", token=""))

        entry = rig.store.document.store
        assert entry is not None and entry.connection == {
            "url": "http://other:8181",
            "token": "t0ken",
        }

    def test_a_token_is_not_carried_over_to_another_kind(self, rig: Rig) -> None:
        use_database(rig)

        rig.post("/setup/database", db("influx2", url="http://x:8086", org="home"))

        entry = rig.store.document.store
        assert entry is not None and entry.kind == "influx2" and "token" not in entry.connection

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            (db("influx3"), "URL is required"),
            (db("influx3", url="influx:8181"), "must start with http://"),
            (db("influx2", url="http://x"), "Organisation is required"),
            (db("sqlite", url="http://x"), "Choose a kind of database"),
        ],
    )
    def test_an_unusable_connection_is_refused_with_the_reason(
        self, rig: Rig, fields: dict[str, str], message: str
    ) -> None:
        response = rig.post("/setup/database", fields)

        assert response.status_code == 400 and message in response.text
        assert rig.store.document.store is None

    def test_the_connection_can_be_removed(self, rig: Rig) -> None:
        use_database(rig)

        assert rig.post("/setup/database", {"action": "clear"}).status_code == 303
        assert rig.store.document.store is None

    def test_a_working_connection_tests_as_working_and_is_not_saved(self, rig: Rig) -> None:
        with json_server({}, status=400, body="incoming write was empty") as url:
            response = rig.post(
                "/setup/database", {**db("influx3", url=url, token="typed"), "action": "test"}
            )

        assert response.status_code == 200
        assert "would accept writes" in response.text
        assert rig.store.document.store is None

    def test_a_refused_connection_tests_as_refused_with_only_the_reason(self, rig: Rig) -> None:
        with json_server({}, status=401, body="internal detail") as url:
            response = rig.post(
                "/setup/database", {**db("influx3", url=url, token="typed"), "action": "test"}
            )

        assert response.status_code == 400
        assert "InfluxDB 3 refused: the token was not accepted" in response.text
        assert "internal detail" not in response.text


class TestDatabaseForm:
    def test_there_is_one_form_with_a_choice_of_type(self, rig: Rig) -> None:
        page = rig.client.get("/setup").text

        assert page.count('action="/setup/database"') == 1
        assert re.search(
            r'<select id="db-kind" name="kind">.*InfluxDB 3.*InfluxDB 2\.x', page, re.S
        )
        # Each type's fields carry its prefix, so the hidden type's fields cannot interfere.
        assert 'name="influx3.url"' in page and 'name="influx2.org"' in page
        assert "Token (if the database needs one)" in page

    def test_the_saved_type_is_the_one_selected(self, rig: Rig) -> None:
        rig.post("/setup/database", db("influx2", url="http://x:8086", org="home"))

        page = rig.client.get("/setup").text

        assert re.search(r'<option value="influx2"\s+selected>', page)
        assert 'value="home"' in page

    def test_a_test_keeps_everything_that_was_typed(self, rig: Rig) -> None:
        """Re-entering the connection after a successful test would be pointless toil."""
        with json_server({}, status=400, body="incoming write was empty") as url:
            response = rig.post(
                "/setup/database",
                {**db("influx3", url=url, database="wx", token="typed-token"), "action": "test"},
            )

        assert 'value="' + url + '"' in response.text
        assert 'value="wx"' in response.text
        assert 'value="typed-token"' in response.text

    def test_a_refused_form_keeps_what_was_typed(self, rig: Rig) -> None:
        response = rig.post("/setup/database", db("influx2", url="http://x:8086", token="tk"))

        assert response.status_code == 400 and "Organisation is required" in response.text
        assert re.search(r'<option value="influx2"\s+selected>', response.text)
        assert 'value="http://x:8086"' in response.text and 'value="tk"' in response.text

    def test_a_saved_token_is_never_put_back_into_the_page(self, rig: Rig) -> None:
        use_database(rig)

        assert "t0ken" not in rig.client.get("/setup").text


class TestLoginForm:
    def test_the_switch_is_off_with_no_login_and_on_with_one(self, rig: Rig) -> None:
        assert not re.search(r'id="a-enabled"[^>]*checked', rig.client.get("/setup").text)

        rig.post(
            "/setup/admin",
            {
                "enabled": "on",
                "username": "a",
                "password": "longenough",
                "password_again": "longenough",
            },
        )

        page = rig.client.get("/setup", auth=("a", "longenough")).text
        assert re.search(r'id="a-enabled"[^>]*checked', page)

    def test_saving_with_the_switch_off_and_no_login_changes_nothing(self, rig: Rig) -> None:
        response = rig.post("/setup/admin", {})

        assert response.status_code == 303 and rig.store.document.admin is None

    def test_an_empty_password_keeps_the_saved_one_and_renames(self, rig: Rig) -> None:
        rig.post(
            "/setup/admin",
            {
                "enabled": "on",
                "username": "a",
                "password": "longenough",
                "password_again": "longenough",
            },
        )
        before = rig.store.document.admin

        rig.post("/setup/admin", {"enabled": "on", "username": "b"}, auth=("a", "longenough"))

        after = rig.store.document.admin
        assert before is not None and after is not None
        assert after.username == "b" and after.password_hash == before.password_hash


@pytest.mark.parametrize(
    ("seconds", "words"),
    [
        (None, "never"),
        (-3, "0 s"),
        (42.4, "42 s"),
        (95, "2 min"),
        (89 * 60, "89 min"),
        (90 * 60, "1 h 30 min"),
        (3 * 3600, "3 h"),
        (49 * 3600, "2 days"),
    ],
)
def test_durations_read_as_words(seconds: float | None, words: str) -> None:
    assert admin.duration(seconds) == words
    assert admin.ago(seconds) == ("never" if seconds is None else f"{words} ago")


def test_a_text_value_is_shown_as_it_is() -> None:
    assert admin._item("mode_text", "eco") == {"field": "mode_text", "text": "eco"}


@pytest.mark.parametrize(
    ("freq", "words"),
    [
        ("868M", "868 MHz, for Europe and the UK"),
        ("915M", "915 MHz, for North America"),
        ("433M", "433 MHz, for Australia, New Zealand and most other regions"),
        ("920 MHz", "920 MHz, where local rules call for it"),
        ("2400M", "2400 MHz"),
        ("unknown", "unknown"),
    ],
)
def test_the_radio_band_is_named_with_its_region(freq: str, words: str) -> None:
    assert admin.band(freq) == words


def test_the_pages_have_an_icon(rig: Rig) -> None:
    rig.store.replace(ConfigDocument(stations=[StationEntry(name="Home", passkey="K")]))
    assert '<link rel="icon" href="/static/favicon.svg"' in rig.client.get("/").text
    icon = rig.client.get("/static/favicon.svg")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg+xml")

"""Recording the notifications Grafana sends, and the page that lists them."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ecowitt.collector.admin import auth, notifications
from ecowitt.collector.admin.stationconfig import (
    AdminLogin,
    ConfigDocument,
    NotificationsEntry,
    StationEntry,
)
from ecowitt.core.store.base import Row
from ecowitt.core.store.query import Point, ReadError

from .conftest import Rig

TOKEN = "t0ken-for-grafana"
DAMP = {
    "receiver": "House",
    "status": "firing",
    "title": "Damp room",
    "message": "These rooms are damp.\n\n- Bathroom (lowest 72%)\n- Attic (lowest 70%)\n",
    "groupLabels": {"alertname": "Damp room"},
    "commonLabels": {"alertname": "Damp room", "station": "Home", "app": "ecowitt"},
    "alerts": [
        {"status": "firing", "labels": {"room": "Bathroom", "station": "Home"}},
        {"status": "firing", "labels": {"room": "Attic", "station": "Home"}},
        {"status": "firing", "labels": {"room": "Attic", "station": "Home"}},
    ],
}


class TestRow:
    def test_a_notification_is_one_row_tagged_with_where_it_went(self) -> None:
        found = notifications.row(DAMP, 1000)

        assert found == Row(
            "notification",
            (
                ("receiver", "House"),
                ("rule", "Damp room"),
                ("station", "Home"),
                ("status", "firing"),
            ),
            1000,
            {
                "alerts": 3.0,
                "title": "Damp room",
                "message": "These rooms are damp. / - Bathroom (lowest 72%) / - Attic (lowest 70%)",
                "rooms": "Attic, Bathroom",
            },
        )

    def test_a_system_notification_has_no_station_and_no_rooms(self) -> None:
        """A failing query names no station; a group without its rule takes the common one."""
        payload = {
            "receiver": "System",
            "status": "resolved",
            "commonLabels": {"alertname": "DatasourceError"},
            "alerts": [{"labels": {}}, "not an alert"],
        }

        found = notifications.row(payload, 5)

        assert dict(found.tags) == {
            "receiver": "System",
            "rule": "DatasourceError",
            "status": "resolved",
        }
        assert found.fields == {"alerts": 1.0, "title": "", "message": ""}

    def test_values_that_are_not_text_are_left_out(self) -> None:
        payload = {"receiver": 3, "status": None, "groupLabels": {"alertname": 7}, "alerts": []}

        assert notifications.row(payload, 0).tags == ()

    @pytest.mark.parametrize("payload", [[], "text", {"alerts": "x"}, {"status": "firing"}])
    def test_a_body_that_is_not_a_notification_is_refused(self, payload: object) -> None:
        with pytest.raises(ValueError, match="no list of alerts"):
            notifications.row(payload, 0)


class TestToken:
    def test_only_the_hash_is_kept_and_it_checks_the_token(self) -> None:
        token = notifications.new_token()
        stored = notifications.token_hash(token)

        assert token not in stored and len(stored) == 64
        assert notifications.new_token() != token
        assert notifications.authorised(f"Bearer {token}", stored)
        assert notifications.authorised(f"bearer  {token} ", stored)

    @pytest.mark.parametrize(
        "header",
        [None, "", "Bearer", "Bearer ", "Basic dXNlcjpwYXNz", f"Token {TOKEN}", "Bearer wrong"],
    )
    def test_anything_else_is_refused(self, header: str | None) -> None:
        assert not notifications.authorised(header, notifications.token_hash(TOKEN))

    def test_nothing_is_accepted_before_a_token_is_made(self) -> None:
        assert not notifications.authorised(f"Bearer {TOKEN}", None)


class MemorySink:
    def __init__(self) -> None:
        self.rows: list[Row] = []

    async def submit(self, rows: list[Row]) -> None:
        self.rows += rows


def recording(rig: Rig, **document: object) -> MemorySink:
    """Record with TOKEN, into a sink the test can read."""
    entry = NotificationsEntry(token_hash=notifications.token_hash(TOKEN))
    rig.store.replace(ConfigDocument(notifications=entry, **document))  # type: ignore[arg-type]
    sink = MemorySink()
    rig.context.sink = sink
    return sink


def post(rig: Rig, body: object, token: str | None = TOKEN, **headers: str):
    """Post a notification as Grafana's webhook does."""
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return rig.client.post(notifications.PATH, content=content, headers=headers)


class TestRoute:
    def test_a_notification_with_the_token_is_recorded(self, rig: Rig) -> None:
        sink = recording(rig)

        response = post(rig, DAMP)

        assert response.status_code == 200
        assert [r.table for r in sink.rows] == ["notification"]
        assert sink.rows[0].fields["rooms"] == "Attic, Bathroom"

    @pytest.mark.parametrize("token", [None, "wrong"])
    def test_without_the_token_nothing_is_recorded(self, rig: Rig, token: str | None) -> None:
        sink = recording(rig)

        assert post(rig, DAMP, token=token).status_code == 401
        assert sink.rows == []

    def test_before_recording_starts_every_token_is_refused(self, rig: Rig) -> None:
        rig.context.sink = sink = MemorySink()

        assert post(rig, DAMP).status_code == 401
        assert sink.rows == []

    def test_guessing_the_token_is_slowed(self, rig: Rig) -> None:
        recording(rig)

        codes = [post(rig, DAMP, token="guess").status_code for _ in range(12)]

        assert codes[:10] == [401] * 10
        assert codes[-1] == 429

    def test_the_token_is_the_whole_gate(self, rig: Rig) -> None:
        """Grafana posts from another container, under its own host name and without the
        admin login, which still guards every other route."""
        login = AdminLogin(username="admin", password_hash=auth.hash_password("pw"))
        sink = recording(rig, admin=login)

        response = post(rig, DAMP, Host="ecowitt:2552")

        assert response.status_code == 200
        assert len(sink.rows) == 1
        assert rig.client.get("/notifications").status_code == 401

    def test_a_body_too_large_is_refused_unread(self, rig: Rig) -> None:
        sink = recording(rig)
        big = b"x" * (notifications.MAX_BYTES + 1)

        assert post(rig, big).status_code == 413
        assert sink.rows == []

    @pytest.mark.parametrize("body", [b"not json", b'{"status": "firing"}'])
    def test_a_body_that_is_not_a_notification_is_refused(self, rig: Rig, body: bytes) -> None:
        sink = recording(rig)

        response = post(rig, body)

        assert response.status_code == 400
        assert sink.rows == []

    def test_a_process_that_cannot_write_says_so(self, rig: Rig) -> None:
        recording(rig)
        rig.context.sink = None

        assert post(rig, DAMP).status_code == 503


TOKEN_SHOWN = 'id="notifications-token">'


class TestGrafanaPage:
    def test_starting_shows_the_token_once_and_keeps_only_its_hash(self, rig: Rig) -> None:
        assert "Start recording" in rig.client.get("/grafana").text

        page = rig.post("/grafana/notifications", {"action": "token"}).text

        token = page.split(TOKEN_SHOWN)[1].split("<")[0]
        entry = rig.store.document.notifications
        assert entry is not None and entry.token_hash == notifications.token_hash(token)
        assert token not in rig.store.path.read_text()
        again = rig.client.get("/grafana").text
        assert TOKEN_SHOWN not in again and "Stop recording" in again
        assert f"http://ecowitt:2552{notifications.PATH}" in again

    def test_a_new_token_replaces_the_old_one(self, rig: Rig) -> None:
        first = rig.post("/grafana/notifications", {"action": "token"}).text
        second = rig.post("/grafana/notifications", {"action": "token"}).text

        old, new = (p.split(TOKEN_SHOWN)[1].split("<")[0] for p in (first, second))
        stored = rig.store.document.notifications
        assert old != new
        assert stored is not None and stored.token_hash == notifications.token_hash(new)

    def test_stopping_forgets_the_token(self, rig: Rig) -> None:
        recording(rig)

        response = rig.post("/grafana/notifications", {"action": "stop"})

        assert response.status_code == 303
        assert rig.store.document.notifications is None
        assert post(rig, DAMP).status_code == 401

    def test_a_process_without_a_configuration_file_cannot_start(self, rig: Rig) -> None:
        rig.context.store = None

        page = rig.post("/grafana/notifications", {"action": "token"}).text

        assert "no configuration file" in page
        assert TOKEN_SHOWN not in page

    def test_a_token_that_cannot_be_saved_is_not_shown(self, rig: Rig) -> None:
        rig.store.path.parent.chmod(0o500)
        try:
            page = rig.post("/grafana/notifications", {"action": "token"}).text
        finally:
            rig.store.path.parent.chmod(0o700)

        assert "Could not save the configuration" in page
        assert TOKEN_SHOWN not in page


NOW = datetime.now(UTC).replace(microsecond=0)


def sent(minutes_ago: int, rule: str, status: str = "firing", **tags: str) -> Point:
    """A recorded notification, as the reader gives it back."""
    return Point(
        NOW - timedelta(minutes=minutes_ago),
        {"rule": rule, "status": status, "receiver": "House", **tags},
        {"title": rule, "message": f"{rule} / second line", "alerts": 1.0},
    )


class StandInReader:
    def __init__(self, points: list[Point] | None = None, error: str | None = None) -> None:
        self.found = points or []
        self.error = error
        self.asked: list[tuple[str | None, str, timedelta]] = []
        self.closed = False

    async def points(self, station, table, fields, *, start, end):  # noqa: ANN001, ANN201
        self.asked.append((station, table, end - start))
        if self.error:
            raise ReadError(self.error)
        return sorted((p for p in self.found if start <= p.time <= end), key=lambda p: p.time)

    async def aclose(self) -> None:
        self.closed = True


def reading(rig: Rig, reader: StandInReader) -> None:
    rig.context.make_reader = lambda: reader


class TestNotificationsPage:
    def test_newest_first_in_the_stations_time_with_every_line(self, rig: Rig) -> None:
        recording(rig, stations=[StationEntry(name="Home", passkey="K", timezone="Europe/Lisbon")])
        reader = StandInReader(
            [sent(90, "Damp room", station="Home", rooms="Bathroom"), sent(30, "DatasourceError")]
        )
        reading(rig, reader)

        page = rig.client.get("/notifications").text

        listed = page.split('<ul class="sent">')[1]
        assert listed.index("DatasourceError") < listed.index("Damp room")
        lisbon = (NOW - timedelta(minutes=90)).astimezone(ZoneInfo("Europe/Lisbon"))
        assert f"{lisbon:%-d %b %Y %H:%M}" in page and "(Europe/Lisbon)" in page
        assert "(UTC)" in page
        assert "<p>second line</p>" in page
        assert reader.asked == [(None, "notification", timedelta(days=7))] and reader.closed

    def test_a_station_located_but_with_no_zone_set_takes_its_coordinates_zone(
        self, rig: Rig
    ) -> None:
        recording(
            rig, stations=[StationEntry(name="Home", passkey="K", latitude=38.8, longitude=-9.4)]
        )
        reading(rig, StandInReader([sent(10, "Damp room", station="Home")]))

        assert "(Europe/Lisbon)" in rig.client.get("/notifications").text

    def test_the_rule_kind_and_span_filter_it(self, rig: Rig) -> None:
        recording(rig)
        found = [sent(10, "Damp room"), sent(20, "Damp room", "resolved"), sent(30, "Heavy rain")]
        reader = StandInReader(found)
        reading(rig, reader)

        page = rig.client.get("/notifications?rule=Damp+room&status=resolved&days=30").text

        assert page.count('<li class="resolved">') == 1
        assert '<li class="firing">' not in page
        assert '<option value="Heavy rain" >' in page.replace("selected", "")
        assert reader.asked[-1][2] == timedelta(days=30)

    @pytest.mark.parametrize("days", ["2", "x", "-1"])
    def test_a_span_not_offered_is_the_default(self, rig: Rig, days: str) -> None:
        reader = StandInReader()
        reading(rig, reader)

        page = rig.client.get(f"/notifications?days={days}").text

        assert reader.asked[-1][2] == timedelta(days=7)
        assert "No notifications in the last 7 days." in page

    def test_only_the_newest_are_listed(self, rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ecowitt.collector.admin.app.NOTIFICATION_LIMIT", 2)
        reading(rig, StandInReader([sent(m, f"Rule {m}") for m in (1, 2, 3)]))

        page = rig.client.get("/notifications").text

        assert "Rule 1" in page.split('<ul class="sent">')[1].split("</ul>")[0]
        assert page.count("<li class=") == 2
        assert "Only the newest 2 are listed" in page

    def test_it_says_how_to_start_recording(self, rig: Rig) -> None:
        reading(rig, StandInReader())

        assert "start\n      recording on the" in rig.client.get("/notifications").text

    def test_a_database_that_cannot_be_read_says_so(self, rig: Rig) -> None:
        assert "cannot be read back" in rig.client.get("/notifications").text
        rig.context.make_reader = lambda: None
        assert "cannot be read back" in rig.client.get("/notifications").text

    def test_a_failed_read_says_why(self, rig: Rig) -> None:
        reader = StandInReader(error="connection refused")
        reading(rig, reader)

        page = rig.client.get("/notifications").text

        assert "Could not read the notifications: connection refused" in page
        assert reader.closed

"""The admin listener: status and setup pages, the read API, and health.

Reached through a reverse proxy or from the host, never from the open internet -- the
host-side publish binds it to loopback. Its routes are mounted only here, so the public
listener does not serve them under any configuration.

Every form is protected against cross-site submission (see `auth`), and the whole interface
except `/healthz` is behind the optional login once one is set.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx2
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from . import auth, lookups
from .calibration import CalibrationMonitor
from .config import Settings
from .configstore import ConfigStore
from .handler import StationHandler
from .http import BodyTooLarge, read_capped_body
from .pending import PendingStations
from .ratelimit import RateLimiter
from .spool import Spool
from .state import State
from .stationconfig import AdminLogin, ConfigDocument, StationEntry
from .units import Units

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
#: Largest form this listener will read.
MAX_FORM_BYTES = 64 * 1024
#: Shortest admin password accepted from the setup page.
MIN_PASSWORD_LENGTH = 8
#: Sensor identifiers as the field table produces them: `indoor`, `ch3`, `soil12`, `pm2`.
SENSOR_ID = re.compile(r"[a-z][a-z0-9_]{0,31}")
#: Fields whose rows are worth showing on the status page, in display order.
SUMMARY_TABLES = ("indoor", "outdoor", "channel", "air", "probe")


@dataclass
class AdminContext:
    """Everything the admin pages read or change."""

    settings: Settings
    state: State
    secret: bytes = b""
    store: ConfigStore | None = None
    handler: StationHandler | None = None
    pending: PendingStations = field(default_factory=PendingStations)
    calibration: CalibrationMonitor = field(default_factory=CalibrationMonitor)
    spool: Spool | None = None
    http: httpx2.AsyncClient | None = None
    #: Station names to report when there is no store, for processes run without one.
    stations: list[str] = field(default_factory=list)

    @property
    def document(self) -> ConfigDocument:
        """The configuration being edited, or an empty one when there is no store."""
        return self.store.document if self.store else ConfigDocument()

    @property
    def station_names(self) -> list[str]:
        return [s.name for s in self.document.stations] if self.store else list(self.stations)


def build_app(context: AdminContext) -> FastAPI:
    """Build the admin application."""
    app = FastAPI(
        title="Ecowitt Server",
        description="Status and configuration for Ecowitt Server.",
    )
    failed_logins = RateLimiter(rate=0.2, burst=10)

    @app.middleware("http")
    async def require_login(request: Request, call_next: Any) -> Response:
        """Ask for the admin login on everything but `/healthz`, once a login is set.

        Failed attempts spend from a small per-address budget, so the password cannot be
        guessed at speed even by someone who can reach the listener.
        """
        login = context.document.admin
        if login is None or request.url.path == "/healthz":
            return await call_next(request)
        if auth.check_basic(
            request.headers.get("authorization"), login.username, login.password_hash
        ):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        if not failed_logins.allow(client):
            return PlainTextResponse("Too many failed logins; wait a minute.", status_code=429)
        return PlainTextResponse(
            "Login required.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Ecowitt Server", charset="UTF-8"'},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        """Report whether this process is serving.

        Both listeners are checked: one of the two failing to bind while the other serves
        would otherwise look healthy from here, with the station's reports going nowhere.
        """
        state = context.state
        serving = state.ingest_serving and state.admin_serving
        return {
            "status": "ok" if serving else "starting",
            "ingest_serving": state.ingest_serving,
            "admin_serving": state.admin_serving,
        }

    @app.get("/api/status")
    async def status() -> dict[str, object]:
        """What this process has received since it started.

        The shape of this response is the contract a separate frontend reads, so fields are
        added to it rather than renamed.
        """
        return _status(context)

    @app.get("/api/readings")
    async def readings() -> dict[str, object]:
        """Each station's latest report, as rows in the operator's units, with its warnings."""
        return {"stations": [_station_view(context, name) for name in context.station_names]}

    @app.get("/")
    async def status_page(request: Request) -> Response:
        return _render(
            request,
            context,
            "status.html",
            {
                "stations": [_station_view(context, name) for name in context.station_names],
                "status": _status(context),
            },
        )

    @app.get("/setup")
    async def setup_page(request: Request) -> Response:
        return _render(request, context, "setup.html", _setup_view(context))

    @app.post("/setup/units")
    async def save_units(request: Request) -> Response:
        form = await _form(request, context)
        if isinstance(form, Response):
            return form
        try:
            units = Units(
                **{
                    k: form.get(k, "")
                    for k in ("temperature", "pressure", "rain", "wind", "distance")
                }
            )
        except (ValueError, TypeError) as exc:
            return _setup_error(request, context, str(exc))
        return _save(
            request, context, context.document.model_copy(update={"units": units}), "Units saved."
        )

    @app.post("/setup/station")
    async def save_station(request: Request) -> Response:
        form = await _form(request, context)
        if isinstance(form, Response):
            return form
        return await _station_action(request, context, form)

    @app.post("/setup/admin")
    async def save_admin(request: Request) -> Response:
        form = await _form(request, context)
        if isinstance(form, Response):
            return form
        if form.get("action") == "clear":
            return _save(
                request,
                context,
                context.document.model_copy(update={"admin": None}),
                "Login removed.",
            )
        username = form.get("username", "").strip()
        password = form.get("password", "")
        if not username:
            return _setup_error(request, context, "A login needs a username.")
        if len(password) < MIN_PASSWORD_LENGTH:
            return _setup_error(
                request, context, f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."
            )
        if password != form.get("password_again", ""):
            return _setup_error(request, context, "The two passwords differ.")
        login = AdminLogin(username=username, password_hash=auth.hash_password(password))
        # Saved last, so the response to this request is the last one served without the login.
        return _save(
            request, context, context.document.model_copy(update={"admin": login}), "Login set."
        )

    @app.post("/dismiss")
    async def dismiss(request: Request) -> Response:
        form = await _form(request, context)
        if isinstance(form, Response):
            return form
        entry = context.document.station(form.get("station", ""))
        if entry is None:
            return _setup_error(request, context, "No such station.")
        kind = form.get("kind", "")
        try:
            value = float(form.get("correction") or 0)
        except ValueError:
            value = 0.0
        updated = entry.model_copy(update={"dismissed": {**entry.dismissed, kind: value}})
        return _save(
            request,
            context,
            _with_station(context.document, entry.name, updated),
            "Warning dismissed.",
            page="/",
        )

    return app


def _status(context: AdminContext) -> dict[str, object]:
    """The `/api/status` document."""
    state, settings = context.state, context.settings
    return {
        "uptime_seconds": round(state.uptime_seconds, 1),
        "reports_accepted": state.reports_accepted,
        "reports_rejected": state.reports_rejected,
        "reports_rate_limited": state.reports_rate_limited,
        "seconds_since_last_report": _rounded(state.seconds_since_last_report),
        "ingest_path": settings.ingest_path,
        # Names only: a PASSKEY is a credential and the status API never returns one.
        "stations": context.station_names,
        "pending_stations": len(context.pending.list()),
        "writes": {
            "succeeded": state.writes_succeeded,
            "failed": state.writes_failed,
            "rejected": state.writes_rejected,
            "seconds_since_last_success": _rounded(state.seconds_since_last_write),
        },
        "spool": _spool_status(state, context.spool),
        "influx": {
            "url": settings.influx_url,
            "database": settings.influx_database,
            "api": settings.influx_api,
            # Whether a token is present, never the token itself.
            "token_configured": bool(settings.influx_token),
        },
    }


def _spool_status(state: State, spool: Spool | None) -> dict[str, object] | None:
    """What is waiting for InfluxDB, or None when this process keeps no spool."""
    if spool is None:
        return None
    stats = spool.stats()
    return {
        "waiting": stats.files,
        "bytes": stats.bytes,
        "oldest_seconds": _rounded(stats.oldest_seconds),
        "spooled_total": state.reports_spooled,
        "dropped": spool.dropped,
        "rejected_kept": spool.rejected_count(),
    }


def _station_view(context: AdminContext, name: str) -> dict[str, object]:
    """One station's latest readings, summarised per sensor, with its calibration warnings."""
    latest = context.handler.latest.get(name) if context.handler else None
    station = context.store.stations.get(name) if context.store else None
    warnings = context.calibration.warnings(station, int(time.time())) if station else []
    view: dict[str, object] = {
        "name": name,
        "timestamp": latest.timestamp if latest else None,
        "age_seconds": round((datetime.now(UTC) - latest.received_at).total_seconds(), 1)
        if latest
        else None,
        "sensors": _summarise(latest.points) if latest else [],
        "pressure": _pressure(latest.points) if latest else {},
        "warnings": [w.__dict__ for w in warnings],
        "rows": [
            {"table": p.table, "tags": dict(p.tags), "fields": p.fields} for p in latest.points
        ]
        if latest
        else [],
    }
    return view


def _summarise(points: list[Any]) -> list[dict[str, object]]:
    """Per-sensor climate and airing summary, in the order a person reads a house."""
    sensors: dict[str, dict[str, object]] = {}
    for point in points:
        tags = dict(point.tags)
        sensor = tags.get("sensor")
        if sensor is None:
            continue
        entry = sensors.setdefault(sensor, {"sensor": sensor, "name": tags.get("name", sensor)})
        if point.table in SUMMARY_TABLES:
            entry["temp"] = _field(point.fields, "temp_")
            entry["humidity"] = _field(point.fields, "humidity_")
            entry["table"] = point.table
        elif point.table == "derived":
            entry["dewpoint"] = _field(point.fields, "dewpoint_")
            entry["unchanged"] = point.fields.get("unchanged_s")
        elif point.table == "ventilation":
            entry["airing_delta"] = _field(point.fields, "dewpoint_delta_")
            entry["airing_humidity"] = point.fields.get("predicted_humidity_pct")
        elif point.table == "battery":
            entry["battery_low"] = point.fields.get("low")
    shown = [s for s in sensors.values() if "temp" in s]
    order = {table: i for i, table in enumerate(SUMMARY_TABLES)}
    return sorted(
        shown, key=lambda s: (order.get(str(s.get("table")), 99), _natural(str(s["sensor"])))
    )


#: The pressure fields the status page shows, matched whole: `rel_error_hpa` must not be read as
#: `rel`, nor `sea_temp_source` as `sea`.
PRESSURE_FIELD = re.compile(r"(abs|rel|sea|rel_error)_(hpa|inhg|mmhg)")


def _pressure(points: list[Any]) -> dict[str, object]:
    """The pressure row's values, keyed without their unit suffix, with the unit alongside."""
    for point in points:
        if point.table != "pressure":
            continue
        out: dict[str, object] = {}
        for key, value in point.fields.items():
            matched = PRESSURE_FIELD.fullmatch(key)
            if matched:
                out[matched.group(1)] = value
                out["unit"] = matched.group(2)
        return out
    return {}


def _field(fields: dict[str, Any], prefix: str) -> dict[str, object] | None:
    """The value and unit of the first field starting with `prefix` -- `temp_` finds `temp_c`."""
    for key, value in fields.items():
        if key.startswith(prefix):
            return {"value": value, "unit": key[len(prefix) :]}
    return None


def _natural(sensor: str) -> tuple[object, ...]:
    """Sort key putting `ch2` before `ch10`."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", sensor))


def _setup_view(
    context: AdminContext,
    *,
    error: str | None = None,
    message: str | None = None,
    draft: dict[str, object] | None = None,
) -> dict[str, object]:
    """Everything the setup page shows."""
    document = context.document
    stations = []
    for entry in document.stations:
        latest = context.handler.latest.get(entry.name) if context.handler else None
        seen = [str(s["sensor"]) for s in _summarise(latest.points)] if latest else []
        sensor_ids = sorted(set(seen) | set(entry.sensors), key=_natural)
        stations.append({"entry": entry, "sensor_ids": sensor_ids})
    return {
        "document": document,
        "stations": stations,
        "pending": context.pending.list(),
        "editable": context.store is not None,
        "error": error,
        "message": message,
        "draft": draft,
        "units": Units(),
    }


async def _station_action(
    request: Request, context: AdminContext, form: dict[str, str]
) -> Response:
    """Save, look up the elevation for, or delete one station."""
    document = context.document
    original = form.get("original", "")
    existing = document.station(original) if original else None
    action = form.get("action", "save")

    if action == "delete":
        if existing is None:
            return _setup_error(request, context, "No such station.")
        remaining = [s for s in document.stations if s.name != original]
        return _save(
            request,
            context,
            document.model_copy(update={"stations": remaining}),
            f"Removed {original}.",
        )

    passkey = existing.passkey if existing else form.get("passkey", "").strip()
    # Looked up, not removed: it leaves the list only once the station has been saved, so a
    # refused form or a lookup leaves it there to adopt again.
    adopted = context.pending.get(form["adopt"]) if not existing and form.get("adopt") else None
    if not existing and form.get("adopt"):
        if adopted is None:
            return _setup_error(request, context, "That station has not reported in the last hour.")
        passkey = adopted.passkey

    try:
        latitude = _optional_float(form.get("latitude"))
        longitude = _optional_float(form.get("longitude"))
        altitude = _optional_float(form.get("altitude_m"))
    except ValueError:
        return _setup_error(request, context, "Coordinates and altitude must be numbers.")

    if action == "lookup":
        draft = dict(form)
        if latitude is None or longitude is None:
            return _setup_error(
                request, context, "Enter both coordinates to look up the altitude.", draft=draft
            )
        found = await _elevation(context, latitude, longitude)
        if found is None:
            return _setup_error(
                request,
                context,
                "The elevation services did not answer; enter the altitude by hand.",
                draft=draft,
            )
        draft["altitude_m"] = f"{found.metres:.0f}"
        return _render(
            request,
            context,
            "setup.html",
            _setup_view(
                context,
                message=f"{found.source} gives {found.metres:.0f} m for that point. Check it, "
                "add the height of the floor the console is on, and save.",
                draft=draft,
            ),
        )

    sensors: dict[str, str] = {}
    for key, value in form.items():
        if key.startswith("sensor_") and value.strip():
            sensors[key[len("sensor_") :]] = value.strip()
    new_id, new_name = (
        form.get("new_sensor_id", "").strip(),
        form.get("new_sensor_name", "").strip(),
    )
    if new_id or new_name:
        if not SENSOR_ID.fullmatch(new_id) or not new_name:
            return _setup_error(
                request, context, "A sensor needs an identifier like ch3 or indoor, and a name."
            )
        sensors[new_id] = new_name
    if any(not SENSOR_ID.fullmatch(k) for k in sensors):
        return _setup_error(request, context, "Sensor identifiers look like ch3 or indoor.")

    try:
        entry = StationEntry(
            name=form.get("name", "").strip(),
            passkey=passkey,
            altitude_m=altitude,
            latitude=latitude,
            longitude=longitude,
            sensors=sensors,
            dismissed=existing.dismissed if existing else {},
        )
    except ValidationError as exc:
        return _setup_error(request, context, _validation_message(exc))

    if existing:
        updated = _with_station(document, original, entry)
    else:
        updated = document.model_copy(update={"stations": [*document.stations, entry]})
    response = _save(request, context, updated, f"Saved {entry.name}.")
    if adopted is not None and response.status_code == 303:
        context.pending.discard(adopted.passkey)
    return response


async def _elevation(
    context: AdminContext, latitude: float, longitude: float
) -> lookups.Elevation | None:
    """Look up an elevation with the shared client, or a short-lived one when there is none."""
    urls = {
        "opentopodata_url": context.settings.opentopodata_url,
        "open_elevation_url": context.settings.open_elevation_url,
    }
    if context.http is not None:
        return await lookups.elevation(context.http, latitude, longitude, **urls)
    async with httpx2.AsyncClient() as client:
        return await lookups.elevation(client, latitude, longitude, **urls)


def _with_station(document: ConfigDocument, name: str, entry: StationEntry) -> ConfigDocument:
    """The document with one station replaced."""
    return document.model_copy(
        update={"stations": [entry if s.name == name else s for s in document.stations]}
    )


def _save(
    request: Request,
    context: AdminContext,
    document: ConfigDocument,
    message: str,
    *,
    page: str = "/setup",
) -> Response:
    """Save a changed document and redirect, or show why it could not be saved."""
    if context.store is None:
        return _setup_error(request, context, "This process has no configuration file to change.")
    try:
        context.store.replace(document)
    except (ValidationError, ValueError) as exc:
        message_text = _validation_message(exc) if isinstance(exc, ValidationError) else str(exc)
        return _setup_error(request, context, message_text)
    except OSError as exc:
        logger.exception("could not save the configuration")
        return _setup_error(request, context, f"Could not save the configuration: {exc.strerror}")
    logger.info("configuration changed: %s", message)
    return RedirectResponse(f"{page}?{urlencode({'message': message})}", status_code=303)


def _setup_error(
    request: Request, context: AdminContext, error: str, *, draft: dict[str, object] | None = None
) -> Response:
    return _render(
        request,
        context,
        "setup.html",
        _setup_view(context, error=error, draft=draft),
        status_code=400,
    )


async def _form(request: Request, context: AdminContext) -> dict[str, str] | Response:
    """A submitted form's fields, or a refusal if it is too large or not from this server."""
    try:
        body = await read_capped_body(request, MAX_FORM_BYTES)
    except BodyTooLarge:
        return PlainTextResponse("Form too large.", status_code=413)
    form = dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))
    allowed = auth.form_allowed(
        form.get("csrf", ""),
        context.secret,
        request.headers.get("origin"),
        request.headers.get("referer"),
        request.headers.get("host", ""),
    )
    if not allowed:
        return PlainTextResponse(
            "This form did not come from this server's own page.", status_code=403
        )
    return form


def _render(
    request: Request,
    context: AdminContext,
    template: str,
    values: dict[str, object],
    status_code: int = 200,
) -> Response:
    """Render a page with what every page needs."""
    values = {
        **values,
        "csrf": auth.csrf_token(context.secret),
        "message": values.get("message") or request.query_params.get("message"),
        "pending_count": len(context.pending.list()),
        "login_set": context.document.admin is not None,
    }
    return TEMPLATES.TemplateResponse(request, template, values, status_code=status_code)


def _optional_float(text: str | None) -> float | None:
    """A number from a form field, or None when it was left empty."""
    text = (text or "").strip().replace(",", ".")
    return float(text) if text else None


def _validation_message(exc: ValidationError) -> str:
    """The first validation error, in words a person can act on."""
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    return f"{where}: {first['msg']}" if where else str(first["msg"])


def _rounded(value: float | None) -> float | None:
    """Round a duration for display, passing None through."""
    return None if value is None else round(value, 1)

"""The dashboard's web application: the read-only API, its health probe, and first-run setup.

Until dashboard.yaml exists, `/setup` asks for the database and the API answers 503. Once it is
written the setup routes are gone (404) for the life of the file: changing the configuration
means editing or deleting it and restarting. Setup is not protected -- whoever reaches the page
first configures the site -- so it should be finished before the port is exposed.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ecowitt.core.ratelimit import RateLimiter
from ecowitt.core.store import settings as store_settings
from ecowitt.core.store.query import Reader, ReadError
from ecowitt.core.units import DistanceUnit, PressureUnit, RainUnit, TemperatureUnit, WindUnit
from ecowitt.dashboard import models, siteconfig
from ecowitt.dashboard.catalogue import METRICS
from ecowitt.dashboard.service import PERIODS, RANGES, Dashboard, UnknownStation
from ecowitt.dashboard.settings import Settings
from ecowitt.dashboard.siteconfig import AlreadyConfigured, SiteConfig

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
API = "/api/v1"
#: Largest setup form accepted; the real one is well under a kilobyte.
MAX_FORM_BYTES = 16 * 1024
#: Most metrics one /series request may ask for.
MAX_METRICS = 12

ReaderFactory = Callable[[str, Mapping[str, str]], Reader]


@dataclass
class Site:
    """The application's state: the dashboard, once the site is configured."""

    settings: Settings
    make_reader: ReaderFactory
    dashboard: Dashboard | None = None

    def configure(self, config: SiteConfig) -> None:
        """Start serving `config`'s database."""
        reader = self.make_reader(config.kind, config.connection)
        self.dashboard = Dashboard(reader, title=config.title, stations=config.stations)

    async def close(self) -> None:
        """Release the database connection."""
        if self.dashboard is not None:
            await self.dashboard.reader.aclose()


def _dashboard(request: Request) -> Dashboard:
    """The configured dashboard, or 503 until setup is done."""
    site: Site = request.app.state.site
    if site.dashboard is None:
        raise HTTPException(503, "not configured yet: finish setup at /setup")
    return site.dashboard


def _units(
    temperature: TemperatureUnit | None = None,
    pressure: PressureUnit | None = None,
    rain: RainUnit | None = None,
    wind: WindUnit | None = None,
    distance: DistanceUnit | None = None,
) -> dict[str, str]:
    """Units to answer in; each one not given is the station's own."""
    chosen = {
        "temperature": temperature,
        "pressure": pressure,
        "rain": rain,
        "wind": wind,
        "distance": distance,
    }
    return {k: v for k, v in chosen.items() if v is not None}


Board = Annotated[Dashboard, Depends(_dashboard)]
Station = Annotated[str, PathParam(description="A station's name, as /stations lists it")]
Choice = Annotated[dict[str, str], Depends(_units)]


async def access(request: Request) -> None:
    """Who may use the API: everyone. Every API route depends on this, so a login or an
    allowlist added here covers them all."""


def build_app(
    settings: Settings,
    *,
    make_reader: ReaderFactory = lambda kind, values: store_settings.reader_from(kind, values),
) -> FastAPI:
    """Build the application. Raises siteconfig.ConfigError if dashboard.yaml cannot be used."""
    site = Site(settings, make_reader)
    config = siteconfig.load(settings.config_path)
    if config is not None:
        site.configure(config)
    else:
        logger.warning("no %s yet: finish setup at /setup", settings.config_path)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await site.close()

    app = FastAPI(
        title="Ecowitt Server dashboard",
        description="Read-only weather data from the stations an Ecowitt Server collects.",
        version="1",
        openapi_url=f"{API}/openapi.json",
        docs_url=f"{API}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.site = site
    limiter = RateLimiter(rate=settings.rate, burst=settings.burst)

    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[..., Awaitable[Response]]
    ) -> Response:
        """Hold each address to its budget; the health probe is exempt."""
        client = request.client.host if request.client else "unknown"
        if request.url.path != "/healthz" and not limiter.allow(client):
            return JSONResponse(
                {"detail": "too many requests"}, status_code=429, headers={"Retry-After": "1"}
            )
        return await call_next(request)

    @app.exception_handler(UnknownStation)
    async def unknown_station(_: Request, exc: UnknownStation) -> Response:
        return JSONResponse({"detail": f"no station named {exc}"}, status_code=404)

    @app.exception_handler(ReadError)
    async def unreadable(_: Request, exc: ReadError) -> Response:
        logger.error("reading the database failed: %s", exc)
        return JSONResponse({"detail": "the database could not be read"}, status_code=503)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Whether this process is serving, and whether setup is done."""
        return {"status": "ok" if site.dashboard else "unconfigured"}

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        return RedirectResponse(f"{API}/docs" if site.dashboard else "/setup", status_code=303)

    @app.get("/setup", include_in_schema=False)
    async def setup_page(request: Request) -> Response:
        if site.dashboard is not None:
            raise HTTPException(404)
        return _setup(request, {})

    @app.post("/setup", include_in_schema=False)
    async def setup_save(request: Request) -> Response:
        if site.dashboard is not None:
            raise HTTPException(404)
        form = await _form(request)
        if isinstance(form, Response):
            return form
        return await _setup_action(request, site, form)

    router = APIRouter(prefix=API, dependencies=[Depends(access)])

    @router.get("/meta")
    async def meta(board: Board, response: Response) -> models.Meta:
        """The metrics, units, chart ranges and extremes periods the API offers."""
        response.headers["Cache-Control"] = "public, max-age=300"
        return board.meta()

    @router.get("/stations")
    async def stations(board: Board, response: Response) -> list[models.Station]:
        """Every station shown, with its location, time zone and stored units."""
        response.headers["Cache-Control"] = "public, max-age=300"
        return await board.stations()

    @router.get("/stations/{station}/now")
    async def now(board: Board, station: Station, choice: Choice, response: Response) -> models.Now:
        """A station at a glance: current conditions, today's range, rooms and sensor health."""
        response.headers["Cache-Control"] = "public, max-age=30"
        return await board.now(station, choice)

    @router.get("/stations/{station}/series")
    async def series(
        board: Board,
        station: Station,
        choice: Choice,
        response: Response,
        metrics: Annotated[str, Query(description="Metric ids from /meta, comma-separated")],
        range_: Annotated[str, Query(alias="range", description=", ".join(RANGES))] = "24h",
    ) -> models.SeriesOut:
        """Metrics over a range, in buckets aligned to the station's midnight."""
        chosen = [m.strip() for m in metrics.split(",") if m.strip()]
        unknown = [m for m in chosen if m not in METRICS]
        if unknown:
            raise HTTPException(422, f"unknown metrics: {', '.join(unknown)}")
        if not chosen or len(chosen) > MAX_METRICS:
            raise HTTPException(422, f"ask for between 1 and {MAX_METRICS} metrics")
        if range_ not in RANGES:
            raise HTTPException(422, f"range must be one of {', '.join(RANGES)}")
        response.headers["Cache-Control"] = f"public, max-age={int(RANGES[range_].ttl)}"
        return await board.series(station, chosen, range_, choice)

    @router.get("/stations/{station}/extremes")
    async def extremes(
        board: Board,
        station: Station,
        choice: Choice,
        response: Response,
        period: Annotated[str, Query(description=", ".join(PERIODS))] = "today",
    ) -> models.ExtremesOut:
        """The lowest and highest of each metric today, this month or this year."""
        if period not in PERIODS:
            raise HTTPException(422, f"period must be one of {', '.join(PERIODS)}")
        response.headers["Cache-Control"] = f"public, max-age={int(PERIODS[period])}"
        return await board.extremes(station, period, choice)

    app.include_router(router)
    return app


async def _setup_action(request: Request, site: Site, form: dict[str, str]) -> Response:
    """Test the connection, or save the configuration once a test of it passes."""
    kind = form.get("kind", "")
    declared = store_settings.KINDS.get(kind)
    if declared is None or not declared.readable:
        return _setup(request, form, error="Choose a kind of database.")
    values = {
        s.name: form.get(f"{kind}.{s.name}", "").strip()
        for s in declared.settings
        if form.get(f"{kind}.{s.name}", "").strip()
    }
    found = store_settings.problems(kind, values)
    title = form.get("title", "").strip() or siteconfig.DEFAULT_TITLE
    stations = tuple(s.strip() for s in form.get("stations", "").split(",") if s.strip())
    if found:
        return _setup(request, form, error="; ".join(found) + ".")
    reader = site.make_reader(kind, values)
    try:
        problem = await reader.check_read()
        if problem is None:
            names = await reader.stations()
    except ReadError as exc:
        problem = str(exc)
    finally:
        await reader.aclose()
    if problem:
        return _setup(request, form, error=f"{declared.label} refused: {problem}.")
    if form.get("action") == "test":
        listed = ", ".join(names) if names else "none yet"
        return _setup(
            request, form, message=f"Connected. Stations that published settings: {listed}."
        )
    config = SiteConfig(kind, values, title, stations)
    try:
        siteconfig.create(site.settings.config_path, config)
    except AlreadyConfigured:
        return PlainTextResponse("This dashboard has already been set up.", status_code=409)
    site.configure(config)
    logger.info("set up: wrote %s", site.settings.config_path)
    return RedirectResponse("/", status_code=303)


def _setup(
    request: Request, form: Mapping[str, str], *, message: str = "", error: str = ""
) -> Response:
    """The setup page, showing what was typed so nothing has to be entered twice."""
    kinds = [kind for kind in store_settings.KINDS.values() if kind.readable]
    return TEMPLATES.TemplateResponse(
        request,
        "setup.html",
        {
            "kinds": kinds,
            "form": dict(form),
            "chosen": form.get("kind") or kinds[0].name,
            "message": message,
            "error": error,
            "default_title": siteconfig.DEFAULT_TITLE,
        },
        status_code=400 if error else 200,
    )


async def _form(request: Request) -> dict[str, str] | Response:
    """A submitted form's fields, or a refusal if it is larger than any real one."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FORM_BYTES:
        return PlainTextResponse("Form too large.", status_code=413)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_FORM_BYTES:
            return PlainTextResponse("Form too large.", status_code=413)
    return dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))

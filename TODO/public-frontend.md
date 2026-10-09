# Public frontend

A companion app that shows a station's weather to anyone: current conditions, the last day or
week as charts, and today's extremes. It ships as its own image and runs as its own container,
next to this server rather than inside it.

## Why a separate app

This server's split is its security model: the ingest listener serves one route, and the admin
listener (status, setup, read API) is meant to stay behind the operator's own access control. A
public page must not loosen either. A separate container can be published openly while both
listeners keep their current exposure, and it can fail, be redeployed or be scaled without
touching ingest.

## Sketch

- **Data source: InfluxDB, read-only.** The frontend queries the `weather` database with a token
  scoped to read it, the way the Grafana dashboard does. It does not call the admin listener's
  `/api/readings`, which would make the internal listener reachable from a public service and
  ties the frontend to whatever one process has seen since it started.
- **Server-rendered pages with a small JSON endpoint for charts**, cached for about one upload
  interval, so a burst of visitors costs one query per interval rather than one per visitor.
- **What is public is chosen, not inherited.** Outdoor conditions, rain, wind, pressure and sun
  by default; indoor rooms, battery state and station health only when the operator opts in,
  since room names and indoor conditions describe a home.
- **Units** follow a viewer's choice (°C/°F, hPa/inHg, km/h/mph/m/s), converted from the stored
  units rather than queried in them.
- **Configuration** by environment: InfluxDB URL, database, token file, which station(s), what to
  show, the site's title. No setup page; nothing it does needs one.
- **Same repository conventions**: `frontend/` beside `backend/`, its own coverage suite in
  `coverage.toml`, its own image in the CI workflow.

## Open questions

- Framework: keep Python (FastAPI + Jinja2, sharing `units.py`) or a static front end with a thin
  API? Sharing the unit conversions argues for Python.
- One station per deployment, or a station picker?
- Whether to show the derived values (dew point, feels-like) or only what was measured.

## Done when

The app runs from its own image with a read-only token, shows live outdoor conditions and charts,
exposes nothing the operator did not opt into, and has tests and coverage like the backend.

# Ecowitt Server

## What this is

A self-hosted server that receives the reports an Ecowitt weather station uploads and stores
them in InfluxDB, converting to the units the operator keeps and deriving the psychrometric
quantities the console does not send.

## Layout

```
core/src/ecowitt/core/   shared by the collector and the dashboard
  units.py        conversions, and the Units preference
  psychro.py      the formulas behind derive, pure and reference-tested
  readings.py     Reading, the canonical-unit value parse produces and derive consumes
  preferences.py  units, sensor names, altitude
  stationinfo.py  a station's published settings: the station_info row the collector writes and
                  the dashboard reads
  ratelimit.py    the public listeners' per-address token bucket
  testing.py      a stand-in HTTP server every project's tests use for InfluxDB and lookups
  store/          where rows are written, behind one interface
    base.py       Row, Outcome, and the Store protocol: encode(rows) -> payload, write(payload)
    lineprotocol.py  rows -> InfluxDB line protocol
    influx.py     InfluxStore: what every InfluxDB version shares -- HTTP, line protocol, and
                  the OK / RETRY / REJECT classification of a write's outcome
    influx3.py    Influx3Store: /api/v3/write_lp, bearer token
    influx2.py    Influx2Store: /api/v2/write, bucket and organisation, `Token` scheme
    factory.py    store_for(kind, ...): the implementation for a configured kind; reader_for
                  for the kinds that can be read back (InfluxDB 3)
    settings.py   each kind's connection settings, declared once for every setup form
    query.py      Reader: what a dashboard asks of a store (spans, extremes, time buckets)
core/tests/       its own tests, which alone count towards its coverage

collector/src/ecowitt/collector/   (`ecowitt` is a namespace: no ecowitt/__init__.py anywhere;
                                    tests/server/test_namespace.py and core's own copy guard it)
  __main__.py     `python -m ecowitt.collector`: configure logging and serve
  config.py       environment settings: ports, limits, logging (the database is configured on the
                  setup page); a credential also accepts a *_FILE variant
  serve.py        builds both apps and runs both listeners in one event loop
  state.py        in-process counters both listeners see
  http.py         read_capped_body, shared by both
  healthcheck.py  module entrypoint for the container's HEALTHCHECK

  ingest/         the public listener and the data path
    app.py        the public app -- one route, and deliberately nothing else
    handler.py    authenticate a report against the stations, process it, write it
    pending.py    unconfigured stations offered for adoption, by fingerprint
    pipeline.py   report fields -> rows: parse, derive, render   <- the data path
    fields.py     the declarative table: which key is stored where, in what unit
    parse.py      fields -> readings in canonical units (°C, hPa, mm, m/s, km); never raises
    derive.py     moisture, ventilation, sea-level pressure, staleness
    points.py     readings -> rows in the operator's units, with tags
    staleness.py  how long each sensor's values have gone unchanged

  admin/          the admin listener
    app.py        status and setup pages, the read API, the login and form checks
    templates/    the pages, Jinja2 with autoescaping
    static/       scripts the pages load, as files so they can be tested (geolocate.js)
    auth.py       scrypt password hashes, Basic login, CSRF token and origin check
    configstore.py  the live configuration: validate, save, then apply and notify (the database
                    connection included, so a save takes effect without a restart)
    stationconfig.py  /data/config.yaml: the database connection, the PASSKEY allowlist and
                      per-station preferences
    calibration.py  the relative, absolute-step and absolute-reference pressure checks
    lookups.py    elevation and model surface pressure from public services
    reference.py  the background refresh of model surface pressure
    timezones.py  a station's time zone from its coordinates (offline, tzfpy), and validation

  delivery/       getting rows into the database (through a core Store)
    database.py   ConfiguredStore: the store config.yaml names, swapped in place on a save
    delivery.py   write now or spool; the replay loop that drains the spool
    spool.py      the bounded on-disk queue, one atomically written file per report
    heartbeat.py  calls a push monitor's URL after writes, at most once per interval
    metadata.py   publishes each station's settings as station_info, only when they change
collector/tests/  one folder per subpackage (ingest/, admin/, delivery/), plus
  server/         wiring: the two listeners, settings, the health probe
  common/         the top-level modules the listeners share
  grafana/        the dashboard and alert rules checked against the golden output
                  (grafana_sql.py holds the checks both share)
  tooling/        the scripts in bin/ that have logic of their own
  js/             node:test suites for admin/static/, against stand-in DOM and browser APIs
  conftest.py     settings/state fixtures and the recorded console payloads
  fixtures/       recorded payloads, the golden line protocol, the known-keys list
dashboard/api/src/ecowitt/dashboard/   the public dashboard's read-only API
  app.py          /api/v1 routes behind one `access` dependency, /healthz, first-run /setup
  service.py      answers built from a Reader: now, series, extremes; cached in stored units
  catalogue.py    the metrics served: table, base field, kind, aggregates, which sensors
  weather.py      compass, Beaufort, feels-like, pressure tendency, airing advice
  sun.py          sunrise, solar noon and sunset (NOAA's equations)
  siteconfig.py   /data/dashboard.yaml, written once by setup; edited or deleted by hand after
  cache.py        a TTL cache whose concurrent requests share one computation
  models.py       the answers, as the OpenAPI document publishes them
  healthcheck.py  module entrypoint for the image's HEALTHCHECK (dashboard/Dockerfile)
dashboard/api/tests/  against an in-memory Reader (memory.py) that answers as the SQL does
grafana/          weather.json, the dashboard, and alerts.json, the alert rules; a renamed table or
                  field fails tests/grafana rather than blanking a panel or silencing an alert
TODO/             one note per planned feature; delete a note when its feature ships
bin/              every script the Makefile and CI run; its Python is linted with the shared
                  ruff.toml (bin/ci-ruff.sh)
```

## Things worth knowing before changing anything

- **The station follows no redirects.** It takes a 3xx, closes the connection, and re-sends
  the identical request on its next interval for ever. So both slash spellings of the ingest
  path are registered outright and `redirect_slashes` is off — and the test clients are built
  with `follow_redirects=False`, because a client that follows one reports success for a
  server no console can talk to.
- **Admin routes must never be mounted on the ingest app.** The split is the security model:
  a route that is absent cannot be exposed by a mistake in a guard. `test_ingest.py` asserts
  those paths return **404 and not 401** — a 401 would mean the route is there and merely
  guarded, which is the thing being avoided. The public app also sets `docs_url`, `redoc_url`
  and `openapi_url` to `None`.
- **`_Listener.capture_signals` overrides the hook uvicorn actually uses.** `Server.serve`
  wraps itself in that context manager and the base implementation points SIGINT and SIGTERM
  at its own `handle_exit` via `signal.signal`, which keeps one handler per signal — so with
  two servers the second would displace the first and SIGTERM would stop only one, hanging the
  process in `asyncio.gather` until SIGKILL. `serve.stop_all` is the single handler instead.
  `test_a_plain_uvicorn_server_would_have_claimed_them` pins the upstream behaviour, so a
  renamed hook fails loudly rather than leaving the override as dead code.
- **A rejected report still answers `200`** with the same body as an accepted one, and the
  answer is sent before the report is handled at all (a Starlette background task). A station
  cannot act on a refusal — it has no backlog to retry from — and a distinguishable response,
  or one slower for a known `PASSKEY` because it waits on InfluxDB, would tell an anonymous
  caller which guesses were right. Anything the handler raises is logged and counted as
  rejected, since there is no response left to carry it.
- **`PASSKEY` is never logged.** `ingest.redact` replaces it, and it is the one field the
  status API must not return. It is `MD5(MAC)` uppercased, so it is not rotatable.
- **Bodies are streamed against a cap, not read whole.** `request.body()` would allocate
  whatever an anonymous caller chose to send; `read_capped_body` checks a declared
  Content-Length first and aborts mid-stream otherwise.
- **The admin listener's login is optional**, set on the setup page and stored as a salted
  scrypt hash. Without one, its host-side publish is the only gate, and the process cannot
  tell whether that publish is safe: in a container both listeners must bind every interface,
  since a loopback bind there is unreachable even through a published port. So
  `warn_if_admin_unauthenticated` keys on whether a login is set, the one thing it can see.
- **Every POST on the admin listener goes through `admin._form`**, which checks the CSRF token
  and that Origin (or Referer) names this host. Browsers attach a Basic login to every request
  automatically, so without both any site the operator visits could post forms here. A new
  form route must use `_form`; `test_no_form_from_elsewhere_changes_anything` lists every
  route and must be extended with it.
- **Page scripts live in `static/` and are tested with `node --test`**, not inlined. Node's own
  coverage measures them -- no npm packages -- and `bin/lcov-to-istanbul.py` turns its lcov into
  the istanbul files the shared tooling reads, so they are the `pages` suite in `coverage.toml`
  with its own gate. A script that runs itself in a browser has a path Node never takes when it
  `require`s the file; `geolocate.test.js` runs it through `vm` as a plain script to cover it.
  Browsers give location only to HTTPS or localhost pages, so the location button explains
  itself instead of failing silently anywhere else -- and it fills the location of the device
  viewing the page, which is not necessarily the station's.
- **Adopting a station never displays its PASSKEY.** `PendingStations` keeps it in memory; the
  page refers to an entry by fingerprint. An entry leaves the list only after the station is
  saved, so a refused form or an altitude lookup leaves it there to adopt.
- **The HP2551's calibration screen has no relative offset.** It has *ABS Barometer*, which sets
  the absolute reading itself, and *Altitude for REL*, which it reduces with. Advice in
  `calibration.py` gives both forms because other firmware uses offsets instead. An absolute
  error moves the relative reading and its reduction together, so the relative check cannot see
  one; the step and reference checks exist for exactly that.
- **The unit belongs in the field name** (`temp_c`, `abs_hpa`). A bare `temp` whose unit
  depends on configuration history would silently mix °F and °C in one series.
- **Every number is written as a float**, `60.0` and never `60i`. InfluxDB fixes a field's type
  on its first write and rejects later writes of another type, so one integer-looking humidity
  would make every fractional one fail. For the same reason an unmapped key's textual values go
  to `<key>_text`, separate from its numeric ones.
- **A key that matches no row is not an error.** It is stored under `unmapped`, so a typo in a
  pattern fails nothing at runtime. `test_fields` is the guard: every key in
  `fixtures/known_keys.txt` must match exactly one row, and every row must be reached by one.
  Add new hardware's keys to that file in the same change as its rows.
- **Fahrenheit spelling differs by family.** Most suffix it (`tempf` / `tempc`); `wbgt`, `bgt`,
  `tf_co2`, `tf_chN` and `soil_ec_tempN` send it under the bare stem and suffix only Celsius.
  `temperature(..., bare_is_fahrenheit=True)` covers those.
- **`sensor` is the join key; `name` is a label.** Every row of a `NAMED_TABLES` table carries
  both. Renaming a room changes its `name` tag and so starts new series under the new name;
  dashboards should group by `sensor`.
- **Derived quantities are always computed, never taken from the report.** A console that also
  sends a dew point uses its own formula, and mixing the two would put a step in the series
  wherever the source changed.
- **`rel_error` is measured against a reduction at the standard atmosphere's temperature**, not
  the outdoor one that `sea` uses. A console's offset is a constant, so it can only match a
  constant-temperature reduction; the temperature-dependent one would swing by a few hPa a
  year and the calibration warning would come and go with the weather. Sea-level reduction
  falls back to the standard atmosphere without an outdoor sensor, never to indoor
  temperature, which in a heated house says nothing about the air outside.
- **A write outcome is RETRY unless InfluxDB refused the data itself.** Connection errors,
  timeouts, 5xx, 408 and 429 retry; so do 401, 403 and 404, because a revoked token or a
  dropped database is a fault to fix and the readings should be waiting when it is. Other 4xx
  are REJECT and the report goes to `spool/rejected/`: retrying data InfluxDB will never accept
  would block every report queued behind it.
- **Replays may duplicate, and that is fine.** A crash between InfluxDB accepting a write and
  the spool file's removal replays it; a point with the same series and timestamp overwrites
  itself. Do not add bookkeeping to prevent it.
- **The spool keeps its queue and file sizes in memory** after one listing at startup. That is
  sound only because one process owns the directory. Sizes are remembered rather than re-read,
  because a file deleted from outside can no longer be measured and the total would drift up.
- **The spool holds rows, not any database's wire format.** `dump_rows` writes them as JSON
  (`.json` files) and each store encodes at write time, so a backlog survives the database
  being set up, replaced or changed to another kind. A spooled file that is not rows -- an
  older version's `.lp` line protocol -- is set aside in `spool/rejected/`, not dropped.
- **While anything is spooled, new reports queue behind it** instead of being written live, so
  an outage costs one attempt per backoff pause rather than one per report.
- **Retention is set once, at database creation, and InfluxDB 3 cannot change it afterwards.**
  The `weather` database is created without any, deliberately.

## Commands

```bash
make install      # one virtualenv at the root, every project installed editable
make dev          # serve from the working copy (ingest :2551, admin :2552)
make test ARGS="tests/ingest/test_ingest.py -k slash"
make test-js      # the page scripts' tests, with coverage (needs node)
make check        # lint + every suite with coverage
UPDATE_GOLDEN=1 bin/test-python.sh collector tests/ingest/test_pipeline.py   # after an intended output change
```

## Testing conventions

- One coverage suite per project (`core`, `collector`, `dashboard`) plus `pages` for the admin's
  scripts, with their gates in `coverage.toml`. Each project measures only its own package, so
  shared code must be covered by core's own tests.
- Recorded console payloads live in `tests/fixtures/`, as the station sends them — one line,
  form-encoded, unmodified apart from the `PASSKEY`, which is a placeholder. A real one
  authenticates a station's reports and belongs in no repository. Names and altitudes in tests
  are invented for the same reason, and `hp2551_ws69.txt` has its relative pressure set equal to
  its absolute one, since the difference between them gives away the site's altitude.
- Each payload's `.lp` file is its golden output. A diff in it is a change of
  output to review line by line, not a file to regenerate and commit unread; the values behind it
  are pinned independently by `test_units` and `test_psychro`, which check against published
  reference tables rather than against this code.
- **`TestClient` blocks the test's event loop while a request runs.** A stand-in server a
  request must reach -- an elevation service, say -- cannot live on that loop; run it on its own
  thread (`test_pages.json_server`).
- **New tests are checked by mutating the code they cover**, not by reading them. A suite that
  survives a deliberate break is not testing that code. A client that follows redirects is the
  standing example: an ingest route reachable only through a 307 passes every assertion on its
  status code, so only removing the route and watching the suite stay green reveals it.

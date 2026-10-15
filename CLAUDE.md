# Ecowitt Server

## What this is

A self-hosted server that receives the reports an Ecowitt weather station uploads and stores
them in InfluxDB, converting to the units the operator keeps and deriving the psychrometric
quantities the console does not send.

## Layout

```
core/src/ecowitt/core/   shared by the collector and the dashboard
  units.py        conversions, the Units preference, and each unit's symbol and decimals
  psychro.py      the formulas behind derive, pure and reference-tested
  readings.py     Reading, the canonical-unit value parse produces and derive consumes
  preferences.py  units, sensor names, altitude
  stationinfo.py  a station's published settings: the station_info row the collector writes and
                  the dashboard reads
  weathermodel.py the `model`, `forecast` and `forecast_daily` tables: Open-Meteo's variables and
                  the fields they are stored as
  windheight.py   wind estimated at 10 m: the anemometer-height factor, the `wind_10m` table
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
    derive.py     moisture, ventilation, sea-level pressure, wind at 10 m, staleness
    points.py     readings -> rows in the operator's units, with tags
    staleness.py  how long each sensor's values have gone unchanged

  admin/          the admin listener
    app.py        status, setup and Grafana pages, the read API, the login and form checks
    templates/    the pages, Jinja2 with autoescaping
    static/       scripts the pages load, as files so they can be tested (geolocate.js,
                  clipboard.js)
    auth.py       scrypt password hashes, Basic login, CSRF token and origin check
    configstore.py  the live configuration: validate, save, then apply and notify (the database
                    connection included, so a save takes effect without a restart)
    stationconfig.py  /data/config.yaml: the database connection, the PASSKEY allowlist and
                      per-station preferences
    calibration.py  the relative, absolute-step and absolute-reference pressure checks
    lookups.py    elevation and a weather model's values from public services
    modelfeed.py  each located station's weather model (chosen on the setup page), every 15 min:
                  written to the `model` table, kept for the status page's comparison, and the
                  reference the absolute-pressure check reads
    forecastfeed.py  the weather forecast of each station that opts in (InfluxDB 3 Core cannot
                  read it back, see README), hourly: `forecast` and `forecast_daily`, tagged
                  with how far ahead (`lead`) each row was made
    timezones.py  a station's time zone from its coordinates (offline, tzfpy), and validation
    grafana.py    the Grafana page's files, and pushing them over Grafana's API

  grafana/        the Grafana dashboard and alert rules as templates, every unit-dependent spot
                  a %{...} placeholder; render.py writes them for the stored units

  delivery/       getting rows into the database (through a core Store)
    database.py   ConfiguredStore: the store config.yaml names, swapped in place on a save
    delivery.py   write now or spool; the replay loop that drains the spool
    spool.py      the bounded on-disk queue, one atomically written file per report
    heartbeat.py  calls a push monitor's URL after a station's readings are written, at most once
                  per interval (the collector's own rows -- settings, the model, the forecast, the
                  10 m wind -- do not count)
    metadata.py   publishes each station's settings as station_info, only when they change
    recompute.py  the setup page's opt-in recompute of a station's 10 m wind over its history
collector/tests/  one folder per subpackage (ingest/, admin/, delivery/), plus
  server/         wiring: the two listeners, settings, the health probe
  common/         the top-level modules the listeners share
  grafana/        the dashboard and alert rules checked against what the pipeline writes, in
                  every choice of units (grafana_sql.py holds the checks they share)
  tooling/        the scripts in bin/ that have logic of their own
  js/             node:test suites for admin/static/, against stand-in DOM and browser APIs
  conftest.py     settings/state fixtures and the recorded console payloads
  fixtures/       recorded payloads, the golden line protocol, the known-keys list
dashboard/api/src/ecowitt/dashboard/   the public dashboard's read-only API
  app.py          /api/v1 routes behind one `access` dependency, /healthz, first-run /setup,
                  /manifest.webmanifest (the home-screen app, named for the site)
  service.py      answers built from a Reader: now (with the weather model's sky), series (with
                  its series when asked), extremes; cached in stored units
  catalogue.py    the metrics served: table, base field, kind, aggregates, which sensors, and
                  the weather model's field for the same quantity
  weather.py      compass, Beaufort, feels-like, pressure tendency, airing advice
  messages.py     every word an answer carries but its error messages, in English, and each in a
                  request's language (and the home-screen manifest's description);
                  template() is the gettext template the catalogues are kept against
  i18n.py         the languages: locale/<locale>/LC_MESSAGES/messages.po read with Babel, and
                  the choice of one per request (?lang=, then Accept-Language, then English)
  forecast.py     the stored forecast read back (the newest row per hour and day), and what the
                  cards warn of from it: rain, frost, heat, gusts, a drier spell for airing
  sun.py          sunrise, solar noon and sunset (NOAA's equations)
  siteconfig.py   /data/dashboard.yaml, written once by setup; edited or deleted by hand after
  cache.py        a TTL cache whose concurrent requests share one computation
  models.py       the answers, as the OpenAPI document publishes them
  healthcheck.py  module entrypoint for the image's HEALTHCHECK (dashboard/Dockerfile)
dashboard/api/tests/  against an in-memory Reader (memory.py) that answers as the SQL does;
                  fixture_server.py serves the real app over it, for a browser to load
dashboard/web/    the dashboard's page: Svelte 5, Vite, TypeScript, uPlot; a thin client of /api/v1
  src/lib/        api.ts (types mirroring the OpenAPI models, the client), format.ts (values and
                  station-time times), chart.ts (chart tabs, aligning series for uPlot, the
                  model's dashed lines), prefs.ts, sky.ts (WMO code -> Meteocons icon),
                  theme.ts (light, dark, or dark from sunset to sunrise), language.ts (which
                  language: the visitor's choice, else the browser's, else English)
  messages/       en.json and pt-PT.json, the page's words; Paraglide compiles them into
                  src/paraglide (generated, not committed) as `m.<key>()`
  project.inlang/ settings.json, Paraglide's project: the languages and the message plugin,
                  loaded from node_modules rather than a CDN
  src/components/ one per card or section; Chart.svelte is the only one that touches uPlot
  src/testing.ts  API answers for the tests, and a fake Api
  icons/          app-icon.svg, the home-screen icon; bin/app-icons.sh renders public/icons/*.png
  build/          legacy-css.ts, the Vite plugin that gives the stylesheet its legacy fallbacks;
                  paraglide.ts, how messages compile, and compile-messages.ts, which writes them
                  for svelte-check (bin/test-web.sh and `npm run check` run it first)
  legacy-browser/ the Chromium 59 image and the check bin/test-legacy-browser.sh runs in it
dashboard/Dockerfile  builds the page in a Node stage and serves it from the API's image
grafana/          weather.json, the dashboard, and alerts.json, the alert rules: the collector's
                  templates rendered for the default units (make grafana); a renamed table or
                  field fails tests/grafana rather than blanking a panel or silencing an alert
TODO/             one note per planned feature; delete a note when its feature ships
bin/              every script the Makefile and CI run; its Python is linted with the shared
                  ruff.toml (bin/ci-ruff.sh). lockfile.sh / check-lockfile.sh write and guard
                  the page's package-lock.json; test-web.sh type-checks and tests the page;
                  version.py keeps every manifest's version and the compose file's major image
                  tag in step, release.sh cuts a release
                  and github-release.sh (CI, on a tag) publishes its notes; grafana.py writes
                  grafana/*.json from the templates; messages.py updates the API's catalogues
CHANGELOG.md      every release's notes; new work goes under `## Unreleased`
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
- **The Grafana files are rendered, not edited.** Change
  `collector/src/ecowitt/collector/grafana/*.template.json`, writing anything that depends on
  the units as a placeholder (`%{temp_c}`, `%{8 temperature}`, `%{2 temperature_delta}` for a
  difference, `%{unit speed}`, `%{symbol speed}`, `%{decimals pressure}`), then `make grafana`.
  Tests fail until `grafana/*.json` match the default render, and until no field, display unit
  or unit word in the default units is written outside a placeholder.
- **The rule file and the API spell a rule differently.** `grafana/alerts.json` is a
  provisioning file, which reads `keepFiringFor` and silently drops keys it does not know; the
  provisioning API takes `keep_firing_for` and the interval in seconds. `admin/grafana.py`
  converts for a push; `test_every_rule_key_is_one_a_provisioning_file_reads` guards the file.
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
- **Every measurement is written as a float**, `60.0` and never `60i`. InfluxDB fixes a field's
  type on its first write and rejects later writes of another type, so one integer-looking
  humidity would make every fractional one fail. For the same reason an unmapped key's textual
  values go to `<key>_text`, separate from its numeric ones. A value that is a category rather
  than a quantity (`Kind.CODE`, a WMO weather code) is an integer, and a yes/no is a boolean:
  neither can arrive in another form.
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
- **A console's derived quantities are always computed, never taken from its report.** A
  console that also sends a dew point uses its own formula, and mixing the two would put a step
  in the series wherever the source changed. The weather model's values are stored as Open-Meteo
  supplies them: they are one source throughout, and its dew point agrees with ours to 0.1 °C.
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

- **The dashboard's setup page is unprotected by design.** Until `dashboard.yaml` exists, whoever
  reaches `/setup` configures the site; once it is written the setup routes are absent (404) for
  the life of the file. Its test connection reports only success or failure, with a short
  timeout, since an anonymous caller chooses the address it connects to.
- **The dashboard API's words are gettext messages, and so are some of core's.** Its English
  is the message id: `messages.py`, and the tables it reads -- `weather.COMPASS` and
  `BEAUFORT_NAMES`, the metric labels in `catalogue.py`, and core's `weathermodel.WEATHER_CODES`
  and `MODELS`. Changing any of them needs `make messages` and a translation in every catalogue;
  `test_i18n` fails until each is current, fully translated and keeps its placeholders. A message
  naming a time of day has plural forms chosen by its hour, for Portuguese's "à 01:00" / "às
  02:00". The page asks for its own language with `lang`, so the API's words always match it.
- **The dashboard's page formats times itself, in its own language** (`language.ts`
  `intlLocale`): English is `en-GB`, day first with a 24-hour clock, rather than the browser's
  locale, since an American locale writes `10/11` and `12:56 AM`. Times are in the station's
  time zone.
- **The page's words are Paraglide messages**, in `messages/<locale>.json`, and every message
  must exist in every file. Its language comes from two strategies of its own in `language.ts`,
  not Paraglide's built-in localStorage and preferredLanguage. Paraglide writes the first language
  it resolves back into every strategy, so the built-in one would save the browser's language as
  if the visitor had chosen it. And preferredLanguage would not match "pt" to "pt-PT". A label
  in a module-level constant is the message function itself (`m.view_wind`), called when drawn:
  constants are evaluated before `main.ts` registers the strategies. Counts match exactly
  (`count=1`) and times carry their `hour` for Portuguese's "à 01:00"; Paraglide's `plural`
  selector needs `Intl.PluralRules`, which Chrome 59 lacks. `main.ts` settles the language once
  (`settleLanguage`), so the page, its API answers and `<html lang>` agree until it reloads, which
  choosing a language does. Storage is read through `prefs.browserStorage()`: with cookies blocked,
  merely reading `window.localStorage` throws.
- **Adding a language touches both halves.** For the page: its locale in
  `project.inlang/settings.json`, a `messages/<locale>.json` with every message, and its name and
  Intl locale in `language.ts`. For the API: `bin/messages.py --add <locale>`, then translate the
  catalogue it starts. The API's tests fail until every message is translated with exactly its
  placeholders; the page's only until every message exists and names no placeholder its English
  lacks, so a message left in English passes there. Have a native speaker review both for
  naturalness, not literal fidelity.
- **The dashboard's page has a legacy build**, for browsers without ES modules down to Chrome 59
  (an Android 4.4 tablet): `@vitejs/plugin-legacy` compiles it down and polyfills it, and those
  browsers load it through `<script nomodule>`. What core-js cannot polyfill needs a fallback in
  the code -- `Chart.svelte` follows the window where `ResizeObserver` is missing. The shared
  stylesheet relies on `:where()` (in every selector Svelte scopes) and on `gap`, which Chrome 59
  lacks or knows only on grids; `build/legacy-css.ts` adds copies and fallbacks for them under a
  `legacy` class that only those browsers get, so a modern browser's computed styles stay as
  they are. `make test-legacy-browser` loads the page in Chromium 59 and is the guard.
- **`dashboard/web/package-lock.json` must resolve only to registry.npmjs.org.** A development
  machine may reach npm only through a proxy, and a plain `npm install` writes the proxy's host
  into every entry -- breaking CI and publishing it. Regenerate it with `bin/lockfile.sh` only;
  `bin/check-lockfile.sh` (lint and CI) asserts the public registry rather than naming any host.

## Commands

```bash
make install      # one virtualenv at the root, every project installed editable
make dev          # serve from the working copy (ingest :2551, admin :2552)
make test ARGS="tests/ingest/test_ingest.py -k slash"
make test-js      # the admin page scripts' tests, with coverage (needs node)
make web-install  # the dashboard page's node_modules, from the lockfile, via this machine's registry
make test-web     # the dashboard page: svelte-check and Vitest with coverage
make test-legacy-browser   # the page's legacy build in Chromium 59 (Docker; slow off x64)
make dashboard-dev SERVER=host   # page :5173 and API :2553, both reloading; host's InfluxDB on :8181
make lockfile     # regenerate dashboard/web/package-lock.json (the only way to)
make grafana      # rewrite grafana/*.json after changing a template
make messages     # update the API's .po catalogues after changing a message, then translate
make check        # lint + every suite with coverage
bin/release.sh 2.9.0   # date the changelog's Unreleased section, commit and tag; then push both
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

# Ecowitt Server

## What this is

A self-hosted server that receives the reports an Ecowitt weather station uploads and stores
them in InfluxDB, converting to the units the operator keeps and deriving the psychrometric
quantities the console does not send.

## Layout

```
backend/src/ecowitt/
  config.py       environment settings; every credential also accepts a *_FILE variant
  serve.py        builds both apps and runs both listeners in one event loop
  ingest.py       the public app -- one route, and deliberately nothing else
  http.py         read_capped_body, shared by both
  state.py        in-process counters both listeners see
  healthcheck.py  module entrypoint for the container's HEALTHCHECK

  pipeline.py     report fields -> rows: parse, derive, render   <- the data path
  fields.py       the declarative table: which key is stored where, in what unit
  parse.py        fields -> readings in canonical units (°C, hPa, mm, m/s, km); never raises
  derive.py       moisture, ventilation, sea-level pressure, staleness
  psychro.py      the formulas behind derive, pure and reference-tested
  units.py        conversions, and the Units preference
  points.py       readings -> rows in the operator's units, with tags
  lineprotocol.py rows -> InfluxDB line protocol
  preferences.py  units, sensor names, altitude
  staleness.py    how long each sensor's values have gone unchanged

  admin.py        status and setup pages, the read API, the login and form checks
  templates/      the pages, Jinja2 with autoescaping
  auth.py         scrypt password hashes, Basic login, CSRF token and origin check
  configstore.py  the live configuration: validate, save, then apply and notify
  pending.py      unconfigured stations offered for adoption, by fingerprint
  calibration.py  the relative, absolute-step and absolute-reference pressure checks
  lookups.py      elevation and model surface pressure from public services
  reference.py    the background refresh of model surface pressure
  handler.py      authenticate a report against the stations, process it, write it
  stationconfig.py  /data/config.yaml: the PASSKEY allowlist and per-station preferences
  writer.py       one write to InfluxDB 3 or 2.x, classified OK / RETRY / REJECT
  delivery.py     write now or spool; the replay loop that drains the spool
  spool.py        the bounded on-disk queue, one atomically written file per report
  ratelimit.py    the ingest listener's per-address token bucket
backend/tests/
  conftest.py     settings/state fixtures and the recorded console payloads
  fixtures/       recorded payloads, the golden line protocol, the known-keys list
  test_infra/     wiring: the two listeners, config resolution, the health probe
  test_data/      the data path, module by module, and the golden end-to-end test
  test_store/     configuration, rate limiting, the handler, and the writer against a real
                  HTTP server standing in for InfluxDB
bin/              every script the Makefile and CI run
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
- **A rejected report still answers `200`** with the same body as an accepted one. A station
  cannot act on a refusal — it has no backlog to retry from — and a distinguishable response
  would tell an anonymous caller which `PASSKEY` guesses were wrong.
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
- **While anything is spooled, new reports queue behind it** instead of being written live, so
  an outage costs one attempt per backoff pause rather than one per report.
- **Retention is set once, at database creation, and InfluxDB 3 cannot change it afterwards.**
  The `weather` database is created without any, deliberately.

## Commands

```bash
make install      # virtualenv + test extras
make dev          # serve from the working copy (ingest :2551, admin :2552)
make test ARGS="tests/test_infra/test_ingest.py -k slash"
make check        # lint + suite + coverage gate
UPDATE_GOLDEN=1 bin/test-backend.sh tests/test_data/test_pipeline.py   # after an intended output change
```

## Testing conventions

- One coverage suite, with its gate in `coverage.toml`.
- Recorded console payloads live in `tests/fixtures/`, as the station sends them — one line,
  form-encoded, unmodified apart from the `PASSKEY`, which is a placeholder. A real one
  authenticates a station's reports and belongs in no repository. Names and altitudes in tests
  are invented for the same reason.
- `fixtures/hp2551_indoor.lp` is the golden output for that payload. A diff in it is a change of
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

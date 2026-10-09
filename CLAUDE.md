# ecowitt

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
  admin.py        the admin app -- status, health, read API
  http.py         read_capped_body, shared by both
  state.py        in-process counters both listeners see
  healthcheck.py  module entrypoint for the container's HEALTHCHECK
backend/tests/
  conftest.py     settings/state fixtures and the recorded console payloads
  test_infra/     wiring: the two listeners, config resolution, the health probe
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
- **The bind address is not a usable signal for "is the admin interface exposed?"** In a
  container both listeners must bind every interface, since a loopback bind there is
  unreachable even through a published port. `warn_if_admin_unauthenticated` keys on the thing
  the operator controls — whether a login is configured — because a warning that fires on
  every start is a warning that gets ignored.
- **The unit belongs in the field name** (`temp_c`, `pressure_abs_hpa`). A bare `temp` whose
  unit depends on configuration history would silently mix °F and °C in one series.
- **Retention is set once, at database creation, and InfluxDB 3 cannot change it afterwards.**
  The `weather` database is created without any, deliberately.

## Commands

```bash
make install      # virtualenv + test extras
make dev          # serve from the working copy (ingest :8000, admin :8001)
make test ARGS="tests/test_infra/test_ingest.py -k slash"
make check        # lint + suite + coverage gate
```

## Testing conventions

- One coverage suite, with its gate in `coverage.toml`.
- Recorded console payloads live in `tests/fixtures/`, as the station sends them — one line,
  form-encoded, unmodified apart from the `PASSKEY`, which is a placeholder. A real one
  authenticates a station's reports and belongs in no repository.
- **New tests are checked by mutating the code they cover**, not by reading them. A suite that
  survives a deliberate break is not testing that code. A client that follows redirects is the
  standing example: an ingest route reachable only through a 307 passes every assertion on its
  status code, so only removing the route and watching the suite stay green reveals it.

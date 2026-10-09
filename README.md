# Ecowitt Server

[![Test and Publish](https://github.com/jmerhar/ecowitt/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/jmerhar/ecowitt/actions/workflows/build-and-push.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

An Ecowitt weather station can upload to a server of your choosing, every few seconds, for
free — no cloud account, no rate limit, no retention policy you do not control. What it cannot
do is store any of it. Point the console at **Ecowitt Server** and every value it reports lands in
InfluxDB, in the units you asked for, alongside the quantities the station does not send but
the data is useless without.

<sub>An independent project, not affiliated with or endorsed by Ecowitt. "Ecowitt" names the
hardware it talks to.</sub>

## What it does

- **Receives what the console sends**, over the Ecowitt protocol or the Wunderground one, by
  POST or GET, and stores all of it. Unrecognised fields are stored too, under their original
  names, so a sensor this server has never heard of still produces data.
- **Converts to the units you keep**, chosen per quantity. The unit is part of each field's
  name, so changing your mind later adds fields instead of silently mixing °C into a column of
  °F.
- **Derives what the console leaves out** — dew point, absolute humidity, mixing ratio and
  vapour pressure deficit for every temperature/humidity pair, and sea-level pressure from
  your altitude rather than from the console's calibration.
- **Answers "should I open the windows?"** For each room it compares the indoor dew point with
  the outdoor one and works out the humidity that room would settle at after ventilating.
- **Keeps readings through an outage.** A station has no backlog: whatever it sends while your
  database is down is gone for ever. Writes are spooled to disk and replayed, so restarting
  InfluxDB costs nothing.
- **Tells stable apart from dead.** Consoles repeat a sensor's last value when its radio goes
  quiet, which looks exactly like a sensor that is not changing. Every reading carries how
  long it has been identical.

## Running it

```bash
mkdir -p ecowitt/data && cd ecowitt
curl -O https://raw.githubusercontent.com/jmerhar/ecowitt/main/docker-compose.yml
docker compose up -d
```

One file is all it takes; there is nothing to clone or build. `data` is created first because
Docker would otherwise create it as root, and the container does not run as root.

Then open <http://127.0.0.1:2552> and work through the setup, which asks where InfluxDB is,
which units you keep, what your channels are called and where the station is.

Finally, on the console — *Menu → Weather Services → Customized*:

| Field | Value |
|---|---|
| State | Enable |
| Protocol Type | Same As Ecowitt |
| IP / Hostname | the host running this |
| Port | `2551` |
| Path | `/data/report/` |
| Interval | see below |

## Two ports, and why it matters

The station speaks **plain HTTP and follows no redirects**, so its endpoint cannot sit behind
TLS or an authenticating proxy. That endpoint is therefore the one thing exposed, and it is
exposed on its own listener:

| Listener | Default publish | Serves |
|---|---|---|
| ingest | `0.0.0.0:2551` | the configured path, and nothing else |
| admin | `127.0.0.1:2552` | status page, setup, read API, health |

The admin routes are not merely *refused* on the ingest listener — they are not mounted on it,
so no mistake in a guard can expose them. Ask the ingest port for the status page and it
answers `404`, because there is nothing there.

Keep the admin listener on loopback and reach it through a reverse proxy. If you widen that
bind, configure a login first: set `HTPASSWD_FILE`, or add credentials in the setup wizard.
The server says so on startup when none is configured.

The ingest endpoint authenticates the station by its `PASSKEY`, which the console sends on
every report; reports from an unlisted station are discarded. Requests are rate limited and
size capped. Note that `PASSKEY` is derived from the station's MAC address, so it cannot be
changed — if you would rather have a rotatable secret, put one in the console's **Path** and
configure `INGEST_PATH` to match.

## Choosing an interval

Sensors transmit on their own schedule, and uploading faster than they transmit only repeats
values. A WN31 channel updates about every 60 s, a WS69 about every 16 s, a WS90 about every
8.8 s — which is why 8 s is the fastest a console will offer.

Uploading more slowly loses less than it appears to: wind gusts and the daily maximum are
tracked by the console between uploads, and rain totals are cumulative counters, so no extreme
is missed. Only instantaneous wind detail is. **60 s suits most stations**; match your fastest
sensor if you want wind texture.

You do not have to guess. Every reading records how long its value has been unchanged, so
after a day the status page shows what each of your sensors actually does.

## Configuration

Infrastructure comes from the environment, so a deployment is reproducible from its compose
file:

| Variable | Default | |
|---|---|---|
| `INFLUX_URL` | — | e.g. `http://influxdb:8181` |
| `INFLUX_DATABASE` | `weather` | |
| `INFLUX_TOKEN` / `INFLUX_TOKEN_FILE` | — | the file form reads a Docker secret |
| `INFLUX_API` | `v3` | `v3` writes line protocol to `/api/v3/write_lp`; `v2` to `/api/v2/write` |
| `INFLUX_ORG` | — | InfluxDB 2.x only |
| `INGEST_PATH` | `/data/report/` | both slash spellings are served |
| `INGEST_HOST` / `INGEST_PORT` | `0.0.0.0` / `8000` | inside the container |
| `ADMIN_HOST` / `ADMIN_PORT` | `0.0.0.0` / `8001` | inside the container |
| `HTPASSWD_FILE` | — | guards every admin route |
| `DATA_DIR` | `/data` | configuration and spool |
| `LOG_LEVEL` | `INFO` | |

Everything describing *your* station — units, channel names, the `PASSKEY` allowlist, the site
location — is set in the browser and kept in `data/config.yaml`, which is editable by hand.
A value set in the environment wins, and the interface marks it as such.

Both listeners bind every interface *inside the container*, where a loopback bind would be
unreachable even through a published port. Which of them the outside world can reach is
decided by the compose file's publish addresses.

## Development

```bash
make install    # virtualenv and test extras
make dev        # serve from the working copy
make test       # the suite
make check      # lint, suite, coverage gate
```

## Licence

GPL-3.0. See [LICENSE](LICENSE).

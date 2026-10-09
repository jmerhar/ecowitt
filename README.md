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
  database is down is gone for ever. Reports that cannot be written are spooled to disk and
  replayed oldest first once InfluxDB answers again — across restarts of either — so restarting
  InfluxDB costs nothing. The spool is bounded (`SPOOL_MAX_BYTES`, 100 MB by default, which is
  days of reports) and drops the oldest first when full. A report InfluxDB refuses outright,
  such as one with a field-type conflict, is set aside in `data/spool/rejected/` rather than
  retried for ever.
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

Set `INFLUX_URL` and a token in the environment (see [Configuration](#configuration)). Then, on
the console — *Menu → Weather Services → Customized*:

| Field | Value |
|---|---|
| State | Enable |
| Protocol Type | Same As Ecowitt |
| IP / Hostname | the host running this |
| Port | `2551` |
| Path | `/data/report/` |
| Interval | see below |

Open <http://127.0.0.1:2552/setup>. Within one upload interval the console appears under
*Stations reporting, not configured*, by model and fingerprint; give it a name and adopt it.
Its PASSKEY — the credential every upload carries — is copied into the configuration without
ever being shown. From then on its reports are stored; there is nothing to restart.

On the same page: the altitude (looked up from coordinates if you give them — or from the
location of the device you are using, when you are at the station), what each sensor is called, the units you keep, and an optional login for these pages. The status page at
<http://127.0.0.1:2552/> shows each room's latest readings and whether airing it would help, the
wind, rain and sun, every other sensor reporting, battery states, and anything wrong with the
console's pressure calibration.

Everything the setup page writes goes to `data/config.yaml`, which can also be written by hand:

```yaml
units:            # optional; these are the defaults
  temperature: c  # c, f
  pressure: hpa   # hpa, inhg, mmhg
  rain: mm        # mm, in
  wind: kmh       # kmh, ms, mph, kn
  distance: km    # km, mi
stations:
  - name: Home
    passkey: 0123456789ABCDEF0123456789ABCDEF
    altitude_m: 180          # enables sea-level pressure
    latitude: 52.37          # optional; enables the absolute-pressure check
    longitude: 4.90
    sensors:                 # display names; anything unnamed keeps its identifier
      indoor: Lounge
      ch1: Bathroom
```

Restart the container after editing it by hand. Saving from the setup page rewrites the file
whole, so comments added by hand do not survive a save.

## Pressure calibration

Consoles have two pressure settings, and they are easy to confuse. The **absolute** one corrects
the barometer itself; a good barometer needs none. The **relative** one turns absolute pressure
into the sea-level pressure forecasts quote. Some firmware takes the relative one as an offset in
hPa; others — the HP2551 among them — take an *Altitude for REL* and compute it, and set the
absolute reading directly with an *ABS Barometer* field.

The status page checks both, and says what to change:

- **Relative**: the console's relative pressure against this server's own reduction of the
  absolute reading for the station's altitude.
- **Absolute, sudden**: a jump in absolute pressure faster than any weather — almost always
  someone changing the absolute calibration when they meant the relative one.
- **Absolute, constant**: for a station with coordinates, the absolute reading against a weather
  model's surface pressure there ([Open-Meteo](https://open-meteo.com)), refreshed every half
  hour.

The stored sea-level pressure (`pressure.sea_hpa`) is computed here from the absolute reading and
the altitude, so it is right whatever the console's relative setting says.

Coordinates are sent to public services, and only when you enter them: to OpenTopoData or
Open-Elevation when you look up an altitude, and to Open-Meteo for the absolute check.

## Two ports, and why it matters

The station speaks **plain HTTP and follows no redirects**, so its endpoint cannot sit behind
TLS or an authenticating proxy. That endpoint is therefore the one thing exposed, and it is
exposed on its own listener:

| Listener | Default publish | Serves |
|---|---|---|
| ingest | `0.0.0.0:2551` | the configured path, and nothing else |
| admin | `127.0.0.1:2552` | status and setup pages, read API, health |

The admin routes are not merely *refused* on the ingest listener — they are not mounted on it,
so no mistake in a guard can expose them. Ask the ingest port for the status page and it
answers `404`, because there is nothing there.

Keep the admin listener on loopback and reach it through a reverse proxy. It can have a login of
its own, set on the setup page (HTTP Basic, stored as a salted scrypt hash); use it, or a proxy
that requires one, if anyone you do not trust can reach these pages. Every form on them is
protected against submission from other sites.

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

## What gets stored

One InfluxDB database (`weather` by default), with a table per kind of sensor. Every row
carries a `station` tag; rows describing a sensor you might name — a room, a soil bed — also
carry `sensor` (a stable identifier such as `indoor` or `ch3`, which joins a room's rows across
tables) and `name` (its display name).

| Table | Holds |
|---|---|
| `indoor`, `outdoor`, `channel` | temperature and humidity, as reported |
| `pressure` | absolute and relative pressure as reported; sea-level pressure and the console's calibration error, derived |
| `wind`, `rain`, `solar` | as reported; `rain` is tagged `gauge=bucket` or `gauge=piezo` |
| `derived` | per sensor: dew point, absolute humidity, mixing ratio, vapour pressure deficit, and how long its values have been unchanged |
| `ventilation` | per indoor sensor: dew-point difference from outdoors, and the humidity the room would settle at after airing |
| `battery` | per sensor, in whichever form that sensor reports: a low flag, a voltage or a level |
| `station` | the console's model, firmware, uptime, upload interval and clock skew |
| `soil`, `soil_ec`, `pm`, `air`, `lightning`, `leak`, `probe`, `leaf`, `depth` | only when those sensors report |
| `unmapped` | any field this server does not recognise, under its original name |

Field names carry their unit — `temp_c`, `abs_hpa`, `speed_kmh` — so a change of preference
starts new fields rather than mixing units in one series. Renaming a sensor likewise starts new
series under the new name, so group by `sensor` in dashboards and use `name` for labels.

Retention is whatever the database was created with, and InfluxDB 3 cannot change it later.
Create it before first use if you want anything other than keeping everything.

## Grafana dashboard

[`grafana/weather.json`](grafana/weather.json) is a dashboard for InfluxDB 3:

- current outdoor conditions;
- whether airing would dry or dampen each room: its dew point against the outdoor one, and
  the humidity it would settle at;
- indoor humidity, temperature, dew point and absolute humidity, room by room;
- outdoor temperature, humidity, wind, pressure, rain and sun;
- battery flags, sensors that have stopped changing, and the console's pressure calibration.

To install it, add an InfluxDB data source with query language **SQL**, the database this server
writes to, and a token that can read it (`influxdb3 create token --permission
"db:weather:read" --name grafana`). Then import the file under *Dashboards → New → Import* and
choose that data source. It expects a data source named `weather` and offers a choice of the
others.

Its queries name fields in the default units (°C, hPa, km/h, mm). If you store other units,
change the field names in the queries to match.

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
| `INGEST_HOST` / `INGEST_PORT` | `0.0.0.0` / `2551` | inside the container; keep the port equal to the published one |
| `ADMIN_HOST` / `ADMIN_PORT` | `0.0.0.0` / `2552` | same |
| `INGEST_RATE` / `INGEST_BURST` | `2` / `20` | requests per second per address, and the burst before that applies |
| `DATA_DIR` | `/data` | holds `config.yaml` and the spool |
| `SPOOL_MAX_BYTES` | `104857600` | most the spool keeps while InfluxDB is unreachable |
| `LOG_LEVEL` | `INFO` | |

Everything describing *your* stations — units, sensor names, the `PASSKEY` allowlist, the
altitude — is in `data/config.yaml`, shown above. Sensor names and altitude are per station,
because `ch1` at one house is not `ch1` at another; units are shared, so one database never
holds two stations in different units. A malformed file stops the server from starting, with
the reason, rather than letting it run and discard every report.

Both listeners bind every interface *inside the container*, where a loopback bind would be
unreachable even through a published port. Which of them the outside world can reach is
decided by the compose file's publish addresses.

## Development

```bash
make install    # virtualenv and test extras
make dev        # serve from the working copy
make test       # the Python suite
make test-js    # the page scripts' suite, with coverage (needs Node 22 or later)
make check      # lint, both suites, coverage
```

## Licence

GPL-3.0. See [LICENSE](LICENSE).

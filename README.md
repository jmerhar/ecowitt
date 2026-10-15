# Ecowitt Server

[![Test and Publish](https://github.com/jmerhar/ecowitt/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/jmerhar/ecowitt/actions/workflows/build-and-push.yml)
[![codecov](https://codecov.io/gh/jmerhar/ecowitt/branch/main/graph/badge.svg)](https://app.codecov.io/gh/jmerhar/ecowitt)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

An Ecowitt weather station can upload to a server of your choosing, every few seconds, for
free — no cloud account, no rate limit, no retention policy you do not control. What it cannot
do is store any of it. Point the console at **Ecowitt Server** and every value it reports lands in
InfluxDB, in the units you asked for, alongside the quantities the station does not send but
the data is useless without.

<sub>An independent project, not affiliated with or endorsed by Ecowitt. "Ecowitt" names the
hardware it talks to.</sub>

## What it does

- **Receives what the console sends**, over the Ecowitt protocol ("Same As Ecowitt"), and
  stores all of it. Unrecognised fields are stored too, under their original
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
- **Shows it to anyone, if you want.** An optional dashboard — its own container — serves a
  page with current conditions, charts from a day to a year and records, from a read-only
  token, and a JSON API another client can use.
- **Tells stable apart from dead.** Consoles repeat a sensor's last value when its radio goes
  quiet, which looks exactly like a sensor that is not changing. Every reading carries how
  long it has been identical.

## Running it

```bash
mkdir -p ecowitt/data && cd ecowitt
curl -O https://raw.githubusercontent.com/jmerhar/ecowitt/main/docker-compose.yml
docker compose up -d
```

One file is all it takes; there is nothing to clone, build or edit. Everything else is set in
the browser.

- **`data` is created first** because Docker would otherwise create it as root.
- **The container runs as user 1000:1000.** If that user cannot write `data`, put
  `ECOWITT_UID=$(id -u)` and `ECOWITT_GID=$(id -g)` in a `.env` file beside the compose file
  first. Every other environment setting is optional; they are in
  [Configuration](#configuration).

Then, on the console — *Menu → Weather Services → Customized*:

| Field | Value |
|---|---|
| State | Enable |
| Protocol Type | Same As Ecowitt |
| IP / Hostname | the host running this |
| Port | `2551` |
| Path | `/data/report/` |
| Interval | see below |

Open <http://127.0.0.1:2552/> on the host running the server; a fresh install opens on the setup
page. From another machine, use a reverse proxy (see [Two ports](#two-ports-and-why-it-matters))
or a tunnel, `ssh -L 2552:127.0.0.1:2552 that-host`.

First, the **database**: choose InfluxDB 3 or InfluxDB 2.x and enter its URL, database (or bucket
and organisation) and a token that may write to it; *Test connection* checks all of that without
writing anything. Until a database is set, reports are kept on disk and written once it is. On
InfluxDB 3 Enterprise a write-only token for one database is
`influxdb3 create token --permission "db:weather:read,write" --name ecowitt`; InfluxDB 3 Core
issues only admin tokens.

Within one upload interval the console appears under
*Stations reporting, not configured*, by model and fingerprint; give it a name and adopt it.
Its PASSKEY — the credential every upload carries — is copied into the configuration without
ever being shown. From then on its reports are stored; there is nothing to restart.

On the same page: the altitude (looked up from coordinates if you give them — or from the
location of the device you are using, when you are at the station), the time zone (taken from the
coordinates offline unless you enter one), what each sensor is called, the units you keep, and an
optional login for these pages. The status page at <http://127.0.0.1:2552/> is for checking
that everything works: reports arriving, writes reaching the database, anything waiting in the
spool, the heartbeat, and the station settings sent for the dashboard — with a banner when a
station stops reporting or a backlog builds. Per station it shows the console's model, firmware,
interval and clock, each sensor's latest readings, how long they have been unchanged and its
battery, the wind, rain and sun, keys the server does not recognise, every value of the latest
report as stored, and anything wrong with the console's pressure calibration.

Everything the setup page writes goes to `data/config.yaml`, which can also be written by hand.
It holds the PASSKEYs and the database token, so it is readable by its owner only:

```yaml
store:            # the database; the setup page writes this section
  kind: influx3   # influx3, influx2
  url: http://influxdb:8181
  database: weather   # influx2: the bucket, plus an org: setting
  token: apiv3_...
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
    timezone: Europe/Amsterdam   # optional; taken from the coordinates if left out
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
  model's surface pressure there, from the [model values](#weather-model) stored beside its
  readings.

The stored sea-level pressure (`pressure.sea_hpa`) is computed here from the absolute reading and
the altitude, so it is right whatever the console's relative setting says.

Coordinates are sent to public services, and only when you enter them: to OpenTopoData or
Open-Elevation when you look up an altitude, and to Open-Meteo for the weather model.

### Weather model

For each station with coordinates, the server stores a weather model's view of the same place in
the `model` table, from [Open-Meteo](https://open-meteo.com): temperature, humidity, dew point,
wind, surface and sea-level pressure, precipitation, radiation, UV, cloud cover and the weather
code, every 15 minutes. Side by side with the station's own readings it shows a sheltered vane, a
thermometer in the sun or a gauge that has stopped tipping, and it supplies what a station cannot
measure.

Open-Meteo adjusts temperature and pressure to the station's altitude, so set the altitude before
comparing. A station is fetched back 7 days when first seen, and after a change of coordinates,
altitude or model; after that each fetch picks up where the last one that answered left off, so
an outage of up to a week leaves no gap. The free service allows 10,000 calls a day for
non-commercial use; a station costs about 140.

Each station's *Weather model* on the setup page chooses the model, or turns it off (which also
turns off the absolute-pressure check). The default, *Best for this location* (`best_match`),
takes the best Open-Meteo has for the location; naming one keeps the reference from changing
character when that choice does. Any other model Open-Meteo serves can be named as
`weather_model` in `config.yaml`. Rows are tagged with the model, so changing it starts new
series.

The status page shows each station's latest model values beside its own readings, with the
difference: a vane pointing the wrong way or a thermometer in the sun stands out there first.

#### Forecast

Ticking *Store the model's forecast too* on the setup page stores the model's forecast for the
next 7 days as well, fetched hourly, for the [public dashboard](#public-dashboard) and the
[Grafana dashboard](#grafana-dashboard) to show. It is off by default, because it needs
**InfluxDB 3 Enterprise** (free for home use), or InfluxDB 3 Core started with a
`--query-file-limit` far above its default of 432. Each fetch writes to every hour of the coming
week; Enterprise compacts the files that leaves, but Core does not, and within a day it refuses
to read the forecast back. The opt-in is stored as `weather_forecast` in `config.yaml`. A fetch
costs one Open-Meteo call, about 24 a day.

### Wind at 10 m

Forecasts, weather models and official stations give wind at 10 m above open ground. A garden
anemometer lower down reads less, often half as much, so beside every measured wind the server
stores an estimate at 10 m in the `wind_10m` table, which the dashboards show first.

Set each station's *Anemometer height* (above the ground, a roof's height included) and
*Surroundings* on the setup page; the page shows the factor they give. Measured wind is scaled
by the neutral logarithmic wind profile, ln(10 / z0) / ln(h / z0), with roughness length z0 of
0.1 m in the open, 0.3 m among gardens and 0.5 m where buildings and trees are close: ×1.54,
×1.85 and ×2.16 at 2 m. *No correction*, the default, stores the measured wind unchanged.

The estimate holds in daylight and in a breeze. On still nights the air near the ground
decouples from the wind above and cups below about 1 m/s stop turning; while they do, and the
station has a [weather model](#weather-model), the estimate is the model's 10 m wind, and the
row's `source` is `model`. Untick *Use the weather model's wind while the cups are too slow to
turn* to keep the stalled reading, scaled, instead. A changed height or surroundings applies to
readings from then on.

To bring the history in line, *Recompute the 10 m wind* on the setup page recalculates it with
the saved factor, from a chosen moment in the station's time or, left empty, from the first
reading. It runs in the background, with its progress on the status page, and needs a database
the server can read back (InfluxDB 3) with a token allowed to read. Readings before the chosen
moment keep their values, so after moving the anemometer give the moment it was moved.

The dashboard leads with the 10 m figures -- speed, gusts, the Beaufort force, which is defined
at 10 m, and the strong-gust warning -- marking an estimate as one, with what the sensor
measured beneath it and faint behind the speed in the wind chart. A visitor can choose *Wind at:
The sensor* in its *Units* menu to swap the two on the wind card, chart and records; the
strong-gust warning stays at 10 m. The choice is kept in that browser.

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

The admin listener answers only to the host names in `ADMIN_HOSTS` — by default `localhost`,
`127.0.0.1` and `::1` — and refuses any other with `421`, so a hostile web page cannot point its
own domain at this address and drive the setup page from your browser. Behind a reverse proxy, add
the name the proxy serves it under: `ADMIN_HOSTS=localhost,127.0.0.1,::1,weather.example`.
`/healthz` answers under any name.

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
| `wind_10m` | the wind estimated at the standard 10 m (see [Wind at 10 m](#wind-at-10-m)): speed, gust, 10-minute average speed and the day's strongest gust, and `source`, `sensor` or `model` |
| `derived` | per sensor: dew point, absolute humidity, mixing ratio, vapour pressure deficit, and how long its values have been unchanged |
| `ventilation` | per indoor sensor: dew-point difference from outdoors, and the humidity the room would settle at after airing |
| `battery` | per sensor, in whichever form that sensor reports: a low flag, a voltage or a level |
| `station` | the console's model, firmware, uptime, upload interval and clock skew |
| `model` | per located station, a weather model's values every 15 minutes, tagged `source` and `model`; see [Weather model](#weather-model). Precipitation (`precip_15m_mm`) is the 15 minutes ending at the row's time |
| `forecast`, `forecast_daily` | per station storing its weather model's [forecast](#forecast), its forecast for the next 7 days, hour by hour and by local day, fetched hourly. Each row's time is the hour or day forecast; its `lead` tag says how many hours (or days) ahead it was made, so the newest forecast for a time has the smallest lead, and forecasts made at each distance ahead are kept |
| `station_info` | each station's settings: coordinates, altitude, time zone, stored units, sensor names and the weather model it uses. Written at startup and when the configuration changes them, never otherwise; read the newest row as a whole |
| `soil`, `soil_ec`, `pm`, `air`, `lightning`, `leak`, `probe`, `leaf`, `depth` | only when those sensors report |
| `unmapped` | any field this server does not recognise, under its original name |

Field names carry their unit — `temp_c`, `abs_hpa`, `speed_kmh` — so a change of preference
starts new fields rather than mixing units in one series. Renaming a sensor likewise starts new
series under the new name, so group by `sensor` in dashboards and use `name` for labels.

Retention is whatever the database was created with, and InfluxDB 3 cannot change it later.
Create it before first use if you want anything other than keeping everything.

## Grafana dashboard

[`grafana/weather.json`](grafana/weather.json) is a dashboard for InfluxDB 3:

- the alerts firing or pending from the [alert rules](#grafana-alerts);
- current outdoor conditions;
- whether airing would dry or dampen each room: its dew point against the outdoor one, and
  the humidity it would settle at;
- indoor humidity, temperature, dew point and absolute humidity, room by room;
- outdoor temperature, humidity, wind, pressure, rain and sun, each with the
  [weather model](#weather-model)'s value dashed behind it;
- the outdoor temperature and wind direction minus the model's, with the band within which a
  difference is usual shaded;
- for a station storing it, the model's [forecast](#forecast): temperature and dew point, rain and its chance, wind, humidity and cloud
  cover for the next 48 hours, whatever time range is chosen, and a table of the next 7 days
  with each day's mean humidity;
- battery flags, rooms and outdoor sensors that have stopped changing, the console's pressure
  calibration, and the station's settings as last published (time zone, coordinates, altitude,
  stored units).

Two links at the top, *Station time* and *My time*, reopen it with times shown in the station's
time zone or in your browser's, keeping the station and the time range.

To install it, add an InfluxDB data source with query language **SQL**, the database this server
writes to, and a token that can read it (`influxdb3 create token --permission
"db:weather:read" --name grafana`). Then import the file under *Dashboards → New → Import* and
choose that data source. It expects a data source named `weather` and offers a choice of the
others.

Its queries name fields in the default units (°C, hPa, km/h, mm). If you store other units,
change the field names in the queries to match.

## Grafana alerts

[`grafana/alerts.json`](grafana/alerts.json) holds alert rules in Grafana's provisioning format,
one alert per room or station (*Close the windows* is one per station):

| Rule | Fires when | Severity |
|---|---|---|
| Good time to air | a room is at 65% humidity or more and the outdoor dew point is more than 2 °C below the room's, for 15 minutes | info |
| Close the windows | airing would leave the rooms at a median of 65% humidity or more, and at least 5 points damper than they are (less is within the sensors' error), for 30 minutes, while no room would be dried by airing: the advice the dashboard gives | info |
| Damp room | a room has not dropped below 70% humidity in 6 hours | warning |
| Sensor not updating | a room or outdoor sensor's readings have not changed, or not arrived, for 3 hours of the station's reports | warning |
| Battery low | a sensor's low-battery flag has been set for an hour | warning |
| Room too cold / too hot | a room is below 8 °C or above 32 °C for 15 minutes | warning |
| Strong wind | a gust above 60 km/h at 10 m (see [Wind at 10 m](#wind-at-10-m)) in the last 10 minutes | info |
| Heavy rain | a rain rate above 10 mm/h in the last 10 minutes | info |
| Pressure falling fast | sea-level pressure more than 3 hPa lower than 3 hours ago | info |

- The rules read the data source whose uid is `weather`. Give yours that uid, or replace it in
  the file before loading it.
- Load the file through Grafana's file provisioning or its alerting API.
- Routing is yours to set up. Every rule carries the labels `app=ecowitt` and `severity`
  (`warning` or `info`, the second suiting quiet hours); *Good time to air* also carries
  `resolve_message=off`, for a contact point that sends no message when the window closes, and
  so does *Close the windows*. *Damp room* and both airing rules carry `notify=daily`: they
  describe the house over hours, so a message each time another room joins is noise -- route
  them with a long group interval and a 24-hour repeat interval, so a room that turns damp while
  others still are waits for a later message.
- Each rule's `summary` annotation is a complete sentence, ready to send as the notification.
  Rules with an alert per room also have a `headline`, the same for every room, and an `item`
  naming the room: a message about several rooms reads better as the headline once and an item
  per room.
- The weather rules (both airing rules, wind, rain, pressure) keep firing for 30 minutes, or an
  hour for pressure, after their condition clears, so a value hovering at a threshold does not
  send a stream of firing and resolved messages.
- *Sensor not updating* counts a sensor's age against the station's last report, so a station
  that stops uploading does not flag every sensor; watch the station itself with the heartbeat.
  A sensor silent for more than 7 days drops out of the rule.
- A query that fails raises Grafana's own *DatasourceError* alert, with the rule's labels.
- Like the dashboard, the queries name fields in the default units.

## Public dashboard

The dashboard is a second, optional container: a page anyone can be given the address of, and the
read-only JSON API it is built on. It reads InfluxDB with a token that can only read, and never
talks to the server's own listeners, so publishing it changes nothing about who can reach
those.

The page shows a station at a glance — temperature with what it feels like and today's range,
humidity and dew point as bars coloured by level (dry to very humid; crisp to oppressive),
wind on a compass, rain, pressure and its three-hour trend, sunrise and sunset, each room with
whether airing it would help, and any sensor that needs attention — then charts over the last 1,
3, 6 or 12 hours, a day, a week, a month or a year, and the highs and lows of today, this month or this year. A card with
something to act on is edged in colour and says what: cold (5 °C or below) or heat, very humid or
very dry air, strong gusts, heavy rain, pressure falling fast, very high UV, a room that is cold,
hot, damp or dry, a good time to air the house or one to keep its windows closed (when airing
would leave the rooms at 65% or more and damper than they are), a sensor that needs attention —
the thresholds of the [Grafana alerts](#grafana-alerts) where there is one. Visitors choose their own units; times are in the station's time zone.

For a station storing its model's [forecast](#forecast), the page shows it — the next 24 hours
and the days ahead — and the cards say what is coming within the day: rain likely within six
hours, frost or heat, strong gusts, and drier air to open the windows for. For a station with a
[weather model](#weather-model), it also shows the sky the model gives — clear,
overcast, rain, fog — with an icon from [Meteocons](https://meteocons.com), and the charts can
draw the model's values dashed beside the station's (*Model*, beside the range). The page credits
Open-Meteo, as its data's licence asks, and lists the licences of what it bundles at
`/licenses.md`.

Served over HTTPS, the page can be added to a phone's or tablet's home screen (*Add to Home
screen* or *Install app* in Chrome, *Share → Add to Home Screen* on an iPhone or iPad), where it
opens as an app of its own, named for the site's title. Its icon is drawn in
`dashboard/web/icons/app-icon.svg`; `make app-icons` renders the PNGs after a change.

**Setting it up**

1. Create a token that can only read the database:
   `influxdb3 create token --permission "db:weather:read" --name dashboard`.
2. Start it: `docker compose --profile dashboard up -d`. It listens on `127.0.0.1:2553`.
3. Open `http://127.0.0.1:2553/setup`. Enter the database connection and choose *Connect and
   load stations*; then choose which stations to show (every one, including any added later, or
   only those ticked) and a title, and *Finish setup*.

Setup writes `data-dashboard/dashboard.yaml` and the setup page disappears. **The setup page is
not protected** — whoever reaches it first configures the dashboard — so finish setup before
putting the port behind a public reverse proxy. To change the settings later, edit or delete
the file and restart the container.

**The API** is at `/api/v1`, documented at `/api/v1/docs`:

| Path | |
|---|---|
| `/meta` | the metrics, units, chart ranges and record periods on offer, and which metrics the weather model has |
| `/stations` | each station shown, with its location, time zone, stored units and weather model |
| `/stations/{id}/now` | current conditions, the sky from the weather model, today's range, rooms with airing advice, sensor health, a one-line summary |
| `/stations/{id}/series?metrics=…&range=24h` | metrics over `1h`, `3h`, `6h`, `12h`, `24h`, `7d`, `30d` or `1y`, in buckets that start at the station's midnight; `&model=true` adds the weather model's series (`source: model`) |
| `/stations/{id}/forecast` | the latest forecast from the station's weather model: the next 24 hours and the days it reaches |
| `/stations/{id}/extremes?period=today` | the lowest and highest of each metric `today`, this `month` or this `year` |

Every answer is in the station's stored units unless the request asks otherwise, per quantity:
`?temperature=f&wind=mph&pressure=inhg&rain=in`. Answers are cached for everyone alike for up to
a minute (longer for long ranges), and each visitor's address has a request budget.

| Variable | Default | |
|---|---|---|
| `PORT` | `2553` | inside the container |
| `DATA_DIR` | `/data` | holds `dashboard.yaml` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | reverse proxies whose `X-Forwarded-For` is believed — name yours, or every visitor shares one budget; `*` lets a visitor claim any address |
| `RATE` / `BURST` | `5` / `60` | requests per second per visitor, and the burst before that applies |
| `LOG_LEVEL` | `INFO` | |

The compose file publishes it at `DASHBOARD_BIND:DASHBOARD_PORT` (`127.0.0.1:2553`) and passes
`DASHBOARD_FORWARDED_ALLOW_IPS` through. The dashboard reads InfluxDB 3 only; reading an
InfluxDB 2.x bucket is [planned](TODO/influxdb2-reads.md).

## Configuration

The environment holds only how the process runs -- ports, limits, logging. The database
connection and everything about the stations are set on the setup page. All of these are
optional:

| Variable | Default | |
|---|---|---|
| `INGEST_PATH` | `/data/report/` | both slash spellings are served |
| `INGEST_HOST` / `INGEST_PORT` | `0.0.0.0` / `2551` | inside the container; keep the port equal to the published one |
| `ADMIN_HOST` / `ADMIN_PORT` | `0.0.0.0` / `2552` | same |
| `ADMIN_HOSTS` | `localhost,127.0.0.1,::1` | host names the admin listener answers to; `*` for any |
| `INGEST_RATE` / `INGEST_BURST` | `2` / `20` | requests per second per address, and the burst before that applies |
| `DATA_DIR` | `/data` | holds `config.yaml`, the spool, and `secret.key`, which signs the admin forms |
| `SPOOL_MAX_BYTES` | `104857600` | most the spool keeps while InfluxDB is unreachable |
| `HEARTBEAT_URL` / `HEARTBEAT_URL_FILE` | — | a push monitor's URL, called after readings are written; see below |
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | the least time between two heartbeat calls |
| `LOG_LEVEL` | `INFO` | |
| `MODEL_INTERVAL_SECONDS` | `900` | how often a located station's model values are fetched |
| `FORECAST_INTERVAL_SECONDS` | `3600` | how often a station's weather forecast is fetched |
| `OPEN_METEO_URL`, `OPENTOPODATA_URL`, `OPEN_ELEVATION_URL` | the public services | the weather model and elevation lookups, for a mirror or an air-gapped host |

The shipped compose file passes all of these through except the last two rows, the listeners'
bind addresses and `DATA_DIR`, which the container fixes; add those to its `environment:` to
change them. It also reads a few of its own:

| Variable | Default | |
|---|---|---|
| `ECOWITT_UID` / `ECOWITT_GID` | `1000` / `1000` | the user the container runs as; it must be able to write `data` |
| `ECOWITT_INGEST_BIND` / `ECOWITT_INGEST_PORT` | `0.0.0.0` / `2551` | where the ingest listener is published |
| `ECOWITT_ADMIN_BIND` / `ECOWITT_ADMIN_PORT` | `127.0.0.1` / `2552` | where the admin listener is published |
| `TZ` | `UTC` | the container's time zone, for log timestamps |

Everything describing *your* stations — units, sensor names, the `PASSKEY` allowlist, the
altitude — is in `data/config.yaml`, shown above. Sensor names and altitude are per station,
because `ch1` at one house is not `ch1` at another; units are shared, so one database never
holds two stations in different units. A malformed file stops the server from starting, with
the reason, rather than letting it run and discard every report.

A push monitor — Uptime Kuma's *Push* type, healthchecks.io — alerts when its URL stops being
called. Set its URL as `HEARTBEAT_URL` and the server calls it after each write of a station's
readings InfluxDB accepts, at most once a minute (its own rows, the station settings and the
weather model, do not count), so the monitor alerts whenever readings stop reaching the database: the
console has stopped uploading, the server is unreachable or down, or InfluxDB is refusing writes
or unreachable. Reports held in the spool do not count until they are written. Give the monitor a
grace period of a few upload intervals.

Both listeners bind every interface *inside the container*, where a loopback bind would be
unreachable even through a published port. Which of them the outside world can reach is
decided by the compose file's publish addresses.

## Versions

Both images carry one version, listed with what changed in [`CHANGELOG.md`](CHANGELOG.md), which
also says what, if anything, to do on upgrading. Each image is published as `latest` (every change
to `main`), as each release's version (`2.8.0`) and its minor and major lines (`2.8`, `2`), and by
commit (`sha-…`). The shipped `docker-compose.yml` follows the major line, so `docker compose pull`
brings every release that keeps its settings and the stored data working; a new major is a change
to that file. The collector's status page and the dashboard's footer show the version running.

## Development

```bash
make install      # virtualenv and test extras
make dev          # serve from the working copy
make test         # the Python suites
make test-js      # the admin page scripts' suite, with coverage (needs Node 22 or later)
make web-install  # the dashboard page's dependencies, from its lockfile (needs Node 24)
make test-web     # the dashboard page: type check and tests, with coverage
make web-dev      # the dashboard page with hot reload, against a dashboard API on :2553
make check        # lint, every suite, coverage
```

The dashboard page's `package-lock.json` is written only by `make lockfile`, which installs in a
Linux container (so it records the binaries CI and the image build need) and keeps every package
on the public npm registry.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

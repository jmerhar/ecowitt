# Changelog

Every release of Ecowitt Server: the collector image (`ghcr.io/jmerhar/ecowitt`) and, from 2.1.0,
the dashboard image (`ghcr.io/jmerhar/ecowitt-dashboard`), which share one version. Versions follow
[Semantic Versioning](https://semver.org): a major release needs something done on upgrading, and
says what under *Upgrading*.

## 2.5.0 — 2026-10-13

### Added

- **Wind at 10 m**: each station's anemometer height and surroundings on the setup page give a
  factor by the logarithmic wind profile, and every report's wind is also stored in a `wind_10m`
  table, scaled by it. While the cups stall below 1 m/s, the weather model's wind can stand in (a
  per-station switch, on by default).
- The dashboard, its API and Grafana lead with the 10 m wind, with the measured wind beside it;
  the status page compares the model's wind with the 10 m estimate.
- A recompute on the setup page applies a station's factor to its stored history, from a chosen
  moment or from the first reading, with progress on the status page.

### Changed

- The *Strong wind* alert and the dashboard's strong-gust notice judge the 10 m gust, the height
  their 60 km/h threshold is meant for. A station with no height set is unaffected.
- The API's `wind.speed` and `wind.gust` series are the 10 m estimates; `wind.measured_speed` and
  `wind.measured_gust` chart the measurement.

### Upgrading

- Import `grafana/weather.json` and `grafana/alerts.json` again: both read `wind_10m`.

## 2.4.1 — 2026-10-12

### Fixed

- Keeping the windows closed was advised whenever airing would not help, even with the rooms at
  60% and airing taking them to 59%. It is advised only when airing would leave the rooms at 65% or
  more and damper than they are; the *Close the windows* alert asks the same.
- The wind and rain cards are marked by the strongest gust and heaviest rain of the last ten
  minutes, as the alerts are, instead of flickering with each report.
- The airing card says plainly what airing would do to the rooms' humidity.

### Upgrading

- Import `grafana/alerts.json` again.

## 2.4.0 — 2026-10-12

### Added

- The dashboard can be added to a phone's or tablet's home screen as an app.
- The rooms table sorts by any column, remembering the order.
- A plain click on a chart's legend entry picks out that line; Cmd or Ctrl and a click shows or
  hides it.

### Changed

- The airing card shows the rooms' humidity now and after airing in large numbers.

### Fixed

- On Safari before 17, charts answered 422 and the cards were misaligned.

## 2.3.0 — 2026-10-11

### Added

- **Weather model**: every 15 minutes, for each station with coordinates, Open-Meteo's values
  for the location are stored in the `model` table, catching up on up to a week missed. Each
  station chooses its model on the setup page (best for the location by default, a named one, or
  off).
- The status page compares the model with the station, saying which differences are beyond the
  usual; the absolute-pressure check reads the same values.
- Grafana draws the model dashed beside the station's readings, and plots the outdoor temperature
  and wind direction minus the model's.
- The dashboard shows the sky the model gives, with an icon, and its charts can draw the model's
  values dashed (*Model*). The page credits Open-Meteo and lists the licences of what it bundles.
- Weather codes are stored as integers.

## 2.2.0 — 2026-10-11

### Added

- The dashboard leads with airing advice for the whole house, and the rooms table shows the
  humidity each room would settle at if aired.
- Cards are edged and labelled when something deserves attention: frost risk from 5 °C, heat,
  very humid or dry air, strong gusts, heavy rain, pressure falling fast, very high UV, rooms that
  are cold, hot, damp or dry, and sensors needing attention. Cards, charts and highs and lows have
  icons.
- The status page is about whether everything works: the health of reports, writes, the spool,
  the heartbeat and the settings sent for the dashboard, with each console's model, firmware,
  radio band, interval and clock, and every value of its latest report.

### Changed

- The dashboard's extremes are called *Highs and lows*, with a tile per room.

## 2.1.0 — 2026-10-11

### Added

- **Public dashboard**, a second image (`ghcr.io/jmerhar/ecowitt-dashboard`): a read-only JSON API
  (`/api/v1`) over what the collector stores and a page built on it, showing a station at a glance,
  its rooms with airing advice, charts from a day to a year, and highs and lows. It is set up on a
  first-run page that writes `/data/dashboard.yaml`, and reads stations from what the collector
  publishes.
- A *Close the windows* alert, sent when airing would not dry the house.
- Alerts about several rooms state their headline once and list the rooms; *Damp room* and *Good
  time to air* are sent at most daily.
- The console's fixed sensors are named (Barometer, Rain gauge, Wind sensor) wherever no name was
  given.

### Fixed

- Alert values no longer show −99 for a room that has stopped meeting the condition.
- The rain gauge and light sensor are no longer flagged as not updating through a dry night.

## 2.0.0 — 2026-10-10

### Added

- The database is set up on the setup page: choose InfluxDB 3 or 2.x, enter its settings, test
  the connection, and save; a change applies without a restart. A fresh install opens on the setup
  page and needs nothing in its compose file.
- Each station's settings are published to the database as `station_info` rows, with a time zone
  taken offline from its coordinates unless one is entered.
- Grafana shows each station's settings, with links reopening the dashboard in the station's time
  or the browser's.

### Changed

- The spool holds rows as JSON, so a backlog survives the database being set up or changed.
- `/api/status` reports the database as `database` instead of `influx`, with secrets reduced to
  whether they are set.
- The server starts with `python -m ecowitt.collector`; the image does so already.

### Removed

- The `INFLUX_*` environment variables.

### Upgrading

- Enter the database connection on the setup page, then remove the `INFLUX_*` variables (and any
  token secret mounted for them) from the compose file. Reports received before that are kept in
  the spool and written once the database is set.
- Line-protocol files left in the spool by 1.x are set aside in `spool/rejected/`, not replayed.
- Anything reading `/api/status` reads `database` in place of `influx`.

## 1.0.0 — 2026-10-10

The first stable release.

### Added

- `ADMIN_HOSTS` names the host names the admin listener answers; any other gets 421, so a site
  cannot rebind its own domain to the admin listener.

### Changed

- The station's reply is sent before its report is handled, so a slow database no longer holds
  it, and a known PASSKEY answers no slower than an unknown one.
- The PASSKEY fingerprint shown on the setup page and in the log is keyed with the server's
  secret, so it cannot be reversed to the PASSKEY.
- The shipped container runs with a read-only root filesystem and no capabilities.

### Fixed

- Request headers and connections are bounded on both listeners.
- The spool's replay loop and the heartbeat survive unexpected errors; a malformed `INFLUX_URL`,
  or InfluxDB 2.x without `INFLUX_ORG`, stops startup with the reason.
- Admin pages cope with names and values containing quotes, line breaks, `nan` or `inf`;
  derivations ignore impossible temperatures; line breaks are kept out of line protocol.
- The shipped compose file forwards every documented setting.

### Upgrading

- Behind a reverse proxy, add the host name the admin pages are reached by to `ADMIN_HOSTS`.

## 0.6.0 — 2026-10-09

### Added

- A heartbeat: `HEARTBEAT_URL` is called after readings are written, at most once per
  `HEARTBEAT_INTERVAL_SECONDS`, so one push monitor covers the console, the server and the
  database.
- Grafana alert rules for the house and the weather: airing, damp rooms, silent sensors, low
  batteries, cold and hot rooms, strong wind, heavy rain and falling pressure. The dashboard lists
  those firing.

### Fixed

- Silent sensors stay flagged, measured against the station's last report, and the weather alerts
  no longer flap at their thresholds.

## 0.5.0 — 2026-10-09

### Added

- A Grafana dashboard for the stored readings: current conditions, airing per room, indoor and
  outdoor history, and station health.

## 0.4.0 — 2026-10-09

### Added

- The status page shows wind, rain, sun and every other sensor, not only temperature and humidity.

### Changed

- The batteries of outdoor arrays (WS69, WS80, WS90) carry `sensor=outdoor`, so they appear with
  the outdoor readings. A WS69's battery series stored before splits at this change.

## 0.3.0 — 2026-10-09

### Added

- The status and setup pages: adopt a reporting console without ever seeing its PASSKEY, edit
  names, coordinates and altitude (with an elevation lookup and the browser's location), set the
  units, and set an optional login. Changes apply without a restart.
- Pressure calibration checks with the fix for the console's own settings: relative against the
  server's reduction, absolute against sudden steps, and absolute against a weather model's
  surface pressure.

### Fixed

- The status page showed a sea-level pressure's temperature source in place of the pressure.

## 0.2.0 — 2026-10-09

### Added

- A bounded on-disk spool: reports InfluxDB cannot take are kept and replayed in arrival order,
  across restarts. Reports InfluxDB refuses outright are set aside rather than retried.

## 0.1.0 — 2026-10-09

The first release: a collector for the reports an Ecowitt console uploads.

### Added

- A public listener carrying only the upload route, rate limited per address, and an admin
  listener for status and health, in one container.
- Reports from the stations in `/data/config.yaml` are converted to the operator's units, given
  derived values (dew point, absolute humidity, airing advice, sea-level pressure, staleness), and
  written to InfluxDB 3 or 2.x.
- 415 known report keys mapped to tables and units; unknown keys are kept, not dropped.

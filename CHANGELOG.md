# Changelog

Every release of Ecowitt Server: the collector image (`ghcr.io/jmerhar/ecowitt`) and, from 2.1.0,
the dashboard image (`ghcr.io/jmerhar/ecowitt-dashboard`), which share one version. Versions follow
[Semantic Versioning](https://semver.org): a major release needs something done on upgrading, and
says what under *Upgrading*.

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

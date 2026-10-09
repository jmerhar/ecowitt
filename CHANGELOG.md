# Changelog

Every release of Ecowitt Server: the collector image (`ghcr.io/jmerhar/ecowitt`) and, from 2.1.0,
the dashboard image (`ghcr.io/jmerhar/ecowitt-dashboard`), which share one version. Versions follow
[Semantic Versioning](https://semver.org): a major release needs something done on upgrading, and
says what under *Upgrading*.

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

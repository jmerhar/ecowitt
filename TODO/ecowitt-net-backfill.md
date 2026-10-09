# Backfill from ecowitt.net

A console can upload to ecowitt.net alongside this server, and ecowitt.net keeps a history. When
this server was unreachable — the host down, the network out — those reports are lost here, since
a console never re-sends. The spool covers InfluxDB outages, not outages of this server itself.
Backfill fills such gaps from ecowitt.net's history.

## The API

`GET https://api.ecowitt.net/api/v3/device/history`, per the official documentation
(doc.ecowitt.net, "Getting Device History Data"):

- **Credentials**: `application_key` and `api_key`, created in the ecowitt.net member centre, and
  the device's `mac` (`FF:FF:FF:FF:FF:FF`). The `PASSKEY` cannot stand in for it: it is the MAC's
  MD5 hash, which does not reverse.
- **Range**: `start_date`, `end_date`; `call_back` selects field groups (`outdoor`,
  `indoor.humidity`, ...).
- **Resolution depends on age**, and so does the longest span one request may cover: 5 minutes
  for the past 90 days (a day per request), 30 minutes for a year (a week per request), 4 hours
  for two years (a month), a day for four years (a year). `cycle_type=auto` picks it from the
  span.
- **Units are request parameters** (`temp_unitid`, `pressure_unitid`, `wind_speed_unitid`,
  `rainfall_unitid`, `solar_irradiance_unitid`); asking for °C, hPa, m/s and mm gives canonical
  units directly.
- **Response**: nested groups, each field `{"unit": ..., "list": {"<epoch>": "<value>", ...}}`.

## Sketch

- **Gap detection** from InfluxDB: per station, spans in the `station` table longer than a few
  upload intervals, within the last 90 days so the 5-minute data covers them.
- **A command, not a background loop**, at least at first: `python -m ecowitt.backfill
  --station NAME --since 7d [--dry-run]`, printing the gaps found and the points it would write.
- **Through the existing data path**: map ecowitt.net's field names onto the same readings
  `parse.py` produces, then derive and write as usual, so backfilled rows get the same derived
  values, tags and units as live ones. A mapping table belongs beside `fields.py`, with a test
  that every field the API returns for the recorded fixture maps to a row.
- **Tagged as backfilled**, e.g. `source=ecowitt_net` on each row, so a 5-minute series is never
  mistaken for the console's own cadence and can be dropped and redone.
- **Never overwrites live data**: only timestamps inside a detected gap are written.

## Open questions

- How many requests a key may make per minute or day; the documentation does not say.
- How rain counters (daily, event, hourly) appear at 5-minute resolution, and whether they can be
  stored as reported or need recomputing.
- Where the MAC and API keys live: per station in `config.yaml`, entered on the setup page, with
  the keys treated like the `PASSKEY` (never logged, never returned by the read API).

## Done when

A dry run lists real gaps and the points that would fill them; a real run fills a test gap with
values that match ecowitt.net's charts, tagged as backfilled, through the normal derive path; and
the mapping is tested against a recorded API response.

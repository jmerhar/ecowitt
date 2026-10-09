# MQTT republish

Publish every accepted report to an MQTT broker, with Home Assistant's MQTT discovery messages, so
the station's sensors appear in Home Assistant without a separate integration polling anything.

## Sketch

- **Optional, off unless configured**: `MQTT_URL` (`mqtt://host:1883` or `mqtts://`),
  `MQTT_USERNAME`, `MQTT_PASSWORD` / `MQTT_PASSWORD_FILE` (the `*_FILE` convention every
  credential here follows), `MQTT_TOPIC_PREFIX` (default `ecowitt`).
- **Fed from the processed rows**, after `pipeline.process_report`, so MQTT receives the same
  values InfluxDB does: converted to the operator's units, derived quantities included, sensor
  names applied. One state topic per sensor, e.g. `ecowitt/<station>/<sensor>/state`, carrying a
  JSON object of that sensor's fields, published retained.
- **Discovery** under `homeassistant/sensor/.../config`, one entity per field, with
  `device_class`, `unit_of_measurement` and `state_class` taken from the field table's kind and
  unit. Entities group into one Home Assistant device per station. Discovery is sent on connect
  and when the configuration changes (sensor names, units), not with every report.
- **Never in the ingest path's way.** Publishing runs on its own task with a small bounded
  queue; a broker that is down or slow drops the newest messages and logs once, and ingest and
  InfluxDB writes carry on. No spool: a retained state topic only ever needs the latest value.
- **Availability** via an MQTT last-will on `ecowitt/<station>/availability`, and a staleness
  rule: a sensor whose readings stop arriving goes `unavailable` rather than showing its last
  value forever.

## Open questions

- Client library: an asyncio client (e.g. `aiomqtt`) fits the single event loop; check it is
  maintained and supports Python 3.14.
- Whether text fields (`model`, `stationtype`) are worth exposing, or only measurements.
- Entity IDs must survive a sensor rename, so they key on the `sensor` tag, never on its name.

## Done when

With the variables set, every sensor appears in Home Assistant under one device per station,
values update with each report in the configured units, a broker outage never delays ingest, and
the tests cover publishing against a stand-in broker the way the writer's tests use a stand-in
InfluxDB.

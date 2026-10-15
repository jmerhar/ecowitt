# TODO

Planned work, one note per item. Each note says what the feature is for, sketches a design that
fits the existing code, and lists what is still undecided. Delete a note when its feature ships.

| Note | In short |
|---|---|
| [MQTT republish](mqtt-republish.md) | publish each report to an MQTT broker, with Home Assistant discovery |
| [Backfill from ecowitt.net](ecowitt-net-backfill.md) | fill outage gaps from the history ecowitt.net keeps |
| [Sun position](sun-position.md) | sunrise, sunset, sun elevation and clear-sky radiation per station |
| [Model disagreement alert](model-disagreement-alert.md) | alert when a station's readings stay far from its weather model's |
| [Reading from InfluxDB 2.x](influxdb2-reads.md) | let the dashboard read a station stored in an InfluxDB 2.x bucket |
| [Wind factor from the model](wind-factor-from-model.md) | suggest each station's 10 m wind factor from its own wind against the model's |
| [Forecast in the charts](forecast-in-charts.md) | carry the charts' lines past now as a dashed forecast |
| [More languages](more-languages.md) | the dashboard in German, Spanish, French, Dutch and more, for a wider audience |

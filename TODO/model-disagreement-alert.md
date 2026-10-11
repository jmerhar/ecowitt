# Alert on a station that disagrees with its weather model

A Grafana alert for a station whose readings stay beyond the usual distance from its weather
model's: the bounds the status page judges by (`collector/.../admin/modelcompare.py`) and the
station-minus-model panels shade, held for hours rather than for one comparison.

## Why

The status page and the dashboard show a disagreement only to someone looking. A vane pointed the
wrong way, a thermometer screen in afternoon sun or a gauge that has stopped tipping can go
unnoticed for weeks, and every reading stored meanwhile is wrong.

## Sketch

- **Rules beside the others in `grafana/alerts.json`**, one per station: temperature more than
  3 °C from the model's, and wind direction more than 60° from it while the model has 3 m/s of
  wind, each for several hours. Shared thresholds are pinned by tests, as the other rules' are.
- **Severity warning**, sent once a day like *Damp room*: nothing breaks, but the data is wrong.

## Open questions

- How long a disagreement must last, and how much of it: a few weeks of stored model values will
  show how often a well-sited sensor leaves the band, and for how long.
- Whether humidity and pressure deserve rules of their own: pressure is checked already, on the
  status page's calibration warning.

## Done when

A station whose temperature or wind direction stays well away from the model's raises one alert
a day, and a well-sited one never does.

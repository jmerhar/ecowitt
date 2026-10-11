# Public weather data

A weather model's view of each station's location, stored beside the station's own readings
(the `model` table, written by `collector/.../admin/modelfeed.py`; see the README's *Weather
model*). What is left is showing it.

## Decided

- **Model**: Open-Meteo's `best_match`, overridable with `OPEN_METEO_MODEL` and recorded in a
  `model` tag. Models disagree by several degrees and on the weather code at the same place, so
  the comparison catches gross faults (a vane pointing the wrong way, a thermometer in the sun, a
  gauge that has stopped), and the most local model is the best reference for that.
- **Altitude**: Open-Meteo's `elevation` parameter adjusts temperature and pressure to the
  station's altitude; no correction of our own on top.
- **History**: 7 days on first sight and after a change of place or model; each later fetch
  starts where the last one that answered ended.
- **Dew point**: Open-Meteo's own; computed from its temperature and humidity it agrees to 0.1 °C.

## Still to do

- **Grafana**: model series dashed behind the station's in the outdoor panels; a "station minus
  model" panel for temperature and wind direction (the direction difference wrapped to ±180°).
- **Dashboard API**: `now.sky` (weather code in words, day or night, cloud cover) from the newest
  model row, empty when that row is over an hour old; the summary line opens with it; `/series`
  can add the model's series for the metrics it has.
- **Dashboard page**: a weather icon in the Now card -- Meteocons (MIT), only the icons used,
  vendored with their licence unless a package passes the 14-day rule -- and dashed model lines in
  the charts behind a "Show model" toggle.
- **Later**: an alert for a station disagreeing with the model for hours, once a few weeks of data
  show what disagreement is normal.

## Done when

The dashboard and Grafana draw model and station together, and the page headlines the sky.

# Alert on a station that disagrees with its weather model

A Grafana alert for a station whose readings stay beyond the usual distance from its weather
model's: the bounds the status page judges by (`collector/.../admin/modelcompare.py`) and the
station-minus-model panels shade, held for hours rather than for one comparison. It goes to
whoever runs the server, not to the household the other alerts are for.

## Why

The status page and the dashboard show a disagreement only to someone looking. A vane pointed the
wrong way, a thermometer screen in afternoon sun or a gauge that has stopped tipping can go
unnoticed for weeks, and every reading stored meanwhile is wrong.

## Sketch

### The rules

Two rules in `collector/src/ecowitt/collector/grafana/alerts.template.json`, beside the others,
each one alert per station, regenerated into `grafana/alerts.json` with `make grafana`:

- **Thermometer:** the station's outdoor temperature minus its model's, averaged over 12 hours,
  beyond ±3 °C. Station and model are joined per time bucket, as the dashboard's
  *Temperature: station minus model* panel does.
- **Wind vane:** the station's ten-minute direction minus the model's, the short way round,
  averaged as an absolute angle over 24 hours, counting only the hours when the model has at
  least 3 m/s of wind; beyond 60°. The same comparison as the *Wind direction: station minus
  model* panel.
- **Enough data to judge:** each query yields a row only with most of its window covered (say 8
  of 12 hours; 6 windy hours), so a gap or a calm day cannot fire it.
- **The station's model:** each compares with the model the station's settings name
  (`station_info`'s newest `weather_model`), so the hours after a change of model, when the
  `model` table holds both, are not compared against the old one.
- **Units:** written with the template's placeholders (`%{temp_c}`, `%{3 temperature_delta}`,
  `%{10.8 speed}`), so the rules follow the units a collector stores and the Grafana page pushes
  them like the others.
- **Labels:** severity `warning`, `notify=daily` (one message a day while it lasts), and
  `audience=operator` -- see routing below.
- **Messages:** say what to check, for example "Home's outdoor temperature has averaged 4.1 °C
  above the weather model's for 12 hours: check the thermometer and its screen (afternoon sun, a
  wall close by, a failing sensor)."

### Routing: a label for the operator

The rules carry `app=ecowitt` and `severity` today, and the README leaves routing to whoever runs
Grafana, with labels to route by (`notify`, `resolve_message`). A new label, `audience=operator`,
marks an alert about the server and its sensors rather than about the house: a deployment that
sends house alerts to a household group can send these to its operator instead. *Sensor not
updating* and *Battery low* carry it too, since a silent sensor or a flat battery is the
operator's to fix. The README's routing section describes the label; existing deployments add a
route matching it above the one for `app=ecowitt`.

### One set of bounds

The status page, the dashboard panels' shaded bands and the rules use the same bounds:
`modelcompare.TEMPERATURE_C` (3 °C), `DIRECTION_DEG` (60°) and `WIND_JUDGED_FROM_MS` (3 m/s,
10.8 km/h). A test in `collector/tests/grafana` pins the rules' and the panels' numbers to those
constants, so changing one fails until all agree.

### Why 12 and 24 hours

Six days of a well-sited station against its model, as hourly means:

| | Temperature, station minus model | Wind direction, model at 3 m/s or more |
|---|---|---|
| Typical | mean -0.8 °C | median 8° |
| Extremes | -3.6 to +3.7 °C | 46° at most |
| Beyond the bound | 7 of 146 hours; 3 hours at most in a row | none of 65 hours |
| Worst average | 3.3 °C over 3 h, 2.9 °C over 6 h, 2.2 °C over 12 h | -- |

A 6-hour window comes within 0.1 °C of firing on a station with nothing wrong; 12 hours leaves a
margin while a constant offset, or sun on the screen every afternoon, still shows within the day.
Direction has a wide margin, so a 24-hour window mainly gathers enough windy hours.

## Open questions

- Whether 12 and 24 hours hold through the year: six days of October say little about summer
  afternoon sun on a screen. Revisit after a few weeks of stored model values.
- Whether humidity (the status page's bound is 15 points) and wind speed deserve rules of their
  own. Low wind speed is normal for a sheltered anemometer, so a speed rule would need the
  station's 10 m factor; pressure is checked already, by the status page's calibration warning.

## Done when

A station whose temperature or wind direction stays well away from the model's raises one alert
a day to the operator, and a well-sited one never does; *Sensor not updating* and *Battery low*
carry `audience=operator` as well.

# Forecast in the charts

Carry the charts' lines past "now" as a dashed forecast for the hours ahead, so a temperature,
wind or rain chart shows where the weather is heading as well as where it has been.

## Why

The forecast section gives the coming hours as numbers; a line that continues the measured one
shows the change at a glance -- the evening's drop in temperature, the wind picking up at noon --
on the same axes as the day so far.

## Sketch

- **Data**: the newest stored forecast (`forecast` table, the smallest `lead` per hour, read as
  `dashboard/.../forecast.py` does), for the metrics it has: temperature, dew point, humidity, wind
  speed and gust, precipitation.
- **API**: `/series` takes `forecast=true` and adds each metric's forecast as a series with
  `source: forecast`, hourly, from the hour under way to the end of the chart's range ahead -- the
  same span forward as the range shows back, capped at the forecast's 7 days.
- **Page**: the chart's time axis runs past "now", with a faint vertical line at the present; the
  forecast is dashed in the metric's colour, like the model's lines. Offered on the shorter ranges
  (up to the week), where a forecast is worth reading.

## Open questions

- Whether the chart should always extend into the future, or only when asked (a toggle like
  *Model*); always is simpler to read, but shifts what "Day" means.
- Rain: the forecast's hourly amounts against the gauge's running daily total need one scale.

## Done when

The day and week charts can show the forecast continuing each line past now, dashed, without
changing what the past part shows.

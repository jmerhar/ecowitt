# Wind factor measured against the weather model

Suggest each station's 10 m wind factor from its own data, beside the one its anemometer height
and surroundings give, with a button on the setup page to use it.

## Why

The height-based factor (`core/.../windheight.py`) knows the anemometer's height and a rough class
of surroundings, but not the building or hedge a few metres upwind. A station with a weather model
already stores both its measured wind and the model's 10 m wind every 15 minutes, so the factor
that best lines the two up is there to be read. On the first station it came out at x2.0-2.6 in
daytime against x2.16 from its height and surroundings.

## Sketch

- **Measured, not modelled, conditions only.** Over the last 14 days, take quarter-hours in
  daylight (the sun above the horizon, from `dashboard/.../sun.py` or the model's `is_day`) with
  the model's wind at least 3 m/s and the cups turning (measured at least 1 m/s, so the model's
  stand-in rows never feed it). At night the air near the ground decouples from the wind above and
  no single factor fits; the first station's night ratio was a tenth of its daytime one.
- **The factor** is the median of model speed / measured speed over those quarter-hours, from the
  `wind` table (never `wind_10m`, which already carries a factor). Shown only once there are
  enough of them -- say 100, a day or two of breezy daylight -- with how many it rests on.
- **Where it is computed**: the collector, which can read its database (`Reader.points`, as the
  recompute does), on a slow cycle or when the setup page opens. Requires a readable database and
  a weather model; the page says which is missing otherwise.
- **Using it**: an explicit `wind_factor` per station in `config.yaml`, which overrides height and
  surroundings while set, with *Use this* on the setup page writing it and a way to clear it. The
  published `station_info.wind_factor` and the recompute take whichever is in force.
- **Direction**: the first station's ratio differed by wind direction (N 0.31, NW 0.47 of the
  model) because of shelter on one side. A factor per direction sector would fit better but is a
  lot more to explain and set; start with one factor and report the spread by sector beside it.
- **Gusts**: the factor is fitted to mean wind, but `wind_10m` scales the gust by it too, and a
  gust's excess over the mean grows less with height than the mean does. On the first station
  (x2.16) the 10 m gust estimate peaked at 59.9 km/h when the model's highest was 41 km/h, close
  to the Strong wind alert's 60, while mean speeds agreed (13.7 against 13.3 km/h). Scaling only
  the mean part -- gust + (factor - 1) x speed -- came closer on peaks but under-read on average,
  over a few days of light wind. Compare both against the model's gusts in the same quarter-hours
  once there are windy days, and if the excess-kept form fits better, store the gust that way
  (with a recompute) so the alert and the dashboard read it.

## Open questions

- Whether to suggest at all when the spread is wide, or say the site is too sheltered for one
  factor.
- Whether the model is trustworthy enough everywhere to calibrate against; a nearby official
  station's wind would be better where one exists, but needs a source per country.

## Done when

The setup page of a station with two weeks of data shows a measured factor, how many quarter-hours
it rests on and how much it varies, and one click makes it the station's factor.

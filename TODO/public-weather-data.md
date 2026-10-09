# Public weather data

Store a weather model's view of each station's location beside the station's own readings: the
same quantities, from a free public API, on a slow cycle. It gives a reference to check sensors
against, a way to spot a sheltered or failing sensor, and values for quantities the station does
not measure.

## Why

A single station has nothing to compare itself with. A wind vane in a building's lee, a
thermometer in afternoon sun, or a rain gauge that has stopped tipping all look like weather.
Side by side with a model the difference shows, and stays in the history.

## Sketch

- **Open-Meteo**, already used for the absolute-pressure reference (`lookups.surface_pressure`,
  refreshed by `reference.py`): free for non-commercial use, no key, global. Extend that cycle
  rather than add a second client.
- **Fetched every 15 minutes** for stations with coordinates, matching the model's
  `minutely_15` resolution where available, `current` otherwise.
- **Quantities**: temperature, humidity, dew point, wind speed, gust and direction, surface and
  sea-level pressure, precipitation, cloud cover, shortwave radiation, UV index. Cloud cover and
  model radiation are what the station cannot measure.
- **Stored in a `model` table**, tagged `station` and `source=open_meteo`, with field names in
  the operator's units like every other table (`temp_c`, `speed_kmh`). Values pass through
  `points.py` so units and rounding match the station's own rows.
- **The existing pressure reference** moves onto this data, so one fetch serves both.
- **Dashboard**: model series drawn dashed behind the station's in the outdoor panels; a
  "station minus model" panel for temperature and wind direction.

## Open questions

- Which model: Open-Meteo's best-match default, or a pinned one (e.g. a regional model where
  there is one) so the reference does not change character when the default does.
- Model grid cells are kilometres wide and often at another altitude; temperature needs a lapse
  correction to the station's altitude before comparing, as pressure already has.
- Whether to fetch the model's history for days the station already has, to give new
  installations a comparison from the first day.

## Done when

Each located station has a `model` series beside its own, refreshed every 15 minutes, in the
operator's units, with the pressure check reading from it, and the dashboard can draw model and
station together.

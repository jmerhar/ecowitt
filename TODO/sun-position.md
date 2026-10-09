# Sun position

The station's coordinates are already known whenever its pressure is reduced to sea level, which
is enough to compute where the sun is. With that, a solar radiation reading means something on its
own: 300 W/m² is a clear evening or an overcast noon, and only the sun's elevation tells them
apart.

## Sketch

- **Derived per report**, in `derive.py`, for stations with coordinates, into the `solar` table:
  - `sun_elevation_deg` and `sun_azimuth_deg`;
  - `clear_sky_wm2`, the radiation a cloudless sky would give at that elevation;
  - `clearness_pct`, measured radiation as a share of the clear-sky value, left out while the sun
    is too low for the ratio to mean anything (below about 5°).
- **Formulas in `psychro.py`'s spirit**: pure functions in their own module (`solar.py`),
  tested against published reference values (NOAA's solar position calculator for elevation,
  azimuth, sunrise and sunset), not against this code.
- **Clear-sky model**: a simple one that needs no extra inputs (Haurwitz, or Ineichen–Perez with
  a fixed Linke turbidity). Compare candidates against a clear day's measurements before
  choosing.
- **Sunrise and sunset** are a property of the date, not of a report, so they are not stored per
  report. The status page and the API compute them on request; dashboards get them as
  annotations or a once-a-day row, whichever proves simpler to query.
- **Dashboard**: clear-sky radiation drawn behind measured radiation in the Sun panel, and the
  clearness ratio as a rough cloud-cover indicator.

## Open questions

- Whether a sensor reading consistently below clear sky on cloudless days (dirt, shading, a
  tilted array) should raise a status-page note, the way pressure calibration does.
- Refraction near the horizon: whether to correct elevation for it, which moves sunrise by a
  couple of minutes.

## Done when

Sun elevation, azimuth and clear-sky radiation are stored for located stations, match NOAA's
reference values within their stated precision, and the dashboard shows measured against
clear-sky radiation.

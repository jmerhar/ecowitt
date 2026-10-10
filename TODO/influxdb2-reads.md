# Reading from InfluxDB 2.x

The collector writes to InfluxDB 2.x as well as 3; the dashboard reads from InfluxDB 3 only,
because its reader is SQL and InfluxDB 2.x has none. A station whose readings live in an InfluxDB
2.x bucket cannot have a dashboard.

## Sketch

- **`Influx2Store` implements `Reader`** (`ecowitt.core.store.query`), and `influx2` joins
  `factory.READABLE`, which is all the dashboard's setup page needs to offer it.
- **Flux over `/api/v2/query`**, one query per `Reader` question:
  - `stations`, `station_info`: `station_info` rows, the newest one pivoted into fields;
  - `span`: `first()` and `last()` per field, grouped by the table's tags;
  - `extremes`: `min()` and `max()` per field, keeping `_time`;
  - `buckets`: `aggregateWindow(every:, offset:)` with the offset putting bucket edges on the
    station's midnight, `mean`/`min`/`max`, and the circular mean as `sin`/`cos` means joined
    and turned back with `math.atan2`;
  - the catalogue: `schema.tagKeys` and `schema.fieldKeys` per measurement.
- **Annotated CSV** is what `/api/v2/query` answers with; parse it into the same `Span`,
  `Extremes` and `Buckets` the SQL reader returns, so the dashboard does not change.
- **Values travel as Flux parameters** (`params` in the request body), never in the query text,
  as station names do as SQL parameters now.

## Testing

The stand-in server answers each query with recorded CSV, as the SQL reader's tests answer with
recorded JSON. That proves the parsing, not the Flux: before shipping, run the queries against a
real InfluxDB 2.x (the `influxdb:2` image) loaded with a day of rows, and compare each answer with
the SQL reader's over the same rows in InfluxDB 3.

## Open questions

- InfluxQL through the v1 compatibility API would read more like the SQL, but needs a DBRP
  mapping set up by hand and has no ordered aggregates. Flux is the native language; is it worth
  that tradeoff?

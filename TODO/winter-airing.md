# Winter airing: a short burst, then close

Advice and an alert for airing in cold weather: a few minutes with the windows wide open in the
morning, then closed again, rather than the windows left open for hours that the airing rules are
built around.

## Why

In winter the outdoor air holds little water, so a short airing dries a house well; leaving the
windows open longer only cools the rooms, and with most of a house unheated -- a fireplace in one
room, an air conditioner in another -- the cold soaks into the walls and the humidity of the
unheated rooms climbs once the windows close. Cold, unheated rooms are where damp and mould start,
so airing matters most in exactly the months it should be brief.

The present rules do not fit it:

- `house.aired` needs the rooms' median temperature within 2.5 °C of outdoors
  (`collector/.../ingest/derive.py`), which keeps out a closed house that matches the outdoor dew
  point by chance on a still night. On a cold morning an aired house stays more than 2.5 °C above
  outdoors, so it would not read as aired. The condition does real work in autumn: on the first
  station it alone kept a closed house from reading as aired for six hours one night, and neither
  the rooms' temperature trend nor the gap's trend told that night from a real airing.
- *Close the windows* fires when the air coming in turns damper, which a dry winter morning
  rarely does: the reason to close is the cold, not the moisture.

## Sketch

- **Recognising a winter airing.** With the outdoor air well below the rooms', open windows show
  as a sudden fall in the temperature of the unheated rooms -- a degree or more within minutes --
  and a fall in their dew point towards the outdoor one, both recovering once the windows close.
  A closed house does neither. Judge the unheated rooms: one warmed by a fire or a heat pump may
  not cool. This needs the rooms' recent history, so it belongs where history is read (the alert
  query, the dashboard API), or in a short in-memory trend in the collector like the staleness
  tracker's, which a backfill would have to replay.
- **Aired enough.** Once the unheated rooms' dew points have come down to near the outdoor one
  (most of the moisture gone), or after about ten minutes, an alert says to close the windows,
  and the airing card says the same. Nothing is sent if they close before. Grafana evaluates
  every minute, so a ten-minute reminder is within reach.
- **Good time to air**, unchanged: one message in the morning, quiet hours holding back anything
  earlier. In winter it would add that a short airing is enough.
- **Seasons, not dates.** Switch between the long-airing and short-airing behaviour on the
  temperature gap (say the outdoor air 6 °C or more below the rooms), not the calendar, so it
  suits any climate and a cold spell in autumn.
- **Keep `house.aired` honest meanwhile.** Its temperature condition could scale with the gap
  or be dropped once the winter signal above exists; until then it stays, and the history can be
  recomputed with the new rule (as `outdoor_share_pct` was).

## Undecided

- The thresholds: how fast the unheated rooms cool when a house is aired in winter, how long
  their dew point takes to level out, and how big a fall counts. They need a few real winter
  airings to set; guessing them would give either false alarms or silence.
- Whether the closing alert waits for the dew point to level out or fires at a fixed time.
- Whether a fire lit in the living room, which draws air in through every gap, looks like an
  airing.

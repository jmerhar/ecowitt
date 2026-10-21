"""The forecast read back: the newest for each hour and day, and what the cards make of it."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from ecowitt.dashboard import models
from ecowitt.dashboard.i18n import LANGUAGES
from ecowitt.dashboard.service import Dashboard

from .conftest import INFO, MIDNIGHT, NOW, readings, row
from .memory import MemoryReader

MODELLED = dataclasses.replace(INFO, weather_model="best_match")
HOUR = timedelta(hours=1)
#: NOW is 14:00 UTC, 15:00 in Lisbon; the forecasts were made at 13:00 and at 11:00 UTC.
ISSUED = NOW - HOUR


def hour(at, lead: int, model: str = "best_match", **fields: object):  # noqa: ANN001, ANN201
    values = {
        "temp_c": 17.0,
        "dewpoint_c": 12.0,
        "precip_probability_pct": 10.0,
        "weather_code": 3,
        "speed_kmh": 15.0,
        "gust_kmh": 25.0,
        "dir_deg": 350.0,
        "is_day": True,
    }
    values.update(fields)
    return row("forecast", at, {k: v for k, v in values.items() if v is not None},
               lead=str(lead), model=model, source="open_meteo")  # fmt: skip


def day(at, lead: int, **fields: object):  # noqa: ANN001, ANN201
    values = {
        "temp_max_c": 21.0,
        "temp_min_c": 13.0,
        "precip_mm": 0.4,
        "precip_probability_pct": 30.0,
        "weather_code": 61,
        "gust_max_kmh": 40.0,
        "dir_deg": 10.0,
        "uv_index_max": 5.0,
    }
    values.update(fields)
    return row(
        "forecast_daily", at, values, lead=str(lead), model="best_match", source="open_meteo"
    )


def board(*rows, info=MODELLED) -> Dashboard:  # noqa: ANN001, ANN002
    return Dashboard(MemoryReader([*readings(), *rows], {"example": info}), clock=lambda: NOW)


def coming(**at_hours: dict) -> list:  # noqa: ANN003
    """The newest forecast's rows for the hours from NOW, made at ISSUED."""
    return [hour(NOW + h * HOUR, h + 1, **at_hours.get(str(h), {})) for h in range(0, 25)]


async def test_the_newest_forecast_for_each_hour_and_day() -> None:
    older = [hour(NOW + h * HOUR, h + 3, temp_c=99.0) for h in range(0, 4)]
    other = [hour(NOW, 0, model="icon_seamless", temp_c=55.0)]
    days = [day(MIDNIGHT - timedelta(days=1), 0), day(MIDNIGHT, 0, temp_max_c=22.0),
            day(MIDNIGHT + timedelta(days=1), 1)]  # fmt: skip

    found = await board(*coming(), *older, *other, *days).forecast("example")

    assert found.issued == ISSUED
    assert found.model is not None and found.model.id == "best_match"
    assert len(found.hours) == 24
    first = found.hours[0]
    # The newest forecast, not the older one or another model's.
    assert (first.time, first.temperature, first.description) == (NOW, 17.0, "Overcast")
    assert (first.wind_gust, first.compass, first.is_day) == (25.0, "N", True)
    # Today and on: yesterday's local day is left out.
    assert [(d.date, d.temperature_max) for d in found.days] == [
        (MIDNIGHT, 22.0), (MIDNIGHT + timedelta(days=1), 21.0),
    ]  # fmt: skip
    assert (found.days[0].description, found.days[0].uv_index_max, found.days[0].compass) == (
        "Light rain", 5.0, "N",
    )  # fmt: skip


async def test_the_forecast_is_converted() -> None:
    found = await board(*coming()).forecast("example", {"temperature": "f", "wind": "mph"})

    assert (found.units.temperature, found.hours[0].temperature) == ("f", 62.6)
    assert found.hours[0].wind_speed == 9.3


async def test_no_model_or_a_stale_forecast_shows_nothing() -> None:
    """A forecast made over 12 hours ago means the collector has stopped fetching."""
    stale = [hour(NOW + h * HOUR, h + 13) for h in range(0, 3)]

    for found in (
        await board(*coming(), info=INFO).forecast("example"),
        await board(*stale).forecast("example"),
        await board().forecast("example"),
    ):
        assert (found.issued, found.hours, found.days) == (None, [], [])


async def test_a_row_with_an_unreadable_lead_never_wins() -> None:
    odd = hour(NOW, 0, temp_c=99.0)
    odd = dataclasses.replace(odd, tags=tuple((k, "x" if k == "lead" else v) for k, v in odd.tags))

    found = await board(odd, *coming()).forecast("example")

    assert found.hours[0].temperature == 17.0


async def test_rain_coming_is_on_the_rain_card_while_it_is_dry() -> None:
    reader_rows = [r for r in readings() if r.table != "rain"]
    rows = coming(**{"3": {"precip_probability_pct": 70.0}})
    dashboard = Dashboard(
        MemoryReader([*reader_rows, *rows], {"example": MODELLED}), clock=lambda: NOW
    )

    notices = (await dashboard.now("example")).notices

    # The row at 17:00 UTC is the hour ending then, which begins at 17:00 in Lisbon.
    assert notices["rain"].text == "Rain likely from 17:00."
    assert [(i.code, i.time) for i in notices["rain"].items] == [
        (models.NoticeCode.RAIN_FROM, NOW + 2 * HOUR)
    ]


async def test_a_wet_hour_by_amount_counts_too_and_not_while_raining() -> None:
    dry = [r for r in readings() if r.table != "rain"]
    rows = coming(**{"2": {"precip_probability_pct": None, "precip_1h_mm": 0.8}})
    found = await Dashboard(
        MemoryReader([*dry, *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")
    assert found.notices["rain"].text == "Rain likely from 16:00."
    # The example station is raining already: there is nothing to announce.
    raining = await board(*rows).now("example")
    assert raining.rain is not None and raining.rain.raining
    assert "rain" not in raining.notices


async def test_rain_beyond_six_hours_is_left_to_the_forecast() -> None:
    dry = [r for r in readings() if r.table != "rain"]
    rows = coming(**{"8": {"precip_probability_pct": 90.0}})
    found = await Dashboard(
        MemoryReader([*dry, *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert "rain" not in found.notices


async def test_frost_heat_and_gusts_coming_are_on_their_cards() -> None:
    rows = coming(**{"13": {"temp_c": 1.0}, "20": {"temp_c": 33.0}, "5": {"gust_kmh": 72.0}})

    notices = (await board(*rows).now("example")).notices

    # 03:00 and 10:00 UTC tomorrow are 04:00 and 11:00 in Lisbon. A gust is the strongest in the
    # hour ending at its row, so the 19:00 UTC row's hour begins at 19:00 in Lisbon.
    assert notices["outdoor"].text == (
        "Down to 1 °C at tomorrow 04:00: frost possible. Up to 33 °C at tomorrow 11:00."
    )
    assert notices["wind"].text == "Gusts to 72 km/h at 19:00."
    Code = models.NoticeCode
    assert [(i.code, i.value, i.unit, i.time) for i in notices["outdoor"].items] == [
        (Code.FROST_FORECAST, 1.0, "c", NOW + 13 * HOUR),
        (Code.HEAT_FORECAST, 33.0, "c", NOW + 20 * HOUR),
    ]
    assert [(i.code, i.value, i.unit) for i in notices["wind"].items] == [
        (Code.GUSTS_FORECAST, 72.0, "kmh")
    ]


async def test_the_forecasts_frost_replaces_the_present_readings_hint() -> None:
    cold = [r for r in readings() if r.table != "outdoor"] + [
        row("outdoor", NOW - timedelta(minutes=1), {"temp_c": 4.0, "humidity_pct": 70.0},
            sensor="outdoor", name="Garden"),
    ]  # fmt: skip
    rows = coming(**{"10": {"temp_c": 0.5}})
    found = await Dashboard(
        MemoryReader([*cold, *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert found.notices["outdoor"].text == "Down to 0.5 °C at tomorrow 01:00: frost possible."
    assert [i.code for i in found.notices["outdoor"].items] == [models.NoticeCode.FROST_FORECAST]
    portuguese = await Dashboard(
        MemoryReader([*cold, *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example", language=LANGUAGES["pt-PT"])
    assert portuguese.notices["outdoor"].text == (
        "Mínima de 0,5 °C amanhã à 01:00: possibilidade de geada."
    )


async def test_a_drier_spell_ahead_is_given_while_the_advice_is_not_to_open() -> None:
    """The bathroom, at 75%, would settle at 72%: to bring it to 70%, the model's air must come
    to hold 70/72 of the water it holds now, which a dew point of 10.9 °C rather than 12 does."""
    dry_later = coming(**{str(h): {"dewpoint_c": 10.9} for h in range(4, 25)})
    airing = {"dewpoint_delta_c": 1.0, "predicted_humidity_pct": 72.0}
    vent = [r for r in readings() if r.table != "ventilation"] + [
        row("ventilation", NOW - timedelta(minutes=1), airing, sensor=s, name=n)
        for s, n in (("indoor", "Living"), ("ch1", "ch1"))
    ]

    found = await Dashboard(
        MemoryReader([*vent, *dry_later], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert found.airing is not None and found.airing.advice != "open"
    assert found.airing.drier_from == NOW + 4 * HOUR


async def test_an_hour_without_a_weather_code_has_no_description() -> None:
    found = await board(*coming(**{"0": {"weather_code": None}})).forecast("example")

    assert (found.hours[0].weather_code, found.hours[0].description) == (None, None)


async def test_no_drier_spell_without_an_outdoor_dew_point() -> None:
    airing = {"dewpoint_delta_c": 1.0, "predicted_humidity_pct": 72.0}
    rows = [
        r
        for r in readings()
        if r.table != "ventilation"
        and not (r.table == "derived" and dict(r.tags).get("sensor") == "outdoor")
    ] + [
        row("ventilation", NOW - timedelta(minutes=1), airing, sensor=s, name=n)
        for s, n in (("indoor", "Living"), ("ch1", "ch1"))
    ]
    dry_later = coming(**{str(h): {"dewpoint_c": 5.0} for h in range(0, 25)})

    found = await Dashboard(
        MemoryReader([*rows, *dry_later], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert found.airing is not None and found.airing.advice != "open"
    assert found.airing.drier_from is None


async def test_the_route_serves_it(client: TestClient, reader: MemoryReader) -> None:
    reader.infos["example"] = MODELLED
    reader.rows += coming()

    response = client.get("/api/v1/stations/example/forecast?temperature=f")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.json()["hours"][0]["temperature"] == 62.6


def damp_rooms(living: tuple[float, float], bath: tuple[float, float] = (50.0, 50.0)) -> list:
    """The readings with each room's humidity, now and once aired, replaced."""
    rooms = {"indoor": living, "ch1": bath}
    kept = [r for r in readings() if r.table not in {"ventilation", "indoor", "channel"}]
    return kept + [
        row("indoor", NOW - timedelta(minutes=1), {"temp_c": 20.0, "humidity_pct": living[0]},
            sensor="indoor", name="Living"),
        row("channel", NOW - timedelta(minutes=1), {"temp_c": 20.0, "humidity_pct": bath[0]},
            sensor="ch1", name="ch1", channel="1"),
    ] + [
        row("ventilation", NOW - timedelta(minutes=1),
            {"dewpoint_delta_c": 0.0, "predicted_humidity_pct": after}, sensor=s, name=s)
        for s, (_, after) in rooms.items()
    ]  # fmt: skip


async def airing_with(rows: list, dew: dict[int, float], clock=NOW) -> object:  # noqa: ANN001
    found = await Dashboard(
        MemoryReader([*rows, *coming(**{str(h): {"dewpoint_c": d} for h, d in dew.items()})],
                     {"example": MODELLED}),
        clock=lambda: clock,
    ).now("example")  # fmt: skip
    assert found.airing is not None
    return found.airing


async def test_a_model_reading_drier_than_the_station_announces_nothing_by_itself() -> None:
    """The model's dew point 3 °C under the station's, throughout: no change is coming."""
    airing = await airing_with(damp_rooms((70.0, 68.0)), dict.fromkeys(range(25), 9.5))

    assert airing.advice != "open" and airing.drier_from is None


async def test_the_dampest_rooms_need_decides_and_dry_rooms_are_left_out() -> None:
    """Of two rooms at 70%, one would settle at 68% and needs the air to hold 65/68 of its water
    (a dew point of 11.3 °C from 12), the other at 74% and needs 65/74 (10.1 °C). A dry room at
    55% that would settle at 52% needs less than either, but it does not need airing."""
    dew = {0: 12.0, **dict.fromkeys(range(3, 25), 11.2)}
    damp = await airing_with(damp_rooms((70.0, 74.0), (70.0, 68.0)), dew)
    dry = await airing_with(damp_rooms((70.0, 74.0), (55.0, 52.0)), dew)

    assert damp.drier_from == NOW + 3 * HOUR
    assert dry.drier_from is None


async def test_a_damp_room_without_its_humidity_after_airing_is_left_out() -> None:
    rows = [r for r in damp_rooms((70.0, 68.0)) if r.table != "ventilation"] + [
        row("ventilation", NOW - timedelta(minutes=1), {"dewpoint_delta_c": 1.0}, sensor=s, name=s)
        for s in ("indoor", "ch1")
    ]
    airing = await airing_with(rows, dict.fromkeys(range(1, 25), 5.0))

    assert airing.advice != "open" and airing.drier_from is None


async def test_no_drier_spell_while_the_advice_is_to_open_already() -> None:
    airing = await airing_with(damp_rooms((70.0, 60.0)), dict.fromkeys(range(1, 25), 5.0))

    assert (airing.advice, airing.drier_from) == ("open", None)


async def test_the_hour_under_way_is_not_drier_air_coming() -> None:
    """At 14:40 the 14:00 row is past: the first hour that can be coming is 15:00."""
    later = NOW + timedelta(minutes=40)
    airing = await airing_with(damp_rooms((70.0, 68.0)), {0: 12.0, 1: 12.0, 2: 10.0}, clock=later)

    assert airing.drier_from == NOW + 2 * HOUR


async def test_a_drier_spell_is_offered_only_when_someone_will_open_a_window() -> None:
    """At 23:00 in Lisbon, air dry enough from 00:00 to 09:00: the spell is offered from 08:00,
    not in the small hours; one over by 08:00 is not offered at all."""
    late = NOW + 8 * HOUR
    steady = dict.fromkeys(range(25), 12.0)
    airing = await airing_with(
        damp_rooms((70.0, 68.0)), steady | dict.fromkeys(range(9, 18), 10.0), clock=late
    )
    assert airing.drier_from == NOW + 17 * HOUR

    airing = await airing_with(
        damp_rooms((70.0, 68.0)), steady | dict.fromkeys(range(9, 16), 10.0), clock=late
    )
    assert airing.drier_from is None


async def test_no_drier_spell_without_the_models_present_dew_point() -> None:
    rows = [hour(NOW + h * HOUR, h + 1, dewpoint_c=5.0) for h in range(1, 25)]
    found = await Dashboard(
        MemoryReader([*damp_rooms((70.0, 68.0)), *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert found.airing is not None and found.airing.drier_from is None


async def test_rain_in_the_hour_under_way_is_within_the_hour_and_past_rain_is_not() -> None:
    """At 14:40, the row at 15:00 is the hour under way; the row at 14:00 is the hour gone. At
    14:00 itself the row at 15:00 is under way too, not coming."""
    dry = [r for r in readings() if r.table != "rain"]
    later = NOW + timedelta(minutes=40)

    async def notices(at_hours: dict, clock: datetime = later) -> dict:  # noqa: ANN001
        board = Dashboard(MemoryReader([*dry, *coming(**at_hours)], {"example": MODELLED}),
                          clock=lambda: clock)  # fmt: skip
        return (await board.now("example")).notices

    under_way = await notices({"1": {"precip_probability_pct": 80.0}})
    on_the_hour = await notices({"1": {"precip_probability_pct": 80.0}}, clock=NOW)
    gone = await notices({"0": {"precip_probability_pct": 80.0}})

    assert under_way["rain"].text == "Rain likely within the hour."
    assert [i.code for i in under_way["rain"].items] == [models.NoticeCode.RAIN_SOON]
    board_pt = Dashboard(MemoryReader([*dry, *coming(**{"1": {"precip_probability_pct": 80.0}})],
                         {"example": MODELLED}), clock=lambda: later)  # fmt: skip
    in_portuguese = await board_pt.now("example", language=LANGUAGES["pt-PT"])
    assert in_portuguese.notices["rain"].text == "Chuva provável na próxima hora."
    assert [i.code for i in on_the_hour["rain"].items] == [models.NoticeCode.RAIN_SOON]
    assert "rain" not in gone


async def test_each_hour_shows_the_rain_and_gusts_of_the_hour_from_it() -> None:
    rows = coming(**{"1": {"precip_1h_mm": 1.5, "gust_kmh": 44.0, "temp_c": 9.0}})

    found = await board(*rows[:-1]).forecast("example")

    first, second = found.hours[0], found.hours[1]
    assert (first.time, first.precipitation, first.wind_gust, first.temperature) == (
        NOW, 1.5, 44.0, 17.0,
    )  # fmt: skip
    assert (second.temperature, second.wind_gust) == (9.0, 25.0)
    # The last hour's end is beyond what is stored: its rain is not known.
    assert found.hours[-1].precipitation is None and found.hours[-1].wind_gust is None


async def test_a_gust_already_blowing_is_not_announced_again() -> None:
    blowing = [r for r in readings() if r.table != "wind_10m"] + [
        row("wind_10m", NOW - timedelta(minutes=1),
            {"speed_kmh": 40.0, "gust_kmh": 70.0, "source": "sensor"}),
    ]  # fmt: skip
    rows = coming(**{"5": {"gust_kmh": 80.0}})
    found = await Dashboard(
        MemoryReader([*blowing, *rows], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")

    assert found.notices["wind"].text == "Strong gusts."


async def test_each_day_has_its_mean_humidity() -> None:
    found = await board(*coming(), day(MIDNIGHT, 0, humidity_mean_pct=81.0)).forecast("example")

    assert found.days[0].humidity == 81.0


async def test_a_past_or_present_hours_frost_is_the_stations_to_report() -> None:
    """At 14:40 the 14:00 row is gone, and at 14:00 it is now: neither is coming."""
    frost = coming(**{"0": {"temp_c": 0.0}})
    for clock in (NOW + timedelta(minutes=40), NOW):
        found = await Dashboard(
            MemoryReader([*readings(), *frost], {"example": MODELLED}), clock=lambda c=clock: c
        ).now("example")
        assert "frost" not in found.notices.get("outdoor", models.Notice(level="x", text="")).text


async def test_the_forecast_and_its_notices_are_in_the_language_asked_for() -> None:
    portuguese = LANGUAGES["pt-PT"]
    rows = coming(**{"13": {"temp_c": 1.0}, "20": {"temp_c": 33.0}, "5": {"gust_kmh": 72.0}})
    dashboard = board(*rows, day(MIDNIGHT, 0))

    notices = (await dashboard.now("example", language=portuguese)).notices
    found = await dashboard.forecast("example", language=portuguese)

    assert notices["outdoor"].text == (
        "Mínima de 1 °C amanhã às 04:00: possibilidade de geada. Máxima de 33 °C amanhã às 11:00."
    )
    assert notices["wind"].text == "Rajadas até 72 km/h às 19:00."
    assert (found.hours[0].description, found.hours[0].compass) == ("Céu encoberto", "N")
    assert (found.days[0].description, found.days[0].compass) == ("Chuva fraca", "N")
    assert found.model is not None and found.model.label == "Melhor para este local"


async def test_windows_misting_up_tonight_are_on_the_rooms_card() -> None:
    """The bathroom, at 20 °C with a 15.4 °C dew point, mists up once the air outside is at
    9.8 °C or less; the living room, drier, does not."""
    mild = await board(*coming(**{str(h): {"temp_c": 12.0} for h in range(1, 25)})).now("example")
    assert "mist" not in (mild.notices["rooms"].text if "rooms" in mild.notices else "")
    # An hour the model gave no temperature for says nothing either way.
    rows = coming(
        **{str(h): {"temp_c": 12.0 if h < 10 else 9.0} for h in range(1, 25)}
        | {"9": {"temp_c": None}}
    )
    found = await board(*rows).now("example")
    item = next(
        i for i in found.notices["rooms"].items if i.code is models.NoticeCode.MIST_FORECAST
    )
    assert item.time == NOW + 10 * HOUR
    assert item.text == "Windows likely to mist up from tomorrow 01:00."
    portuguese = await board(*rows).now("example", language=LANGUAGES["pt-PT"])
    assert "As janelas devem embaciar amanhã a partir da 01:00." in portuguese.notices["rooms"].text


def offset_rows(station_minus_model: float, hours: int = 24) -> list:
    """A day of hourly outdoor readings and model values, the station that much warmer; one
    hour the model gave no temperature for, which is left out of the comparison."""
    rows = []
    for n in range(hours):
        at = NOW - timedelta(minutes=1) - n * HOUR
        outdoor = {"temp_c": 15.0 + station_minus_model}
        rows.append(row("outdoor", at, outdoor, sensor="outdoor", name="Garden"))
        model = {"humidity_pct": 70.0} if n == 5 else {"temp_c": 15.0}
        rows.append(row("model", at, model, model="best_match", source="open_meteo"))
    return rows


async def test_the_forecast_is_judged_as_the_station_has_lately_read_from_it() -> None:
    """A model reading 1.5 °C warmer than the station: its 3 °C low is a 1.5 °C one, frost."""
    base = [r for r in readings() if r.table != "outdoor"]
    low = coming(**{"10": {"temp_c": 3.0}})

    async def outdoor(extra: list) -> str:
        reader = MemoryReader([*base, *extra, *low], {"example": MODELLED})
        notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
        return notices["outdoor"].text if "outdoor" in notices else ""

    assert await outdoor(offset_rows(0.0)) == ""
    assert await outdoor(offset_rows(-1.5)) == "Down to 1.5 °C at tomorrow 01:00: frost possible."
    # Too few hours of both to say how far apart they read.
    assert await outdoor(offset_rows(-1.5, hours=11)) == ""
    # Another model's values are not this station's model.
    other = [r if r.table != "model" else dataclasses.replace(
        r, tags=tuple((k, "icon_seamless" if k == "model" else v) for k, v in r.tags)
    ) for r in offset_rows(-1.5)]  # fmt: skip
    assert await outdoor(other) == ""


async def test_misting_is_judged_as_the_station_has_lately_read_from_the_model() -> None:
    """A 10.5 °C night in a model reading 1.5 °C warm is a 9 °C one: the bathroom mists up."""
    base = [r for r in readings() if r.table != "outdoor"]
    night = coming(**{str(h): {"temp_c": 12.0 if h < 10 else 10.5} for h in range(1, 25)})

    async def rooms(extra: list) -> str:
        reader = MemoryReader([*base, *extra, *night], {"example": MODELLED})
        notices = (await Dashboard(reader, clock=lambda: NOW).now("example")).notices
        return notices["rooms"].text if "rooms" in notices else ""

    assert "mist" not in await rooms(offset_rows(0.0))
    assert "Windows likely to mist up from tomorrow 01:00." in await rooms(offset_rows(-1.5))


async def test_a_showers_steam_does_not_mist_the_windows_overnight() -> None:
    """The bathroom at a 21 °C dew point just after a shower, 15.4 °C before it: a 12 °C night
    mists glass only for the steam, which has passed by then."""
    steam = [
        r
        for r in readings()
        if not (r.table == "derived" and dict(r.tags).get("sensor") == "ch1")
    ] + [
        row("derived", NOW - timedelta(minutes=m), {"dewpoint_c": 15.4 if m > 20 else 21.0},
            sensor="ch1", name="ch1")
        for m in range(1, 181, 10)
    ]  # fmt: skip
    night = coming(**{str(h): {"temp_c": 12.0} for h in range(1, 25)})
    found = await Dashboard(
        MemoryReader([*steam, *night], {"example": MODELLED}), clock=lambda: NOW
    ).now("example")
    assert "mist" not in (found.notices["rooms"].text if "rooms" in found.notices else "")


async def test_a_room_without_three_hours_of_dew_points_is_not_judged() -> None:
    """A sensor just back after an outage has no lowest dew point over the three hours yet."""
    recent = [
        r for r in readings() if not (r.table == "derived" and dict(r.tags).get("sensor") == "ch1")
    ] + [row("derived", NOW - timedelta(minutes=1), {"dewpoint_c": 15.4}, sensor="ch1", name="ch1")]
    night = coming(**{str(h): {"temp_c": 9.0} for h in range(1, 25)})
    reader = MemoryReader([*recent, *night], {"example": MODELLED})
    found = await Dashboard(reader, clock=lambda: NOW).now("example")
    assert "mist" not in (found.notices["rooms"].text if "rooms" in found.notices else "")

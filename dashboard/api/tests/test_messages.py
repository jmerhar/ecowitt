"""Every code the API sends has words beside it, in every language."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from ecowitt.core import weathermodel
from ecowitt.dashboard import messages, weather
from ecowitt.dashboard.i18n import ENGLISH, LANGUAGES
from ecowitt.dashboard.models import NoticeCode
from ecowitt.dashboard.weather import Tendency

PORTUGUESE = LANGUAGES["pt-PT"]


def test_every_notice_code_is_worded_once() -> None:
    assert set(messages.NOTICES) | set(messages.NOTICES_AT) == set(NoticeCode)
    assert not set(messages.NOTICES) & set(messages.NOTICES_AT)


def test_every_tendency_is_worded() -> None:
    assert set(messages.TENDENCIES) == set(Tendency)


def test_every_room_flag_is_worded() -> None:
    raised = {*weather.room_flags(-10, 100, 100), *weather.room_flags(40, 0, 0)}
    assert raised == set(messages.ROOM_FLAGS)


def test_the_template_has_every_table_with_its_context() -> None:
    template = messages.template()
    for context, table in [
        (messages.COMPASS, weather.COMPASS),
        (messages.BEAUFORT, weather.BEAUFORT_NAMES),
        (messages.SKY, weathermodel.WEATHER_CODES.values()),
        (messages.MODEL, weathermodel.MODELS.values()),
        (messages.SENSOR, messages.SENSOR_NAMES.values()),
    ]:
        assert all(template.get(m, context=context) is not None for m in table), context
    timed = template.get(("Gusts to {value} at {clock}.",) * 2, context=messages.NOTICE)
    assert timed is not None and timed.auto_comments == [messages.AT_HOUR]
    assert "python-brace-format" in timed.flags


def test_the_tables_are_put_in_words() -> None:
    assert messages.compass(PORTUGUESE, 270) == "O"
    assert messages.beaufort(PORTUGUESE, 3) == "Vento bonançoso"
    assert messages.sky(PORTUGUESE, 3) == "Céu encoberto"
    assert messages.sky(PORTUGUESE, 42) == "Código meteorológico 42"
    assert messages.sky(ENGLISH, 42) == "Weather code 42"
    assert messages.model(PORTUGUESE, "icon_seamless") == "ICON (DWD, Alemanha)"
    assert messages.model(PORTUGUESE, "jma_seamless") == "jma_seamless"
    assert messages.metric(PORTUGUESE, "Dew point") == "Ponto de orvalho"
    assert messages.sensor(PORTUGUESE, "rain") == "Pluviómetro"
    assert messages.sensor(PORTUGUESE, "ch3") == "ch3"
    assert messages.tendency(PORTUGUESE, Tendency.FALLING_QUICKLY) == "a descer rapidamente"
    assert messages.room_flag(PORTUGUESE, "damp") == "Húmido"


@pytest.mark.parametrize("code", list(messages.NOTICES_AT), ids=lambda c: c.value)
@pytest.mark.parametrize("tomorrow", [False, True], ids=["today", "tomorrow"])
def test_every_time_takes_the_article_its_hour_needs(code: NoticeCode, tomorrow: bool) -> None:
    """Portuguese writes "à 01:00" and "da 01:00" but "às 13:00" and "das 13:00"."""

    def said(hour: int) -> str:
        local = datetime(2026, 10, 10, hour, 30)
        return messages.notice_at(PORTUGUESE, code, local, tomorrow, value="1 °C")

    assert re.search(r"\b(à|da) 01:30", said(1)), said(1)
    assert re.search(r"\b(às|das) 13:30", said(13)), said(13)

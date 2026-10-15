"""Every code the API sends has words beside it."""

from __future__ import annotations

from ecowitt.dashboard import messages, weather
from ecowitt.dashboard.models import NoticeCode
from ecowitt.dashboard.weather import Tendency


def test_every_notice_code_is_worded() -> None:
    assert set(messages.NOTICES) == set(NoticeCode)


def test_every_tendency_is_worded() -> None:
    assert set(messages.TENDENCIES) == set(Tendency)


def test_every_room_flag_is_worded() -> None:
    raised = {*weather.room_flags(-10, 100), *weather.room_flags(40, 0)}
    assert raised == set(messages.ROOM_FLAGS)

"""The counters both listeners read."""

from __future__ import annotations

from ecowitt.collector.state import State


def test_a_model_fetch_that_answers_clears_the_failures_before_it() -> None:
    state = State()
    state.record_model(False)
    state.record_model(False)
    assert state.model_failures == 2
    assert state.seconds_since_last_model is None

    state.record_model(True)

    assert state.model_failures == 0
    assert state.seconds_since_last_model is not None

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.scoring.trailscore import trailscore_score

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _event(event_type: str, minutes_ago: float):
    return {
        "event_type": event_type,
        "ts": _NOW - timedelta(minutes=minutes_ago),
    }


def test_a_four_events_in_order_with_implicit_transfer_ordered_and_clamped():
    events = [
        _event("login_new_device", 8),
        _event("credential_changed", 6),
        _event("payee_added", 4),
        _event("limit_raised", 2),
    ]
    result = trailscore_score(
        events,
        now=_NOW,
        include_transfer_attempted=True,
    )
    assert result.bonus_kind == "ordered"
    assert result.bonus == 0.25
    assert result.score >= 0.75
    assert result.score == 1.0
    assert result.window_minutes == 15
    assert result.fired_rules, "score must include fired_rules"


def test_b_four_events_out_of_order_unordered_score():
    events = [
        _event("limit_raised", 8),
        _event("payee_added", 6),
        _event("credential_changed", 4),
        _event("login_new_device", 2),
    ]
    result = trailscore_score(
        events,
        now=_NOW,
        include_transfer_attempted=True,
    )
    assert result.bonus_kind == "unordered"
    assert result.bonus == 0.10
    assert abs(result.score - 0.87) < 1e-9


def test_c_no_events_no_amount_is_zero():
    result = trailscore_score([], now=_NOW, include_transfer_attempted=False)
    assert result.score == 0.0
    assert result.bonus == 0.0
    assert result.bonus_kind == "none"
    assert result.steps_present == []
    assert result.fired_rules == []
    assert result.window_minutes == 15


def test_quote_default_marks_transfer_attempted_without_weight():
    result = trailscore_score([], now=_NOW)
    assert result.score == 0.0
    assert result.bonus_kind == "none"
    assert result.steps_present == ["transfer_attempted"]
    assert result.fired_rules == []


def test_accepts_event_objects_and_ignores_payload():
    events = [
        SimpleNamespace(
            event_type="login_new_device",
            ts=_NOW - timedelta(minutes=3),
            payload={"ignored": True},
        )
    ]
    result = trailscore_score(events, now=_NOW, include_transfer_attempted=False)
    assert "login_new_device" in result.steps_present
    assert abs(result.score - 0.20) < 1e-9
    assert result.bonus_kind == "none"


def test_full_balance_amount_is_derived_not_an_event():
    result = trailscore_score(
        [],
        now=_NOW,
        amount_paise=5000,
        available_balance_paise=5000,
        include_transfer_attempted=False,
    )
    assert "full_balance_amount" in result.steps_present
    assert abs(result.score - 0.20) < 1e-9
    codes = [rule["code"] for rule in result.fired_rules]
    assert "full_balance_amount" in codes


def test_events_outside_window_are_excluded():
    events = [
        _event("login_new_device", 15),
        _event("credential_changed", 16),
    ]
    result = trailscore_score(events, now=_NOW, include_transfer_attempted=False)
    assert result.score == 0.0
    assert result.steps_present == []

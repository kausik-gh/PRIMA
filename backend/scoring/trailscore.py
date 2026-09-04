"""Sequence score for the sender. DecisionService contract only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from backend.core.config import get_config
from backend.core.models import Account, Event

_WEIGHTED_STEPS: tuple[str, ...] = (
    "login_new_device",
    "credential_changed",
    "payee_added",
    "limit_raised",
    "screen_share_active",
    "lookout_dismissed",
)

_CANONICAL_STEPS: tuple[str, ...] = (
    "login_new_device",
    "credential_changed",
    "payee_added",
    "limit_raised",
    "transfer_attempted",
)

_DEFAULT_WEIGHTS: dict[str, float] = {
    "login_new_device": 0.20,
    "credential_changed": 0.22,
    "payee_added": 0.15,
    "limit_raised": 0.20,
    "full_balance_amount": 0.20,
    "screen_share_active": 0.25,
    # Dismissing an explicit Lookout warning right before committing is
    # itself a sequence signal — see payer.py's beneficiary_check_dismiss.
    "lookout_dismissed": 0.25,
}


def trailscore_score(
    account_id: str, amount_paise: int, session: Session
) -> tuple[float, list[dict]]:
    """Return (score, fired_rules) for sender events in the configured window."""
    cfg = get_config().get("trailscore") or {}
    window_minutes = int(cfg.get("window_minutes", 15))
    weights = dict(_DEFAULT_WEIGHTS)
    provided = cfg.get("weights")
    if isinstance(provided, dict):
        for key, value in provided.items():
            if key in weights:
                weights[key] = float(value)
    ordered_bonus = float(cfg.get("ordered_bonus", 0.25))
    unordered_bonus = float(cfg.get("unordered_bonus", 0.10))

    now = datetime.now(timezone.utc)
    in_window = _events_in_window(session, account_id, now, window_minutes)

    present_weighted: set[str] = set()
    canonical_ts: dict[str, datetime] = {}
    for event_type, ts in in_window:
        if event_type in _WEIGHTED_STEPS:
            present_weighted.add(event_type)
        if event_type in _CANONICAL_STEPS:
            previous = canonical_ts.get(event_type)
            if previous is None or ts < previous:
                canonical_ts[event_type] = ts

    if _is_full_balance(session, account_id, amount_paise):
        present_weighted.add("full_balance_amount")

    fired_rules: list[dict] = []
    raw = 0.0
    for step in (*_WEIGHTED_STEPS[:4], "full_balance_amount", "screen_share_active", "lookout_dismissed"):
        if step not in present_weighted:
            continue
        points = float(weights[step])
        raw += points
        fired_rules.append({"code": step, "points": points, "detail": step})

    bonus, bonus_code = _sequence_bonus(canonical_ts, ordered_bonus, unordered_bonus)
    if bonus_code is not None:
        fired_rules.append({"code": bonus_code, "points": bonus, "detail": bonus_code})

    score = min(max(raw + bonus, 0.0), 1.0)
    return score, fired_rules


def _events_in_window(
    session: Session, account_id: str, now: datetime, window_minutes: int
) -> list[tuple[str, datetime]]:
    window_start = now - timedelta(minutes=window_minutes)
    rows = session.exec(select(Event).where(Event.account_id == account_id)).all()
    out: list[tuple[str, datetime]] = []
    for row in rows:
        ts = _as_utc(row.ts)
        if window_start < ts <= now:
            out.append((str(row.event_type), ts))
    return out


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _is_full_balance(session: Session, account_id: str, amount_paise: int) -> bool:
    account = session.get(Account, account_id)
    if account is None:
        return False
    balance = int(account.balance_paise)
    return amount_paise >= 0.90 * balance


def _sequence_bonus(
    canonical_ts: dict[str, datetime],
    ordered_bonus: float,
    unordered_bonus: float,
) -> tuple[float, str | None]:
    present = [step for step in _CANONICAL_STEPS if step in canonical_ts]
    if len(present) < 4:
        return 0.0, None
    times = [canonical_ts[step] for step in present]
    in_order = all(times[i] < times[i + 1] for i in range(len(times) - 1))
    if in_order:
        return float(ordered_bonus), "ordered_bonus"
    return float(unordered_bonus), "unordered_bonus"

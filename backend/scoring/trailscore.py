"""Sequence scorer: events in a time window plus optional amount/balance checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

DEFAULT_WINDOW_MINUTES = 15
DEFAULT_ORDERED_BONUS = 0.25
DEFAULT_UNORDERED_BONUS = 0.10

DEFAULT_WEIGHTS: dict[str, float] = {
    "login_new_device": 0.20,
    "credential_changed": 0.22,
    "payee_added": 0.15,
    "limit_raised": 0.20,
    "full_balance_amount": 0.20,
    "screen_share_active": 0.25,
}

CANONICAL_STEPS: tuple[str, ...] = (
    "login_new_device",
    "credential_changed",
    "payee_added",
    "limit_raised",
    "transfer_attempted",
)

_EVENT_WEIGHTED_STEPS: frozenset[str] = frozenset(
    {
        "login_new_device",
        "credential_changed",
        "payee_added",
        "limit_raised",
        "screen_share_active",
    }
)

_STEP_PRESENT_ORDER: tuple[str, ...] = (
    "login_new_device",
    "credential_changed",
    "payee_added",
    "limit_raised",
    "full_balance_amount",
    "screen_share_active",
    "transfer_attempted",
)

_STEP_DETAILS: dict[str, str] = {
    "login_new_device": "New-device login occurred inside the scoring window.",
    "credential_changed": "A credential change occurred inside the scoring window.",
    "payee_added": "A payee was added inside the scoring window.",
    "limit_raised": "A limit was raised inside the scoring window.",
    "full_balance_amount": "Requested amount is positive and at least the available balance.",
    "screen_share_active": "A screen-share event occurred inside the scoring window.",
}

_BONUS_DETAILS: dict[str, str] = {
    "ordered": "At least four canonical steps appear in canonical order.",
    "unordered": "At least four canonical steps appear, not in canonical order.",
}

BonusKind = Literal["ordered", "unordered", "none"]


@dataclass(frozen=True)
class TrailScoreResult:
    score: float
    steps_present: list[str]
    bonus: float
    bonus_kind: BonusKind
    fired_rules: list[dict[str, Any]]
    window_minutes: int


def trailscore_score(
    events: Iterable[Any] | None,
    *,
    now: datetime | None = None,
    amount_paise: int | None = None,
    available_balance_paise: int | None = None,
    include_transfer_attempted: bool = True,
    config: Mapping[str, Any] | None = None,
) -> TrailScoreResult:
    """Score sender events in a sliding window. Pure; no I/O.

    ``events`` are objects or dicts with ``event_type`` and ``ts`` (datetime).
    ``payload`` is ignored. ``full_balance_amount`` is derived from the amount
    arguments, not from an event. Quote-time scoring should leave
    ``include_transfer_attempted`` at True so transfer is the last canonical
    step (weight 0).
    """
    window_minutes, weights, ordered_bonus, unordered_bonus = _resolve_config(config)
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _as_utc(now)

    window_start = now - timedelta(minutes=window_minutes)
    in_window = _events_in_window(events or (), window_start, now)

    present_weighted: set[str] = set()
    canonical_ts: dict[str, datetime] = {}
    for event_type, ts in in_window:
        if event_type in _EVENT_WEIGHTED_STEPS:
            present_weighted.add(event_type)
        if event_type in CANONICAL_STEPS:
            previous = canonical_ts.get(event_type)
            if previous is None or ts < previous:
                canonical_ts[event_type] = ts

    if _is_full_balance(amount_paise, available_balance_paise):
        present_weighted.add("full_balance_amount")

    if include_transfer_attempted:
        canonical_ts["transfer_attempted"] = now

    raw = 0.0
    fired_rules: list[dict[str, Any]] = []
    for step in _STEP_PRESENT_ORDER:
        if step not in present_weighted:
            continue
        points = float(weights[step])
        raw += points
        fired_rules.append(
            {
                "code": step,
                "points": points,
                "detail": _STEP_DETAILS[step],
            }
        )

    bonus, bonus_kind = _sequence_bonus(
        canonical_ts, ordered_bonus, unordered_bonus
    )
    if bonus_kind != "none":
        fired_rules.append(
            {
                "code": f"{bonus_kind}_bonus",
                "points": bonus,
                "detail": _BONUS_DETAILS[bonus_kind],
            }
        )

    score = min(max(raw + bonus, 0.0), 1.0)
    steps_present = [step for step in _STEP_PRESENT_ORDER if step in present_weighted]
    if "transfer_attempted" in canonical_ts:
        steps_present.append("transfer_attempted")

    if score > 0.0 and not fired_rules:
        raise RuntimeError("score produced without fired_rules")

    return TrailScoreResult(
        score=score,
        steps_present=steps_present,
        bonus=bonus,
        bonus_kind=bonus_kind,
        fired_rules=fired_rules,
        window_minutes=window_minutes,
    )


def _resolve_config(
    config: Mapping[str, Any] | None,
) -> tuple[int, dict[str, float], float, float]:
    section: Mapping[str, Any] = {}
    if isinstance(config, Mapping):
        raw_section = config.get("trailscore")
        if isinstance(raw_section, Mapping):
            section = raw_section

    window_minutes = int(section.get("window_minutes", DEFAULT_WINDOW_MINUTES))
    ordered_bonus = float(section.get("ordered_bonus", DEFAULT_ORDERED_BONUS))
    unordered_bonus = float(section.get("unordered_bonus", DEFAULT_UNORDERED_BONUS))

    weights = dict(DEFAULT_WEIGHTS)
    provided = section.get("weights")
    if isinstance(provided, Mapping):
        for key, value in provided.items():
            if key in weights:
                weights[key] = float(value)

    return window_minutes, weights, ordered_bonus, unordered_bonus


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _field(event: Any, name: str) -> Any:
    if isinstance(event, Mapping):
        return event.get(name)
    return getattr(event, name, None)


def _events_in_window(
    events: Iterable[Any],
    window_start: datetime,
    now: datetime,
) -> list[tuple[str, datetime]]:
    out: list[tuple[str, datetime]] = []
    for event in events:
        event_type = _field(event, "event_type")
        ts = _field(event, "ts")
        if not event_type or not isinstance(ts, datetime):
            continue
        ts = _as_utc(ts)
        if window_start < ts <= now:
            out.append((str(event_type), ts))
    return out


def _is_full_balance(
    amount_paise: int | None, available_balance_paise: int | None
) -> bool:
    if amount_paise is None or available_balance_paise is None:
        return False
    return amount_paise > 0 and amount_paise >= available_balance_paise


def _sequence_bonus(
    canonical_ts: Mapping[str, datetime],
    ordered_bonus: float,
    unordered_bonus: float,
) -> tuple[float, BonusKind]:
    present: Sequence[str] = [step for step in CANONICAL_STEPS if step in canonical_ts]
    if len(present) < 4:
        return 0.0, "none"
    times = [canonical_ts[step] for step in present]
    in_order = all(times[i] < times[i + 1] for i in range(len(times) - 1))
    if in_order:
        return float(ordered_bonus), "ordered"
    return float(unordered_bonus), "unordered"

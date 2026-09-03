"""Context score from note + recent call_context events. DecisionService contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from backend.context.lexicon import match_categories
from backend.core.config import get_config
from backend.core.models import Event

_DEFAULT_WEIGHTS: dict[str, float] = {
    "urgency": 0.25,
    "secrecy": 0.30,
    "fear": 0.30,
    "greed": 0.15,
    "bypass_approval": 0.30,
}


def contextflag_score(
    note: str | None, account_id: str, session: Session
) -> tuple[float, list[dict]]:
    """Return (score, fired_rules). Rules carry category names only, never spans."""
    cfg = get_config()
    weights = dict(_DEFAULT_WEIGHTS)
    section = cfg.get("contextflag") or {}
    provided = section.get("weights") if isinstance(section, dict) else None
    if isinstance(provided, dict):
        for key, value in provided.items():
            if key in weights:
                weights[key] = float(value)
    trail_cfg = cfg.get("trailscore") or {}
    window_minutes = int(trail_cfg.get("window_minutes", 15)) if isinstance(trail_cfg, dict) else 15

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)
    parts: list[str] = []
    if note:
        parts.append(str(note))
    rows = session.exec(select(Event).where(Event.account_id == account_id)).all()
    for row in rows:
        if row.event_type != "call_context":
            continue
        ts = row.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not (window_start < ts <= now):
            continue
        payload = row.payload if isinstance(row.payload, dict) else {}
        text = payload.get("text")
        if text:
            parts.append(str(text))

    matched = match_categories(" ".join(parts))
    fired_rules: list[dict] = []
    raw = 0.0
    for category in matched:
        points = float(weights[category])
        raw += points
        fired_rules.append({"code": category, "points": points, "detail": category})
    score = min(max(raw, 0.0), 1.0)
    return score, fired_rules

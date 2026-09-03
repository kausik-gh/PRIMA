# Remove stub branch when P2 fusion/ladder are on main.

"""Decision evaluation for payer quote. Tries real fusion/ladder, else fixture stub."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "tier4_decision.json"

_DEFAULT_WEIGHTS = {"ringwatch": 0.40, "trailscore": 0.35, "contextflag": 0.25}


def _load_tier4_fixture() -> dict[str, Any]:
    import json

    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _age_days(created_at: datetime, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0, (now - created_at).days)


def _try_real_evaluate(
    sender: Any,
    beneficiary: Any,
    amount_paise: int,
    note: str | None,
    *,
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        from backend.scoring import fusion, ladder  # type: ignore
    except Exception:
        return None
    # Real path reserved for when P2 modules land; keep signature stable.
    ring = float(getattr(fusion, "ringwatch_score", lambda *_a, **_k: 0.0)(sender, beneficiary))
    trail = float(getattr(fusion, "trailscore_score", lambda *_a, **_k: 0.0)(sender))
    ctx = float(getattr(fusion, "contextflag_score", lambda *_a, **_k: 0.0)(note or ""))
    fused, bonus, rules = fusion.fuse(ring, trail, ctx)  # type: ignore[attr-defined]
    tier, verdict, _action = ladder.tier(fused)  # type: ignore[attr-defined]
    return {
        "ringwatch_score": ring,
        "trailscore_score": trail,
        "contextflag_score": ctx,
        "cross_term_bonus": float(bonus or 0),
        "fused_score": float(fused),
        "tier": int(tier),
        "verdict": str(verdict),
        "rules_fired": list(rules or []),
        "meta": meta,
    }


def evaluate(
    sender: Any,
    beneficiary: Any,
    amount_paise: int,
    note: str | None,
    *,
    prior_payments: int = 0,
    config_version: str = "1.0.0-stub",
    unique_senders_today: int | None = None,
) -> dict[str, Any]:
    """Return a reasonline-ready decision body (without id / quote_at / reasons)."""
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
        raise TypeError("amount_paise must be integer paise")
    bene_age = _age_days(beneficiary.created_at)
    meta = {
        "beneficiary_age_days": bene_age,
        "unique_senders_today": unique_senders_today if unique_senders_today is not None else (14 if "quickcash" in beneficiary.handle else 1),
        "retention_minutes_typical": 12 if "quickcash" in beneficiary.handle else 240,
        "minutes_since_limit_raised": 8,
        "minutes_since_new_device": 15,
        "prior_payments_to_beneficiary": int(prior_payments),
        "fusion_weights": dict(_DEFAULT_WEIGHTS),
        "model_sha256": {
            "rf": "fixture_rf_sha256_not_a_real_model_digest_0001",
            "gnn": "fixture_gnn_sha256_not_a_real_model_digest_0001",
        },
    }
    real = _try_real_evaluate(sender, beneficiary, amount_paise, note, meta=meta)
    if real is not None:
        real["amount_paise"] = amount_paise
        real["sender_id"] = sender.id
        real["beneficiary_id"] = beneficiary.id
        real["config_version"] = config_version
        return real

    note_s = note or ""
    force_tier4 = ("quickcash" in beneficiary.handle) or (len(note_s.strip()) >= 20)
    if force_tier4:
        fixture = _load_tier4_fixture()
        body = deepcopy(fixture)
        body.pop("id", None)
        body.pop("quote_at", None)
        body["sender_id"] = sender.id
        body["beneficiary_id"] = beneficiary.id
        body["amount_paise"] = amount_paise
        body["config_version"] = config_version
        body_meta = dict(body.get("meta") or {})
        body_meta.update(meta)
        if "quickcash" in beneficiary.handle:
            body_meta["beneficiary_age_days"] = max(bene_age, 6)
            body_meta["unique_senders_today"] = 14
        body_meta["prior_payments_to_beneficiary"] = int(prior_payments)
        body["meta"] = body_meta
        body["tier"] = 4
        body["verdict"] = "high_risk"
        body["fused_score"] = 0.859
        return body

    if amount_paise >= 1_000_000:
        return {
            "sender_id": sender.id,
            "beneficiary_id": beneficiary.id,
            "amount_paise": amount_paise,
            "ringwatch_score": 0.22,
            "trailscore_score": 0.18,
            "contextflag_score": 0.05,
            "cross_term_bonus": 0.0,
            "fused_score": 0.25,
            "tier": 1,
            "verdict": "watch",
            "rules_fired": [
                {"code": "fresh_fan_in", "points": 1, "detail": f"account {bene_age} days old"},
            ],
            "config_version": config_version,
            "meta": meta,
        }

    verdict = "known" if prior_payments >= 1 else "no_history"
    return {
        "sender_id": sender.id,
        "beneficiary_id": beneficiary.id,
        "amount_paise": amount_paise,
        "ringwatch_score": 0.02,
        "trailscore_score": 0.01,
        "contextflag_score": 0.0,
        "cross_term_bonus": 0.0,
        "fused_score": 0.05,
        "tier": 0,
        "verdict": verdict,
        "rules_fired": [],
        "config_version": config_version,
        "meta": meta,
    }

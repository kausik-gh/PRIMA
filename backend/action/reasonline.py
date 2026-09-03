"""One decision, three checkable facts plus a counterfactual.

Full drop-each-rule re-score lands when fusion/ladder are importable (later).
Do not call scorers here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from backend.action.circuit_breaker import format_paise

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "tier4_decision.json"

BANNED_WORDS = (
    "fraud",
    "mule",
    "scam",
    "criminal",
    "illegal",
    "blocked",
    "declined",
    "suspended",
    "frozen",
)

HEADLINES = {
    "high_risk": "Money sent here usually leaves within minutes.",
    "suspicious": "This account is behaving like a collection point.",
    "watch": "This account is new to the network.",
    "no_history": "Nothing unusual about this account.",
    "known": "You've paid this account before.",
}

DEFAULT_WEIGHTS = {"ringwatch": 0.40, "trailscore": 0.35, "contextflag": 0.25}


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _meta(decision: dict) -> dict:
    meta = decision.get("meta")
    return meta if isinstance(meta, dict) else {}


def _headline(decision: dict) -> str:
    prior = _meta(decision).get("prior_payments_to_beneficiary")
    if isinstance(prior, int) and prior >= 1:
        return HEADLINES["known"]
    verdict = str(decision.get("verdict") or "")
    return HEADLINES.get(verdict, HEADLINES["no_history"])


def _facts(decision: dict) -> list[str]:
    meta = _meta(decision)
    candidates: list[str] = []
    age = meta.get("beneficiary_age_days")
    if age is not None:
        candidates.append(f"This account was opened {age} days ago.")
    senders = meta.get("unique_senders_today")
    if senders is not None:
        candidates.append(f"{senders} different people have sent it money today.")
    if meta.get("prior_payments_to_beneficiary") == 0:
        candidates.append("You have never paid this account before.")
    retention = meta.get("retention_minutes_typical")
    if retention is not None:
        candidates.append(
            f"Money that arrives here usually leaves within {retention} minutes."
        )
    limit = meta.get("minutes_since_limit_raised")
    if limit is not None:
        candidates.append(f"Your transfer limit was raised {limit} minutes ago.")
    device = meta.get("minutes_since_new_device")
    if device is not None:
        candidates.append(
            f"A new device signed in to your account {device} minutes ago."
        )
    return candidates[:3]


def _counterfactual(decision: dict) -> str:
    # Full drop-each-rule re-score lands when fusion/ladder are importable (later).
    # Do not call scorers here.
    meta = _meta(decision)
    prior = meta.get("prior_payments_to_beneficiary")
    age = meta.get("beneficiary_age_days")
    if prior == 0:
        return "This would not have been flagged if you had paid this account before."
    if age is not None and age < 30:
        return "This would not have been flagged if the account were older than 30 days."
    return "This would not have been flagged if fewer risk signals had fired together."


def assert_user_reason_safe(user_reason: dict) -> None:
    facts = user_reason.get("facts")
    if not isinstance(facts, list) or len(facts) != 3:
        raise ValueError("user_reason.facts must be exactly 3 strings")
    blob = " ".join(
        [
            str(user_reason.get("headline") or ""),
            str(user_reason.get("counterfactual") or ""),
            *[str(item) for item in facts],
        ]
    ).lower()
    for word in BANNED_WORDS:
        if word in blob:
            raise ValueError(f"banned word in user_reason: {word}")


def user(decision: dict) -> dict:
    format_paise(int(decision["amount_paise"]))
    facts = _facts(decision)
    if len(facts) != 3:
        raise ValueError("need exactly 3 checkable facts from decision meta")
    reason = {
        "headline": _headline(decision),
        "facts": facts,
        "counterfactual": _counterfactual(decision),
    }
    assert_user_reason_safe(reason)
    return reason


def bank(decision: dict) -> dict:
    format_paise(int(decision["amount_paise"]))
    meta = _meta(decision)
    weights = meta.get("fusion_weights") if isinstance(meta.get("fusion_weights"), dict) else {}
    ring_w = float(weights.get("ringwatch", DEFAULT_WEIGHTS["ringwatch"]))
    trail_w = float(weights.get("trailscore", DEFAULT_WEIGHTS["trailscore"]))
    ctx_w = float(weights.get("contextflag", DEFAULT_WEIGHTS["contextflag"]))
    ring_v = float(decision["ringwatch_score"])
    trail_v = float(decision["trailscore_score"])
    ctx_v = float(decision["contextflag_score"])
    cross_v = float(decision.get("cross_term_bonus") or 0)
    contributions = [
        {
            "scorer": "ringwatch",
            "weight": round(ring_w, 3),
            "value": ring_v,
            "contribution": round(ring_w * ring_v, 3),
        },
        {
            "scorer": "trailscore",
            "weight": round(trail_w, 3),
            "value": trail_v,
            "contribution": round(trail_w * trail_v, 3),
        },
        {
            "scorer": "contextflag",
            "weight": round(ctx_w, 3),
            "value": ctx_v,
            "contribution": round(ctx_w * ctx_v, 3),
        },
        {
            "scorer": "cross_term",
            "weight": None,
            "value": cross_v,
            "contribution": round(cross_v, 3),
        },
    ]
    fired = list(decision.get("rules_fired") or [])
    scored = [dict(rule) for rule in fired if int(rule.get("points") or 0) > 0]
    rest = [dict(rule) for rule in fired if int(rule.get("points") or 0) <= 0]
    return {"contributions": contributions, "rules": scored + rest}


def _canonical_json(obj: dict) -> str:
    """Canonical JSON for hashing: sort_keys=True, separators=(',', ':'), ensure_ascii=False."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_sha256(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def regulator(decision: dict) -> dict:
    """Immutable signed record. Pure function of decision; does not mutate the input."""
    format_paise(int(decision["amount_paise"]))
    meta = _meta(decision)
    models = meta.get("model_sha256") if isinstance(meta.get("model_sha256"), dict) else {}
    user_reason = user(decision)
    bank_reason = bank(decision)
    rules_fired = copy.deepcopy(list(decision.get("rules_fired") or []))
    payload = {
        "decision_id": decision["id"],
        "fused": decision["fused_score"],
        "sub_scores": {
            "ringwatch": decision["ringwatch_score"],
            "trailscore": decision["trailscore_score"],
            "contextflag": decision["contextflag_score"],
            "cross_term_bonus": decision.get("cross_term_bonus") or 0,
        },
        "rules_fired": rules_fired,
        "tier": decision["tier"],
        "verdict": decision["verdict"],
        "config_version": decision["config_version"],
        "model_sha256": {
            "rf": models.get("rf"),
            "gnn": models.get("gnn"),
        },
        "quote_at": decision.get("quote_at"),
        "commit_at": decision.get("commit_at"),
        "user_reason": user_reason,
        "bank_reason": bank_reason,
    }
    digest = _payload_sha256(payload)
    return {**payload, "sha256_of_payload": digest}


def verify_regulator_record(record: dict) -> bool:
    if "sha256_of_payload" not in record:
        return False
    payload = {key: value for key, value in record.items() if key != "sha256_of_payload"}
    return _payload_sha256(payload) == record["sha256_of_payload"]

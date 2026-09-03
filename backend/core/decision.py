"""Pre-commitment quote: score, persist a quoted tx + RiskDecision, move no money."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from backend.core.config import get_config, get_config_version
from backend.core.db import engine
from backend.core.ledger import account_by_handle
from backend.core.models import RiskDecision, Transaction, new_id, utc_now
from backend.graph.pathgraph import get_graph, node_features, rebuild_from_db
from backend.scoring.ringwatch import ringwatch_score

HEADLINES = {
    "known": "You've paid this account before.",
    "no_history": "Nothing unusual about this account.",
    "watch": "This account is new to the network.",
    "suspicious": "This account is behaving like a collection point.",
    "high_risk": "Money sent here usually leaves within minutes.",
}

QUOTE_CHANNEL = "upi"


def _has_account_nodes(graph) -> bool:
    for _, data in graph.nodes(data=True):
        if data.get("node_type") == "account":
            return True
    return False


def _trailscore_score(
    account_id: str,
    amount_paise: int,
    session: Session,
) -> tuple[float, list[dict]]:
    try:
        from backend.scoring.trailscore import trailscore_score
    except ImportError:
        return 0.0, []
    return trailscore_score(account_id, amount_paise, session)


def _contextflag_score(
    note: str | None,
    account_id: str,
    session: Session,
) -> tuple[float, list[dict]]:
    try:
        from backend.scoring.contextflag import contextflag_score
    except ImportError:
        return 0.0, []
    return contextflag_score(note, account_id, session)


def fuse(
    ringwatch: float,
    trailscore: float,
    contextflag: float,
    cfg: dict[str, Any],
) -> tuple[float, float]:
    try:
        from backend.scoring.fusion import fuse as p2_fuse
        return p2_fuse(ringwatch, trailscore, contextflag, cfg)
    except ImportError:
        pass
    fusion = cfg["fusion"]
    base = (
        float(fusion["ringwatch_weight"]) * ringwatch
        + float(fusion["trailscore_weight"]) * trailscore
        + float(fusion["contextflag_weight"]) * contextflag
    )
    cross = fusion.get("cross_term") or {}
    bonus = 0.0
    if cross.get("enabled"):
        trail_min = float(cross["trail_min"])
        ring_max = float(cross["ring_max"])
        if trailscore >= trail_min and ringwatch < ring_max:
            bonus = float(cross["bonus"])
    fused = min(base + bonus, 1.0)
    return fused, bonus


def ladder_tier(fused: float, cfg: dict[str, Any]) -> tuple[int, str]:
    try:
        from backend.scoring.ladder import ladder_tier as p2_ladder
        return p2_ladder(fused, cfg)
    except ImportError:
        pass
    rows = list(cfg["ladder"])
    for row in rows:
        if fused < float(row["max"]):
            return int(row["tier"]), str(row["action"])
    last = rows[-1]
    return int(last["tier"]), str(last["action"])


def _verdict_from_fused(fused: float) -> str:
    if fused < 0.15:
        return "no_history"
    if fused < 0.40:
        return "watch"
    if fused < 0.70:
        return "suspicious"
    return "high_risk"


def _known_payee(session: Session, sender_id: str, beneficiary_id: str) -> bool:
    row = session.exec(
        select(Transaction).where(
            Transaction.sender_id == sender_id,
            Transaction.receiver_id == beneficiary_id,
            Transaction.status == "settled",
        )
    ).first()
    return row is not None


def _facts(
    *,
    known_payee: bool,
    age_days: int,
    in_degree: int,
) -> list[str]:
    lines: list[str] = []
    lines.append(f"This account was opened {age_days} days ago.")
    lines.append(f"{in_degree} different people have sent it money.")
    if not known_payee:
        lines.append("You have never paid this account before.")
    return lines[:3]


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def evaluate_quote(
    session: Session,
    sender_handle: str,
    beneficiary_handle: str,
    amount_paise: int,
    note: str | None = None,
) -> dict[str, Any]:
    """Score a payment attempt and persist a quoted row. Does not change balances.

    Inbound money is never held. Only outbound. This phase writes a quote only;
    it does not write amount-scoped hold rows even at tier 3/4.
    """
    sender = account_by_handle(session, sender_handle)
    beneficiary = account_by_handle(session, beneficiary_handle)
    if sender is None:
        raise ValueError(f"unknown sender: {sender_handle}")
    if beneficiary is None:
        raise ValueError(f"unknown beneficiary: {beneficiary_handle}")

    cfg = get_config()
    if not _has_account_nodes(get_graph()):
        rebuild_from_db(session)

    # RingWatch scores the beneficiary. TrailScore/ContextFlag score the sender
    # (P2 modules if present; otherwise 0.0 and []).
    ring = ringwatch_score(beneficiary.id, session)
    trail_score, trail_rules = _trailscore_score(sender.id, amount_paise, session)
    context_score, context_rules = _contextflag_score(note, sender.id, session)

    fused, cross_bonus = fuse(ring.score, trail_score, context_score, cfg)
    fused = max(0.0, min(1.0, fused))
    tier, action_kind = ladder_tier(fused, cfg)
    # Prior settled payment: verdict known, tier 0. Sub-scores stay the real ones.
    known = _known_payee(session, sender.id, beneficiary.id)
    if known:
        verdict = "known"
        tier = 0
        action_kind = "pass_silent"
    else:
        verdict = _verdict_from_fused(fused)

    feats = node_features(beneficiary.id, get_graph(), session)
    age_days = int(feats.get("account_age_days") or 0)
    in_degree = int(feats.get("in_degree") or 0)
    facts = _facts(known_payee=known, age_days=age_days, in_degree=in_degree)
    headline = HEADLINES[verdict]
    counterfactual = ""

    rules_fired: list[dict] = list(ring.rules_fired) + list(trail_rules) + list(context_rules)

    quote_at = utc_now()
    config_version = get_config_version()
    hold_cfg = cfg.get("scoped_hold") or {}
    immediate = int(hold_cfg.get("immediate_paise") or 0) if tier >= 3 else 0
    held = max(0, int(amount_paise) - immediate) if tier >= 3 else 0
    cooling = int(hold_cfg.get("cooling_minutes") or 0)

    # Quoted rows are not money movement. Do not change any balance_paise.
    tx_id = new_id()
    decision_id = new_id()
    tx = Transaction(
        id=tx_id,
        sender_id=sender.id,
        receiver_id=beneficiary.id,
        amount_paise=int(amount_paise),
        channel=QUOTE_CHANNEL,
        note=note,
        status="quoted",
        attempted_at=quote_at,
        settled_at=None,
        taint_ratio=0.0,
        is_seeded_attack=False,
    )
    session.add(tx)
    session.flush()

    # Append-only: insert the row complete. Do not UPDATE score fields after flush.
    regulator_record = {
        "decision_id": decision_id,
        "fused": float(fused),
        "sub_scores": {
            "ringwatch": float(ring.score),
            "trailscore": float(trail_score),
            "contextflag": float(context_score),
        },
        "rules_fired": rules_fired,
        "config_version": config_version,
        "quote_at": _iso(quote_at),
    }
    decision = RiskDecision(
        id=decision_id,
        transaction_id=tx_id,
        sender_id=sender.id,
        beneficiary_id=beneficiary.id,
        amount_paise=int(amount_paise),
        ringwatch_score=float(ring.score),
        trailscore_score=float(trail_score),
        contextflag_score=float(context_score),
        cross_term_bonus=float(cross_bonus),
        fused_score=float(fused),
        tier=int(tier),
        verdict=verdict,
        rules_fired=rules_fired,
        user_reason={
            "headline": headline,
            "facts": facts,
            "counterfactual": counterfactual,
        },
        bank_reason={
            "contributions": {
                "ringwatch": float(ring.score),
                "trailscore": float(trail_score),
                "contextflag": float(context_score),
            },
            "rules": rules_fired,
        },
        regulator_record=regulator_record,
        payload_sha256=_canonical_sha256(regulator_record),
        config_version=config_version,
        quote_at=quote_at,
        commit_at=None,
        lead_time_ms=None,
    )
    session.add(decision)
    session.flush()

    return {
        "decision_id": decision.id,
        "verdict": verdict,
        "tier": tier,
        "headline": headline,
        "facts": facts,
        "counterfactual": counterfactual,
        "action": {
            "kind": action_kind,
            "immediate_paise": immediate,
            "held_paise": held,
            "cooling_minutes": cooling,
            "trusted_contact_name": None,
        },
        "probe": None,
        "lead_time_started_at": _iso(quote_at),
        "sub_scores": {
            "ringwatch": float(ring.score),
            "trailscore": float(trail_score),
            "contextflag": float(context_score),
            "fused": float(fused),
            "cross_term_bonus": float(cross_bonus),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist a pre-commitment quote")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_quote = sub.add_parser("quote")
    p_quote.add_argument("--from", dest="sender_handle", required=True)
    p_quote.add_argument("--to", dest="beneficiary_handle", required=True)
    p_quote.add_argument("--amount", dest="amount_paise", type=int, required=True)
    p_quote.add_argument("--note", default=None)
    args = parser.parse_args()
    if args.cmd != "quote":
        raise SystemExit(f"unknown command: {args.cmd}")
    with Session(engine) as session:
        payload = evaluate_quote(
            session,
            args.sender_handle,
            args.beneficiary_handle,
            args.amount_paise,
            args.note,
        )
        session.commit()
    print(json.dumps(payload))


if __name__ == "__main__":
    main()

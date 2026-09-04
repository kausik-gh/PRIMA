"""Read-only console graph, decisions, investigate, and PS3 metrics.

Metrics MAY read ground_truth_role / is_seeded_attack. Scorers must not.
Inbound is never held. There is no freeze-account helper here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any
import uuid

from sqlmodel import Session, col, select

from backend.action.payer_ledger import active_hold_rows, available_paise, iso
from backend.action.scoped_hold import COOLING_MINUTES, next_reason_ref
from backend.core.config import get_config
from backend.core.decision import _verdict_from_fused, fuse, ladder_tier
from backend.core.models import (
    Account,
    ComprehensionProbe,
    Event,
    PatternSignature,
    RiskDecision,
    ScopedHold,
    Transaction,
    utc_now,
)
from backend.graph.taint import mark_fraudulent
from backend.scoring.contextflag import contextflag_score
from backend.scoring.ringwatch import ringwatch_score
from backend.scoring.trailscore import trailscore_score

AVAILABLE_ACTIONS = [
    "open_scoped_hold",
    "mark_reviewed",
    "export_regulator_record",
]


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _age_days(created_at: datetime, now: datetime | None = None) -> int:
    now = now or utc_now()
    return max(0, int((_aware(now) - _aware(created_at)).total_seconds() // 86400))


def _accounts_by_id(session: Session) -> dict[str, Account]:
    return {row.id: row for row in session.exec(select(Account)).all()}


def _latest_decision_for(
    session: Session, account_id: str
) -> RiskDecision | None:
    rows = session.exec(select(RiskDecision)).all()
    matching = [
        row
        for row in rows
        if row.sender_id == account_id or row.beneficiary_id == account_id
    ]
    if not matching:
        return None
    matching.sort(key=lambda row: _aware(row.quote_at), reverse=True)
    return matching[0]


def _held_account_ids(session: Session) -> set[str]:
    rows = session.exec(select(ScopedHold)).all()
    return {row.account_id for row in rows if row.released_at is None}


def _top_rule(rules: list[Any] | None) -> str | None:
    fired = [dict(item) for item in (rules or []) if isinstance(item, dict)]
    if not fired:
        return None
    fired.sort(key=lambda item: int(item.get("points") or 0), reverse=True)
    code = fired[0].get("code")
    return str(code) if code is not None else None


def decision_item(session: Session, row: RiskDecision) -> dict[str, Any]:
    accounts = _accounts_by_id(session)
    sender = accounts.get(row.sender_id)
    receiver = accounts.get(row.beneficiary_id)
    return {
        "decision_id": row.id,
        "ts": iso(row.quote_at),
        "sender": sender.handle if sender is not None else row.sender_id,
        "receiver": receiver.handle if receiver is not None else row.beneficiary_id,
        "amount_paise": row.amount_paise,
        "tier": row.tier,
        "fused_score": row.fused_score,
        "top_rule": _top_rule(list(row.rules_fired or [])),
        "verdict": row.verdict,
    }


def graph_payload(
    session: Session, *, window: int = 500, bank: str = "ALL"
) -> dict[str, Any]:
    window = max(1, min(int(window), 2000))
    bank_key = (bank or "ALL").strip().upper()
    accounts = list(session.exec(select(Account)).all())
    if bank_key != "ALL":
        accounts = [row for row in accounts if row.bank_code.upper() == bank_key]
    allowed = {row.id for row in accounts}
    held_ids = _held_account_ids(session)

    txs = list(session.exec(select(Transaction)).all())
    txs.sort(key=lambda row: _aware(row.attempted_at), reverse=True)
    links: list[dict[str, Any]] = []
    linked_ids: set[str] = set()
    for tx in txs:
        if tx.sender_id not in allowed or tx.receiver_id not in allowed:
            continue
        decision = session.exec(
            select(RiskDecision).where(RiskDecision.transaction_id == tx.id)
        ).first()
        links.append(
            {
                "source": tx.sender_id,
                "target": tx.receiver_id,
                "amount_paise": tx.amount_paise,
                "ts": iso(tx.attempted_at),
                "taint": tx.taint_ratio,
                "decision_id": decision.id if decision is not None else None,
            }
        )
        linked_ids.add(tx.sender_id)
        linked_ids.add(tx.receiver_id)
        if len(links) >= window:
            break

    stage_handles = {
        "ramesh@prima",
        "priya.k@prima",
        "grocery@prima",
        "rentals@prima",
        "quickcash@prima",
        "merchant.ok@prima",
    }
    nodes = []
    for acct in accounts:
        keep = (
            acct.id in linked_ids
            or acct.is_demo_guest
            or acct.handle in stage_handles
        )
        if not keep:
            continue
        latest = _latest_decision_for(session, acct.id)
        nodes.append(
            {
                "id": acct.id,
                "handle": acct.handle,
                "label": acct.display_name,
                "bank": acct.bank_code,
                "tier": latest.tier if latest is not None else 0,
                "risk": latest.fused_score if latest is not None else 0.0,
                "age_days": _age_days(acct.created_at),
                "is_held": acct.id in held_ids,
                "is_guest": bool(acct.is_demo_guest),
            }
        )
    return {"nodes": nodes, "links": links}


def graph_node(session: Session, account_id: str) -> dict[str, Any] | None:
    acct = session.get(Account, account_id)
    if acct is None:
        return None
    latest = _latest_decision_for(session, account_id)
    held = any(row.released_at is None for row in active_hold_rows(session, account_id))
    return {
        "id": acct.id,
        "handle": acct.handle,
        "label": acct.display_name,
        "bank": acct.bank_code,
        "tier": latest.tier if latest is not None else 0,
        "risk": latest.fused_score if latest is not None else 0.0,
        "age_days": _age_days(acct.created_at),
        "is_held": held,
        "is_guest": bool(acct.is_demo_guest),
    }


def graph_link_for_tx(session: Session, tx: Transaction) -> dict[str, Any]:
    decision = None
    if tx.id:
        decision = session.exec(
            select(RiskDecision).where(RiskDecision.transaction_id == tx.id)
        ).first()
    return {
        "source": tx.sender_id,
        "target": tx.receiver_id,
        "amount_paise": tx.amount_paise,
        "ts": iso(tx.attempted_at),
        "taint": tx.taint_ratio,
        "decision_id": decision.id if decision is not None else None,
    }


def list_decisions(
    session: Session, *, limit: int = 100, since: datetime | None = None
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    rows = list(session.exec(select(RiskDecision)).all())
    if since is not None:
        since_aware = _aware(since)
        rows = [row for row in rows if _aware(row.quote_at) >= since_aware]
    rows.sort(key=lambda row: _aware(row.quote_at), reverse=True)
    return {"items": [decision_item(session, row) for row in rows[:limit]]}


def _contributions_from_values(
    ring: float, trail: float, ctx: float, cross_bonus: float
) -> list[dict[str, Any]]:
    cfg = get_config()
    fusion = cfg.get("fusion") if isinstance(cfg.get("fusion"), dict) else {}
    weights = {
        "ringwatch": float(fusion.get("ringwatch_weight", 0.40)),
        "trailscore": float(fusion.get("trailscore_weight", 0.35)),
        "contextflag": float(fusion.get("contextflag_weight", 0.25)),
    }
    values = {"ringwatch": ring, "trailscore": trail, "contextflag": ctx}
    out = [
        {
            "scorer": name,
            "weight": weights[name],
            "value": values[name],
            "contribution": round(weights[name] * values[name], 3),
        }
        for name in ("ringwatch", "trailscore", "contextflag")
    ]
    out.append(
        {
            "scorer": "cross_term",
            "weight": None,
            "value": round(cross_bonus, 3),
            "contribution": round(cross_bonus, 3),
        }
    )
    return out


def _rules_from_lists(*rule_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rules in rule_lists:
        for item in rules or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "code": item.get("code"),
                    "points": item.get("points"),
                    "detail": item.get("detail"),
                }
            )
    return out


def investigate_payload(session: Session, account_id: str) -> dict[str, Any] | None:
    """Investigation is always this account's OWN risk profile.

    RingWatch is this account's network position (fan-in/out, taint, GNN).
    TrailScore is this account's OWN event sequence — it must NOT be pulled
    from a decision where this account was only the beneficiary, or the
    sender's trail leaks onto every account they've recently paid. Both are
    recomputed fresh here rather than read off `_latest_decision_for`, which
    only reflects the role this account played in one past transaction.
    """
    acct = session.get(Account, account_id)
    if acct is None:
        return None

    ring_result = ringwatch_score(account_id, session)
    trail_score, trail_rules = trailscore_score(account_id, amount_paise=0, session=session)
    ctx_score, ctx_rules = contextflag_score(None, account_id, session)

    cfg = get_config()
    fused, cross_bonus = fuse(ring_result.score, trail_score, ctx_score, cfg)
    fused = max(0.0, min(1.0, fused))
    tier, _action = ladder_tier(fused, cfg)
    verdict = _verdict_from_fused(fused)

    sub = {
        "ringwatch": float(ring_result.score),
        "trailscore": float(trail_score),
        "contextflag": float(ctx_score),
    }
    contributions = _contributions_from_values(
        ring_result.score, trail_score, ctx_score, cross_bonus or 0.0
    )
    rules = _rules_from_lists(ring_result.rules_fired, trail_rules, ctx_rules)

    events = [
        row
        for row in session.exec(select(Event)).all()
        if row.account_id == account_id
    ]
    events.sort(key=lambda row: _aware(row.ts), reverse=True)
    timeline = [
        {
            "ts": iso(row.ts),
            "type": row.event_type,
            "summary": row.event_type.replace("_", " "),
        }
        for row in events[:50]
    ]

    txs = [
        row
        for row in session.exec(select(Transaction)).all()
        if row.sender_id == account_id or row.receiver_id == account_id
    ]
    txs.sort(key=lambda row: _aware(row.attempted_at), reverse=True)
    accounts = _accounts_by_id(session)
    neighbours = []
    for tx in txs[:20]:
        outbound = tx.sender_id == account_id
        other_id = tx.receiver_id if outbound else tx.sender_id
        other = accounts.get(other_id)
        neighbours.append(
            {
                "id": other_id,
                "handle": other.handle if other is not None else other_id,
                "direction": "out" if outbound else "in",
                "amount_paise": tx.amount_paise,
                "ts": iso(tx.attempted_at),
            }
        )

    return {
        "account": {
            "id": acct.id,
            "handle": acct.handle,
            "display_name": acct.display_name,
            "bank_code": acct.bank_code,
            "created_at": iso(acct.created_at),
            "balance_paise": acct.balance_paise,
            "available_paise": available_paise(session, acct),
            "age_days": _age_days(acct.created_at),
            "is_held": bool(active_hold_rows(session, acct.id)),
        },
        "sub_scores": sub,
        "fused_score": round(fused, 3),
        "tier": tier,
        "verdict": verdict,
        "contributions": contributions,
        "rules_fired": rules,
        "event_timeline": timeline,
        "neighbours": neighbours,
        "pattern_match": None,
        "available_actions": list(AVAILABLE_ACTIONS),
    }


def _rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return num / den


def ps3_metrics(session: Session) -> dict[str, Any]:
    """Five PS3 metrics only. Ground-truth columns are allowed here."""
    txs = list(session.exec(select(Transaction)).all())
    decisions = list(session.exec(select(RiskDecision)).all())
    probes = list(session.exec(select(ComprehensionProbe)).all())
    structures = list(session.exec(select(PatternSignature)).all())

    tx_by_id = {row.id: row for row in txs}
    legit_tx = [row for row in txs if not row.is_seeded_attack]
    legit_ids = {row.id for row in legit_tx}

    prevented = 0
    for row in decisions:
        if row.tier < 3:
            continue
        tx = tx_by_id.get(row.transaction_id or "")
        if tx is None or not tx.is_seeded_attack:
            continue
        if tx.status in ("held", "cancelled"):
            prevented += tx.amount_paise

    lead_times = [int(row.lead_time_ms) for row in decisions if row.lead_time_ms is not None]
    median_lead = int(median(lead_times)) if lead_times else 0

    challenged = 0
    for row in decisions:
        if row.tier < 1:
            continue
        if row.transaction_id and row.transaction_id in legit_ids:
            challenged += 1
        elif not row.transaction_id:
            continue

    shown = len(probes)
    correct = 0
    for probe in probes:
        if probe.chosen_index is None or probe.answered_at is None:
            continue
        if probe.chosen_index == probe.correct_index:
            correct += 1

    seeded_structures = len(structures)
    covered = 0
    if seeded_structures:
        # A structure is covered if any decision at tier ≥ 2 exists for a seeded attack tx.
        # Thin seed has zero signatures; leave coverage at 0 with an honest denominator.
        attack_ids = {row.id for row in txs if row.is_seeded_attack}
        covered_flag = any(
            row.tier >= 2 and row.transaction_id in attack_ids for row in decisions
        )
        covered = seeded_structures if covered_flag else 0

    return {
        "prevented_loss_paise": prevented,
        "median_lead_time_ms": median_lead,
        "false_challenge_rate": _rate(challenged, len(legit_tx)),
        "comprehension_rate": _rate(correct, shown),
        "multiparty_coverage": _rate(covered, seeded_structures),
        "denominators": {
            "legit_tx": len(legit_tx),
            "probes_shown": shown,
            "seeded_structures": seeded_structures,
        },
    }


def pay_snapshot(session: Session, account_id: str) -> dict[str, Any] | None:
    acct = session.get(Account, account_id)
    if acct is None:
        return None
    holds = active_hold_rows(session, account_id)
    return {
        "account_id": acct.id,
        "handle": acct.handle,
        "balance_paise": acct.balance_paise,
        "available_paise": available_paise(session, acct),
        "active_holds": [
            {
                "id": row.id,
                "reason_ref": row.reason_ref,
                "held_paise": row.held_paise,
                "releases_at": iso(row.releases_at) if row.releases_at else None,
                "opened_at": iso(row.opened_at),
                "outcome": row.outcome,
            }
            for row in holds
        ],
    }


def console_snapshot(session: Session) -> dict[str, Any]:
    return {
        "graph": graph_payload(session, window=500, bank="ALL"),
        "decisions": list_decisions(session, limit=100)["items"],
    }


def confirm_ring(
    session: Session, account_ids: list[str], fraud_type: str
) -> dict[str, Any]:
    """Analyst confirms a subgraph as a ring. Writes one pattern_signatures
    row for future PatternMemory similarity, and opens a ScopedHold on each
    account's most recent settled inbound transaction — never on the
    account itself. Reuses mark_fraudulent (Act 5's already-proven taint
    path) per account rather than inventing a second hold-amount rule, so
    the traced amount is computed the same way everywhere in the system.

    hops=1 per call: this taints only that one origin transaction and its
    immediate children, so confirming several accounts in one ring doesn't
    each re-chase the whole graph — each account's own inbound transaction
    is the origin for its own hold.
    """
    accounts: list[Account] = []
    for account_id in account_ids:
        acct = session.get(Account, account_id)
        if acct is None:
            raise ValueError(f"unknown_account:{account_id}")
        accounts.append(acct)

    signature = PatternSignature(
        label=fraud_type,
        signature={
            "account_ids": account_ids,
            "node_count": len(account_ids),
            "confirmed_by": "analyst",
            "confirmed_at": iso(utc_now()),
        },
    )
    session.add(signature)
    session.flush()

    opened_holds: list[dict[str, Any]] = []
    for acct in accounts:
        tx = session.exec(
            select(Transaction)
            .where(Transaction.receiver_id == acct.id)
            .where(Transaction.status == "settled")
            .order_by(col(Transaction.attempted_at).desc())
        ).first()
        if tx is None:
            continue
        try:
            result = mark_fraudulent(tx.id, hops=1, session=session)
        except ValueError:
            continue
        origin_hop = next((hop for hop in result.hops if hop.tx_id == tx.id), None)
        if origin_hop is None or origin_hop.taint_ratio <= 0:
            continue
        traced_paise = int(tx.amount_paise * origin_hop.taint_ratio)
        if traced_paise <= 0:
            continue
        hold = ScopedHold(
            id="sh_" + uuid.uuid4().hex,
            transaction_id=tx.id,
            account_id=acct.id,
            held_paise=traced_paise,
            reason_ref=next_reason_ref(),
            opened_at=utc_now(),
            releases_at=utc_now() + timedelta(minutes=COOLING_MINUTES),
        )
        session.add(hold)
        opened_holds.append(
            {
                "account": acct.handle,
                "transaction_id": tx.id,
                "held_paise": traced_paise,
                "reason_ref": hold.reason_ref,
            }
        )

    session.commit()
    return {
        "ok": True,
        "pattern_id": signature.id,
        "accounts_in_ring": len(accounts),
        "opened_holds": opened_holds,
    }

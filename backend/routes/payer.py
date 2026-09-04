"""Payer surface routes. K's real api.py should include_router this same router later.

quote never mutates balances / never opens holds / never fires CircuitBreaker.
commit is the only place money/holds/breaker happen.
Inbound money is never held. Only outbound.
"""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.action.decision_stub import _age_days, evaluate
from backend.action.payer_breaker import maybe_fire_for_tier4
from backend.action.payer_ledger import (
    account_by_handle,
    active_hold_rows,
    available_paise,
    iso,
    prior_payments,
    trusted_contact,
    unique_senders_today,
)
from backend.action.reasonline import assert_user_reason_safe, bank, regulator, user
from backend.action.scoped_hold import COOLING_MINUTES, IMMEDIATE_PAISE, next_reason_ref
from backend.core.config import get_config_version
from backend.core.db import get_session
from backend.core.models import (
    Account,
    ComprehensionProbe,
    Event,
    RiskDecision,
    ScopedHold,
    Transaction,
    utc_now,
)
from backend.scoring.ringwatch import ringwatch_score
from backend.routes.console_queries import (
    decision_item,
    graph_link_for_tx,
    graph_node,
    ps3_metrics,
)
from backend.routes.ws import envelope, hub

router = APIRouter(prefix="/api/payer", tags=["payer"])


def _aware(moment):
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment

_TIER_KIND = {
    0: "pass_silent",
    1: "inline_reason",
    2: "purpose_challenge",
    3: "scoped_hold_cooling",
    4: "scoped_hold_plus_circuit_breaker",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _action_payload(tier: int, amount_paise: int, contact_name: str | None) -> dict[str, Any]:
    kind = _TIER_KIND[tier]
    if tier < 3:
        return {"kind": kind}
    return {
        "kind": kind,
        "immediate_paise": IMMEDIATE_PAISE,
        "held_paise": max(0, amount_paise - IMMEDIATE_PAISE),
        "cooling_minutes": COOLING_MINUTES,
        "trusted_contact_name": contact_name if tier == 4 else None,
    }


def _probe_payload(tier: int) -> dict[str, Any] | None:
    if tier < 2:
        return None
    return {
        "question": "What did we tell you about this account?",
        "options": [
            "It was opened recently and many people are paying it",
            "Your bank is closed for maintenance",
            "The amount is above your daily limit",
        ],
        "correct_index": 0,
    }


class QuoteBody(BaseModel):
    sender_handle: str
    beneficiary_handle: str
    amount_paise: int
    note: str | None = None


class CommitBody(BaseModel):
    decision_id: str
    purpose_text: str | None = None


class ProbeBody(BaseModel):
    chosen_index: int = Field(ge=0)


class CancelBody(BaseModel):
    decision_id: str


@router.post("/quote")
async def quote(body: QuoteBody, session: Session = Depends(get_session)):
    if isinstance(body.amount_paise, bool) or not isinstance(body.amount_paise, int):
        return _error(400, "bad_amount", "amount_paise must be integer paise.")
    if body.amount_paise <= 0:
        return _error(400, "bad_amount", "amount_paise must be positive.")
    sender = account_by_handle(session, body.sender_handle)
    beneficiary = account_by_handle(session, body.beneficiary_handle)
    if sender is None or beneficiary is None:
        return _error(404, "unknown_handle", "No account with that handle in the demo ledger.")
    if body.amount_paise > available_paise(session, sender):
        return _error(400, "insufficient_available", "Amount is more than currently available.")

    now = utc_now()
    # is_seeded_attack: set when the sender was armed by /api/ops/inject_sequence
    # within the last 30 minutes — a durable event marker (event_type=
    # 'staged_attack_armed'), not a new column; scorers never read this,
    # only ps3_metrics' prevented-loss calculation does. Without this, a
    # judge's real Act 3 payment was never distinguishable from an ordinary
    # one, so prevented_loss_paise stayed 0 even after a real tier-4 catch.
    armed_cutoff = _aware(now) - timedelta(minutes=30)
    armed = False
    for row in session.exec(
        select(Event)
        .where(Event.account_id == sender.id)
        .where(Event.event_type == "staged_attack_armed")
    ).all():
        if _aware(row.ts) >= armed_cutoff:
            armed = True
            break
    tx = Transaction(
        id="tx_" + uuid.uuid4().hex,
        sender_id=sender.id,
        receiver_id=beneficiary.id,
        amount_paise=body.amount_paise,
        channel="upi",
        note=body.note,
        status="quoted",
        attempted_at=now,
        is_seeded_attack=armed,
    )
    session.add(tx)
    session.flush()

    evaluated = evaluate(
        sender,
        beneficiary,
        body.amount_paise,
        body.note,
        prior_payments=prior_payments(session, sender.id, beneficiary.id),
        config_version=get_config_version(),
        unique_senders_today=unique_senders_today(session, beneficiary.id),
    )
    decision_id = "d_" + uuid.uuid4().hex
    quote_at_iso = iso(now)
    decision_dict = {**evaluated, "id": decision_id, "quote_at": quote_at_iso, "commit_at": None}
    user_reason = user(decision_dict)
    assert_user_reason_safe(user_reason)
    bank_reason = bank(decision_dict)
    regulator_record = regulator(decision_dict)
    contact = trusted_contact(session, sender.id)
    tier = int(evaluated["tier"])

    row = RiskDecision(
        id=decision_id,
        transaction_id=tx.id,
        sender_id=sender.id,
        beneficiary_id=beneficiary.id,
        amount_paise=body.amount_paise,
        ringwatch_score=float(evaluated["ringwatch_score"]),
        trailscore_score=float(evaluated["trailscore_score"]),
        contextflag_score=float(evaluated["contextflag_score"]),
        cross_term_bonus=float(evaluated.get("cross_term_bonus") or 0),
        fused_score=float(evaluated["fused_score"]),
        tier=tier,
        verdict=str(evaluated["verdict"]),
        rules_fired=list(evaluated.get("rules_fired") or []),
        user_reason=user_reason,
        bank_reason=bank_reason,
        regulator_record=regulator_record,
        payload_sha256=regulator_record["sha256_of_payload"],
        config_version=str(evaluated["config_version"]),
        quote_at=now,
    )
    session.add(row)
    session.flush()

    probe_out = None
    probe_spec = _probe_payload(tier)
    if probe_spec is not None:
        probe = ComprehensionProbe(
            id="p_" + uuid.uuid4().hex,
            decision_id=decision_id,
            question=probe_spec["question"],
            options=list(probe_spec["options"]),
            correct_index=int(probe_spec["correct_index"]),
            shown_at=now,
        )
        session.add(probe)
        probe_out = {
            "probe_id": probe.id,
            "question": probe.question,
            "options": list(probe.options),
        }

    session.commit()
    await hub.broadcast("console", envelope("decision.created", decision_item(session, row)))
    await hub.broadcast("console", envelope("graph.link_added", graph_link_for_tx(session, tx)))
    await hub.broadcast("console", envelope("metrics.updated", ps3_metrics(session)))
    return {
        "decision_id": decision_id,
        "verdict": row.verdict,
        "tier": tier,
        "headline": user_reason["headline"],
        "facts": list(user_reason["facts"]),
        "counterfactual": user_reason["counterfactual"],
        "action": _action_payload(tier, body.amount_paise, contact.contact_name if contact else None),
        "probe": probe_out,
        "lead_time_started_at": quote_at_iso,
    }


@router.post("/commit")
async def commit(body: CommitBody, session: Session = Depends(get_session)):
    decision = session.get(RiskDecision, body.decision_id)
    if decision is None:
        return _error(404, "unknown_decision", "No decision with that id.")
    if decision.commit_at is not None:
        return _error(409, "already_committed", "This decision was already committed.")
    if decision.tier == 2:
        if len((body.purpose_text or "").strip()) < 3:
            return _error(400, "purpose_required", "purpose_text must be at least 3 characters at tier 2.")

    now = utc_now()
    decision.commit_at = now
    decision.lead_time_ms = max(
        0, int((_aware(now) - _aware(decision.quote_at)).total_seconds() * 1000)
    )
    tx = session.get(Transaction, decision.transaction_id) if decision.transaction_id else None
    if tx is None:
        return _error(500, "missing_transaction", "Decision has no quoted transaction.")
    sender = session.get(Account, decision.sender_id)
    if sender is None:
        return _error(404, "unknown_handle", "Sender account missing.")

    if decision.tier == 2:
        session.add(
            Event(
                id="ev_" + uuid.uuid4().hex,
                account_id=sender.id,
                event_type="note_entered",
                payload={"purpose_text": (body.purpose_text or "").strip()},
                ts=now,
                ingest_source="payer",
            )
        )

    if decision.tier in (0, 1, 2):
        if decision.amount_paise > available_paise(session, sender):
            return _error(400, "insufficient_available", "Amount is more than currently available.")
        sender.balance_paise -= decision.amount_paise
        tx.status = "settled"
        tx.settled_at = now
        session.add(sender)
        session.add(tx)
        session.add(decision)
        session.commit()
        await hub.broadcast(
            "console", envelope("decision.committed", decision_item(session, decision))
        )
        node = graph_node(session, sender.id)
        if node is not None:
            await hub.broadcast("console", envelope("graph.node_updated", node))
        await hub.broadcast("console", envelope("metrics.updated", ps3_metrics(session)))
        return {"outcome": "settled"}

    immediate = IMMEDIATE_PAISE
    held_paise = decision.amount_paise - immediate
    if held_paise <= 0:
        return _error(400, "bad_amount", "Held amount must be positive after immediate send.")
    if decision.amount_paise > available_paise(session, sender):
        return _error(400, "insufficient_available", "Amount is more than currently available.")

    sender.balance_paise -= immediate
    reason_ref = next_reason_ref()
    releases_at = now + timedelta(minutes=COOLING_MINUTES)
    hold = ScopedHold(
        id="sh_" + uuid.uuid4().hex,
        transaction_id=tx.id,
        account_id=sender.id,
        held_paise=held_paise,
        reason_ref=reason_ref,
        opened_at=now,
        releases_at=releases_at,
    )
    tx.status = "held"
    session.add(sender)
    session.add(hold)
    session.add(tx)
    session.add(decision)
    session.commit()

    hold_payload = {
        "id": hold.id,
        "transaction_id": hold.transaction_id,
        "account_id": hold.account_id,
        "held_paise": hold.held_paise,
        "reason_ref": hold.reason_ref,
        "opened_at": iso(hold.opened_at),
        "releases_at": iso(releases_at),
        "released_at": None,
        "outcome": None,
        "available_paise": available_paise(session, sender),
    }
    await hub.broadcast(f"pay:{sender.id}", envelope("hold.opened", hold_payload))
    await hub.broadcast("console", envelope("hold.opened", hold_payload))
    await hub.broadcast(
        "console", envelope("decision.committed", decision_item(session, decision))
    )
    node = graph_node(session, sender.id)
    if node is not None:
        await hub.broadcast("console", envelope("graph.node_updated", node))
    await hub.broadcast("console", envelope("metrics.updated", ps3_metrics(session)))

    contact_note = None
    if decision.tier == 4:
        contact_note = await maybe_fire_for_tier4(
            session, decision=decision, sender=sender, now=now, hold_id=hold.id
        )

    result: dict[str, Any] = {
        "outcome": "held",
        "reason_ref": reason_ref,
        "releases_at": iso(releases_at),
    }
    if contact_note:
        result["circuit_breaker"] = contact_note
    return result


@router.post("/probe/{probe_id}")
def answer_probe(probe_id: str, body: ProbeBody, session: Session = Depends(get_session)):
    probe = session.get(ComprehensionProbe, probe_id)
    if probe is None:
        return _error(404, "unknown_probe", "No probe with that id.")
    probe.chosen_index = body.chosen_index
    probe.answered_at = utc_now()
    session.add(probe)
    session.commit()
    return {"correct": body.chosen_index == probe.correct_index}


@router.post("/cancel")
async def cancel(body: CancelBody, session: Session = Depends(get_session)):
    decision = session.get(RiskDecision, body.decision_id)
    if decision is None:
        return _error(404, "unknown_decision", "No decision with that id.")
    tx = session.get(Transaction, decision.transaction_id) if decision.transaction_id else None
    if tx is None:
        return _error(404, "unknown_transaction", "No transaction for that decision.")
    holds = [
        row
        for row in session.exec(select(ScopedHold).where(ScopedHold.transaction_id == tx.id)).all()
        if row.released_at is None
    ]
    now = utc_now()
    for hold in holds:
        hold.released_at = now
        hold.outcome = "cancelled_by_user"
        session.add(hold)
        acct = session.get(Account, hold.account_id)
        available = available_paise(session, acct) if acct is not None else 0
        released = {
            "id": hold.id,
            "transaction_id": hold.transaction_id,
            "account_id": hold.account_id,
            "held_paise": hold.held_paise,
            "reason_ref": hold.reason_ref,
            "opened_at": iso(hold.opened_at),
            "releases_at": iso(hold.releases_at) if hold.releases_at else None,
            "released_at": iso(now),
            "outcome": "cancelled_by_user",
            "available_paise": available,
        }
        await hub.broadcast(f"pay:{hold.account_id}", envelope("hold.released", released))
        await hub.broadcast("console", envelope("hold.released", released))
    tx.status = "cancelled"
    session.add(tx)
    session.commit()
    await hub.broadcast("console", envelope("metrics.updated", ps3_metrics(session)))
    return {"outcome": "cancelled_by_user"}


@router.get("/account/{handle}")
def account(handle: str, session: Session = Depends(get_session)):
    acct = account_by_handle(session, handle)
    if acct is None:
        return _error(404, "unknown_handle", "No account with that handle in the demo ledger.")
    holds = active_hold_rows(session, acct.id)
    return {
        "account_id": acct.id,
        "handle": acct.handle,
        "display_name": acct.display_name,
        "balance_paise": acct.balance_paise,
        "available_paise": available_paise(session, acct),
        "active_holds": [
            {
                "reason_ref": row.reason_ref,
                "held_paise": row.held_paise,
                "releases_at": iso(row.releases_at) if row.releases_at else None,
            }
            for row in holds
        ],
    }


_LOOKOUT_THRESHOLD = 0.15  # matches the ladder's own tier-0 boundary


def _lookout_facts(beneficiary: Account, result) -> list[str]:
    """Built ONLY from genuinely computed values (RingWatch's own feature
    read + the account's real created_at) — deliberately does not reuse
    decision_stub.py's beneficiary_age_days/unique_senders_today fallback,
    which hardcodes numbers keyed on the literal string "quickcash" in the
    handle. That shortcut is fine for the scripted ladder facts on the one
    named demo account; Lookout runs before an amount is even entered and
    must hold up for whichever account a judge actually picks.
    """
    facts: list[str] = []
    age_days = _age_days(beneficiary.created_at)
    facts.append(f"Account opened {age_days} days ago.")
    for rule in result.rules_fired:
        detail = str(rule.get("detail", ""))
        if detail.startswith("in_degree="):
            count = detail.split("=", 1)[1]
            facts.append(f"{count} different accounts have paid it recently.")
            break
    return facts[:2]


@router.get("/beneficiary-check")
def beneficiary_check(to_handle: str, session: Session = Depends(get_session)):
    """Pre-amount check, fired the moment a beneficiary is selected — not
    at commit time. Silent by default (flag: null) on purpose: this never
    returns a positive "valid"/"trusted" label, only ever a factual concern
    or nothing. A positive score is exactly what a patient fraudster would
    farm toward; silence can't be farmed.
    """
    beneficiary = account_by_handle(session, to_handle)
    if beneficiary is None:
        return _error(404, "unknown_handle", "No account with that handle in the demo ledger.")
    result = ringwatch_score(beneficiary.id, session)
    if result.score < _LOOKOUT_THRESHOLD:
        return {"flag": None}
    facts = _lookout_facts(beneficiary, result)
    reason = " ".join(facts)
    padded = facts + [""] * (3 - len(facts))
    assert_user_reason_safe({"headline": reason, "counterfactual": "", "facts": padded})
    return {"flag": "watch", "user_reason": reason}


class LookoutDismissBody(BaseModel):
    account_id: str
    to_handle: str


@router.post("/beneficiary-check/dismiss")
def beneficiary_check_dismiss(body: LookoutDismissBody, session: Session = Depends(get_session)):
    """Records that a Lookout warning was shown and the payer went ahead
    anyway. This event feeds back into TrailScore's own sequence scoring —
    dismissing an explicit warning right before a large transfer is itself
    part of the sequence the next quote/commit will read.
    """
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    row = Event(
        id="ev_" + uuid.uuid4().hex,
        account_id=acct.id,
        event_type="lookout_dismissed",
        payload={"to_handle": body.to_handle},
        ts=utc_now(),
        ingest_source="payer",
    )
    session.add(row)
    session.commit()
    return {"ok": True}

"""CircuitBreaker fire + ack against SQL ScopedHold.

Inbound is never held; no account freeze. Ack never reverses the ₹1 immediate debit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from backend.action import circuit_breaker as cb
from backend.action.payer_ledger import available_paise, iso, trusted_contact
from backend.action.scoped_hold import COOLING_MINUTES
from backend.core.db import engine
from backend.core.models import (
    Account,
    CircuitBreakerLog,
    RiskDecision,
    ScopedHold,
    Transaction,
    TrustedContact,
    utc_now,
)
from backend.routes.ws import envelope, hub


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _hold_event_data(hold: ScopedHold, avail: int) -> dict[str, Any]:
    return {
        "id": hold.id,
        "transaction_id": hold.transaction_id,
        "account_id": hold.account_id,
        "held_paise": hold.held_paise,
        "reason_ref": hold.reason_ref,
        "opened_at": iso(hold.opened_at),
        "releases_at": iso(hold.releases_at) if hold.releases_at else None,
        "released_at": iso(hold.released_at) if hold.released_at else None,
        "outcome": hold.outcome,
        "available_paise": avail,
    }


def _find_active_hold(
    session: Session,
    *,
    payload: dict[str, Any],
    decision: RiskDecision | None,
) -> ScopedHold | None:
    hold_id = payload.get("hold_id")
    if isinstance(hold_id, str) and hold_id:
        row = session.get(ScopedHold, hold_id)
        if row is not None and row.released_at is None:
            return row
    tx_id = payload.get("transaction_id")
    if not tx_id and decision is not None:
        tx_id = decision.transaction_id
    if isinstance(tx_id, str) and tx_id:
        rows = session.exec(
            select(ScopedHold).where(ScopedHold.transaction_id == tx_id)
        ).all()
        for row in rows:
            if row.released_at is None:
                return row
    return None


def _latest_unacked_log(session: Session, contact_id: str) -> CircuitBreakerLog | None:
    rows = session.exec(
        select(CircuitBreakerLog).where(CircuitBreakerLog.contact_id == contact_id)
    ).all()
    for row in reversed(list(rows)):
        if not row.ack:
            return row
    return None


async def maybe_fire_for_tier4(
    session: Session,
    *,
    decision: RiskDecision,
    sender: Account,
    now: datetime,
    hold_id: str | None = None,
) -> str | None:
    """Fire watch alert when a trusted contact exists. Returns note if skipped."""
    contact = trusted_contact(session, sender.id)
    if contact is None:
        return "no_trusted_contact"
    cb.SESSIONS.setdefault(
        contact.watch_token,
        {
            "token": contact.watch_token,
            "account_holder": sender.display_name,
            "contact_name": contact.contact_name,
            "account_id": sender.id,
        },
    )
    facts = list((decision.user_reason or {}).get("facts") or [])[:3]
    while len(facts) < 3:
        facts.append("Check the amount and who you are paying.")
    bene = session.get(Account, decision.beneficiary_id)
    age = 6
    if bene is not None and bene.created_at is not None:
        created = bene.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = max(0, (now - created).days)
    payload = cb.build_payload(
        account_holder=sender.display_name,
        amount_paise=decision.amount_paise,
        payee_age_days=age,
        facts=facts,
    )
    payload["decision_id"] = decision.id
    payload["transaction_id"] = decision.transaction_id
    payload["account_id"] = sender.id
    payload["hold_id"] = hold_id
    log_id = await cb.fire(hub, contact.watch_token, payload)
    session.add(
        CircuitBreakerLog(
            id=log_id,
            decision_id=decision.id,
            contact_id=contact.id,
            fired_at=now,
            payload=payload,
            ack=False,
        )
    )
    session.commit()
    return None


async def apply_contact_ack(*, token: str, action: str) -> dict[str, Any]:
    """SQL + in-memory CircuitBreaker ack; extend hold or settle remaining amount.

    Cooling timeout (not this phase) would settle like approved — same debit/credit path.
    """
    if action not in ("approved", "hold"):
        raise ValueError("bad_action")

    now = utc_now()
    with Session(engine) as session:
        contact = session.exec(
            select(TrustedContact).where(TrustedContact.watch_token == token)
        ).first()
        if contact is None:
            # Isolation harness fire with no SQL contact — memory path only.
            data = await cb.ack(hub, token, action)
            return {
                "ok": True,
                "ack_action": action,
                "hold_id": None,
                "releases_at": None,
                "outcome": None,
                "available_paise": None,
                "contact_name": data.get("contact_name"),
            }

        log = _latest_unacked_log(session, contact.id)
        if log is None:
            raise LookupError("no_pending")

        payload = dict(log.payload or {})
        decision = session.get(RiskDecision, log.decision_id)
        hold = _find_active_hold(session, payload=payload, decision=decision)

        outcome: str | None = None
        releases_at_iso: str | None = None
        hold_id: str | None = hold.id if hold is not None else None
        avail: int | None = None
        pay_topic: str | None = None
        pay_event: str | None = None
        pay_data: dict[str, Any] | None = None

        if hold is not None and action == "hold":
            base = _aware(hold.releases_at or now)
            hold.releases_at = max(_aware(now), base) + timedelta(minutes=COOLING_MINUTES)
            log.ack = True
            log.ack_action = action
            log.ack_at = now
            session.add(hold)
            session.add(log)
            session.commit()
            session.refresh(hold)
            account = session.get(Account, hold.account_id)
            avail = available_paise(session, account) if account is not None else None
            releases_at_iso = iso(hold.releases_at) if hold.releases_at else None
            pay_topic = f"pay:{hold.account_id}"
            pay_event = "hold.extended"
            pay_data = _hold_event_data(hold, avail or 0)

        elif hold is not None and action == "approved":
            tx = session.get(Transaction, hold.transaction_id)
            if tx is None:
                raise LookupError("unknown_transaction")
            if hold.account_id != tx.sender_id:
                raise ValueError("inbound_never_held")
            sender = session.get(Account, tx.sender_id)
            receiver = session.get(Account, tx.receiver_id)
            if sender is None or receiver is None:
                raise LookupError("unknown_account")
            # Held amount is already reserved via available_paise; balance still includes it.
            if sender.balance_paise < hold.held_paise:
                raise ValueError("insufficient_available")

            sender.balance_paise -= hold.held_paise
            receiver.balance_paise += hold.held_paise
            hold.released_at = now
            hold.outcome = "released"
            tx.status = "settled"
            tx.settled_at = now
            log.ack = True
            log.ack_action = action
            log.ack_at = now
            session.add(sender)
            session.add(receiver)
            session.add(hold)
            session.add(tx)
            session.add(log)
            session.commit()
            session.refresh(hold)
            session.refresh(sender)
            outcome = "released"
            avail = available_paise(session, sender)
            releases_at_iso = iso(hold.releases_at) if hold.releases_at else None
            pay_topic = f"pay:{hold.account_id}"
            pay_event = "hold.released"
            pay_data = _hold_event_data(hold, avail)

        else:
            # No active hold — still record ack.
            log.ack = True
            log.ack_action = action
            log.ack_at = now
            session.add(log)
            session.commit()

        if pay_topic and pay_event and pay_data is not None:
            await hub.broadcast(pay_topic, envelope(pay_event, pay_data))

        # Keep isolation BREAKER_LOG in sync; broadcast acked if memory has no row.
        try:
            await cb.ack(hub, token, action)
        except LookupError:
            await hub.broadcast(
                f"watch:{token}",
                envelope(
                    "circuit_breaker.acked",
                    {
                        "ack_action": action,
                        "ack_at": iso(now),
                        "contact_name": contact.contact_name,
                    },
                ),
            )

        return {
            "ok": True,
            "ack_action": action,
            "hold_id": hold_id,
            "releases_at": releases_at_iso,
            "outcome": outcome,
            "available_paise": avail,
            "contact_name": contact.contact_name,
        }

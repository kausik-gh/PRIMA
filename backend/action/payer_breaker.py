"""CircuitBreaker fire from payer commit. Inbound is never held; no account freeze."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from backend.action import circuit_breaker as cb
from backend.action.payer_ledger import trusted_contact
from backend.core.models import Account, CircuitBreakerLog, RiskDecision
from backend.routes.ws import hub


async def maybe_fire_for_tier4(
    session: Session,
    *,
    decision: RiskDecision,
    sender: Account,
    now: datetime,
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

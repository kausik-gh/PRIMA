"""Ledger helpers. Money is integer paise. Never mutate balance_paise here.

Inbound money is never held. Available funds are ledger balance minus
active amount-scoped holds on outbound transfers.
"""

from __future__ import annotations

from sqlmodel import Session, select

from backend.core.models import Account, ScopedHold


def account_by_handle(session: Session, handle: str) -> Account | None:
    return session.exec(select(Account).where(Account.handle == handle)).first()


def available_paise(session: Session, account: Account) -> int:
    """Ledger balance minus unreleased scoped holds. Does not change balance_paise."""
    holds = session.exec(
        select(ScopedHold).where(
            ScopedHold.account_id == account.id,
            ScopedHold.released_at.is_(None),
        )
    ).all()
    held = sum(row.held_paise for row in holds)
    return account.balance_paise - held

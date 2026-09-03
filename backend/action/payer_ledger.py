"""Payer ledger helpers over SQLModel. No freeze-account path exists here."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, col, select

from backend.core.models import Account, ScopedHold, Transaction, TrustedContact, utc_now


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def account_by_handle(session: Session, handle: str) -> Account | None:
    return session.exec(select(Account).where(Account.handle == handle)).first()


def active_hold_rows(session: Session, account_id: str) -> list[ScopedHold]:
    rows = session.exec(select(ScopedHold).where(ScopedHold.account_id == account_id)).all()
    return [row for row in rows if row.released_at is None]


def available_paise(session: Session, account: Account) -> int:
    held = sum(row.held_paise for row in active_hold_rows(session, account.id))
    return account.balance_paise - held


def prior_payments(session: Session, sender_id: str, beneficiary_id: str) -> int:
    rows = session.exec(
        select(Transaction).where(
            Transaction.sender_id == sender_id,
            Transaction.receiver_id == beneficiary_id,
            Transaction.status == "settled",
        )
    ).all()
    return len(rows)


def unique_senders_today(session: Session, beneficiary_id: str) -> int:
    start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.exec(
        select(Transaction).where(
            Transaction.receiver_id == beneficiary_id,
            col(Transaction.attempted_at) >= start,
        )
    ).all()
    return len({row.sender_id for row in rows}) or 1


def trusted_contact(session: Session, account_id: str) -> TrustedContact | None:
    return session.exec(
        select(TrustedContact).where(TrustedContact.account_id == account_id)
    ).first()

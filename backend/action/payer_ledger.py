"""Payer ledger helpers over SQLModel. No freeze-account path exists here."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from backend.core.models import Account, Event, ScopedHold, Transaction, TrustedContact, utc_now


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def iso(moment: datetime) -> str:
    moment = _aware(moment)
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


def retention_minutes_typical(session: Session, beneficiary_id: str) -> int | None:
    """Median minutes between an inbound settled transaction landing on this
    account and the next outbound settled transaction leaving it. None if
    there isn't at least one real inbound-then-outbound pair to measure —
    do not invent a number when there's nothing to measure from."""
    inbound = session.exec(
        select(Transaction)
        .where(Transaction.receiver_id == beneficiary_id)
        .where(Transaction.status == "settled")
        .order_by(col(Transaction.attempted_at).asc())
    ).all()
    outbound = session.exec(
        select(Transaction)
        .where(Transaction.sender_id == beneficiary_id)
        .where(Transaction.status == "settled")
        .order_by(col(Transaction.attempted_at).asc())
    ).all()
    if not inbound or not outbound:
        return None
    gaps: list[float] = []
    for in_tx in inbound:
        # first outbound tx that happened at or after this inbound one
        later = [o for o in outbound if _aware(o.attempted_at) >= _aware(in_tx.attempted_at)]
        if not later:
            continue
        gap_minutes = (
            _aware(later[0].attempted_at) - _aware(in_tx.attempted_at)
        ).total_seconds() / 60.0
        gaps.append(gap_minutes)
    if not gaps:
        return None
    gaps.sort()
    mid = len(gaps) // 2
    median_minutes = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2
    return max(0, round(median_minutes))


def minutes_since_limit_raised(session: Session, sender_id: str, window_minutes: int = 15) -> int | None:
    """Real minutes since the sender's most recent limit_raised event within
    TrailScore's own scoring window. None if no such event is in that
    window — matches what TrailScore itself would see, so the fact text
    and the score it's explaining are always consistent."""
    return _minutes_since_event(session, sender_id, "limit_raised", window_minutes)


def minutes_since_new_device(session: Session, sender_id: str, window_minutes: int = 15) -> int | None:
    """Same as above, for login_new_device."""
    return _minutes_since_event(session, sender_id, "login_new_device", window_minutes)


def _minutes_since_event(
    session: Session, account_id: str, event_type: str, window_minutes: int
) -> int | None:
    cutoff = utc_now() - timedelta(minutes=window_minutes)
    rows = session.exec(
        select(Event)
        .where(Event.account_id == account_id)
        .where(Event.event_type == event_type)
        .order_by(col(Event.ts).desc())
    ).all()
    row = None
    for candidate in rows:
        if _aware(candidate.ts) >= cutoff:
            row = candidate
            break
    if row is None:
        return None
    elapsed = (utc_now() - _aware(row.ts)).total_seconds() / 60.0
    return max(0, round(elapsed))


def trusted_contact(session: Session, account_id: str) -> TrustedContact | None:
    return session.exec(
        select(TrustedContact).where(TrustedContact.account_id == account_id)
    ).first()

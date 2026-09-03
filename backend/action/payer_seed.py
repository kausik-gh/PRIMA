"""Tiny payer seed for isolation. Ops will own seeding later (/api/ops/seed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from backend.action import circuit_breaker as cb
from backend.core.db import create_db_and_tables, engine
from backend.core.models import Account, TrustedContact, utc_now


def ensure_payer_seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        existing = session.exec(select(Account).where(Account.handle == "ramesh@prima")).first()
        if existing is not None:
            _sync_watch_session(session, existing)
            return

        now = utc_now()
        ramesh = Account(
            handle="ramesh@prima",
            display_name="Ramesh K.",
            bank_code="BANKA",
            device_id="device_ramesh_isolation",
            created_at=now - timedelta(days=400),
            balance_paise=50_000_000,
            is_demo_guest=False,
            ground_truth_role=None,
        )
        quickcash = Account(
            handle="quickcash@prima",
            display_name="Quick Cash",
            bank_code="BANKB",
            device_id="device_quickcash_isolation",
            created_at=now - timedelta(days=6),
            balance_paise=120_000,
            is_demo_guest=False,
            ground_truth_role=None,
        )
        merchant = Account(
            handle="merchant@prima",
            display_name="Demo Merchant",
            bank_code="BANKA",
            device_id="device_merchant_isolation",
            created_at=now - timedelta(days=200),
            balance_paise=14_000_000,
            is_demo_guest=False,
            ground_truth_role=None,
        )
        session.add(ramesh)
        session.add(quickcash)
        session.add(merchant)
        session.commit()
        session.refresh(ramesh)

        contact = TrustedContact(
            account_id=ramesh.id,
            contact_name="Priya",
            watch_token="test",
            nominated_at=now,
        )
        session.add(contact)
        session.commit()
        _sync_watch_session(session, ramesh)


def _sync_watch_session(session: Session, ramesh: Account) -> None:
    contact = session.exec(
        select(TrustedContact).where(TrustedContact.account_id == ramesh.id)
    ).first()
    if contact is None:
        return
    cb.SESSIONS[contact.watch_token] = {
        "token": contact.watch_token,
        "account_holder": ramesh.display_name,
        "contact_name": contact.contact_name,
        "account_id": ramesh.id,
    }

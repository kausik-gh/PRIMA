"""Thin extra handles so P3 quote smoke works on a K-seeded ledger.

P3 isolation seeder (ensure_payer_seed) no-ops if ramesh@prima already exists
and therefore never creates merchant@prima. This adds that handle only.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from backend.core.db import engine
from backend.core.models import Account, utc_now


def ensure_smoke_merchant() -> None:
    """Insert merchant@prima if missing. Does not reset the database."""
    now = utc_now()
    with Session(engine) as session:
        existing = session.exec(
            select(Account).where(Account.handle == "merchant@prima")
        ).first()
        if existing is not None:
            return
        session.add(
            Account(
                handle="merchant@prima",
                display_name="Demo Merchant",
                bank_code="BANKA",
                device_id="device_merchant_smoke",
                created_at=now - timedelta(days=200),
                balance_paise=14_000_000,
                is_demo_guest=False,
                ground_truth_role="legit",
            )
        )
        session.commit()

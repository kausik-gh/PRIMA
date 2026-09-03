"""Deterministic demo ledger seed. CLI only this phase (no HTTP route).

Handles look like UPI (name@prima). Money is integer paise.
Transaction notes are bland merchant text only.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session

from backend.core.db import create_db_and_tables, engine
from backend.core.models import (
    Account,
    BankMeshSignal,
    CircuitBreakerLog,
    ComprehensionProbe,
    ContextFlag,
    Event,
    PatternSignature,
    RiskDecision,
    ScopedHold,
    Transaction,
    TrustedContact,
)

# Stable namespace so named handles keep the same UUID across reruns.
PRIMA_NS = uuid.UUID("8f14e45f-ceea-467c-9d73-aa6096e25423")

NAMED_HANDLES = [
    "ramesh@prima",
    "priya.k@prima",
    "grocery@prima",
    "rentals@prima",
    "quickcash@prima",
    "merchant.ok@prima",
]

# Extra labelled mule structures so the later PS3 denominator is > 1.
EXTRA_MULE_HANDLES = [
    "cashpool@prima",
    "neel.m@prima",
    "tara.m@prima",
    "om.m@prima",
]

BANK_CODES = ("BANKA", "BANKA", "BANKA", "BANKA", "BANKA", "BANKA", "BANKA", "BANKB", "BANKC")

# Bland merchant notes only. Do not add social-engineering phrasing here.
NOTES = (
    "rent",
    "groceries",
    "utilities",
    "salary",
    "food",
    "fuel",
    "pharmacy",
    "mobile recharge",
    "school fees",
    "household",
)

GIVEN_NAMES = (
    "arjun", "diya", "kabir", "isha", "rohan", "ananya", "vikas", "naina",
    "harsh", "kavya", "sameer", "riya", "yash", "pooja", "nikhil", "tanvi",
    "aditya", "shruti", "manav", "aisha", "kunal", "meera", "varun", "sana",
    "ravi", "lina", "gopal", "nina", "farhan", "leela", "siddharth", "ira",
    "dev", "maya", "arun", "kiran", "neha", "amit", "sonia", "vijay",
)

FAMILY_NAMES = (
    "sharma", "patel", "nair", "iyer", "khan", "das", "reddy", "gupta",
    "joshi", "menon", "rao", "singh", "verma", "kaur", "mishra", "pillai",
    "bose", "mehta", "desai", "naik",
)

WIPE_ORDER = (
    CircuitBreakerLog,
    ComprehensionProbe,
    ContextFlag,
    ScopedHold,
    RiskDecision,
    Event,
    TrustedContact,
    Transaction,
    PatternSignature,
    BankMeshSignal,
    Account,
)


def _stable_id(*parts: str) -> str:
    return str(uuid.uuid5(PRIMA_NS, "|".join(parts)))


def _utc(seed_now: datetime, **delta_kwargs: float) -> datetime:
    return seed_now - timedelta(**delta_kwargs)


def _pick_channel() -> str:
    roll = random.random()
    if roll < 0.70:
        return "upi"
    if roll < 0.85:
        return "imps"
    if roll < 0.95:
        return "neft"
    return "card"


def _pick_bank() -> str:
    return random.choice(BANK_CODES)


def _clamp_ts(ts: datetime, *accounts: Account) -> datetime:
    earliest = max(a.created_at for a in accounts)
    if ts < earliest:
        return earliest + timedelta(hours=1)
    return ts


def _apply_settled(
    sender: Account,
    receiver: Account,
    amount_paise: int,
    ts: datetime,
    *,
    note: str,
    is_seeded_attack: bool,
    seq: int,
) -> Transaction | None:
    if sender.id == receiver.id:
        return None
    if amount_paise <= 0:
        return None
    if sender.balance_paise < amount_paise:
        return None

    sender.balance_paise -= amount_paise
    receiver.balance_paise += amount_paise
    settled_at = ts + timedelta(seconds=12)
    return Transaction(
        id=_stable_id("tx", sender.handle, receiver.handle, str(seq), str(amount_paise)),
        sender_id=sender.id,
        receiver_id=receiver.id,
        amount_paise=amount_paise,
        channel=_pick_channel(),
        note=note,
        status="settled",
        attempted_at=ts,
        settled_at=settled_at,
        taint_ratio=0.0,
        is_seeded_attack=is_seeded_attack,
    )


def _wipe_all(session: Session) -> None:
    for model in WIPE_ORDER:
        session.execute(delete(model))


def _build_regular_handles(needed: int, reserved: set[str]) -> list[str]:
    handles: list[str] = []
    n = 0
    while len(handles) < needed:
        given = GIVEN_NAMES[n % len(GIVEN_NAMES)]
        family = FAMILY_NAMES[(n // len(GIVEN_NAMES)) % len(FAMILY_NAMES)]
        suffix = n // (len(GIVEN_NAMES) * len(FAMILY_NAMES))
        if suffix == 0:
            handle = f"{given}.{family}@prima"
        else:
            handle = f"{given}.{family}{suffix}@prima"
        n += 1
        if handle in reserved:
            continue
        handles.append(handle)
    return handles


def _make_account(
    handle: str,
    display_name: str,
    *,
    created_at: datetime,
    balance_paise: int,
    device_id: str,
    bank_code: str = "BANKA",
    ground_truth_role: str | None = None,
) -> Account:
    return Account(
        id=_stable_id("account", handle),
        handle=handle,
        display_name=display_name,
        bank_code=bank_code,
        device_id=device_id,
        created_at=created_at,
        balance_paise=balance_paise,
        is_demo_guest=False,
        ground_truth_role=ground_truth_role,
    )


def seed_database(accounts: int = 500, days: int = 21, *, reset: bool = True) -> dict[str, Any]:
    """Wipe (optional) and insert the demo ledger. Returns counts."""
    random.seed(42)
    create_db_and_tables()
    seed_now = datetime.now(timezone.utc)

    if accounts < 20:
        raise ValueError("seed_database requires at least 20 accounts")

    reserved = set(NAMED_HANDLES) | set(EXTRA_MULE_HANDLES)
    regular_count = accounts - len(reserved)
    regular_handles = _build_regular_handles(regular_count, reserved)

    by_handle: dict[str, Account] = {}

    # Named demo accounts -- handles are locked for P2/P3/F fixtures.
    ramesh_grocery_paise = 45000
    by_handle["ramesh@prima"] = _make_account(
        "ramesh@prima",
        "Ramesh K.",
        created_at=_utc(seed_now, days=400),
        balance_paise=40_000_000 + ramesh_grocery_paise,
        device_id="dev-ramesh-own",
        ground_truth_role="victim",
    )
    by_handle["priya.k@prima"] = _make_account(
        "priya.k@prima",
        "Priya K.",
        created_at=_utc(seed_now, days=280),
        balance_paise=random.randint(5_000_00, 5_00_000_00),
        device_id="dev-priya-own",
        ground_truth_role="legit",
    )
    by_handle["grocery@prima"] = _make_account(
        "grocery@prima",
        "Daily Mart",
        created_at=_utc(seed_now, days=800),
        balance_paise=random.randint(20_000_00, 5_00_000_00),
        device_id="dev-grocery",
        ground_truth_role="legit",
    )
    by_handle["rentals@prima"] = _make_account(
        "rentals@prima",
        "Prima Rentals",
        created_at=_utc(seed_now, days=800),
        balance_paise=random.randint(20_000_00, 5_00_000_00),
        device_id="dev-rentals",
        ground_truth_role="legit",
    )
    by_handle["quickcash@prima"] = _make_account(
        "quickcash@prima",
        "Quick Cash",
        created_at=_utc(seed_now, days=6),
        balance_paise=random.randint(5_000_00, 12_000_00),
        device_id="dev-quickcash",
        ground_truth_role="mule",
    )
    by_handle["merchant.ok@prima"] = _make_account(
        "merchant.ok@prima",
        "OK Merchant",
        created_at=_utc(seed_now, days=200),
        balance_paise=random.randint(1_50_000_00, 5_00_000_00),
        device_id="dev-merchant-ok",
        ground_truth_role="legit",
    )
    by_handle["cashpool@prima"] = _make_account(
        "cashpool@prima",
        "Cash Pool",
        created_at=_utc(seed_now, days=9),
        balance_paise=random.randint(5_000_00, 12_000_00),
        device_id="dev-cashpool",
        ground_truth_role="mule",
    )
    ring_device = "dev-ring-shared"
    by_handle["neel.m@prima"] = _make_account(
        "neel.m@prima",
        "Neel M.",
        created_at=_utc(seed_now, days=11),
        balance_paise=random.randint(8_000_00, 20_000_00),
        device_id=ring_device,
        ground_truth_role="mule",
    )
    by_handle["tara.m@prima"] = _make_account(
        "tara.m@prima",
        "Tara M.",
        created_at=_utc(seed_now, days=11),
        balance_paise=random.randint(8_000_00, 20_000_00),
        device_id=ring_device,
        ground_truth_role="mule",
    )
    by_handle["om.m@prima"] = _make_account(
        "om.m@prima",
        "Om M.",
        created_at=_utc(seed_now, days=11),
        balance_paise=random.randint(8_000_00, 20_000_00),
        device_id=ring_device,
        ground_truth_role="mule",
    )

    window_start = seed_now - timedelta(days=days)
    for i, handle in enumerate(regular_handles):
        given, rest = handle.split("@", 1)[0].split(".", 1)
        family = "".join(ch for ch in rest if not ch.isdigit())
        display = f"{given.capitalize()} {family.capitalize()}"
        age_days = random.randint(30, 900)
        created_at = _utc(seed_now, days=age_days)
        by_handle[handle] = _make_account(
            handle,
            display,
            created_at=created_at,
            balance_paise=random.randint(5_000_00, 5_00_000_00),
            device_id=f"dev-{_stable_id('device', handle)[:8]}",
            bank_code=_pick_bank(),
            ground_truth_role=None,
        )

    regular_accounts = [by_handle[h] for h in regular_handles]
    txs: list[Transaction] = []
    events: list[Event] = []
    seq = 0

    def add_tx(
        sender: Account,
        receiver: Account,
        amount_paise: int,
        ts: datetime,
        *,
        note: str,
        is_seeded_attack: bool = False,
    ) -> None:
        nonlocal seq
        seq += 1
        ts = _clamp_ts(ts, sender, receiver)
        row = _apply_settled(
            sender,
            receiver,
            amount_paise,
            ts,
            note=note,
            is_seeded_attack=is_seeded_attack,
            seq=seq,
        )
        if row is not None:
            txs.append(row)

    # Act 1 known-payee history: ramesh -> grocery.
    grocery_ts = seed_now - timedelta(days=min(30, max(days, 2)))
    add_tx(
        by_handle["ramesh@prima"],
        by_handle["grocery@prima"],
        ramesh_grocery_paise,
        grocery_ts,
        note="groceries",
    )

    # Background settled volume among regular accounts.
    background_target = 3100
    attempts = 0
    max_attempts = background_target * 6
    while len(txs) < 1 + background_target and attempts < max_attempts:
        attempts += 1
        sender = random.choice(regular_accounts)
        receiver = random.choice(regular_accounts)
        amount = random.randint(50_000, 20_00_000)
        offset_sec = random.randint(0, max(1, days * 24 * 3600))
        ts = window_start + timedelta(seconds=offset_sec)
        add_tx(sender, receiver, amount, ts, note=random.choice(NOTES))

    # Act 2 landlord shape: fan-in, high retention, taint_ratio 0.0.
    rentals = by_handle["rentals@prima"]
    rentals_senders = regular_accounts[:8]
    for i, sender in enumerate(rentals_senders):
        ts = seed_now - timedelta(days=3, hours=i * 3)
        add_tx(sender, rentals, 18_00_000, ts, note="rent")

    # Act 3 collection point: fresh account, fan-in, then most funds leave.
    quickcash = by_handle["quickcash@prima"]
    qc_senders = regular_accounts[8:18]
    for i, sender in enumerate(qc_senders):
        ts = seed_now - timedelta(days=2, hours=i * 2)
        add_tx(
            sender,
            quickcash,
            9_00_000,
            ts,
            note="household",
            is_seeded_attack=True,
        )
    sink_a = regular_accounts[-1]
    sink_b = regular_accounts[-2]
    drain = (quickcash.balance_paise * 9) // 10
    part_a = drain // 2
    part_b = drain - part_a
    add_tx(
        quickcash,
        sink_a,
        part_a,
        seed_now - timedelta(hours=6),
        note="utilities",
        is_seeded_attack=True,
    )
    add_tx(
        quickcash,
        sink_b,
        part_b,
        seed_now - timedelta(hours=5),
        note="utilities",
        is_seeded_attack=True,
    )

    # Extra mule fan-in (structure 2).
    cashpool = by_handle["cashpool@prima"]
    pool_senders = regular_accounts[18:24]
    for i, sender in enumerate(pool_senders):
        ts = seed_now - timedelta(days=4, hours=i * 4)
        add_tx(
            sender,
            cashpool,
            6_00_000,
            ts,
            note="food",
            is_seeded_attack=True,
        )
    pool_drain = (cashpool.balance_paise * 8) // 10
    add_tx(
        cashpool,
        sink_a,
        pool_drain,
        seed_now - timedelta(hours=10),
        note="fuel",
        is_seeded_attack=True,
    )

    # Extra mule ring (structure 3).
    ring = [
        by_handle["neel.m@prima"],
        by_handle["tara.m@prima"],
        by_handle["om.m@prima"],
    ]
    hop_amount = 4_00_000
    for round_i in range(2):
        for i in range(3):
            sender = ring[i]
            receiver = ring[(i + 1) % 3]
            ts = seed_now - timedelta(days=3, hours=round_i * 6 + i)
            add_tx(
                sender,
                receiver,
                hop_amount,
                ts,
                note="household",
                is_seeded_attack=True,
            )

    # Sparse events so TrailScore has material later -- not a firehose.
    for i, acct in enumerate(regular_accounts[:40]):
        ts = window_start + timedelta(hours=6 + i * 8)
        ts = _clamp_ts(ts, acct)
        events.append(
            Event(
                id=_stable_id("event", acct.handle, "login_new_device", str(i)),
                account_id=acct.id,
                event_type="login_new_device",
                payload={"device_id": acct.device_id},
                ts=ts,
                ingest_source="seed",
            )
        )

    # Ramesh four-event chain in the last 20 minutes, canonical order,
    # packed inside the 15-minute TrailScore window.
    ramesh = by_handle["ramesh@prima"]
    ramesh_chain = (
        ("login_new_device", {"device_id": "dev-ramesh-new"}, 14),
        ("credential_changed", {"device_id": "dev-ramesh-new"}, 11),
        ("payee_added", {"payee_handle": "quickcash@prima"}, 8),
        ("limit_raised", {"old_limit": 5000000, "new_limit": 50000000}, 4),
    )
    for event_type, payload, minutes_ago in ramesh_chain:
        events.append(
            Event(
                id=_stable_id("event", ramesh.handle, event_type, "chain"),
                account_id=ramesh.id,
                event_type=event_type,
                payload=payload,
                ts=seed_now - timedelta(minutes=minutes_ago),
                ingest_source="seed",
            )
        )

    trusted = TrustedContact(
        id=_stable_id("tc", "ramesh@prima", "priya-ramesh-demo"),
        account_id=ramesh.id,
        contact_name="Priya",
        watch_token="priya-ramesh-demo",
        nominated_at=_utc(seed_now, days=30),
    )

    account_rows = list(by_handle.values())
    with Session(engine) as session:
        if reset:
            _wipe_all(session)
        session.add_all(account_rows)
        session.add_all(txs)
        session.add_all(events)
        session.add(trusted)
        session.commit()

    return {
        "accounts": len(account_rows),
        "transactions": len(txs),
        "events": len(events),
        "trusted_contacts": 1,
        "named_handles": list(NAMED_HANDLES),
    }


def wipe_database() -> None:
    """Clear all SQLModel tables. Ops reset uses this, then re-seeds."""
    create_db_and_tables()
    with Session(engine) as session:
        _wipe_all(session)
        session.commit()


if __name__ == "__main__":
    print(json.dumps(seed_database()))

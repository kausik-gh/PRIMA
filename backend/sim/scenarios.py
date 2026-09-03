"""Demo-time operators: inject events, provision guests, report a tx, reset.

P3 will HTTP-wrap these later. No routes in this module.
call_context text is stored as given; this file does not parse it.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from backend.core.config import get_config
from backend.core.db import engine
from backend.core.ledger import account_by_handle
from backend.core.models import Account, Event, Transaction, utc_now
from backend.graph.pathgraph import rebuild_from_db, upsert_event
from backend.graph.taint import mark_fraudulent
from backend.sim.seed import seed_database

ALLOWED_EVENT_TYPES = frozenset({
    "login_new_device",
    "credential_changed",
    "payee_added",
    "limit_raised",
    "screen_share_active",
    "note_entered",
    "call_context",
    "transfer_attempted",
})

SEQUENCE_SCENARIO = "takeover_isolation"

SEQUENCE_STEPS = (
    ("login_new_device", {"device_id": "dev-injected"}, 14),
    ("credential_changed", {"device_id": "dev-injected"}, 11),
    ("payee_added", {"payee_handle": "quickcash@prima"}, 8),
    ("limit_raised", {"old_limit": 5000000, "new_limit": 50000000}, 4),
)


def inject_event(
    session: Session,
    account_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    *,
    ingest_source: str = "operator",
) -> Event:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"unknown account: {account_id}")
    event = Event(
        account_id=account_id,
        event_type=event_type,
        payload=payload,
        ts=utc_now(),
        ingest_source=ingest_source,
    )
    session.add(event)
    session.flush()
    upsert_event(event, account)
    return event


def inject_sequence(
    session: Session,
    account_id: str,
    scenario: str = SEQUENCE_SCENARIO,
) -> list[Event]:
    if scenario != SEQUENCE_SCENARIO:
        raise ValueError(f"unsupported scenario: {scenario}")
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"unknown account: {account_id}")
    now = datetime.now(timezone.utc)
    written: list[Event] = []
    for event_type, payload, minutes_ago in SEQUENCE_STEPS:
        event = Event(
            account_id=account_id,
            event_type=event_type,
            payload=dict(payload),
            ts=now - timedelta(minutes=minutes_ago),
            ingest_source="operator",
        )
        session.add(event)
        session.flush()
        upsert_event(event, account)
        written.append(event)
    return written


def inject_context(session: Session, account_id: str, text: str) -> Event:
    return inject_event(
        session,
        account_id,
        "call_context",
        {"text": text},
        ingest_source="operator",
    )


def _slug_from_display(display_name: str) -> str:
    slug = display_name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "guest"


def _unique_handle(session: Session, slug: str) -> str:
    candidate = f"{slug}@prima"
    if account_by_handle(session, candidate) is None:
        return candidate
    for _ in range(32):
        suffix = uuid.uuid4().hex[:4]
        candidate = f"{slug}-{suffix}@prima"
        if account_by_handle(session, candidate) is None:
            return candidate
    raise RuntimeError("could not allocate a unique guest handle")


def provision_guest(session: Session, display_name: str) -> dict:
    cfg = get_config()
    balance_paise = int(cfg["ledger"]["default_guest_balance_paise"])
    handle = _unique_handle(session, _slug_from_display(display_name))
    account = Account(
        handle=handle,
        display_name=display_name,
        bank_code="BANKA",
        device_id=f"dev-guest-{uuid.uuid4().hex[:8]}",
        created_at=utc_now(),
        balance_paise=balance_paise,
        is_demo_guest=True,
        ground_truth_role=None,
    )
    session.add(account)
    session.flush()
    return {
        "handle": account.handle,
        "account_id": account.id,
        "display_name": account.display_name,
        "balance_paise": account.balance_paise,
        "pay_url": f"/pay?as={account.handle}",
    }


def report_fraud(session: Session, transaction_id: str) -> dict:
    result = mark_fraudulent(transaction_id, hops=3, session=session)
    return asdict(result)


def reset_demo(session: Session) -> dict:
    summary = seed_database(reset=True)
    rebuild_from_db(session)
    return summary


def _event_json(event: Event) -> dict:
    ts = event.ts
    return {
        "id": event.id,
        "account_id": event.account_id,
        "event_type": event.event_type,
        "payload": event.payload,
        "ts": ts.isoformat() if ts is not None else None,
        "ingest_source": event.ingest_source,
    }


def _require_account(session: Session, handle: str) -> Account:
    account = account_by_handle(session, handle)
    if account is None:
        raise SystemExit(f"unknown handle: {handle}")
    return account


def _settled_tx(session: Session, sender_handle: str, receiver_handle: str) -> Transaction:
    sender = _require_account(session, sender_handle)
    receiver = _require_account(session, receiver_handle)
    rows = session.exec(
        select(Transaction).where(
            Transaction.sender_id == sender.id,
            Transaction.receiver_id == receiver.id,
            Transaction.status == "settled",
        )
    ).all()
    if not rows:
        raise SystemExit(f"no settled tx {sender_handle} -> {receiver_handle}")

    def _aware(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    rows.sort(key=lambda tx: _aware(tx.attempted_at))
    return rows[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo scenario helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seq = sub.add_parser("inject-sequence")
    p_seq.add_argument("--handle", required=True)

    p_guest = sub.add_parser("provision-guest")
    p_guest.add_argument("--name", required=True)

    p_report = sub.add_parser("report-fraud")
    p_report.add_argument("--sender-handle", required=True)
    p_report.add_argument("--receiver-handle", required=True)

    sub.add_parser("reset")

    args = parser.parse_args()
    with Session(engine) as session:
        if args.cmd == "inject-sequence":
            account = _require_account(session, args.handle)
            events = inject_sequence(session, account.id)
            session.commit()
            print(json.dumps([_event_json(ev) for ev in events]))
        elif args.cmd == "provision-guest":
            payload = provision_guest(session, args.name)
            session.commit()
            print(json.dumps(payload))
        elif args.cmd == "report-fraud":
            origin = _settled_tx(session, args.sender_handle, args.receiver_handle)
            payload = report_fraud(session, origin.id)
            print(json.dumps(payload))
        elif args.cmd == "reset":
            print(json.dumps(reset_demo(session)))
        else:
            raise SystemExit(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()

# Inbound money is NEVER held. Only outbound. A hold is scoped to an amount on a
# transaction, never to an account. Freezing an account is not an available operation
# in this system — there is deliberately no function that does it.
#
# Replace with SQLModel session when core/schema lands (K). Do not create tables here.

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

IMMEDIATE_PAISE = 100
COOLING_MINUTES = 30
REASON_REF_PREFIX = "PRIMA-2026-"
RELEASE_OUTCOMES = frozenset({"released", "cancelled_by_user", "escalated"})

_lock = threading.Lock()
_reason_seq = 0

# Isolation seed. available_paise is derived, never stored as source of truth.
ACCOUNTS: dict[str, dict] = {
    "acct_isolation_merchant": {
        "account_id": "acct_isolation_merchant",
        "handle": "merchant@prima",
        "display_name": "Demo Merchant",
        "balance_paise": 14000000,
    }
}

TRANSACTIONS: dict[str, dict] = {
    "tx_isolation_1": {
        "transaction_id": "tx_isolation_1",
        "account_id": "acct_isolation_merchant",
        "amount_paise": 800000,
        "direction": "outbound",
        "status": "quoted",
    },
    "tx_isolation_inbound": {
        "transaction_id": "tx_isolation_inbound",
        "account_id": "acct_isolation_merchant",
        "amount_paise": 500000,
        "direction": "inbound",
        "status": "quoted",
    },
}

SCOPED_HOLDS: list[dict] = []


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_ts(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_account(account_id: str) -> dict | None:
    return ACCOUNTS.get(account_id)


def _require_paise(paise: int) -> int:
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("held_paise must be integer paise, never float")
    return paise


def _copy_hold(row: dict) -> dict:
    return dict(row)


def _is_active(row: dict) -> bool:
    return row["released_at"] is None


def available_paise(account_id: str) -> int:
    account = ACCOUNTS.get(account_id)
    if account is None:
        raise LookupError("unknown_account")
    held = sum(row["held_paise"] for row in SCOPED_HOLDS if row["account_id"] == account_id and _is_active(row))
    return account["balance_paise"] - held


def active_holds(account_id: str) -> list[dict]:
    return [
        _copy_hold(row)
        for row in SCOPED_HOLDS
        if row["account_id"] == account_id and _is_active(row)
    ]


def _next_reason_ref_unlocked() -> str:
    global _reason_seq
    _reason_seq += 1
    return f"{REASON_REF_PREFIX}{_reason_seq:06d}"


def next_reason_ref() -> str:
    with _lock:
        return _next_reason_ref_unlocked()


def open_hold(
    *,
    transaction_id: str,
    account_id: str,
    held_paise: int,
    cooling_minutes: int = COOLING_MINUTES,
    reason_ref: str | None = None,
) -> dict:
    held_paise = _require_paise(held_paise)
    if held_paise <= 0:
        raise ValueError("bad_amount")
    if isinstance(cooling_minutes, bool) or not isinstance(cooling_minutes, int) or cooling_minutes < 0:
        raise ValueError("bad_cooling")
    tx = TRANSACTIONS.get(transaction_id)
    if tx is None:
        raise LookupError("unknown_transaction")
    if tx["direction"] != "outbound":
        raise ValueError("inbound_never_held")
    if ACCOUNTS.get(account_id) is None:
        raise LookupError("unknown_account")
    if tx["account_id"] != account_id:
        raise ValueError("account_mismatch")
    with _lock:
        if held_paise > available_paise(account_id):
            raise ValueError("insufficient_available")
        opened = utc_now()
        row = {
            "id": "sh_" + uuid.uuid4().hex,
            "transaction_id": transaction_id,
            "account_id": account_id,
            "held_paise": held_paise,
            "reason_ref": reason_ref or _next_reason_ref_unlocked(),
            "opened_at": format_ts(opened),
            "releases_at": format_ts(opened + timedelta(minutes=cooling_minutes)),
            "released_at": None,
            "outcome": None,
        }
        SCOPED_HOLDS.append(row)
        return _copy_hold(row)


def release_hold(hold_id: str, outcome: str) -> dict:
    if outcome not in RELEASE_OUTCOMES:
        raise ValueError("bad_outcome")
    with _lock:
        row = None
        for item in SCOPED_HOLDS:
            if item["id"] == hold_id:
                row = item
                break
        if row is None:
            raise LookupError("unknown_hold")
        if not _is_active(row):
            return _copy_hold(row)
        row["released_at"] = format_ts(utc_now())
        row["outcome"] = outcome
        return _copy_hold(row)


def account_view(account_id: str) -> dict:
    account = ACCOUNTS.get(account_id)
    if account is None:
        raise LookupError("unknown_account")
    holds = [
        {
            "reason_ref": row["reason_ref"],
            "held_paise": row["held_paise"],
            "releases_at": row["releases_at"],
        }
        for row in active_holds(account_id)
    ]
    return {
        "balance_paise": account["balance_paise"],
        "available_paise": available_paise(account_id),
        "active_holds": holds,
    }

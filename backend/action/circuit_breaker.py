"""Trusted-contact CircuitBreaker.

Caller (payer commit / ops) must invoke only at tier 4 when a trusted_contacts
row exists. This module does not check tier.

Replace with SQLModel session when core/schema lands (K). Do not create tables here.

Inbound money is never held. Only outbound. This module alerts a nominated
contact; it does not move money. There is deliberately no function that can
freeze an account in this system.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Protocol

# Isolation seed so /watch/test works with zero DB.
SESSIONS: dict[str, dict] = {
    "test": {
        "token": "test",
        "account_holder": "Ramesh K.",
        "contact_name": "Priya",
        "account_id": "acct_isolation_ramesh",
    }
}

BREAKER_LOG: list[dict] = []
_log_lock = asyncio.Lock()

DEFAULT_FACTS: list[str] = [
    "14 people sent money to this account today",
    "Ramesh has never paid it before",
    "His transfer limit was raised 8 minutes ago",
]

ACTIONS: list[str] = [
    "This is fine",
    "Something is wrong — hold it",
]


class Hub(Protocol):
    async def broadcast(self, topic: str, event: dict) -> None: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def get_session(token: str) -> dict | None:
    return SESSIONS.get(token)


def latest_log(token: str) -> dict | None:
    for row in reversed(BREAKER_LOG):
        if row["token"] == token:
            return row
    return None


def _require_paise(paise: int) -> int:
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("amount_paise must be integer paise, never float")
    return paise


def _indian_group(rupees: int) -> str:
    digits = str(rupees)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while head:
        parts.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(parts)) + "," + tail


def format_paise(paise: int) -> str:
    paise = _require_paise(paise)
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), 100)
    grouped = _indian_group(rupees)
    if remainder:
        return f"{sign}₹{grouped}.{remainder:02d}"
    return f"{sign}₹{grouped}"


def headline(account_holder: str, amount_paise: int, payee_age_days: int) -> str:
    first = account_holder.strip().split()[0] if account_holder.strip() else account_holder
    amount = format_paise(amount_paise)
    return (
        f"{first} is about to send {amount} to an account opened "
        f"{payee_age_days} days ago."
    )


def build_payload(
    *,
    account_holder: str,
    amount_paise: int,
    payee_age_days: int,
    facts: list[str],
) -> dict:
    if len(facts) != 3 or any(not isinstance(item, str) for item in facts):
        raise ValueError("facts must be exactly 3 strings")
    return {
        "type": "circuit_breaker",
        "account_holder": account_holder,
        "amount": format_paise(amount_paise),
        "payee_age_days": payee_age_days,
        "headline": headline(account_holder, amount_paise, payee_age_days),
        "facts": list(facts),
        "actions": list(ACTIONS),
    }


def _envelope(event_type: str, data: dict, ts: str | None = None) -> dict:
    return {"type": event_type, "ts": ts or utc_now(), "data": data}


async def fire(hub: Hub, token: str, payload: dict) -> str:
    log_id = "cb_" + uuid.uuid4().hex
    fired_at = utc_now()
    row = {
        "id": log_id,
        "token": token,
        "fired_at": fired_at,
        "payload": payload,
        "ack": False,
        "ack_action": None,
        "ack_at": None,
    }
    async with _log_lock:
        BREAKER_LOG.append(row)
    await hub.broadcast(
        f"watch:{token}",
        _envelope("circuit_breaker.fired", payload, fired_at),
    )
    return log_id


async def ack(hub: Hub, token: str, action: str) -> dict:
    # SQL ScopedHold extend/release is applied by payer_breaker.apply_contact_ack.
    if action not in ("approved", "hold"):
        raise ValueError("bad_action")
    session = get_session(token)
    if session is None:
        raise LookupError("unknown_token")
    async with _log_lock:
        row = None
        for item in reversed(BREAKER_LOG):
            if item["token"] == token and not item["ack"]:
                row = item
                break
        if row is None:
            raise LookupError("no_pending")
        ack_at = utc_now()
        row["ack"] = True
        row["ack_action"] = action
        row["ack_at"] = ack_at
    data = {
        "ack_action": action,
        "ack_at": ack_at,
        "contact_name": session["contact_name"],
    }
    await hub.broadcast(
        f"watch:{token}",
        _envelope("circuit_breaker.acked", data, ack_at),
    )
    return data

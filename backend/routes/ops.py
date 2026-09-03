"""Operator / demo-control API. Not a product surface. No freeze-account path."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.action import circuit_breaker as cb
from backend.action.payer_ledger import iso
from backend.action.payer_seed import ensure_payer_seed, sync_watch_sessions
from backend.core.config import get_config
from backend.core.db import engine, get_session
from backend.core.models import (
    Account,
    Event,
    RiskDecision,
    TrustedContact,
    utc_now,
)
from backend.routes.console_queries import graph_node
from backend.routes.ws import envelope, hub
from backend.sim.seed import seed_database, wipe_database

router = APIRouter(prefix="/api/ops", tags=["ops"])

ALLOWED_EVENTS = frozenset(
    {
        "login_new_device",
        "credential_changed",
        "payee_added",
        "limit_raised",
        "screen_share_active",
        "note_entered",
        "call_context",
        "transfer_attempted",
    }
)
TAKEOVER_CHAIN = (
    ("login_new_device", {"device_id": "ops-injected-device"}, 14),
    ("credential_changed", {"device_id": "ops-injected-device"}, 11),
    ("payee_added", {"source": "ops"}, 8),
    ("limit_raised", {"source": "ops"}, 4),
)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _public_origin(request: Request) -> str:
    port = int((get_config().get("server") or {}).get("port") or 8088)
    header = (request.headers.get("host") or "").strip()
    host = request.url.hostname or "127.0.0.1"
    if not header or host in {"testserver", "test"}:
        return f"http://127.0.0.1:{port}"
    if ":" in header:
        return f"http://{header}"
    return f"http://{header}:{port}"


def _guest_handle(session: Session, display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", display_name.lower())
    if not slug:
        slug = "guest"
    base = f"{slug}@prima"
    if session.exec(select(Account).where(Account.handle == base)).first() is None:
        return base
    n = 2
    while True:
        candidate = f"{slug}{n}@prima"
        if session.exec(select(Account).where(Account.handle == candidate)).first() is None:
            return candidate
        n += 1


class SeedBody(BaseModel):
    accounts: int | None = None
    days: int | None = None


class GuestBody(BaseModel):
    display_name: str


class EventBody(BaseModel):
    account_id: str
    event_type: str
    payload: dict[str, Any] | None = None


class InjectBody(BaseModel):
    account_id: str
    scenario: str


class ContextBody(BaseModel):
    account_id: str
    text: str


class AttackBody(BaseModel):
    pattern: str


class NominateBody(BaseModel):
    account_id: str
    contact_name: str


class FireBreakerBody(BaseModel):
    token: str | None = None


class ReportFraudBody(BaseModel):
    transaction_id: str | None = None
    sender_handle: str | None = None
    receiver_handle: str | None = None


@router.post("/seed")
def ops_seed(body: SeedBody):
    cfg = get_config().get("ledger") or {}
    accounts = body.accounts if body.accounts is not None else int(cfg.get("seed_accounts") or 500)
    days = body.days if body.days is not None else int(cfg.get("seed_days") or 21)
    try:
        result = seed_database(accounts=accounts, days=days, reset=True)
    except ValueError as exc:
        return _error(400, "bad_seed", str(exc))
    with Session(engine) as session:
        sync_watch_sessions(session)
    return {"ok": True, **result}


@router.post("/guest")
async def ops_guest(body: GuestBody, request: Request, session: Session = Depends(get_session)):
    name = body.display_name.strip()
    if len(name) < 2:
        return _error(400, "bad_name", "display_name must be at least 2 characters.")
    cfg = get_config().get("ledger") or {}
    balance = int(cfg.get("default_guest_balance_paise") or 50_000_000)
    handle = _guest_handle(session, name)
    now = utc_now()
    acct = Account(
        id="acct_" + uuid.uuid4().hex,
        handle=handle,
        display_name=name,
        bank_code="BANKA",
        device_id="device_guest_" + uuid.uuid4().hex[:12],
        created_at=now,
        balance_paise=balance,
        is_demo_guest=True,
        ground_truth_role=None,
    )
    session.add(acct)
    session.commit()
    session.refresh(acct)
    node = graph_node(session, acct.id)
    if node is not None:
        await hub.broadcast("console", envelope("graph.node_updated", node))
    origin = _public_origin(request)
    return {
        "handle": acct.handle,
        "account_id": acct.id,
        "pay_url": f"{origin}/pay?as={acct.handle}",
        "balance_paise": acct.balance_paise,
    }


@router.post("/event")
def ops_event(body: EventBody, session: Session = Depends(get_session)):
    if body.event_type not in ALLOWED_EVENTS:
        return _error(400, "bad_event_type", "event_type is not an allowed event.")
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    row = Event(
        id="ev_" + uuid.uuid4().hex,
        account_id=acct.id,
        event_type=body.event_type,
        payload=body.payload,
        ts=utc_now(),
        ingest_source="ops",
    )
    session.add(row)
    session.commit()
    return {"ok": True, "event_id": row.id, "event_type": row.event_type}


@router.post("/inject_sequence")
def ops_inject(body: InjectBody, session: Session = Depends(get_session)):
    if body.scenario != "takeover_isolation":
        return _error(400, "unknown_scenario", "Only takeover_isolation is available.")
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    now = utc_now()
    written: list[dict[str, Any]] = []
    for event_type, payload, minutes_ago in TAKEOVER_CHAIN:
        row = Event(
            id="ev_" + uuid.uuid4().hex,
            account_id=acct.id,
            event_type=event_type,
            payload=dict(payload),
            ts=now - timedelta(minutes=minutes_ago),
            ingest_source="ops",
        )
        session.add(row)
        written.append({"event_type": event_type, "ts": iso(row.ts)})
    session.commit()
    return {"ok": True, "scenario": body.scenario, "events": written}


@router.post("/context")
def ops_context(body: ContextBody, session: Session = Depends(get_session)):
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    text = body.text.strip()
    if not text:
        return _error(400, "bad_text", "text must not be empty.")
    row = Event(
        id="ev_" + uuid.uuid4().hex,
        account_id=acct.id,
        event_type="call_context",
        payload={"text": text},
        ts=utc_now(),
        ingest_source="ops",
    )
    session.add(row)
    session.commit()
    return {"ok": True, "event_id": row.id, "event_type": "call_context"}


@router.post("/attack")
def ops_attack(_body: AttackBody):
    return _error(
        501,
        "not_implemented",
        "Attack injection is not ported onto the SQL ledger on this branch.",
    )


@router.post("/nominate_contact")
def ops_nominate(body: NominateBody, request: Request, session: Session = Depends(get_session)):
    name = body.contact_name.strip()
    if len(name) < 2:
        return _error(400, "bad_name", "contact_name must be at least 2 characters.")
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    token = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "contact"
    token = f"{token}-{uuid.uuid4().hex[:8]}"
    row = TrustedContact(
        id="tc_" + uuid.uuid4().hex,
        account_id=acct.id,
        contact_name=name,
        watch_token=token,
        nominated_at=utc_now(),
    )
    session.add(row)
    session.commit()
    sync_watch_sessions(session, acct)
    origin = _public_origin(request)
    return {"watch_url": f"{origin}/watch/{token}", "watch_token": token, "contact_name": name}


@router.post("/reset")
def ops_reset():
    wipe_database()
    cb.SESSIONS.clear()
    cb.BREAKER_LOG.clear()
    ensure_payer_seed()
    return {"ok": True}


@router.get("/health")
def ops_health(session: Session = Depends(get_session)):
    db_ok = True
    try:
        session.exec(select(Account)).first()
    except Exception:
        db_ok = False
    latest = None
    if db_ok:
        rows = list(session.exec(select(RiskDecision)).all())
        if rows:
            rows.sort(key=lambda row: row.quote_at, reverse=True)
            latest = iso(rows[0].quote_at)
    return {
        "db_ok": db_ok,
        "rf_model_loaded": (_REPO_ROOT / "fraud_model.pkl").is_file(),
        "gnn_model_loaded": (_REPO_ROOT / "gnn_model.pth").is_file(),
        "ws_clients": hub.client_count(),
        "last_decision_at": latest,
    }


@router.post("/fire_breaker")
async def ops_fire_breaker(body: FireBreakerBody):
    token = (body.token or "test").strip() or "test"
    session_row = cb.get_session(token)
    if session_row is None:
        with Session(engine) as db:
            contact = db.exec(
                select(TrustedContact).where(TrustedContact.watch_token == token)
            ).first()
            if contact is not None:
                acct = db.get(Account, contact.account_id)
                if acct is not None:
                    sync_watch_sessions(db, acct)
                    session_row = cb.get_session(token)
    if session_row is None:
        return _error(404, "unknown_token", "No watch session for that token.")
    payload = cb.build_payload(
        account_holder=session_row["account_holder"],
        amount_paise=40_000_000,
        payee_age_days=6,
        facts=list(cb.DEFAULT_FACTS),
    )
    log_id = await cb.fire(hub, token, payload)
    return {"ok": True, "log_id": log_id, "token": token}


@router.post("/report_fraud")
def ops_report_fraud(_body: ReportFraudBody):
    return _error(
        501,
        "taint_unavailable",
        "TaintTrace is not on this branch; fraud report cannot propagate yet.",
    )

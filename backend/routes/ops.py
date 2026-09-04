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
from sqlmodel import Session, col, select

from backend.action import circuit_breaker as cb
from backend.action.payer_ledger import iso
from backend.action.payer_seed import ensure_payer_seed, sync_watch_sessions
from backend.action.scoped_hold import COOLING_MINUTES, next_reason_ref
from backend.core.config import get_config
from backend.core.db import engine, get_session
from backend.core.models import (
    Account,
    Event,
    RiskDecision,
    ScopedHold,
    Transaction,
    TrustedContact,
    utc_now,
)
from backend.graph.taint import mark_fraudulent
from backend.routes.console_queries import graph_node
from backend.routes.ws import envelope, hub
from backend.sim import ambient
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
    # Previously (14, 11, 8, 4) against a 15-minute TrailScore window left
    # under 60s margin — confirmed live to silently collapse tier 4 to
    # tier 0 after normal setup delay. Retuned for a ~6-minute margin.
    ("login_new_device", {"device_id": "ops-injected-device"}, 9),
    ("credential_changed", {"device_id": "ops-injected-device"}, 7),
    ("payee_added", {"source": "ops"}, 5),
    ("limit_raised", {"source": "ops"}, 2),
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RF_LOAD_CACHE: bool | None = None


def _gnn_actually_loads() -> bool:
    """True only if the GAT artifact both exists and imports into FraudGAT."""
    try:
        from backend.gnn import PYG_AVAILABLE, _load_gnn_model

        if not PYG_AVAILABLE or not (_REPO_ROOT / "gnn_model.pth").is_file():
            return False
        _load_gnn_model(str(_REPO_ROOT / "gnn_model.pth"), "cpu")
        return True
    except Exception:
        return False


def _rf_actually_loads() -> bool:
    """File presence is not enough — a missing sklearn/joblib used to report true."""
    global _RF_LOAD_CACHE
    if _RF_LOAD_CACHE is not None:
        return _RF_LOAD_CACHE
    path = _REPO_ROOT / "fraud_model.pkl"
    if not path.is_file():
        _RF_LOAD_CACHE = False
        return False
    try:
        import joblib

        joblib.load(path)
        _RF_LOAD_CACHE = True
    except Exception:
        _RF_LOAD_CACHE = False
    return _RF_LOAD_CACHE


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


class RearmBody(BaseModel):
    account_id: str


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
    # Arm this account for is_seeded_attack tagging — see payer.py's quote
    # handler. Re-armed to "now" each call, same 30-minute window rearm
    # uses for the canonical chain, so re-injecting also re-arms cleanly.
    session.add(
        Event(
            id="ev_" + uuid.uuid4().hex,
            account_id=acct.id,
            event_type="staged_attack_armed",
            payload={},
            ts=now,
            ingest_source="ops",
        )
    )
    session.commit()
    return {"ok": True, "scenario": body.scenario, "events": written}


@router.post("/rearm_sequence")
def ops_rearm(body: RearmBody, session: Session = Depends(get_session)):
    """Re-stamp an already-injected scenario's events to 'now'. See the
    TAKEOVER_CHAIN comment above for why this exists."""
    acct = session.get(Account, body.account_id)
    if acct is None:
        return _error(404, "unknown_account", "No account with that id.")
    latest_by_type: dict[str, Event] = {}
    for event_type, _payload, _minutes in TAKEOVER_CHAIN:
        row = session.exec(
            select(Event)
            .where(Event.account_id == acct.id)
            .where(Event.event_type == event_type)
            .order_by(col(Event.ts).desc())
        ).first()
        if row is not None:
            latest_by_type[event_type] = row
    if not latest_by_type:
        return _error(
            404, "no_sequence_to_rearm",
            "No injected sequence found on this account — run inject_sequence first.",
        )
    now = utc_now()
    rearmed: list[dict[str, Any]] = []
    for event_type, _payload, minutes_ago in TAKEOVER_CHAIN:
        row = latest_by_type.get(event_type)
        if row is None:
            continue
        row.ts = now - timedelta(minutes=minutes_ago)
        session.add(row)
        rearmed.append({"event_type": row.event_type, "ts": iso(row.ts)})
    context_row = session.exec(
        select(Event)
        .where(Event.account_id == acct.id)
        .where(Event.event_type == "call_context")
        .order_by(col(Event.ts).desc())
    ).first()
    if context_row is not None:
        context_row.ts = now - timedelta(minutes=1)
        session.add(context_row)
        rearmed.append({"event_type": "call_context", "ts": iso(context_row.ts)})

    # Refresh the is_seeded_attack arming window too — rearm is pressed
    # right before the judge actually pays, so this is the more reliable
    # place to guarantee the window is fresh, not just inject_sequence.
    session.add(
        Event(
            id="ev_" + uuid.uuid4().hex,
            account_id=acct.id,
            event_type="staged_attack_armed",
            payload={},
            ts=now,
            ingest_source="ops",
        )
    )
    session.commit()
    return {"ok": True, "rearmed": rearmed}


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
async def ops_reset():
    # Stop ambient traffic first — a reseed against pre-reset account ids would
    # otherwise crash or silently no-op mid-run.
    await ambient.stop()
    wipe_database()
    cb.SESSIONS.clear()
    cb.BREAKER_LOG.clear()
    ensure_payer_seed()
    return {"ok": True}


@router.post("/ambient/start")
async def ops_ambient_start():
    """Begin low-stakes real background traffic between ordinary seeded accounts.

    Idempotent: calling it while already running just confirms running:true.
    """
    ambient.start()
    return {"ok": True, "running": ambient.is_running()}


@router.post("/ambient/stop")
async def ops_ambient_stop():
    await ambient.stop()
    return {"ok": True, "running": ambient.is_running()}


NAMED_HANDLES = frozenset(
    {
        "ramesh@prima",
        "priya.k@prima",
        "grocery@prima",
        "rentals@prima",
        "quickcash@prima",
        "merchant.ok@prima",
    }
)


@router.get("/directory")
def ops_directory(session: Session = Depends(get_session)):
    """Named demo accounts plus guests. Ops panel uses this to pick inject targets."""
    contacts = {
        row.account_id: row for row in session.exec(select(TrustedContact)).all()
    }
    items: list[dict[str, Any]] = []
    for acct in session.exec(select(Account)).all():
        if acct.handle not in NAMED_HANDLES and not acct.is_demo_guest:
            continue
        contact = contacts.get(acct.id)
        items.append(
            {
                "id": acct.id,
                "handle": acct.handle,
                "display_name": acct.display_name,
                "is_demo_guest": bool(acct.is_demo_guest),
                "balance_paise": acct.balance_paise,
                "watch_token": contact.watch_token if contact is not None else None,
                "contact_name": contact.contact_name if contact is not None else None,
            }
        )
    items.sort(key=lambda row: (not row["is_demo_guest"], row["handle"]))
    return {"items": items}


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
        "rf_model_loaded": _rf_actually_loads(),
        "gnn_model_loaded": _gnn_actually_loads(),
        "ws_clients": hub.client_count(),
        "last_decision_at": latest,
        "ambient_running": ambient.is_running(),
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
def ops_report_fraud(body: ReportFraudBody, session: Session = Depends(get_session)):
    if not body.transaction_id:
        return _error(400, "bad_request", "transaction_id is required.")
    try:
        result = mark_fraudulent(body.transaction_id, hops=3, session=session)
    except ValueError as exc:
        return _error(400, "cannot_taint", str(exc))

    # mark_fraudulent only writes taint_ratio. Act 5 still needs an amount-scoped
    # hold on downstream receivers so an innocent merchant is not frozen.
    TAINT_HOLD_THRESHOLD = 0.15  # matches ringwatch's taint_gate.min_ratio
    opened_holds: list[dict[str, Any]] = []
    for hop in result.hops:
        if hop.hop == 0 or hop.taint_ratio < TAINT_HOLD_THRESHOLD:
            continue
        tx = session.get(Transaction, hop.tx_id)
        if tx is None or tx.status != "settled":
            continue
        receiver = session.get(Account, hop.receiver_id)
        if receiver is None:
            continue
        traced_paise = int(tx.amount_paise * hop.taint_ratio)
        if traced_paise <= 0:
            continue
        hold = ScopedHold(
            id="sh_" + uuid.uuid4().hex,
            transaction_id=tx.id,
            account_id=receiver.id,
            held_paise=traced_paise,
            reason_ref=next_reason_ref(),
            opened_at=utc_now(),
            releases_at=utc_now() + timedelta(minutes=COOLING_MINUTES),
        )
        session.add(hold)
        opened_holds.append(
            {
                "account": receiver.handle,
                "held_paise": traced_paise,
                "reason_ref": hold.reason_ref,
            }
        )
    session.commit()
    return {
        "ok": True,
        "origin_tx_id": result.origin_tx_id,
        "hops": [
            {
                "tx_id": h.tx_id,
                "hop": h.hop,
                "taint_ratio": h.taint_ratio,
                "sender_id": h.sender_id,
                "receiver_id": h.receiver_id,
            }
            for h in result.hops
        ],
        "opened_holds": opened_holds,
    }

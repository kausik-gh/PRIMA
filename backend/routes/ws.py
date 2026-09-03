"""TopicHub and the trusted-contact watch websocket.

Full snapshot only on connect. Diffs after that — never a 1-second full-state timer.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.action import circuit_breaker as cb
from backend.action import scoped_hold as sh
from backend.core.db import engine
from backend.core.models import CircuitBreakerLog, ScopedHold, TrustedContact
from sqlmodel import Session, select

router = APIRouter()
harness_router = APIRouter()


class TopicHub:
    def __init__(self) -> None:
        self._topics: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, topic: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._topics.setdefault(topic, set()).add(ws)

    async def disconnect(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._topics.get(topic)
            if conns is None:
                return
            conns.discard(ws)
            if not conns:
                self._topics.pop(topic, None)

    async def broadcast(self, topic: str, event: dict) -> None:
        async with self._lock:
            targets = list(self._topics.get(topic, ()))
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.disconnect(topic, ws)

    def client_count(self, topic: str | None = None) -> int:
        if topic is None:
            return sum(len(conns) for conns in self._topics.values())
        return len(self._topics.get(topic, ()))


hub = TopicHub()


def envelope(event_type: str, data: dict) -> dict:
    return {"type": event_type, "ts": cb.utc_now(), "data": data}


def _http_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


@router.websocket("/ws/watch/{token}")
async def watch_socket(ws: WebSocket, token: str) -> None:
    session = cb.get_session(token)
    if session is None:
        await ws.accept()
        await ws.close(code=4404)
        return
    topic = f"watch:{token}"
    await hub.connect(topic, ws)
    try:
        await ws.send_json(
            envelope(
                "snapshot",
                {
                    "watching_for": session["account_holder"],
                    "connected": True,
                },
            )
        )
        while True:
            message = await ws.receive_json()
            if not isinstance(message, dict) or message.get("type") != "circuit_breaker.ack":
                await ws.send_json(
                    envelope(
                        "error",
                        {
                            "code": "bad_type",
                            "message": "Only circuit_breaker.ack is accepted on this channel.",
                        },
                    )
                )
                continue
            action = message.get("action")
            if action not in ("approved", "hold"):
                await ws.send_json(
                    envelope(
                        "error",
                        {
                            "code": "bad_action",
                            "message": "action must be approved or hold.",
                        },
                    )
                )
                continue
            try:
                from backend.action.payer_breaker import apply_contact_ack

                await apply_contact_ack(token=token, action=action)
            except LookupError:
                await ws.send_json(
                    envelope(
                        "error",
                        {
                            "code": "no_pending",
                            "message": "Nothing to respond to right now.",
                        },
                    )
                )
            except ValueError:
                await ws.send_json(
                    envelope(
                        "error",
                        {
                            "code": "bad_action",
                            "message": "action must be approved or hold.",
                        },
                    )
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(topic, ws)


@router.websocket("/ws/pay/{account_id}")
async def pay_socket(ws: WebSocket, account_id: str) -> None:
    if sh.get_account(account_id) is None:
        await ws.accept()
        await ws.close(code=4404)
        return
    topic = f"pay:{account_id}"
    await hub.connect(topic, ws)
    try:
        await ws.send_json(envelope("snapshot", sh.account_view(account_id)))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(topic, ws)


def _hold_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, LookupError):
        code = str(exc)
        messages = {
            "unknown_account": "No isolation account with that id.",
            "unknown_transaction": "No isolation transaction with that id.",
            "unknown_hold": "No hold with that id.",
        }
        return _http_error(404, code, messages.get(code, code))
    if isinstance(exc, TypeError):
        return _http_error(400, "bad_amount", "held_paise must be integer paise.")
    code = str(exc)
    messages = {
        "inbound_never_held": "Inbound money is never held. Only outbound.",
        "bad_amount": "held_paise must be a positive integer.",
        "bad_cooling": "cooling_minutes must be a non-negative integer.",
        "account_mismatch": "Hold account must match the outbound transaction.",
        "insufficient_available": "Held amount is more than currently available.",
        "bad_outcome": "outcome must be released, cancelled_by_user, or escalated.",
    }
    return _http_error(400, code, messages.get(code, code))


def _hold_plus_available(hold: dict) -> dict:
    payload = dict(hold)
    payload["available_paise"] = sh.available_paise(hold["account_id"])
    return payload


class FireRequest(BaseModel):
    token: str
    amount_paise: int
    payee_age_days: int
    account_holder: str | None = None
    facts: list[str] | None = None


@harness_router.post("/api/watch/fire")
async def watch_fire(body: FireRequest):
    session = cb.get_session(body.token)
    if session is None:
        return _http_error(404, "unknown_token", "No watch session for that token.")
    if isinstance(body.amount_paise, bool) or not isinstance(body.amount_paise, int):
        return _http_error(400, "bad_amount", "amount_paise must be integer paise.")
    facts = body.facts
    if facts is None:
        facts = list(cb.DEFAULT_FACTS)
    elif len(facts) != 3 or any(not isinstance(item, str) for item in facts):
        return _http_error(400, "bad_facts", "facts must be exactly 3 strings.")
    holder = body.account_holder or session["account_holder"]
    payload = cb.build_payload(
        account_holder=holder,
        amount_paise=body.amount_paise,
        payee_age_days=body.payee_age_days,
        facts=facts,
    )
    log_id = await cb.fire(hub, body.token, payload)
    return {
        "ok": True,
        "log_id": log_id,
        "clients": hub.client_count(f"watch:{body.token}"),
    }


@harness_router.get("/api/watch/{token}/status")
async def watch_status(token: str):
    if cb.get_session(token) is None:
        # Allow status for SQL-only tokens after seed sync
        with Session(engine) as db:
            contact = db.exec(
                select(TrustedContact).where(TrustedContact.watch_token == token)
            ).first()
            if contact is None:
                return _http_error(404, "unknown_token", "No watch session for that token.")
    row = cb.latest_log(token)
    sql_ack = None
    hold_summary = None
    with Session(engine) as db:
        contact = db.exec(
            select(TrustedContact).where(TrustedContact.watch_token == token)
        ).first()
        if contact is not None:
            logs = list(
                db.exec(
                    select(CircuitBreakerLog).where(
                        CircuitBreakerLog.contact_id == contact.id
                    )
                ).all()
            )
            if logs:
                latest = logs[-1]
                sql_ack = {
                    "ack": bool(latest.ack),
                    "ack_action": latest.ack_action,
                    "ack_at": latest.ack_at.isoformat().replace("+00:00", "Z")
                    if latest.ack_at
                    else None,
                    "log_id": latest.id,
                }
                payload = dict(latest.payload or {})
                hold_id = payload.get("hold_id")
                hold = db.get(ScopedHold, hold_id) if hold_id else None
                if hold is not None:
                    hold_summary = {
                        "hold_id": hold.id,
                        "released_at": hold.released_at.isoformat().replace("+00:00", "Z")
                        if hold.released_at
                        else None,
                        "releases_at": hold.releases_at.isoformat().replace("+00:00", "Z")
                        if hold.releases_at
                        else None,
                        "outcome": hold.outcome,
                        "held_paise": hold.held_paise,
                    }
    return {
        "connected": hub.client_count(f"watch:{token}") > 0,
        "last_payload": None if row is None else row["payload"],
        "ack": False if row is None else bool(row["ack"]),
        "ack_action": None if row is None else row["ack_action"],
        "sql_ack": sql_ack,
        "hold": hold_summary,
    }


class WatchAckRequest(BaseModel):
    token: str
    action: str


@harness_router.post("/api/watch/ack")
async def watch_ack(body: WatchAckRequest):
    if body.action not in ("approved", "hold"):
        return _http_error(400, "bad_action", "action must be approved or hold.")
    # Ensure watch token is known in memory or SQL
    if cb.get_session(body.token) is None:
        with Session(engine) as db:
            contact = db.exec(
                select(TrustedContact).where(TrustedContact.watch_token == body.token)
            ).first()
            if contact is None:
                return _http_error(404, "unknown_token", "No watch session for that token.")
    try:
        from backend.action.payer_breaker import apply_contact_ack

        result = await apply_contact_ack(token=body.token, action=body.action)
    except LookupError as exc:
        code = str(exc) if str(exc) in {"no_pending", "unknown_transaction", "unknown_account"} else "no_pending"
        messages = {
            "no_pending": "Nothing to respond to right now.",
            "unknown_transaction": "No transaction for that hold.",
            "unknown_account": "Sender or receiver account missing.",
        }
        return _http_error(404, code, messages.get(code, code))
    except ValueError as exc:
        code = str(exc)
        messages = {
            "bad_action": "action must be approved or hold.",
            "inbound_never_held": "Inbound money is never held. Only outbound.",
            "insufficient_available": "Sender balance cannot cover the held remainder.",
        }
        if code not in messages:
            code = "bad_action"
        return _http_error(400, code, messages[code])
    return result


class OpenHoldRequest(BaseModel):
    transaction_id: str
    account_id: str
    held_paise: int
    cooling_minutes: int | None = None


class ReleaseHoldRequest(BaseModel):
    hold_id: str
    outcome: str


@harness_router.get("/api/hold/account/{account_id}")
async def hold_account(account_id: str):
    try:
        return sh.account_view(account_id)
    except LookupError as exc:
        return _hold_error(exc)


@harness_router.post("/api/hold/open")
async def hold_open(body: OpenHoldRequest):
    kwargs: dict = {
        "transaction_id": body.transaction_id,
        "account_id": body.account_id,
        "held_paise": body.held_paise,
    }
    if body.cooling_minutes is not None:
        kwargs["cooling_minutes"] = body.cooling_minutes
    try:
        hold = sh.open_hold(**kwargs)
    except (LookupError, ValueError, TypeError) as exc:
        return _hold_error(exc)
    payload = _hold_plus_available(hold)
    await hub.broadcast(f"pay:{body.account_id}", envelope("hold.opened", payload))
    return payload


@harness_router.post("/api/hold/release")
async def hold_release(body: ReleaseHoldRequest):
    try:
        hold = sh.release_hold(body.hold_id, body.outcome)
    except (LookupError, ValueError) as exc:
        return _hold_error(exc)
    payload = _hold_plus_available(hold)
    await hub.broadcast(f"pay:{hold['account_id']}", envelope("hold.released", payload))
    return payload

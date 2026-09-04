"""Razorpay webhook — the only place a real Razorpay event reaches PRIMA.

Signature verification uses the RAW request body exactly as Razorpay sent
it. FastAPI's body-parsing helpers reserialize JSON, which can reorder
keys or change whitespace and silently break signature verification. This
route reads request.body() directly, before any JSON parsing, and verifies
against those exact bytes.
"""
from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from backend.action.razorpay_client import verify_webhook_signature
from backend.core.db import engine
from backend.core.models import Account, RazorpayTopup, utc_now
from backend.routes.ws import envelope, hub

router = APIRouter(prefix="/api/razorpay", tags=["razorpay"])
log = logging.getLogger("prima.razorpay")
# Uvicorn's default last-resort filter hides INFO on this logger; the
# test script in the prompt looks for those credit lines on stdout.
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    ok = False
    try:
        ok = verify_webhook_signature(raw, signature)
    except Exception:
        log.exception("razorpay webhook: signature check raised")
    if not ok:
        log.warning("razorpay webhook: invalid signature, rejected")
        return _error(400, "bad_signature", "Signature verification failed.")

    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception:
        log.warning("razorpay webhook: body was not valid JSON despite valid signature")
        return _error(400, "bad_body", "Body was not valid JSON.")

    event = payload.get("event", "")
    entity = (payload.get("payload") or {}).get("payment", {}).get("entity", {})
    payment_id = entity.get("id")
    order_id = entity.get("order_id")
    log.info("razorpay webhook received: event=%s payment_id=%s order_id=%s", event, payment_id, order_id)

    if event not in ("payment.captured", "payment.failed"):
        log.info("razorpay webhook: ignoring unhandled event type %s", event)
        return {"ok": True, "ignored": True}

    if not order_id:
        log.warning("razorpay webhook: %s with no order_id in payload", event)
        return _error(400, "missing_order_id", "No order_id in webhook payload.")

    with Session(engine) as session:
        topup = session.exec(
            select(RazorpayTopup).where(RazorpayTopup.razorpay_order_id == order_id)
        ).first()
        if topup is None:
            log.warning("razorpay webhook: no topup row for order_id=%s", order_id)
            return _error(404, "unknown_order", "No matching top-up for this order.")

        # Idempotency: a payment_id already recorded as captured means this
        # is a duplicate delivery. Razorpay retries webhooks; this must be
        # a no-op on repeat, not a second credit.
        if topup.status == "captured":
            log.info("razorpay webhook: order_id=%s already captured, skipping", order_id)
            return {"ok": True, "duplicate": True}

        if event == "payment.failed":
            topup.status = "failed"
            topup.razorpay_payment_id = payment_id
            session.add(topup)
            session.commit()
            log.info("razorpay webhook: order_id=%s marked failed", order_id)
            return {"ok": True, "status": "failed"}

        # payment.captured
        account = session.get(Account, topup.account_id)
        if account is None:
            log.error("razorpay webhook: order_id=%s references missing account_id=%s", order_id, topup.account_id)
            return _error(404, "unknown_account", "Top-up references a missing account.")

        topup.status = "captured"
        topup.razorpay_payment_id = payment_id
        topup.verified_at = utc_now()
        account.balance_paise += topup.amount_paise
        session.add(topup)
        session.add(account)
        session.commit()
        session.refresh(account)

        log.info(
            "razorpay webhook: order_id=%s payment_id=%s captured, credited %d paise to %s",
            order_id, payment_id, topup.amount_paise, account.handle,
        )

        await hub.broadcast(
            f"pay:{account.id}",
            envelope("topup.captured", {
                "balance_paise": account.balance_paise,
                "amount_paise": topup.amount_paise,
            }),
        )
        return {"ok": True, "status": "captured"}

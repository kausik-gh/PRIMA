"""Create a Razorpay Test Mode order that will later fund one demo account.

This is not a payment between two ledger accounts. Quote and commit never
call this. The webhook is the only path that credits balance_paise.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from backend.action.razorpay_client import RazorpayConfigError, create_order
from backend.core.db import get_session
from backend.core.models import Account, RazorpayTopup, utc_now

router = APIRouter(prefix="/api/razorpay", tags=["razorpay"])
log = logging.getLogger("prima.razorpay")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class TopupOrderBody(BaseModel):
    account_id: str
    amount_paise: int


@router.post("/order")
def create_topup_order(body: TopupOrderBody, session: Session = Depends(get_session)):
    if body.amount_paise <= 0 or body.amount_paise > 10000:
        # Hard cap: this funds a demo wallet, never a real transfer target.
        # 10000 paise = Rs 100 is already generous for a top-up demo.
        return _error(400, "bad_amount", "amount_paise must be between 1 and 10000.")
    account = session.get(Account, body.account_id)
    if account is None:
        return _error(404, "unknown_account", "No account with that id.")
    try:
        order = create_order(body.amount_paise, receipt="topup_" + uuid.uuid4().hex[:12])
    except RazorpayConfigError as exc:
        return _error(500, "razorpay_not_configured", str(exc))
    except Exception:
        log.exception("razorpay order: create_order failed")
        return _error(502, "razorpay_error", "Could not create Razorpay order.")

    topup = RazorpayTopup(
        account_id=account.id,
        razorpay_order_id=order["id"],
        amount_paise=body.amount_paise,
        status="created",
        created_at=utc_now(),
    )
    session.add(topup)
    session.commit()

    return {
        "order_id": order["id"],
        "amount_paise": body.amount_paise,
        "key_id": os.environ.get("RAZORPAY_KEY_ID", ""),  # publishable, safe client-side
        "account_handle": account.handle,
    }

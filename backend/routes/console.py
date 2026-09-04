"""Console read APIs and PS3 metrics. No freeze-account path. No payer GT leakage."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from backend.core.db import get_session
from backend.core.models import RiskDecision
from backend.routes.console_queries import (
    confirm_ring,
    graph_payload,
    investigate_payload,
    list_decisions,
    ps3_metrics,
)

router = APIRouter(tags=["console"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get("/api/console/graph")
def console_graph(
    window: int = Query(default=500, ge=1, le=2000),
    bank: str = Query(default="ALL"),
    session: Session = Depends(get_session),
):
    return graph_payload(session, window=window, bank=bank)


@router.get("/api/console/decisions")
def console_decisions(
    limit: int = Query(default=100, ge=1, le=500),
    since: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    parsed = _parse_since(since)
    if since is not None and parsed is None:
        return _error(400, "bad_since", "since must be an ISO-8601 timestamp.")
    return list_decisions(session, limit=limit, since=parsed)


@router.get("/api/console/investigate/{account_id}")
def console_investigate(account_id: str, session: Session = Depends(get_session)):
    payload = investigate_payload(session, account_id)
    if payload is None:
        return _error(404, "unknown_account", "No account with that id.")
    return payload


@router.get("/api/console/decision/{decision_id}/regulator")
def console_regulator(decision_id: str, session: Session = Depends(get_session)):
    row = session.get(RiskDecision, decision_id)
    if row is None:
        return _error(404, "unknown_decision", "No decision with that id.")
    return row.regulator_record


class ConfirmRingBody(BaseModel):
    account_ids: list[str]
    fraud_type: str = "fan_in_ring"


@router.post("/api/console/rings/confirm")
def console_confirm_ring(body: ConfirmRingBody, session: Session = Depends(get_session)):
    if not body.account_ids:
        return _error(400, "empty_ring", "account_ids must not be empty.")
    try:
        return confirm_ring(session, body.account_ids, body.fraud_type)
    except ValueError as exc:
        code, _, detail = str(exc).partition(":")
        return _error(404, code, f"No account with id {detail}.")


@router.get("/api/metrics/ps3")
def metrics_ps3(session: Session = Depends(get_session)):
    return ps3_metrics(session)

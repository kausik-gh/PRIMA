"""Canonical PRIMA app. Isolation harness remains backend.action_dev:app.

Payer still uses backend.action.decision_stub until P2 fusion/ladder and
backend.core.decision are merged onto main. Do not start RealTimeEngine.
Do not load pkl/pth here.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.action.reasonline import (
    assert_user_reason_safe,
    bank,
    load_fixture,
    regulator,
    user,
    verify_regulator_record,
)
from backend.core.config import get_config, get_config_version
from backend.core.db import create_db_and_tables, engine
from backend.core.ensure_demo import ensure_smoke_merchant
from backend.routes.payer import router as payer_router
from backend.routes.ws import harness_router, router as ws_router


def _cors_origins() -> list[str]:
    origins = list(get_config().get("cors", {}).get("allow_origins") or [])
    # Never allow a wildcard, even if yaml or env is wrong.
    return [item for item in origins if item and item != "*"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_config()
    create_db_and_tables()
    # K seed (python -m backend.sim.seed) remains the real seeder.
    # This only adds merchant@prima for P3 quote smoke if it is missing.
    ensure_smoke_merchant()
    yield


app = FastAPI(title="PRIMA", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(ws_router)
app.include_router(harness_router)
app.include_router(payer_router)


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": str(exc)}},
    )


@app.get("/api/ops/health")
def health() -> dict:
    db_ok = False
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    return {
        "db_ok": db_ok,
        "rf_model_loaded": False,
        "gnn_model_loaded": False,
        "ws_clients": 0,
        "last_decision_at": None,
        "config_version": get_config_version(),
    }


@app.get("/api/reason/demo")
def reason_demo():
    decision = load_fixture()
    user_reason = user(decision)
    assert_user_reason_safe(user_reason)
    bank_reason = bank(decision)
    record = regulator(decision)
    if not verify_regulator_record(record):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "regulator_hash_mismatch",
                    "message": "Regulator payload hash did not verify.",
                }
            },
        )
    return {
        "decision_id": decision["id"],
        "tier": decision["tier"],
        "user_reason": user_reason,
        "bank_reason": bank_reason,
        "regulator_record": record,
        "payload_sha256": record["sha256_of_payload"],
        "verified": True,
    }

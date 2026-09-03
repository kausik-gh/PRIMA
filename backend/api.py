"""Thin PRIMA app. Routing splits happen in later phases.

P3 will relocate /api/ops/health to routes/ops.py. Do not start
RealTimeEngine, do not load pkl/pth, do not mount /frontend.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.config import get_config, get_config_version
from backend.core.db import create_db_and_tables, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_config()
    create_db_and_tables()
    yield


app = FastAPI(title="PRIMA", lifespan=lifespan)

_cors_origins = get_config()["cors"]["allow_origins"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


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
    # P3 will relocate to routes/ops.py
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

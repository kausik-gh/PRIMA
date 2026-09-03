"""Canonical PRIMA app. Isolation harness remains backend.action_dev:app.

Payer scores via RingWatch/TrailScore/ContextFlag (DecisionService fallbacks).
Do not start RealTimeEngine. Do not load CUDA paths.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.action.reasonline import (
    assert_user_reason_safe,
    bank,
    load_fixture,
    regulator,
    user,
    verify_regulator_record,
)
from backend.core.config import get_config
from backend.core.db import create_db_and_tables
from backend.core.ensure_demo import ensure_smoke_merchant
from backend.routes.console import router as console_router
from backend.routes.ops import router as ops_router
from backend.routes.payer import router as payer_router
from backend.routes.ws import harness_router, router as ws_router


def _cors_origins() -> list[str]:
    origins = list(get_config().get("cors", {}).get("allow_origins") or [])
    return [item for item in origins if item and item != "*"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_config()
    create_db_and_tables()
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
app.include_router(console_router)
app.include_router(ops_router)


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


def _mount_web(app: FastAPI) -> None:
    """Serve the built React app from web/dist when present."""
    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="web-assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "No such route."}},
            )
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_web(app)

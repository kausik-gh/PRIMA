"""CPU-safe CircuitBreaker isolation app. Does not load models.

Run: uvicorn backend.action_dev:app --host 0.0.0.0 --port 8088
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from backend.action import circuit_breaker as cb
from backend.routes.ws import harness_router, router as ws_router

HARNESS_PATH = Path(__file__).resolve().parent / "action" / "watch_harness.html"
HOLD_HARNESS_PATH = Path(__file__).resolve().parent / "action" / "hold_harness.html"


def _cors_origins() -> list[str]:
    origins = [
        "http://localhost:8088",
        "http://127.0.0.1:8088",
    ]
    extra = os.environ.get("PRIMA_CORS_ORIGINS", "")
    for item in extra.split(","):
        origin = item.strip()
        if origin and origin != "*":
            origins.append(origin)
    seen: set[str] = set()
    unique: list[str] = []
    for origin in origins:
        if origin not in seen:
            seen.add(origin)
            unique.append(origin)
    return unique


app = FastAPI(title="PRIMA CircuitBreaker isolation", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(ws_router)
app.include_router(harness_router)


@app.exception_handler(RequestValidationError)
async def validation_error(_request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request body was not valid.",
            }
        },
    )


@app.get("/watch/{token}")
def watch_page(token: str) -> HTMLResponse:
    session = cb.get_session(token)
    if session is None:
        return HTMLResponse(
            (
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                "<title>Not found</title></head>"
                "<body><p>Watch token not found.</p></body></html>"
            ),
            status_code=404,
        )
    html = HARNESS_PATH.read_text(encoding="utf-8")
    boot = json.dumps(
        {
            "token": session["token"],
            "account_holder": session["account_holder"],
        },
        ensure_ascii=False,
    )
    return HTMLResponse(html.replace("__BOOT_JSON__", boot))


@app.get("/hold/test")
def hold_page() -> HTMLResponse:
    html = HOLD_HARNESS_PATH.read_text(encoding="utf-8")
    boot = json.dumps(
        {
            "account_id": "acct_isolation_merchant",
            "transaction_id": "tx_isolation_1",
            "held_paise": 800000,
        }
    )
    return HTMLResponse(html.replace("__BOOT_JSON__", boot))

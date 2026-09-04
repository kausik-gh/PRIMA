"""Ambient traffic generator — keeps the console graph moving between demo acts.

Every transaction this writes is a REAL row, scored by the REAL payer pipeline
(``backend.routes.payer.quote`` / ``commit``), on REAL seeded accounts. Nothing
here fabricates data or bypasses scoring. It only keeps ordinary, low-stakes
traffic flowing so the graph has a pulse.

Hard rules (see docs prompt 11):
  * Reuses the real quote/commit path — no second, simplified scoring path.
  * Only picks accounts with ``ground_truth_role is None`` and never a named
    demo account, so a scripted scenario can never collide with ambient noise.
  * Amounts stay in a tight, boring band (₹50–₹5,000).
  * Default OFF. Never starts on its own at server boot — only ``/api/ops/ambient/start``.
"""

from __future__ import annotations

import asyncio
import logging
import random

from sqlmodel import Session, col, select

from backend.core.db import engine
from backend.core.models import Account
from backend.routes.payer import CommitBody, QuoteBody, commit, quote

logger = logging.getLogger("prima.ambient")

# Reserved handles the operator drives by hand during the scripted acts.
# Ambient traffic must never touch these as sender or receiver.
NAMED_HANDLES = frozenset(
    {
        "ramesh@prima",
        "priya.k@prima",
        "grocery@prima",
        "rentals@prima",
        "quickcash@prima",
        "merchant.ok@prima",
        "merchant@prima",
        "dormant.wake@prima",
        "pipe.a@prima",
        "pipe.b@prima",
        "cashpool@prima",
        "neel.m@prima",
        "tara.m@prima",
        "om.m@prima",
    }
)

MIN_PAISE = 50 * 100
MAX_PAISE = 5_000 * 100

_task: asyncio.Task | None = None


def _eligible_accounts(session: Session) -> list[Account]:
    """Ordinary seeded accounts only: no ground-truth role, not a guest, not named."""
    rows = session.exec(
        select(Account).where(
            col(Account.ground_truth_role).is_(None),
            col(Account.is_demo_guest).is_(False),
        )
    ).all()
    return [row for row in rows if row.handle not in NAMED_HANDLES]


async def _tick() -> None:
    with Session(engine) as session:
        pool = _eligible_accounts(session)
        if len(pool) < 2:
            return
        sender, receiver = random.sample(pool, 2)
        amount = random.randint(MIN_PAISE, MAX_PAISE)
        if amount >= sender.balance_paise:
            return
        body = QuoteBody(
            sender_handle=sender.handle,
            beneficiary_handle=receiver.handle,
            amount_paise=amount,
            note=None,
        )
        quoted = await quote(body, session)
        if not isinstance(quoted, dict) or "decision_id" not in quoted:
            return
        # Do not suppress an interesting score — just commit it like any decision.
        await commit(
            CommitBody(decision_id=quoted["decision_id"], purpose_text="routine payment"),
            session,
        )


async def run_ambient_loop(interval_seconds: float = 4.0) -> None:
    """Background task. One small real transfer between two ordinary accounts,
    then sleep. Runs until cancelled."""
    logger.info("ambient loop started (interval=%.1fs)", interval_seconds)
    try:
        while True:
            try:
                await _tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the loop alive across a bad pick
                logger.exception("ambient tick failed")
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info("ambient loop stopped")


def is_running() -> bool:
    return _task is not None and not _task.done()


def start(interval_seconds: float = 4.0) -> bool:
    """Idempotent. Returns True if a new loop was spawned, False if already running."""
    global _task
    if is_running():
        return False
    _task = asyncio.create_task(run_ambient_loop(interval_seconds))
    return True


async def stop() -> None:
    """Cancel the loop and wait for it to unwind. Safe to call when not running."""
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

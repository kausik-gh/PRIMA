"""Label money on settled transactions along later outbound hops.

Inbound funds are never held. This module only writes taint_ratio on
transaction rows. It does not lock an account. P3 may later hold an
amount on an outbound transfer.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.core.db import engine
from backend.core.models import Account, Transaction
from backend.graph.pathgraph import rebuild_from_db

MERCHANT_HANDLE = "merchant.ok@prima"


@dataclass
class TaintHop:
    tx_id: str
    hop: int
    taint_ratio: float
    sender_id: str
    receiver_id: str


@dataclass
class TaintResult:
    origin_tx_id: str
    hops: list[TaintHop] = field(default_factory=list)


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _child_taint(parent_taint: float, parent_amount: int, child_amount: int) -> float:
    share = min(1.0, child_amount / max(parent_amount, 1))
    return min(1.0, parent_taint * share)


def _later_outbound(session: Session, sender_id: str, after: datetime) -> list[Transaction]:
    after_ts = _aware(after)
    rows = session.exec(
        select(Transaction).where(
            Transaction.sender_id == sender_id,
            Transaction.status == "settled",
        )
    ).all()
    later = [tx for tx in rows if _aware(tx.attempted_at) > after_ts]
    later.sort(key=lambda tx: _aware(tx.attempted_at))
    return later


def mark_fraudulent(
    transaction_id: str,
    hops: int = 3,
    session: Session | None = None,
) -> TaintResult:
    """Set origin taint to 1.0 and push labels along later outbound hops."""
    own_session = session is None
    if own_session:
        session = Session(engine)
    assert session is not None

    try:
        origin = session.get(Transaction, transaction_id)
        if origin is None:
            raise ValueError(f"unknown transaction: {transaction_id}")
        if origin.status != "settled":
            raise ValueError(f"origin is not settled: {transaction_id}")

        best: dict[str, float] = {}
        hop_of: dict[str, TaintHop] = {}
        queue: deque[tuple[Transaction, int, float]] = deque()
        queue.append((origin, 0, 1.0))

        while queue:
            tx, hop, proposed = queue.popleft()
            applied = max(tx.taint_ratio, proposed, best.get(tx.id, 0.0))
            if tx.id in best and applied <= best[tx.id]:
                continue
            tx.taint_ratio = applied
            session.add(tx)
            best[tx.id] = applied
            hop_of[tx.id] = TaintHop(
                tx_id=tx.id,
                hop=hop,
                taint_ratio=applied,
                sender_id=tx.sender_id,
                receiver_id=tx.receiver_id,
            )
            if hop >= hops:
                continue
            for child in _later_outbound(session, tx.receiver_id, tx.attempted_at):
                nxt = _child_taint(applied, tx.amount_paise, child.amount_paise)
                queue.append((child, hop + 1, nxt))

        session.commit()
        rebuild_from_db(session)

        ordered = sorted(hop_of.values(), key=lambda item: (item.hop, item.tx_id))
        return TaintResult(origin_tx_id=origin.id, hops=ordered)
    finally:
        if own_session:
            session.close()


def _account_by_handle(session: Session, handle: str) -> Account:
    row = session.exec(select(Account).where(Account.handle == handle)).first()
    if row is None:
        raise SystemExit(f"unknown handle: {handle}")
    return row


def _tx_by_handles(session: Session, sender_handle: str, receiver_handle: str) -> Transaction:
    sender = _account_by_handle(session, sender_handle)
    receiver = _account_by_handle(session, receiver_handle)
    rows = session.exec(
        select(Transaction).where(
            Transaction.sender_id == sender.id,
            Transaction.receiver_id == receiver.id,
            Transaction.status == "settled",
        )
    ).all()
    if not rows:
        raise SystemExit(f"no settled tx {sender_handle} -> {receiver_handle}")
    rows.sort(key=lambda tx: _aware(tx.attempted_at))
    return rows[0]


def _max_inbound_taint(session: Session, handle: str) -> float:
    account = _account_by_handle(session, handle)
    inbound = session.exec(
        select(Transaction).where(
            Transaction.receiver_id == account.id,
            Transaction.status == "settled",
        )
    ).all()
    if not inbound:
        return 0.0
    return max(tx.taint_ratio for tx in inbound)


def main() -> None:
    parser = argparse.ArgumentParser(description="Propagate taint along later outbound hops")
    parser.add_argument("--tx-id")
    parser.add_argument("--sender-handle")
    parser.add_argument("--receiver-handle")
    parser.add_argument("--hops", type=int, default=3)
    args = parser.parse_args()

    with Session(engine) as session:
        if args.tx_id:
            origin_id = args.tx_id
        elif args.sender_handle and args.receiver_handle:
            origin_id = _tx_by_handles(
                session, args.sender_handle, args.receiver_handle
            ).id
        else:
            raise SystemExit("pass --tx-id or both --sender-handle and --receiver-handle")
        result = mark_fraudulent(origin_id, hops=args.hops, session=session)
        merchant_taint = _max_inbound_taint(session, MERCHANT_HANDLE)

    print(json.dumps(asdict(result)))
    print(json.dumps({
        "handle": MERCHANT_HANDLE,
        "max_inbound_taint": merchant_taint,
    }))


if __name__ == "__main__":
    main()

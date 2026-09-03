"""Network check on a beneficiary: structure of inflows and outflows.

Scorers read graph structure, ledger amounts, and timestamps only.
Columns reserved for later metrics are never read here.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from backend.core.config import get_config
from backend.core.db import engine
from backend.core.models import Account, Transaction
from backend.graph.pathgraph import (
    get_graph,
    node_features,
    rebuild_from_db,
    two_hop_money_subgraph,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
GNN_WEIGHTS = REPO_ROOT / "gnn_model.pth"


@dataclass
class RingWatchResult:
    score: float
    rule_score: float
    gnn_score: float
    taint_gate: float
    gnn_offline: bool
    rules_fired: list[dict] = field(default_factory=list)


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _has_account_nodes(graph) -> bool:
    for _, data in graph.nodes(data=True):
        if data.get("node_type") == "account":
            return True
    return False


def _account_only_money_graph(subgraph) -> Any:
    import networkx as nx

    accounts_graph = nx.DiGraph()
    for node_id, data in subgraph.nodes(data=True):
        if data.get("node_type") == "account":
            accounts_graph.add_node(node_id, **data)
    for src, dst, data in subgraph.edges(data=True):
        if data.get("edge_type") != "money":
            continue
        if src in accounts_graph and dst in accounts_graph:
            accounts_graph.add_edge(src, dst, **data)
    return accounts_graph


def _fire_structure_rules(feats: dict, points: dict) -> list[dict]:
    fired: list[dict] = []

    if feats["in_degree"] >= 2:
        fired.append({
            "code": "fan_in",
            "points": points["fan_in"],
            "detail": f"in_degree={feats['in_degree']}",
        })
    if feats["out_degree"] >= 2:
        fired.append({
            "code": "fan_out",
            "points": points["fan_out"],
            "detail": f"out_degree={feats['out_degree']}",
        })
    if feats["retention_ratio"] < 0.2 and feats["total_in_amount"] > 0:
        fired.append({
            "code": "pass_through",
            "points": points["pass_through"],
            "detail": (
                f"retention_ratio={feats['retention_ratio']:.4f} "
                f"total_in_amount={feats['total_in_amount']:.2f}"
            ),
        })
    if feats["device_cluster_size"] > 2:
        fired.append({
            "code": "shared_device",
            "points": points["shared_device"],
            "detail": f"device_cluster_size={feats['device_cluster_size']}",
        })
    if feats["unique_channels"] > 2:
        fired.append({
            "code": "channel_burst",
            "points": points["channel_burst"],
            "detail": f"unique_channels={feats['unique_channels']}",
        })
    if feats["transaction_count"] >= 3:
        fired.append({
            "code": "high_velocity",
            "points": points["high_velocity"],
            "detail": f"transaction_count={feats['transaction_count']}",
        })
    if feats["account_age_days"] < 7 and feats["in_degree"] >= 3:
        fired.append({
            "code": "fresh_fan_in",
            "points": points["fresh_fan_in"],
            "detail": (
                f"age_days={feats['account_age_days']} "
                f"in_degree={feats['in_degree']}"
            ),
        })
    return fired


def _dormant_wake_rule(account_id: str, session: Session, points: dict) -> dict | None:
    rows = session.exec(
        select(Transaction).where(
            Transaction.status == "settled",
            or_(
                Transaction.sender_id == account_id,
                Transaction.receiver_id == account_id,
            ),
        )
    ).all()
    if len(rows) < 2:
        return None

    ordered = sorted(rows, key=lambda tx: _aware(tx.attempted_at))
    latest = ordered[-1]
    previous = ordered[-2]
    gap_days = (_aware(latest.attempted_at) - _aware(previous.attempted_at)).days
    prior_amounts = [tx.amount_paise for tx in ordered[:-1]]
    if not prior_amounts:
        return None
    baseline_paise = statistics.median(prior_amounts)
    latest_paise = latest.amount_paise
    if gap_days > 30 and latest_paise > 2 * baseline_paise:
        return {
            "code": "dormant_wake",
            "points": points["dormant_wake"],
            "detail": (
                f"gap_days={gap_days} "
                f"latest_settled_amount_paise={latest_paise} "
                f"baseline_paise={int(baseline_paise)}"
            ),
        }
    return None


def _node_taint_gate(account_id: str, min_t: float, lo_t: float) -> float:
    graph = get_graph()
    inbound_taint: list[float] = []
    for _, _, data in graph.in_edges(account_id, data=True):
        if data.get("edge_type") != "money":
            continue
        inbound_taint.append(float(data.get("taint", 0.0)))
    if not inbound_taint:
        return 1.0
    taint_ratio = max(inbound_taint)
    return 1.0 if taint_ratio >= min_t else lo_t


def _gnn_score_for(
    account_id: str,
    session: Session,
) -> tuple[float, bool]:
    subgraph = two_hop_money_subgraph(account_id)
    accounts_graph = _account_only_money_graph(subgraph)
    rows = []
    for node_id in accounts_graph.nodes():
        rows.append(node_features(node_id, subgraph, session))

    try:
        from backend.gnn import PYG_AVAILABLE, GNN_FEATURE_COLUMNS, gnn_predict
    except Exception as exc:
        logger.warning("%s", type(exc).__name__)
        return 0.0, True

    if not PYG_AVAILABLE or not GNN_WEIGHTS.is_file():
        return 0.0, True

    import pandas as pd

    if not rows:
        return 0.0, False

    features_df = pd.DataFrame(rows)
    keep_cols = ["account_id"] + list(GNN_FEATURE_COLUMNS)
    features_df = features_df[keep_cols]

    try:
        scored = gnn_predict(
            accounts_graph,
            features_df,
            model_path=str(GNN_WEIGHTS),
            device="cpu",
        )
    except Exception as exc:
        logger.warning("%s", type(exc).__name__)
        return 0.0, True

    match = scored.loc[scored["account_id"] == account_id]
    if match.empty:
        return 0.0, False
    return float(match.iloc[0]["gnn_score"]), False


def ringwatch_score(
    account_id: str,
    session: Session | None = None,
) -> RingWatchResult:
    cfg = get_config()["ringwatch"]
    points = cfg["rule_points"]
    divisor = float(cfg["rule_score_divisor"])
    gnn_w = float(cfg["gnn_weight"])
    rule_w = 1.0 - gnn_w
    min_t = float(cfg["taint_gate"]["min_ratio"])
    lo_t = float(cfg["taint_gate"]["below_gate_multiplier"])

    own_session = session is None
    if own_session:
        session = Session(engine)
    assert session is not None

    try:
        if not _has_account_nodes(get_graph()):
            rebuild_from_db(session)

        feats = node_features(account_id, get_graph(), session)
        fired = _fire_structure_rules(feats, points)
        dormant = _dormant_wake_rule(account_id, session, points)
        if dormant is not None:
            fired.append(dormant)

        points_sum = sum(rule["points"] for rule in fired)
        rule_score = min(points_sum / divisor, 1.0)
        taint_gate = _node_taint_gate(account_id, min_t, lo_t)
        gnn_score, gnn_offline = _gnn_score_for(account_id, session)
        fused = _clamp01((rule_w * rule_score + gnn_w * gnn_score) * taint_gate)

        return RingWatchResult(
            score=fused,
            rule_score=rule_score,
            gnn_score=gnn_score,
            taint_gate=taint_gate,
            gnn_offline=gnn_offline,
            rules_fired=fired,
        )
    finally:
        if own_session:
            session.close()


def _resolve_account_id(session: Session, handle: str | None, account_id: str | None) -> str:
    if account_id:
        return account_id
    if not handle:
        raise SystemExit("pass --handle or --account-id")
    row = session.exec(select(Account).where(Account.handle == handle)).first()
    if row is None:
        raise SystemExit(f"unknown handle: {handle}")
    return row.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one account with RingWatch")
    parser.add_argument("--handle")
    parser.add_argument("--account-id")
    args = parser.parse_args()
    with Session(engine) as session:
        account_id = _resolve_account_id(session, args.handle, args.account_id)
        result = ringwatch_score(account_id, session)
    print(json.dumps(asdict(result)))


if __name__ == "__main__":
    main()

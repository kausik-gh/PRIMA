import asyncio
import hashlib
import math
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sklearn.metrics import precision_score, recall_score

from backend.config import TX_WINDOW
from backend.detection import (
    adaptive_threshold_update,
    behavioral_drift_detection,
    classify_fraud_roles,
    early_stage_detection,
    explain_risk_categories,
    ml_predict,
    rule_based_detection,
)
from backend.features import build_transaction_graph, extract_node_features
from backend.model import model_runtime
from backend.realtime_engine import RealTimeEngine
from backend.risk_memory import compare_signature, extract_cluster_signature, store_signature

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
LIB_DIR = BASE_DIR / "lib"
DEFAULT_FEATURES = [
    "in_degree",
    "out_degree",
    "total_in_amount",
    "total_out_amount",
    "retention_ratio",
    "unique_neighbors",
    "unique_channels",
    "device_cluster_size",
    "transaction_count",
]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if LIB_DIR.exists():
    app.mount("/lib", StaticFiles(directory=str(LIB_DIR)), name="lib")

engine = RealTimeEngine()
threading.Thread(target=engine.run, daemon=True).start()


@app.on_event("startup")
async def startup_event():
    model_runtime.load()


class DashboardState:
    def __init__(self):
        self.lock = threading.RLock()
        self.model = None
        self.explainer = None
        self.reset()

    def reset(self):
        self.threshold = 0.45
        self.threshold_history = []
        self.fraud_history = []
        self.role_history = []
        self.attack_index = 0
        self.selected_account = None
        self.early_accounts = []
        self.early_accounts_frozen = []
        self.baseline_snapshot = None
        self.baseline_tx_count = 0
        self.last_detection = None
        self.early_warning_cache = None
        self.early_warning_updated_at = 0.0
        self.detection_job = {
            "job_id": 0,
            "status": "idle",
            "attack_name": None,
            "attack_time": None,
            "error": None,
        }


dashboard_state = DashboardState()
_channel_filter: dict[str, Any] = {"channel": None}


def _clean_value(value: Any):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean_value(v) for v in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if pd.isna(value):
        return None
    return value


def _clean(records: list[dict[str, Any]]):
    return [{str(k): _clean_value(v) for k, v in row.items()} for row in records]


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    frame = df.copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].astype(str)
    return _clean(frame.to_dict(orient="records"))


def _stable_pos(account_id: str, spread_x: float = 1800.0, spread_y: float = 1150.0):
    digest = hashlib.md5(str(account_id).encode()).hexdigest()
    x = (int(digest[0:4], 16) / 65535.0) * spread_x
    y = (int(digest[4:8], 16) / 65535.0) * spread_y
    return round(x, 1), round(y, 1)


def _load_model():
    with dashboard_state.lock:
        if dashboard_state.model is None:
            dashboard_state.model = model_runtime.get_rf_model()
            dashboard_state.explainer = model_runtime.get_explainer()
        return dashboard_state.model, dashboard_state.explainer


def _accounts_df():
    df = engine.get_accounts()
    if "creation_time" in df.columns:
        df["creation_time"] = pd.to_datetime(df["creation_time"], errors="coerce")
    return df


def _risk_snapshot():
    snapshot = engine.get_risk_snapshot()
    if engine.last_attack_name is None:
        warning_summary = engine.get_warning_summary()
        warning_threshold = float(warning_summary.get("threshold", 0.0))
        for value in snapshot.values():
            if value.get("status") == "fraud":
                value["status"] = (
                    "early"
                    if float(value.get("risk_score", 0.0)) >= warning_threshold
                    else "normal"
                )
    return snapshot


def _network_accounts_payload():
    accounts_df = _accounts_df().copy()
    if accounts_df.empty:
        return []

    risk_snapshot = _risk_snapshot()
    accounts_df["x"] = accounts_df["account_id"].apply(
        lambda value: _stable_pos(str(value))[0]
    )
    accounts_df["y"] = accounts_df["account_id"].apply(
        lambda value: _stable_pos(str(value))[1]
    )
    payload = []
    for row in accounts_df.to_dict(orient="records"):
        account_id = str(row["account_id"])
        risk = risk_snapshot.get(account_id, {})
        payload.append(
            {
                "account_id": account_id,
                "channel": row.get("channel"),
                "is_active": row.get("is_active", True),
                "is_fraud": row.get("is_fraud", 0),
                "x": row.get("x"),
                "y": row.get("y"),
                "risk_score": risk.get("risk_score", 0.0),
                "early_status": risk.get("status", "normal"),
                "risk_reasons": risk.get("reasons", []),
                "signal_breakdown": risk.get("signal_breakdown", {}),
                "signal_count": risk.get("signal_count", 0),
            }
        )
    return _clean(payload)


def _transactions_df(limit: int | None = None):
    df = engine.get_all_transactions()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.tail(limit).copy() if limit else df.copy()


def _metrics_snapshot():
    with engine.lock:
        tx_count = len(engine.transactions_df)
        active_count = (
            int(engine.accounts_df["is_active"].sum())
            if "is_active" in engine.accounts_df.columns
            else len(engine.accounts_df)
        )
        fraud_count = (
            int((engine.accounts_df["is_fraud"] == 1).sum())
            if "is_fraud" in engine.accounts_df.columns
            else 0
        )
        total_count = len(engine.accounts_df)

    risk_snapshot = _risk_snapshot()
    suspicious_count = sum(
        1 for value in risk_snapshot.values() if value.get("status") == "early"
    )

    return {
        "tps": engine.get_real_tps(),
        "tx_count": tx_count,
        "fraud_count": fraud_count,
        "active_accounts": active_count,
        "total_accounts": total_count,
        "banned_count": len(engine.banned_accounts),
        "suspicious_count": suspicious_count,
    }


def _ensure_baseline():
    metrics = _metrics_snapshot()
    with dashboard_state.lock:
        if dashboard_state.baseline_snapshot is not None or metrics["tx_count"] < 30:
            return

    accounts_df = _accounts_df()
    transactions_df = _transactions_df(limit=TX_WINDOW)
    if accounts_df.empty or transactions_df.empty:
        return

    graph = build_transaction_graph(accounts_df, transactions_df)
    baseline = extract_node_features(accounts_df, transactions_df, graph)
    with dashboard_state.lock:
        dashboard_state.baseline_snapshot = baseline
        dashboard_state.baseline_tx_count = len(transactions_df)


def _cache_early_warning(payload: dict[str, Any]):
    with dashboard_state.lock:
        dashboard_state.early_warning_cache = payload
        dashboard_state.early_warning_updated_at = time.monotonic()
    return payload


def _invalidate_live_caches():
    with dashboard_state.lock:
        dashboard_state.early_warning_cache = None
        dashboard_state.early_warning_updated_at = 0.0


def _compute_early_warning(force: bool = False):
    with dashboard_state.lock:
        cached = dashboard_state.early_warning_cache
        updated_at = dashboard_state.early_warning_updated_at
    if not force and cached is not None and (time.monotonic() - updated_at) < 0.75:
        return cached

    metrics = _metrics_snapshot()
    risk_snapshot = _risk_snapshot()
    warning_summary = engine.get_warning_summary()
    distribution = sorted(
        [round(float(value.get("risk_score", 0.0)), 4) for value in risk_snapshot.values()],
        reverse=True,
    )[:40]
    early_rows = [
        {
            "account_id": value["account_id"],
            "risk_score": round(float(value.get("risk_score", 0.0)), 4),
            "status": value.get("status", "normal"),
            "signal_count": value.get("signal_count", 0),
            "reasons": ", ".join(value.get("reasons", [])) or "Learning normal behavior",
        }
        for value in risk_snapshot.values()
        if value.get("status") == "early"
    ]
    early_rows.sort(key=lambda row: row["risk_score"], reverse=True)
    early_accounts = [row["account_id"] for row in early_rows]
    with dashboard_state.lock:
        dashboard_state.early_accounts = early_accounts

    if metrics["tx_count"] < 15 and not early_rows:
        return _cache_early_warning({
            "status": "learning",
            "message": "Learning suspicious behavior from the live transaction stream.",
            "count": 0,
            "total_active": metrics["active_accounts"],
            "table": [],
            "distribution": distribution,
            "threshold": round(float(warning_summary["threshold"]), 3),
            "warning_pct": round(float(warning_summary["warning_pct"]) * 100, 1),
            "explainer": engine.get_early_warning_explainer(),
        })

    if early_rows:
        return _cache_early_warning({
            "status": "warning",
            "message": f"{len(early_rows)} suspicious account(s) are currently above the live adaptive threshold.",
            "count": len(early_rows),
            "total_active": metrics["active_accounts"],
            "table": early_rows,
            "distribution": distribution,
            "threshold": round(float(warning_summary["threshold"]), 3),
            "warning_pct": round(float(warning_summary["warning_pct"]) * 100, 1),
            "explainer": engine.get_early_warning_explainer(),
        })

    return _cache_early_warning({
        "status": "clear",
        "message": "Risk is decaying below the live suspicious threshold.",
        "count": 0,
        "total_active": metrics["active_accounts"],
        "table": [],
        "distribution": distribution,
        "threshold": round(float(warning_summary["threshold"]), 3),
        "warning_pct": round(float(warning_summary["warning_pct"]) * 100, 1),
        "explainer": engine.get_early_warning_explainer(),
    })


def _pattern_status(similarity: float):
    if similarity > 0.7:
        return "Repeat attack structure detected."
    if similarity > 0.4:
        return "Variant of known pattern."
    return "New fraud pattern."


def _severity_label(score: float):
    if score > 0.75:
        return "High Confidence"
    if score > 0.5:
        return "Medium Risk"
    return "Low Confidence"


def _validated_attack_ids(attack_transactions: pd.DataFrame, candidate_ids: list[str] | None = None):
    if attack_transactions is None or attack_transactions.empty:
        return []

    edge_nodes: set[str] = set()
    for _, row in attack_transactions.iterrows():
        sender = str(row.get("sender", ""))
        receiver = str(row.get("receiver", ""))
        if not sender or not receiver or sender == receiver:
            continue
        edge_nodes.add(sender)
        edge_nodes.add(receiver)

    if not edge_nodes:
        return []

    if candidate_ids is None:
        return sorted(edge_nodes)

    candidate_set = {str(account_id) for account_id in candidate_ids}
    return sorted(edge_nodes.intersection(candidate_set))


def _serialize_dashboard_state():
    with dashboard_state.lock:
        detection = dashboard_state.last_detection
        threshold = dashboard_state.threshold
        threshold_history = list(dashboard_state.threshold_history)
        fraud_history = list(dashboard_state.fraud_history)
        role_history = list(dashboard_state.role_history)
        early_frozen = list(dashboard_state.early_accounts_frozen)
        selected_account = dashboard_state.selected_account
        baseline_tx_count = dashboard_state.baseline_tx_count
        detection_job = dict(dashboard_state.detection_job)

    if detection is None:
        return {
            "available": False,
            "is_detecting": detection_job["status"] == "running",
            "detection_job": detection_job,
            "threshold": threshold,
            "threshold_history": threshold_history,
            "fraud_history": fraud_history,
            "role_history_totals": {},
            "selected_account": selected_account,
            "baseline_tx_count": baseline_tx_count,
            "banned_accounts": sorted(engine.banned_accounts),
        }

    risk_df = detection["risk_df"].copy()
    risk_df["verdict"] = risk_df["risk_score"].apply(
        lambda score: "High" if score >= 7 else ("Medium" if score >= 4 else "Low")
    )
    risk_df["reasons_str"] = risk_df["reasons"].apply(
        lambda reasons: ", ".join(reasons) if isinstance(reasons, list) and reasons else "None"
    )
    rule_table = _records(
        risk_df[["account_id", "risk_score", "verdict", "reasons_str"]]
        .sort_values("risk_score", ascending=False)
        .head(15)
    )

    predictions = detection["predictions"].copy()
    ml_columns = ["account_id", "ml_score", "rule_score_norm", "final_score", "predicted_label"]
    for optional in ["gnn_score", "is_fraud"]:
        if optional in predictions.columns:
            ml_columns.append(optional)
    ml_table_df = predictions[ml_columns].copy()
    for column in ["ml_score", "rule_score_norm", "final_score", "gnn_score"]:
        if column in ml_table_df.columns:
            ml_table_df[column] = ml_table_df[column].round(4)
    ml_table = _records(
        ml_table_df.sort_values("final_score", ascending=False).head(15)
    )

    drift_df = detection["drift_df"].copy()
    if not drift_df.empty:
        drift_columns = ["account_id", "drift_score"]
        if "top_changes" in drift_df.columns:
            drift_columns.append("top_changes")
        drift_table = _records(
            drift_df[drift_columns].sort_values("drift_score", ascending=False)
        )
        drift_status = "warning"
        drift_message = (
            f"{len(drift_df)} account(s) show significant behavioral drift from pre-attack baseline."
        )
    elif baseline_tx_count == 0:
        drift_table = []
        drift_status = "baseline_missing"
        drift_message = "No baseline yet. Let transactions accumulate before attacking."
    else:
        drift_table = []
        drift_status = "clear"
        drift_message = "No significant behavioral drift detected in this simulation."

    predicted_fraud = [str(account_id) for account_id in detection["fraud_ids"]]
    matched = sorted(set(early_frozen).intersection(predicted_fraud))
    sleeper = sorted(set(predicted_fraud) - set(early_frozen))
    false_positives = sorted(set(early_frozen) - set(predicted_fraud))

    role_totals: dict[str, int] = {}
    for run in role_history:
        for role, count in run.items():
            role_totals[role] = role_totals.get(role, 0) + int(count)

    roles_df = detection["roles_df"].copy()
    role_counts = roles_df["role"].value_counts().to_dict() if not roles_df.empty else {}

    return {
        "available": True,
        "is_detecting": detection_job["status"] == "running",
        "detection_job": detection_job,
        "attack_name": detection["attack_name"],
        "attack_time": _clean_value(detection["attack_time"]),
        "fraud_ids": [str(account_id) for account_id in detection["fraud_ids"]],
        "fraud_accounts": predicted_fraud,
        "selected_account": selected_account,
        "banned_accounts": sorted(engine.banned_accounts),
        "baseline_tx_count": baseline_tx_count,
        "gnn_available": detection["gnn_available"],
        "rule_based": {
            "high_count": int((risk_df["risk_score"] >= 7).sum()),
            "medium_count": int(
                ((risk_df["risk_score"] >= 4) & (risk_df["risk_score"] < 7)).sum()
            ),
            "scored_count": int(len(risk_df)),
            "table": rule_table,
        },
        "ml_detection": {
            "fraud_flagged": len(predicted_fraud),
            "precision": round(float(detection["precision"]), 3),
            "recall": round(float(detection["recall"]), 3),
            "threshold": round(float(threshold), 3),
            "table": ml_table,
        },
        "drift": {
            "status": drift_status,
            "message": drift_message,
            "table": drift_table,
        },
        "pattern_memory": {
            "similarity": round(float(detection["similarity"]), 4),
            "patterns_stored": len(threshold_history),
            "message": _pattern_status(float(detection["similarity"])),
        },
        "summary": {
            "injected": int(detection["true_fraud_count"]),
            "detected": int(detection["correct_count"]),
            "missed": int(detection["true_fraud_count"] - detection["correct_count"]),
        },
        "early_cross_check": {
            "early_warned": len(early_frozen),
            "matched": len(matched),
            "sleeper": len(sleeper),
            "matched_accounts": matched,
            "sleeper_accounts": sleeper,
            "false_positive_accounts": false_positives,
        },
        "investigation_accounts": predicted_fraud,
        "role_chart": {
            "labels": list(role_counts.keys()),
            "values": [int(value) for value in role_counts.values()],
        },
        "history": {
            "threshold_history": [round(float(value), 3) for value in threshold_history],
            "fraud_history": [round(float(value), 4) for value in fraud_history],
            "role_totals": role_totals,
        },
    }


def _build_explanations(categories: dict[str, float]):
    explanations = []
    if categories.get("Velocity Risk", 0) > 0.1:
        explanations.append("Velocity - Rapid fund movement")
    if categories.get("Shared Device Risk", 0) > 0.05:
        explanations.append("Shared Device - Multi-account control")
    if categories.get("Ring Participation Risk", 0) > 0.1:
        explanations.append("Ring - Embedded in fraud ring")
    if categories.get("Retention Risk", 0) > 0.05:
        explanations.append("Retention - Pass-through mule behavior")
    if categories.get("Channel Risk", 0) > 0.05:
        explanations.append("Channel - Multi-channel burst activity")
    if not explanations:
        explanations.append("Flagged by structural position in the transaction graph.")
    return explanations


def _serialize_investigation(account_id: str):
    model, explainer = _load_model()
    with dashboard_state.lock:
        detection = dashboard_state.last_detection
        if detection is None:
            return {"available": False}
        dashboard_state.selected_account = str(account_id)

    predictions = detection["predictions"].copy()
    features_df = detection["features_df"].copy()
    roles_df = detection["roles_df"].copy()
    prediction_row = predictions[predictions["account_id"].astype(str) == str(account_id)]

    if prediction_row.empty:
        return {"available": False}

    probability = float(prediction_row["final_score"].iloc[0])
    role = "Unclassified"
    if not roles_df.empty:
        role_row = roles_df[roles_df["account_id"].astype(str) == str(account_id)]
        if not role_row.empty:
            role = str(role_row["role"].iloc[0])

    role_counts = roles_df["role"].value_counts().to_dict() if not roles_df.empty else {}

    shap_available = False
    categories = {}
    category_rows = []
    if explainer is not None:
        account_features = features_df[
            features_df["account_id"].astype(str) == str(account_id)
        ][model.feature_list]
        if not account_features.empty:
            try:
                shap_values = explainer.shap_values(account_features)
                if isinstance(shap_values, list):
                    shap_values = shap_values[1]
                if hasattr(shap_values, "ndim") and shap_values.ndim == 3:
                    shap_values = shap_values[0][:, 1]
                elif hasattr(shap_values, "ndim") and shap_values.ndim == 2:
                    shap_values = shap_values[0]
                categories = explain_risk_categories(list(shap_values), model.feature_list)
                category_rows = [
                    {
                        "category": category,
                        "contribution": round(float(value) * 100, 2),
                    }
                    for category, value in sorted(
                        categories.items(), key=lambda item: item[1], reverse=True
                    )
                ]
                shap_available = True
            except Exception:
                shap_available = False

    return {
        "available": True,
        "account_id": str(account_id),
        "fraud_score": round(probability * 100, 2),
        "final_score": round(probability, 4),
        "confidence": _severity_label(probability),
        "severity": "high" if probability > 0.75 else ("medium" if probability > 0.5 else "low"),
        "ml_score": round(float(prediction_row["ml_score"].iloc[0]), 4),
        "rule_score_norm": round(float(prediction_row["rule_score_norm"].iloc[0]), 4),
        "gnn_score": (
            round(float(prediction_row["gnn_score"].iloc[0]), 4)
            if "gnn_score" in prediction_row.columns
            else None
        ),
        "role": role,
        "role_counts": {
            "labels": list(role_counts.keys()),
            "values": [int(value) for value in role_counts.values()],
        },
        "shap": {
            "available": shap_available,
            "categories": category_rows,
            "explanations": _build_explanations(categories) if shap_available else [],
        },
    }


def _run_detection(accounts_df, transactions_df, attack_time, attack_name, ground_truth_ids):
    model, _ = _load_model()
    attack_timestamp = pd.Timestamp(attack_time)
    transactions_df = transactions_df.copy()
    transactions_df["timestamp"] = pd.to_datetime(transactions_df["timestamp"], errors="coerce")

    attack_transactions = transactions_df[transactions_df["timestamp"] >= attack_timestamp].copy()
    if attack_transactions.empty:
        attack_transactions = transactions_df.tail(50).copy()

    graph = build_transaction_graph(accounts_df, attack_transactions)
    features_df = extract_node_features(accounts_df, attack_transactions, graph)
    risk_df = rule_based_detection(features_df)

    gnn_available = False
    try:
        gnn_df = model_runtime.gnn_predict(graph, features_df)
        features_df = features_df.merge(gnn_df, on="account_id", how="left")
        features_df["gnn_score"] = features_df["gnn_score"].fillna(0.0)
        gnn_available = True
    except Exception:
        pass

    with dashboard_state.lock:
        current_threshold = dashboard_state.threshold
    predictions = ml_predict(model, features_df, risk_df, threshold=current_threshold)

    if "is_fraud" not in predictions.columns:
        for source in [features_df, accounts_df]:
            if "is_fraud" in source.columns:
                predictions = predictions.merge(
                    source[["account_id", "is_fraud"]], on="account_id", how="left"
                )
                break

    predicted_fraud_ids = (
        predictions[predictions["predicted_label"] == 1]["account_id"]
        .astype(str)
        .tolist()
    )
    validated_fraud_ids = _validated_attack_ids(attack_transactions, predicted_fraud_ids)
    fraud_id_set = set(validated_fraud_ids)

    fraud_only = features_df[
        features_df["account_id"].astype(str).isin(validated_fraud_ids)
    ].copy()
    roles_df = (
        classify_fraud_roles(fraud_only)
        if not fraud_only.empty
        else pd.DataFrame(columns=["account_id", "role"])
    )

    drift_df = pd.DataFrame()
    with dashboard_state.lock:
        baseline_snapshot = dashboard_state.baseline_snapshot
    if baseline_snapshot is not None and not baseline_snapshot.empty:
        try:
            drift_df = behavioral_drift_detection(
                baseline_snapshot,
                features_df,
                model.feature_list,
                threshold=0.4,
            )
        except Exception:
            drift_df = pd.DataFrame()

    suspicious_txs = []
    for _, tx in attack_transactions.iterrows():
        sender = str(tx.get("sender", ""))
        receiver = str(tx.get("receiver", ""))
        if sender in fraud_id_set or receiver in fraud_id_set or bool(tx.get("is_attack", False)):
            suspicious_txs.append(
                {
                    "sender": sender,
                    "receiver": receiver,
                    "amount": float(tx.get("amount", 0)),
                    "channel": str(tx.get("channel", "TXN")),
                }
            )

    signature = extract_cluster_signature(graph, features_df)
    similarity = compare_signature(signature) if signature else 0.0
    if signature:
        store_signature(signature)

    ground_truth_set = {str(account_id) for account_id in ground_truth_ids}
    true_labels = pd.Series(
        [1 if str(account_id) in ground_truth_set else 0 for account_id in features_df["account_id"]]
    )
    predicted_labels = predictions["predicted_label"].values
    precision = precision_score(true_labels, predicted_labels, zero_division=0)
    recall = recall_score(true_labels, predicted_labels, zero_division=0)
    next_threshold = adaptive_threshold_update(
        current_threshold,
        {"1": {"precision": precision, "recall": recall}},
    )
    correct = ground_truth_set.intersection(set(validated_fraud_ids))

    with dashboard_state.lock:
        dashboard_state.threshold = next_threshold
        dashboard_state.threshold_history.append(next_threshold)
        dashboard_state.fraud_history.append(len(correct) / max(len(ground_truth_set), 1))
        if not fraud_only.empty:
            dashboard_state.role_history.append(roles_df["role"].value_counts().to_dict())
        dashboard_state.last_detection = {
            "accounts_df": accounts_df.copy(),
            "transactions_df": transactions_df.copy(),
            "attack_transactions": attack_transactions.copy(),
            "attack_time": attack_timestamp,
            "attack_name": attack_name,
            "features_df": features_df.copy(),
            "risk_df": risk_df.copy(),
            "predictions": predictions.copy(),
            "roles_df": roles_df.copy(),
            "drift_df": drift_df.copy(),
            "fraud_ids": validated_fraud_ids,
            "suspicious_txs": suspicious_txs,
            "signature": signature,
            "similarity": float(similarity),
            "precision": float(precision),
            "recall": float(recall),
            "true_fraud_count": len(ground_truth_set),
            "correct_count": len(correct),
            "graph": graph,
            "gnn_available": gnn_available,
        }
        if validated_fraud_ids:
            dashboard_state.selected_account = validated_fraud_ids[0]
        else:
            dashboard_state.selected_account = None


def _run_detection_async(job_id: int, attack_name: str, attack_time):
    try:
        accounts_df = _accounts_df()
        transactions_df = _transactions_df()
        ground_truth = engine.get_fraud_accounts()

        if accounts_df.empty or transactions_df.empty:
            raise RuntimeError("Data fetch failed after attack injection.")

        _run_detection(accounts_df, transactions_df, attack_time, attack_name, ground_truth)
        with dashboard_state.lock:
            if dashboard_state.detection_job["job_id"] == job_id:
                dashboard_state.detection_job = {
                    "job_id": job_id,
                    "status": "complete",
                    "attack_name": attack_name,
                    "attack_time": str(attack_time),
                    "error": None,
                }
    except Exception as exc:
        with dashboard_state.lock:
            if dashboard_state.detection_job["job_id"] == job_id:
                dashboard_state.detection_job = {
                    "job_id": job_id,
                    "status": "error",
                    "attack_name": attack_name,
                    "attack_time": str(attack_time),
                    "error": str(exc),
                }


def _queue_detection_job(attack_name: str, attack_time):
    with dashboard_state.lock:
        dashboard_state.selected_account = None
        next_job_id = int(dashboard_state.detection_job["job_id"]) + 1
        dashboard_state.last_detection = None
        dashboard_state.detection_job = {
            "job_id": next_job_id,
            "status": "queued",
            "attack_name": attack_name,
            "attack_time": str(attack_time),
            "error": None,
        }
    return next_job_id


def _start_detection_job(job_id: int, attack_name: str, attack_time):
    with dashboard_state.lock:
        current_job = dict(dashboard_state.detection_job)
        if current_job["job_id"] != job_id:
            return dict(current_job)
        dashboard_state.detection_job = {
            "job_id": job_id,
            "status": "running",
            "attack_name": attack_name,
            "attack_time": str(attack_time),
            "error": None,
        }

    threading.Thread(
        target=_run_detection_async,
        args=(job_id, attack_name, attack_time),
        daemon=True,
    ).start()

    with dashboard_state.lock:
        return dict(dashboard_state.detection_job)


def _live_payload(include_baseline: bool = True, force_early_warning: bool = False):
    if include_baseline:
        _ensure_baseline()
    with dashboard_state.lock:
        detection_job = dict(dashboard_state.detection_job)
    warning_payload = _compute_early_warning(force=force_early_warning)
    return {
        "metrics": _metrics_snapshot(),
        "threshold": round(float(warning_payload.get("threshold", 0.0)), 3),
        "banned_accounts": sorted(engine.banned_accounts),
        "fraud_accounts": [str(account_id) for account_id in engine.get_fraud_accounts()],
        "early_warning": warning_payload,
        "detection_available": dashboard_state.last_detection is not None,
        "detection_job": detection_job,
    }


def _bootstrap_live_payload():
    metrics = _metrics_snapshot()
    with dashboard_state.lock:
        detection_job = dict(dashboard_state.detection_job)
    warning_payload = _compute_early_warning(force=True)
    threshold = round(float(warning_payload.get("threshold", 0.0)), 3)
    return {
        "metrics": metrics,
        "threshold": threshold,
        "banned_accounts": sorted(engine.banned_accounts),
        "fraud_accounts": [str(account_id) for account_id in engine.get_fraud_accounts()],
        "early_warning": warning_payload,
        "detection_available": dashboard_state.last_detection is not None,
        "detection_job": detection_job,
    }


def _latest_attack_payload():
    attack_name = engine.last_attack_name
    attack_time = engine.attack_time
    if not attack_name or attack_time is None:
        return {"attack_name": None, "nodes": [], "edges": []}

    with engine.lock:
        accounts_df = engine.accounts_df.copy()
        transactions_df = engine.transactions_df.copy()

    fraud_ids = set(
        accounts_df[accounts_df["is_fraud"] == 1]["account_id"].astype(str).tolist()
        if "is_fraud" in accounts_df.columns
        else []
    )

    if "is_attack" in transactions_df.columns:
        attack_transactions = transactions_df[transactions_df["is_attack"] == True].copy()
        if not attack_transactions.empty and "timestamp" in attack_transactions.columns:
            attack_transactions["timestamp"] = pd.to_datetime(
                attack_transactions["timestamp"], errors="coerce"
            )
            attack_transactions = attack_transactions[
                attack_transactions["timestamp"] >= pd.Timestamp(attack_time)
            ].copy()
    else:
        attack_transactions = transactions_df[
            transactions_df["sender"].astype(str).isin(fraud_ids)
            | transactions_df["receiver"].astype(str).isin(fraud_ids)
        ].tail(60).copy()

    if "timestamp" in attack_transactions.columns:
        attack_transactions = attack_transactions.sort_values("timestamp")

    involved_ids = set()
    edges = []
    for _, row in attack_transactions.iterrows():
        sender = str(row.get("sender", ""))
        receiver = str(row.get("receiver", ""))
        if not sender or not receiver:
            continue
        involved_ids.add(sender)
        involved_ids.add(receiver)
        edges.append(
            {
                "source": sender,
                "target": receiver,
                "amount": float(row.get("amount", 0)),
                "channel": str(row.get("channel", "")),
                "timestamp": str(row.get("timestamp", "")),
            }
        )

    risk_snapshot = _risk_snapshot()
    nodes = []
    subset = accounts_df[accounts_df["account_id"].astype(str).isin(involved_ids)]
    for _, row in subset.iterrows():
        account_id = str(row["account_id"])
        is_fraud = str(row.get("is_fraud", 0)) == "1"
        risk = risk_snapshot.get(account_id, {})
        x, y = _stable_pos(account_id)
        nodes.append(
            {
                "id": account_id,
                "channel": str(row.get("channel", "")),
                "role": "fraud" if is_fraud or risk.get("status") == "fraud" else "suspicious",
                "sus_score": round(float(risk.get("risk_score", 0.0)), 3),
                "reasons": risk.get("reasons", []),
                "x": x,
                "y": y,
            }
        )

    return {
        "attack_name": attack_name,
        "nodes": _clean(nodes),
        "edges": _clean(edges),
    }


def _stream_dashboard_payload():
    with dashboard_state.lock:
        detection_job = dict(dashboard_state.detection_job)
        available = dashboard_state.last_detection is not None
    return {
        "available": available,
        "is_detecting": detection_job.get("status") == "running",
        "detection_job": detection_job,
    }


def _websocket_snapshot():
    return {
        "type": "snapshot",
        "live": _live_payload(include_baseline=False),
        "accounts": _network_accounts_payload(),
        "transactions": _clean(engine.get_transactions()),
        "latest_attack": _latest_attack_payload(),
        "dashboard": _stream_dashboard_payload(),
    }


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/styles.css", include_in_schema=False)
def serve_styles():
    return FileResponse(FRONTEND_DIR / "styles.css")


@app.get("/app.js", include_in_schema=False)
def serve_app_js():
    return FileResponse(FRONTEND_DIR / "app.js")


@app.get("/tx-worker.js", include_in_schema=False)
def serve_tx_worker_js():
    return FileResponse(FRONTEND_DIR / "tx-worker.js")


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_websocket_snapshot())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@app.get("/accounts")
async def get_accounts():
    return _network_accounts_payload()


@app.get("/transactions")
async def get_transactions():
    return _clean(engine.get_transactions())


@app.get("/all_transactions")
async def get_all_transactions():
    return _records(_transactions_df())


@app.get("/transaction_count")
def get_transaction_count():
    with engine.lock:
        return {"count": len(engine.transactions_df)}


@app.get("/metrics")
async def get_metrics():
    return _metrics_snapshot()


@app.get("/suspicion_scores")
def get_suspicion_scores():
    scores = engine.compute_suspicion_scores()
    return {str(key): float(value) for key, value in scores.items()}


@app.get("/suspicious_accounts")
def get_suspicious_accounts():
    return [row["account_id"] for row in engine.get_early_warning_accounts()]


@app.get("/banned_accounts")
def get_banned_accounts():
    return sorted(engine.banned_accounts)


@app.post("/create_account")
async def create_account():
    account_id = engine.create_account()
    _invalidate_live_caches()
    x, y = _stable_pos(account_id)
    risk = _risk_snapshot().get(account_id, {})
    return {
        "account_id": account_id,
        "x": x,
        "y": y,
        "status": risk.get("status", "normal"),
        "suspicion": risk.get("risk_score", 0),
        "risk_reasons": risk.get("reasons", []),
        "createdAt": pd.Timestamp.now().isoformat(),
    }


@app.get("/trigger_attack")
def trigger_attack(index: int = 0):
    try:
        _invalidate_live_caches()
        attack_name, attack_time = engine.trigger_attack(attack_index=index)
        if attack_name is None:
            return {"status": "skipped", "reason": "not enough active accounts"}
        return {
            "status": "attack triggered",
            "attack_name": attack_name,
            "attack_time": str(attack_time),
            "accounts": _records(_accounts_df()),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Attack trigger failed: {exc}") from exc


@app.get("/fraud_gt")
def get_fraud_gt():
    return [str(account_id) for account_id in engine.get_fraud_accounts()]


@app.get("/fraud_accounts")
def get_fraud_accounts():
    return [str(account_id) for account_id in engine.get_fraud_accounts()]


@app.post("/ban_accounts")
def ban_accounts(account_ids: list = Body(...)):
    if not isinstance(account_ids, list) or not account_ids:
        raise HTTPException(status_code=400, detail="Provide at least one account_id to ban.")
    engine.ban_accounts(account_ids)
    _invalidate_live_caches()
    return {
        "status": "banned",
        "banned": [str(account_id) for account_id in account_ids],
        "remaining_active": engine.get_active_count(),
    }


@app.get("/reset_state")
def reset_state():
    engine.reset_state()
    with dashboard_state.lock:
        dashboard_state.reset()
    _invalidate_live_caches()
    return {"status": "reset"}


@app.get("/latest_attack")
async def get_latest_attack():
    return _latest_attack_payload()


@app.get("/graph")
async def get_graph():
    return {
        "accounts": _network_accounts_payload(),
        "latest_attack": _latest_attack_payload(),
        "metrics": _metrics_snapshot(),
    }


@app.post("/detect")
async def detect_alias():
    return await trigger_attack_async()


@app.post("/ban")
async def ban_alias(account_ids: list = Body(...)):
    return ban_accounts(account_ids)


@app.get("/channel_filter")
def get_channel_filter():
    return _channel_filter


@app.post("/channel_filter")
def set_channel_filter(body: dict = Body(...)):
    _channel_filter["channel"] = body.get("channel")
    return {"status": "ok", "channel": _channel_filter["channel"]}


@app.get("/channel_stats")
def get_channel_stats():
    with engine.lock:
        accounts_df = engine.accounts_df.copy()
        transactions_df = engine.transactions_df.copy()

    risk_snapshot = _risk_snapshot()
    channels = ["UPI", "NEFT", "IMPS", "ATM", "Mobile"]
    stats = {}

    for channel in channels:
        channel_accounts = (
            accounts_df[accounts_df["channel"] == channel]
            if "channel" in accounts_df.columns
            else accounts_df.iloc[:0]
        )
        account_ids = set(channel_accounts["account_id"].astype(str).tolist())
        fraud_count = (
            int((channel_accounts["is_fraud"] == 1).sum())
            if "is_fraud" in channel_accounts.columns
            else 0
        )
        suspicious_count = sum(
            1
            for account_id in account_ids
            if risk_snapshot.get(account_id, {}).get("status") == "early"
        )
        stats[channel] = {
            "total": len(channel_accounts),
            "fraud": fraud_count,
            "suspicious": suspicious_count,
        }

    volume_matrix = {}
    if "channel" in transactions_df.columns:
        for _, row in transactions_df.tail(200).iterrows():
            sender_id = str(row.get("sender", ""))
            receiver_id = str(row.get("receiver", ""))
            sender_row = accounts_df[accounts_df["account_id"].astype(str) == sender_id]
            receiver_row = accounts_df[accounts_df["account_id"].astype(str) == receiver_id]
            if sender_row.empty or receiver_row.empty:
                continue
            sender_channel = str(sender_row.iloc[0].get("channel", ""))
            receiver_channel = str(receiver_row.iloc[0].get("channel", ""))
            key = f"{sender_channel}->{receiver_channel}"
            volume_matrix[key] = volume_matrix.get(key, 0) + 1

    return {"channels": stats, "volume": volume_matrix}


@app.post("/ui/bootstrap")
async def bootstrap_ui():
    engine.reset_state()
    with dashboard_state.lock:
        dashboard_state.reset()
    _invalidate_live_caches()
    return {
        "status": "ok",
        "live": _bootstrap_live_payload(),
        "dashboard": _serialize_dashboard_state(),
        "accounts": _network_accounts_payload(),
        "transactions": _clean(engine.get_transactions()),
        "latest_attack": _latest_attack_payload(),
    }


@app.get("/ui/live_state")
async def get_live_state():
    return _live_payload(force_early_warning=True)


@app.get("/ui/dashboard_state")
async def get_dashboard_state():
    return _serialize_dashboard_state()


@app.post("/ui/simulate_attack")
async def simulate_attack():
    try:
        _load_model()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Model load failed: {exc}") from exc

    _ensure_baseline()
    _compute_early_warning()
    with dashboard_state.lock:
        dashboard_state.early_accounts_frozen = list(dashboard_state.early_accounts)
        attack_index = dashboard_state.attack_index

    attack_name, attack_time = engine.trigger_attack(attack_index=attack_index)
    if attack_name is None:
        return {"status": "skipped", "reason": "not enough active accounts"}

    with dashboard_state.lock:
        dashboard_state.attack_index += 1

    accounts_df = _accounts_df()
    transactions_df = _transactions_df()
    ground_truth = engine.get_fraud_accounts()

    if accounts_df.empty or transactions_df.empty:
        raise HTTPException(
            status_code=500,
            detail="Data fetch failed after attack injection.",
        )

    _run_detection(accounts_df, transactions_df, attack_time, attack_name, ground_truth)

    return {
        "status": "attack triggered",
        "attack_name": attack_name,
        "attack_time": str(attack_time),
        "attack_graph": _latest_attack_payload(),
        "job": {
            "status": "running",
            "attack_name": attack_name,
            "attack_time": str(attack_time),
        },
    }


@app.post("/ui/trigger_attack")
async def trigger_attack_async():
    try:
        _load_model()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Model load failed: {exc}") from exc

    _ensure_baseline()
    _invalidate_live_caches()
    _compute_early_warning(force=True)
    with dashboard_state.lock:
        dashboard_state.early_accounts_frozen = list(dashboard_state.early_accounts)
        attack_index = dashboard_state.attack_index

    attack_name, attack_time = engine.trigger_attack(attack_index=attack_index)
    if attack_name is None:
        return {"status": "skipped", "reason": "not enough active accounts"}

    with dashboard_state.lock:
        dashboard_state.attack_index += 1
    next_job_id = _queue_detection_job(attack_name, attack_time)

    return {
        "status": "attack triggered",
        "attack_name": attack_name,
        "attack_time": str(attack_time),
        "attack_graph": _latest_attack_payload(),
        "job": {
            "job_id": next_job_id,
            "status": "queued",
            "attack_name": attack_name,
            "attack_time": str(attack_time),
        },
    }


@app.post("/ui/start_detection")
async def start_detection():
    with dashboard_state.lock:
        detection_job = dict(dashboard_state.detection_job)

    if not detection_job.get("attack_name") or not detection_job.get("attack_time"):
        return {"status": "idle", "job": detection_job}

    if detection_job.get("status") == "running":
        return {"status": "running", "job": detection_job}

    if detection_job.get("status") == "complete":
        return {"status": "complete", "job": detection_job}

    if detection_job.get("status") == "error":
        return {"status": "error", "job": detection_job}

    started_job = _start_detection_job(
        int(detection_job["job_id"]),
        str(detection_job["attack_name"]),
        pd.Timestamp(detection_job["attack_time"]),
    )
    return {"status": started_job["status"], "job": started_job}


@app.get("/ui/detection_status")
async def get_detection_status():
    with dashboard_state.lock:
        detection_job = dict(dashboard_state.detection_job)
    return {
        "status": detection_job["status"],
        "job": detection_job,
        "dashboard": _serialize_dashboard_state(),
    }


@app.get("/ui/investigation/{account_id}")
async def get_investigation(account_id: str):
    payload = _serialize_investigation(account_id)
    if not payload.get("available"):
        raise HTTPException(status_code=404, detail="Investigation data not available.")
    return payload

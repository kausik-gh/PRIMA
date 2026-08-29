"""
frontend/streamlit_app.py
Cross-Channel Money Mule Detection System

Run:
  Terminal 1: uvicorn backend.api:app --reload --port 8088
  Terminal 2: streamlit run frontend/streamlit_app.py
"""

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import streamlit.components.v1 as components
import joblib, requests, time
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.style.use("seaborn-v0_8")
from sklearn.metrics import precision_score, recall_score

from backend.gnn import gnn_predict
from frontend.threejs_graph import render_network_graph
from backend.features import build_transaction_graph, extract_node_features
from backend.detection import (
    rule_based_detection, ml_predict, explain_risk_categories,
    classify_fraud_roles, behavioral_drift_detection,
    early_stage_detection, adaptive_threshold_update, load_explainer,
)
from backend.risk_memory import extract_cluster_signature, store_signature, compare_signature
from backend.config import TX_WINDOW

API = "http://localhost:8088"
st.set_page_config(page_title="Money Mule Detection", layout="wide")

# ── Session state ──────────────────────────────────────────────────
for k, v in {
    "threshold": 0.45, "threshold_history": [], "fraud_history": [],
    "role_history": [], "model": None, "explainer": None,
    "attack_index": 0, "frozen": {},
    "selected_account": None, "early_accounts": [],
    "early_accounts_frozen": [], "baseline_snapshot": None,
    "baseline_tx_count": 0, "session_initialized": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Load model ─────────────────────────────────────────────────────
if st.session_state.model is None:
    try:
        BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        model = joblib.load(os.path.join(BASE_DIR, "fraud_model.pkl"))
        model.feature_list = getattr(model, "feature_list", [
            "in_degree","out_degree","total_in_amount","total_out_amount",
            "retention_ratio","unique_neighbors","unique_channels",
            "device_cluster_size","transaction_count",
        ])
        st.session_state.model    = model
        st.session_state.explainer = load_explainer(model)
    except Exception as e:
        st.error(f"⚠ Model not found. Run: python -m backend.train_model\n\n{e}")
        st.stop()

model    = st.session_state.model
explainer = st.session_state.explainer

# ── API helpers ────────────────────────────────────────────────────
def ag(ep, timeout=4):
    try: return requests.get(f"{API}/{ep}", timeout=timeout).json()
    except: return None

def ap(ep, data=None, timeout=15):
    try: return requests.post(f"{API}/{ep}", json=data, timeout=timeout).json()
    except: return None

def fetch_accounts():
    d = ag("accounts")
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d)
    if "creation_time" in df.columns:
        df["creation_time"] = pd.to_datetime(df["creation_time"])
    return df

def fetch_transactions(limit=None):
    d = ag("all_transactions")
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.tail(limit) if limit else df

def fetch_banned():       return ag("banned_accounts") or []
def fetch_fraud_gt():     return ag("fraud_accounts") or []
def fetch_suspicious():   return ag("suspicious_accounts") or []
def fetch_sus_scores():
    d = ag("suspicion_scores")
    if not isinstance(d, dict): return {}
    # Filter out any non-numeric values (e.g. error responses)
    return {k: v for k, v in d.items() if isinstance(v, (int, float))}

# ── Check API ──────────────────────────────────────────────────────
accounts_df = fetch_accounts()
if accounts_df.empty:
    st.error("⚠ Start API first:\n```\nuvicorn backend.api:app --reload --port 8088\n```")
    st.stop()

if not st.session_state.session_initialized:
    ap("reset_state")
    st.session_state.session_initialized = True

# ── Title ──────────────────────────────────────────────────────────
st.title("🚨 Cross-Channel Money Mule Detection System")
st.markdown("Graph-based · Explainable · Adaptive · Real-time fraud detection")

# ── Top metrics (fragment = refreshes independently every 8s) ──────
@st.fragment(run_every=8)
def live_metrics():
    m = ag("metrics") or {}
    banned = fetch_banned()
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Threshold",       round(st.session_state.threshold,3))
    c2.metric("Simulations",     len(st.session_state.threshold_history))
    c3.metric("Active Accounts", m.get("active_accounts","—"))
    c4.metric("Fraud Flagged",   len(st.session_state.frozen.get("fraud_ids",[])))
    c5.metric("Banned",          m.get("banned_count","—"))
    c6.metric("Live TXs",        m.get("tx_count","—"))

live_metrics()

# ── Baseline builder ───────────────────────────────────────────────
def build_baseline():
    try:
        accs = fetch_accounts()
        txns = fetch_transactions(limit=TX_WINDOW)
        if accs.empty or txns.empty: return
        G = build_transaction_graph(accs, txns)
        bl = extract_node_features(accs, txns, G)
        st.session_state.baseline_snapshot  = bl
        st.session_state.baseline_tx_count  = len(txns)
    except: pass

m_now = ag("metrics") or {}
if st.session_state.baseline_snapshot is None and m_now.get("tx_count",0) >= 30:
    build_baseline()

# ══════════════════════════════════════════════════════════════════
# ⚡ EARLY WARNING MONITOR
# Real behavioral analysis, top 12% most anomalous only
# Updates every 8s independently via st.fragment
# ══════════════════════════════════════════════════════════════════
st.markdown("---")

@st.fragment(run_every=8)
def early_warning_section():
    st.subheader("⚡ Early Warning Monitor")

    with st.expander("📖 How Early Warning Works"):
        st.markdown("""
Continuously monitors **live transaction behavior** of all 250 accounts.
Flags only the **top 12% most anomalous** accounts — keeping warnings meaningful.

**6 behavioral signals** (relative to current population):

| Signal | Condition | Weight |
|---|---|---|
| New Account | age < 30th percentile of all accounts | 0.25 |
| Shared Device | `device_cluster_size ≥ 3` | 0.20 |
| Pass-Through | `retention_ratio < 0.20` + has incoming tx | 0.20 |
| High Velocity | `transaction_count > mean + 1.5×std` | 0.25 |
| High Fan-Out | `out_degree ≥ 3` | 0.15 |
| Multi-Channel | `unique_channels ≥ 3` | 0.15 |

**Needs 2+ signals AND top 12% by anomaly score to flag.**

Why relative thresholds matter:
- With 250 accounts transacting at different rates, absolute thresholds (e.g. "age < 5 days") miss most suspicious behavior
- Comparing each account against its peers catches genuine outliers
- Top 12% cutoff keeps the signal-to-noise ratio high

Yellow nodes in graph = currently flagged. Updates as transactions accumulate.
When attack is injected, suspicious accounts are preferentially targeted.
""")

    early_df       = pd.DataFrame()
    early_accounts = []

    try:
        accs = fetch_accounts()
        txns = fetch_transactions(limit=TX_WINDOW)
        if not accs.empty and not txns.empty:
            # Only use active accounts
            active_accs = accs[accs.get("is_active", pd.Series(True, index=accs.index)) != False]
            G_e     = build_transaction_graph(active_accs, txns)
            feats_e = extract_node_features(active_accs, txns, G_e)
            early_df = early_stage_detection(
                feats_e,
                top_pct=0.12,
                min_signals=2
            )
            early_accounts = early_df["account_id"].tolist() if not early_df.empty else []
            st.session_state.early_accounts = early_accounts
    except Exception as e:
        st.caption(f"Early detection error: {e}")

    col_a, col_b = st.columns(2)
    col_a.metric("Early Warning Accounts", len(early_accounts))
    col_b.metric("Total Active Accounts",  m_now.get("active_accounts", len(accounts_df)))

    if not early_df.empty:
        st.warning(f"⚠ {len(early_df)} account(s) show suspicious behavioral patterns")
        disp = ["account_id","early_risk_score","anomaly_score"]
        if "signals" in early_df.columns: disp.append("signals")
        st.dataframe(
            early_df[disp].sort_values("anomaly_score", ascending=False),
            width='stretch'
        )

        # Show suspicion score distribution
        sus_scores = fetch_sus_scores()
        if sus_scores:
            scores_list = sorted([float(v) for v in sus_scores.values()], reverse=True)
            fig_s, ax_s = plt.subplots(figsize=(6,2))
            ax_s.bar(range(len(scores_list)), scores_list,
                     color=['#ffcc00' if s>=0.20 else '#112244' for s in scores_list],
                     width=1.0)
            ax_s.axhline(0.20, color='#ffcc00', linestyle='--', alpha=0.5,
                         linewidth=0.8, label='Warning threshold')
            ax_s.set_title("Account Suspicion Score Distribution", fontsize=9)
            ax_s.set_xlabel("Accounts (sorted)", fontsize=8)
            ax_s.set_ylabel("Score", fontsize=8)
            ax_s.set_ylim(0, 1)
            ax_s.legend(fontsize=7)
            plt.tight_layout()
            st.pyplot(fig_s); plt.close(fig_s)
    else:
        cnt = m_now.get("tx_count", 0)
        if cnt < 30:
            st.info(f"Accumulating transactions... ({cnt}/30 so far)")
        else:
            st.success("✅ No anomalous behavior detected above threshold")

early_warning_section()

# ══════════════════════════════════════════════════════════════════
# 🔴 LIVE TRANSACTION NETWORK
# All data real — graph polls API directly every 2.5s
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🔴 Live Transaction Network")

with st.expander("📖 How the Graph Works"):
    st.markdown("""
**All data is real — fetched from the backend API every 2.5 seconds.**

- **Edges** appear only when a real transaction occurs, then fade after 6 seconds
- **Banned nodes** disappear immediately — no lingering edges
- **Yellow nodes** = early warning (top 12% most suspicious, updates every 8s)
- **Red nodes** = fraud detected by ML + GNN pipeline
- **Metrics** (TPS, TX count, accounts) are real engine numbers

When fraud is detected: 🚨 **red flash + audio siren**

Graph 2 below shows only the **attack-window transactions** — not 500 accumulated ones.
""")

fr      = st.session_state.frozen
banned  = fetch_banned()
suspicious_now = st.session_state.early_accounts

# ── Graph slot: use st.empty() so detection can UPDATE it in-place ──
# When no attack is being processed right now, render with current frozen state.
# When sim_clicked, we skip here and render AFTER detection with trigger_siren=True
# so ALL results (red nodes + siren + graph) appear TOGETHER in ONE event.
_graph_slot = st.empty()

def _render_graph(trigger_siren_flag: bool = False):
    _fr = st.session_state.frozen
    _banned = fetch_banned()
    _sus_now = st.session_state.early_accounts
    with _graph_slot:
        render_network_graph(
            accounts_df    = _fr.get("accounts_df", accounts_df),
            fraud_ids      = _fr.get("fraud_ids", []),
            early_ids      = _sus_now,
            banned_ids     = _banned,
            suspicious_txs = _fr.get("suspicious_txs", []),
            attack_name    = _fr.get("attack_name", ""),
            height         = 680,
            api_url        = API,
            trigger_siren  = trigger_siren_flag,
        )

# Render graph immediately for live monitoring (no siren on regular renders)
_render_graph(trigger_siren_flag=False)


# ── Detection pipeline ─────────────────────────────────────────────
def _run_detection(accounts_df, transactions_df, attack_time, attack_name, gt_fraud_ids):
    at = pd.Timestamp(attack_time)
    transactions_df["timestamp"] = pd.to_datetime(transactions_df["timestamp"])

    # Only attack-window transactions for detection
    atxns = transactions_df[transactions_df["timestamp"] >= at]
    if atxns.empty:
        atxns = transactions_df.tail(50)

    G           = build_transaction_graph(accounts_df, atxns)
    features_df = extract_node_features(accounts_df, atxns, G)
    fcols       = model.feature_list

    risk_df = rule_based_detection(features_df)

    gnn_ok = False
    try:
        BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        gnn_df   = gnn_predict(G, features_df, model_path=os.path.join(BASE_DIR,"gnn_model.pth"))
        features_df = features_df.merge(gnn_df, on="account_id", how="left")
        features_df["gnn_score"] = features_df["gnn_score"].fillna(0.0)
        gnn_ok = True
    except: pass

    preds = ml_predict(model, features_df, risk_df, threshold=st.session_state.threshold)

    if "is_fraud" not in preds.columns:
        for src in [features_df, accounts_df]:
            if "is_fraud" in src.columns:
                preds = preds.merge(src[["account_id","is_fraud"]], on="account_id", how="left")
                break

    pred_fraud_ids = preds[preds["predicted_label"]==1]["account_id"].tolist()
    fraud_id_set   = set(str(f) for f in pred_fraud_ids)

    fraud_only = features_df[features_df["account_id"].isin(pred_fraud_ids)]
    roles_df   = classify_fraud_roles(fraud_only) if not fraud_only.empty \
                 else pd.DataFrame(columns=["account_id","role"])

    # Behavioral drift — compare against pre-attack baseline
    drift_df = pd.DataFrame()
    bl = st.session_state.baseline_snapshot
    if bl is not None and not bl.empty:
        try:
            drift_df = behavioral_drift_detection(bl, features_df, fcols, threshold=0.4)
        except: pass

    # Suspicious transactions (attack window only)
    sus_txs = []
    for _, tx in atxns.iterrows():
        s = str(tx["sender"]); r = str(tx["receiver"])
        if s in fraud_id_set or r in fraud_id_set or tx.get("is_attack", False):
            sus_txs.append({
                "sender":  s, "receiver": r,
                "amount":  float(tx.get("amount",0)),
                "channel": str(tx.get("channel","TXN")),
            })

    sig  = extract_cluster_signature(G, features_df)
    sim  = compare_signature(sig) if sig else 0.0
    if sig: store_signature(sig)

    gt_set = set(str(x) for x in gt_fraud_ids)
    tl  = pd.Series([1 if str(a) in gt_set else 0 for a in features_df["account_id"]])
    pl  = preds["predicted_label"].values
    prec = precision_score(tl, pl, zero_division=0)
    rec  = recall_score(tl, pl, zero_division=0)
    nthr = adaptive_threshold_update(st.session_state.threshold, {"1":{"precision":prec,"recall":rec}})
    st.session_state.threshold = nthr
    st.session_state.threshold_history.append(nthr)

    correct = gt_set.intersection(set(str(x) for x in pred_fraud_ids))
    st.session_state.fraud_history.append(len(correct)/max(len(gt_set),1))
    if not fraud_only.empty:
        st.session_state.role_history.append(roles_df["role"].value_counts().to_dict())

    st.session_state.frozen = {
        "accounts_df": accounts_df, "transactions_df": transactions_df,
        "attack_transactions": atxns, "attack_time": at,
        "attack_name": attack_name, "features_df": features_df,
        "risk_df": risk_df, "predictions": preds, "roles_df": roles_df,
        "drift_df": drift_df, "fraud_ids": pred_fraud_ids,
        "suspicious_txs": sus_txs, "signature": sig, "similarity": sim,
        "precision": prec, "recall": rec,
        "true_fraud_count": len(gt_set), "correct_count": len(correct),
        "G": G, "gnn_available": gnn_ok,
    }
    if pred_fraud_ids:
        st.session_state.selected_account = str(pred_fraud_ids[0])

# ══════════════════════════════════════════════════════════════════
# 🚀 SIMULATE ATTACK
# Uses engine's own accounts, prefers suspicious accounts
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
sc1, sc2 = st.columns([2,1])
with sc1:
    sim_clicked = st.button("🚀 Simulate Coordinated Attack", type="primary")
with sc2:
    active_ct = m_now.get("active_accounts", "—")
    banned_ct = len(banned)
    st.info(f"Active: {active_ct} · Banned: {banned_ct}")

if sim_clicked:
    build_baseline()
    st.session_state.early_accounts_frozen = list(st.session_state.early_accounts)

    with st.spinner("Injecting attack into live transaction stream..."):
        result = ag(f"trigger_attack?index={st.session_state.attack_index}", timeout=25)

    if result and result.get("status") == "attack triggered":
        attack_name = result["attack_name"]
        attack_time = result["attack_time"]
        st.session_state.attack_index += 1
        st.success(f"✅ Attack injected: **{attack_name}**")

        # Accounts returned in response (already have is_fraud labels)
        accs_raw = result.get("accounts", [])
        if accs_raw:
            final_accounts = pd.DataFrame(accs_raw)
            if "creation_time" in final_accounts.columns:
                final_accounts["creation_time"] = pd.to_datetime(
                    final_accounts["creation_time"]
                )
        else:
            final_accounts = fetch_accounts()

        final_txns   = fetch_transactions()
        ground_truth = fetch_fraud_gt()

        if not final_accounts.empty and not final_txns.empty:
            with st.spinner("Running ML detection pipeline..."):
                _run_detection(final_accounts, final_txns, attack_time, attack_name, ground_truth)
            st.success("✅ Detection complete — results shown below.")
            # ── Re-render graph IN PLACE with updated fraud_ids + trigger_siren=True
            # This delivers graph + red nodes + siren ALL AT ONCE (single event, no re-init)
            _render_graph(trigger_siren_flag=True)
        else:
            st.error(f"Data fetch failed — Accounts: {len(final_accounts)}, TXs: {len(final_txns)}")
            if result.get("traceback"):
                st.code(result["traceback"])
    elif result and result.get("error"):
        st.error(f"Attack error: {result['error']}")
        if result.get("traceback"):
            st.code(result["traceback"])
    else:
        st.error("API not responding")

# ── Guard — only blocks if NO detection has ever been run ──────────
fr = st.session_state.frozen
if fr.get("predictions") is None:
    st.info("👆 Click **Simulate Coordinated Attack** to run detection.")
    st.stop()

preds       = fr["predictions"]
features_df = fr["features_df"]
risk_df     = fr["risk_df"]
roles_df    = fr["roles_df"]
drift_df    = fr["drift_df"]
fraud_ids   = fr["fraud_ids"]

# ══════════════════════════════════════════════════════════════════
# 🚫 BAN FRAUD ACCOUNTS
# ══════════════════════════════════════════════════════════════════
if fraud_ids:
    st.markdown("---")
    st.subheader("🚫 Ban Fraud Accounts")
    already_banned = set(fetch_banned())
    unbanned = [str(f) for f in fraud_ids if str(f) not in already_banned]
    if unbanned:
        to_ban = st.multiselect("Select accounts to ban:", options=unbanned,
                                default=[], key="ban_sel")
        if st.button("🚫 Ban Selected", type="secondary"):
            if to_ban:
                r = ap("ban_accounts", to_ban)
                if r and r.get("status")=="banned":
                    remaining = r.get("remaining_active","?")
                    st.success(f"✅ Banned {len(to_ban)} accounts. Active pool: {remaining}")
                    st.rerun()
                else: st.error("Ban failed")
            else: st.warning("Select accounts first")
    else:
        st.success("✅ All detected fraud accounts already banned.")
    if already_banned:
        st.caption(f"Banned: {', '.join(sorted(already_banned))}")

# ══════════════════════════════════════════════════════════════════
# 📉 BEHAVIORAL DRIFT
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("📉 Behavioral Drift Detection")

with st.expander("📖 Why Drift Detection Catches What Rules Miss"):
    st.markdown(f"""
Behavioral drift compares **post-attack account behavior** against a
**pre-attack baseline** snapshot ({st.session_state.baseline_tx_count} transactions).

**Key insight:** Many fraud accounts look individually normal.
But their **change in behavior** when activated is dramatic:
- A dormant account suddenly makes 15 transactions
- A low-velocity account suddenly does high-value rapid transfers
- A single-channel account suddenly uses UPI + ATM + NEFT simultaneously

Drift score = Euclidean distance between normalized baseline and current vectors.

**Features compared:**
`transaction_count`, `in_degree`, `out_degree`, `retention_ratio`,
`unique_neighbors`, `unique_channels`, `device_cluster_size`

This is a **Layer 0 detection** — it fires BEFORE the ML model,
based purely on behavioral change, not absolute feature values.
""")

if not drift_df.empty:
    st.warning(f"⚠ {len(drift_df)} account(s) show significant behavioral drift from pre-attack baseline")
    disp_cols = ["account_id","drift_score"]
    if "top_changes" in drift_df.columns: disp_cols.append("top_changes")
    st.dataframe(drift_df[disp_cols].sort_values("drift_score",ascending=False), width='stretch')
elif st.session_state.baseline_snapshot is None:
    st.warning("⚠ No baseline — let transactions accumulate before attacking")
else:
    st.info("No significant behavioral drift detected in this simulation.")

# ══════════════════════════════════════════════════════════════════
# 📌 RULE-BASED DETECTION
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("📌 Rule-Based Risk Scoring")

with st.expander("📖 Rules"):
    st.markdown("""
| Rule | Trigger | Score |
|---|---|---|
| Fan-In | `in_degree ≥ 2` | +2 |
| Fan-Out | `out_degree ≥ 2` | +2 |
| Low Retention | `retention_ratio < 0.2` | +2 |
| Shared Device | `device_cluster_size > 2` | +3 |
| Channel Burst | `unique_channels > 2` | +2 |
| High Volume | `transaction_count ≥ 3` | +1 |

🔴 High ≥7 · 🟠 Medium ≥4 · 🟢 Low <4 — contributes 30% to final score
""")

def rv(s):
    if s>=7: return "🔴 High"
    elif s>=4: return "🟠 Medium"
    else: return "🟢 Low"

rd = risk_df.copy()
rd["verdict"] = rd["risk_score"].apply(rv)
rd["reasons_str"] = rd["reasons"].apply(lambda r: ", ".join(r) if isinstance(r,list) and r else "None")
rd = rd.drop(columns=["reasons"],errors="ignore")

rb1,rb2,rb3 = st.columns(3)
rb1.metric("🔴 High",   int((risk_df["risk_score"]>=7).sum()))
rb2.metric("🟠 Medium", int(((risk_df["risk_score"]>=4)&(risk_df["risk_score"]<7)).sum()))
rb3.metric("Scored",    len(risk_df))
st.dataframe(rd[["account_id","risk_score","verdict","reasons_str"]].sort_values("risk_score",ascending=False).head(15), width='stretch')

# ══════════════════════════════════════════════════════════════════
# 🤖 ML DETECTION
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🤖 ML Detection Results")

with st.expander("📖 3-Layer Detection"):
    st.markdown(f"""
**Layer 1 — Rules** (30%): Explicit fraud heuristics
**Layer 2 — Random Forest** (50%): Trained on synthetic attacks
**Layer 3 — GAT GNN** (20%): {"✅ Active" if fr.get("gnn_available") else "⚠ run train_gnn"}

```
final_score = 0.5×ml + 0.3×rules + 0.2×gnn   threshold: {round(st.session_state.threshold,3)}
```
""")

dcols = ["account_id","ml_score","rule_score_norm","final_score","predicted_label"]
for opt in ["gnn_score","is_fraud"]:
    if opt in preds.columns: dcols.append(opt)

mld = preds[dcols].copy()
for c in ["ml_score","rule_score_norm","final_score"]:
    if c in mld.columns: mld[c] = mld[c].round(4)
if "gnn_score" in mld.columns: mld["gnn_score"] = mld["gnn_score"].round(4)
st.dataframe(mld.sort_values("final_score",ascending=False).head(15), width='stretch')

ml1,ml2,ml3 = st.columns(3)
ml1.metric("Fraud Flagged", len(fraud_ids))
ml2.metric("Precision",     round(fr.get("precision",0),3))
ml3.metric("Recall",        round(fr.get("recall",0),3))

# ══════════════════════════════════════════════════════════════════
# ⚙ ADAPTIVE THRESHOLD
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("⚙ Adaptive Threshold")
at1,at2,at3 = st.columns(3)
at1.metric("Threshold", round(st.session_state.threshold,3))
at2.metric("Precision", round(fr.get("precision",0),3))
at3.metric("Recall",    round(fr.get("recall",0),3))

# ══════════════════════════════════════════════════════════════════
# 🔍 FRAUD INVESTIGATION PANEL
# Dropdown never triggers recomputation — reads from frozen
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🔍 Fraud Investigation Panel")

fp = preds[preds["predicted_label"]==1]
if fp.empty:
    st.info("No fraud accounts detected.")
else:
    st.metric("Detected", len(fp))
    fids = [str(a) for a in fp["account_id"].values]
    sel  = st.session_state.get("selected_account")
    if sel not in fids: sel = fids[0]
    selected = st.selectbox("Select account:", fids, index=fids.index(sel), key="acc_sel")
    st.session_state.selected_account = selected

    prob_row = preds[preds["account_id"].astype(str)==selected]
    prob = float(prob_row["final_score"].values[0]) if not prob_row.empty else 0.0

    def rsev(s):
        if s>0.75: return "🔴 High Confidence"
        elif s>0.5: return "🟠 Medium Risk"
        else: return "🟡 Low Confidence"

    st.markdown("### 🚨 Fraud Alert")
    fa1,fa2,fa3 = st.columns(3)
    fa1.metric("Account ID",    selected)
    fa2.metric("Fraud Score",   f"{round(prob*100,2)}%")
    fa3.metric("Confidence",    rsev(prob))

    if all(c in prob_row.columns for c in ["ml_score","rule_score_norm"]):
        sc1,sc2,sc3 = st.columns(3)
        sc1.metric("ML",   round(float(prob_row["ml_score"].values[0]),4))
        sc2.metric("Rule", round(float(prob_row["rule_score_norm"].values[0]),4))
        if "gnn_score" in prob_row.columns:
            sc3.metric("GNN", round(float(prob_row["gnn_score"].values[0]),4))

    if prob>0.75: st.error("🔴 High Confidence Fraud")
    elif prob>0.5: st.warning("🟠 Medium Risk")
    else: st.info("🟡 Low Confidence")

    # Role
    st.subheader("🧩 Fraud Role")
    rc_map = {"Ring Coordinator":"🔴","Collector Mule":"🟠","Distributor Mule":"🟡",
              "Entry Node":"🔵","Exit Node":"🟣","Unclassified":"⚪"}
    if not roles_df.empty:
        row = roles_df[roles_df["account_id"].astype(str)==selected]
        if not row.empty:
            role = row["role"].values[0]
            st.markdown(f"**Role:** {rc_map.get(role,'⚪')} **{role}**")

    # Ecosystem chart
    if not roles_df.empty:
        rc = roles_df["role"].value_counts()
        lc,cc,_rc = st.columns([1,2,1])
        with cc:
            fig,ax = plt.subplots(figsize=(6,3))
            colors = ["#ff2200","#ff6600","#ffaa00","#0055ff","#8800ff","#888"]
            ax.bar(rc.index,rc.values,color=colors[:len(rc)])
            ax.set_title("Fraud Ecosystem Roles"); ax.set_ylabel("Accounts")
            ax.grid(axis="y",linestyle="--",alpha=0.4)
            plt.xticks(rotation=30,ha="right"); plt.tight_layout()
            st.pyplot(fig); plt.close(fig)

    # SHAP
    st.subheader("📊 SHAP Risk Breakdown")
    fc = model.feature_list
    af = features_df[features_df["account_id"].astype(str)==selected][fc]
    shap_ok = False
    if not af.empty and explainer:
        try:
            sv = explainer.shap_values(af)
            if isinstance(sv,list): sv = sv[1]
            sv = np.array(sv)
            if sv.ndim==3: sv=sv[0][:,1]
            elif sv.ndim==2: sv=sv[0]
            sv=np.array(sv).flatten()
            shap_ok = len(sv)==len(fc)
        except: shap_ok=False

    if shap_ok:
        cats = explain_risk_categories(sv,fc)
        sc   = sorted(cats.items(),key=lambda x:x[1],reverse=True)
        cdf  = pd.DataFrame([(k,round(v*100,2)) for k,v in sc],columns=["Category","Contribution (%)"])
        sh1,sh2=st.columns(2)
        with sh1: st.dataframe(cdf,width='stretch')
        with sh2:
            fig2,ax2=plt.subplots(figsize=(5,3))
            ax2.barh([c[0] for c in sc],[c[1] for c in sc],
                     color=["#ff2200","#ff6600","#ffaa00","#2255ff","#8800ff"][:len(sc)])
            ax2.set_xlabel("Contribution"); ax2.grid(axis="x",linestyle="--",alpha=0.3)
            plt.tight_layout(); st.pyplot(fig2); plt.close(fig2)

        st.subheader("🧠 Why Flagged?")
        exps=[]
        if cats.get("Velocity Risk",0)>0.1: exps.append("• **Velocity** — Rapid fund movement")
        if cats.get("Shared Device Risk",0)>0.05: exps.append("• **Shared Device** — Multi-account control")
        if cats.get("Ring Participation Risk",0)>0.1: exps.append("• **Ring** — Embedded in fraud ring")
        if cats.get("Retention Risk",0)>0.05: exps.append("• **Retention** — Pass-through mule")
        if cats.get("Channel Risk",0)>0.05: exps.append("• **Channel** — Multi-channel burst")
        for e in exps: st.markdown(e)
        if not exps: st.info("Flagged by structural position (GNN).")

# ══════════════════════════════════════════════════════════════════
# 🧠 PATTERN MEMORY
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🧠 Fraud Pattern Memory")
sim_val = fr.get("similarity",0.0)
pm1,pm2=st.columns(2)
pm1.metric("Pattern Similarity", f"{round(sim_val*100,2)}%")
pm2.metric("Patterns Stored",    len(st.session_state.threshold_history))
if sim_val>0.7: st.warning("⚠ Repeat attack structure detected")
elif sim_val>0.4: st.info("ℹ Variant of known pattern")
else: st.success("✅ New fraud pattern")

# ══════════════════════════════════════════════════════════════════
# 🎭 ATTACK SUMMARY + EARLY CROSS-CHECK
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🎭 Detection Summary")
st.success(f"**Detected Pattern:** {fr.get('attack_name','Unknown')}")
ds1,ds2,ds3=st.columns(3)
ds1.metric("Injected", fr.get("true_fraud_count",0))
ds2.metric("Detected", fr.get("correct_count",0))
ds3.metric("Missed",   fr.get("true_fraud_count",0)-fr.get("correct_count",0))

st.markdown("---")
st.subheader("⚡ Early Detection Cross-Check")
early_set  = set(str(a) for a in st.session_state.get("early_accounts_frozen",[]))
det_set    = set(str(a) for a in fr.get("fraud_ids",[]))
matched    = list(early_set & det_set)
only_det   = list(det_set - early_set)
only_early = list(early_set - det_set)

with st.expander("📖 What this shows"):
    st.markdown("""
Compares early-warned accounts (yellow — flagged BEFORE attack)
against ML-confirmed fraud accounts (red — detected AFTER attack).

- ✅ **Matched** = early system caught a real fraud account proactively
- ⚠ **Sleeper** = fraud with no prior suspicious behavior (hard to catch)
- ⚪ **False Positive** = suspicious but not confirmed fraud

Real-world insight: In our system, suspicious accounts are preferentially
targeted for attack. So matched accounts prove the early detection is working —
the system flagged the accounts that actually ended up committing fraud.
""")

ec1,ec2,ec3=st.columns(3)
ec1.metric("Early Warned",   len(early_set))
ec2.metric("Matched",        len(matched))
ec3.metric("Sleeper (New)",  len(only_det))

if matched:   st.success(f"✅ {len(matched)} pre-flagged AND confirmed: {matched}")
if only_det:  st.info(f"ℹ {len(only_det)} sleeper accounts: {only_det}")
if only_early:st.caption(f"⚪ {len(only_early)} false positives: {only_early}")

# ══════════════════════════════════════════════════════════════════
# 🧠 SYSTEM DASHBOARD
# ══════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🧠 System Intelligence Dashboard")

d1,d2=st.columns(2)
with d1:
    if st.session_state.threshold_history:
        fig3,ax3=plt.subplots(figsize=(6,4))
        ax3.plot(st.session_state.threshold_history,marker="o",linewidth=2,color="#4488ff")
        ax3.set_title("Adaptive Threshold Trend"); ax3.set_ylim(0.25,0.85)
        ax3.set_ylabel("Threshold"); ax3.set_xlabel("Simulation Run")
        ax3.grid(True,linestyle="--",alpha=0.4); plt.tight_layout()
        st.pyplot(fig3); plt.close(fig3)
    else: st.info("Run simulations to see threshold trend.")

with d2:
    if st.session_state.fraud_history:
        fig4,ax4=plt.subplots(figsize=(6,4))
        ax4.plot(st.session_state.fraud_history,marker="o",linewidth=2,color="#ff4422")
        ax4.set_title("Fraud Detection Success Rate"); ax4.set_ylim(0,1.05)
        ax4.axhline(1.0,color="green",linestyle="--",alpha=0.4,label="Perfect")
        ax4.set_ylabel("Rate"); ax4.set_xlabel("Run")
        ax4.grid(True,linestyle="--",alpha=0.4); ax4.legend()
        plt.tight_layout(); st.pyplot(fig4); plt.close(fig4)
    else: st.info("Run simulations to see detection rate.")

if st.session_state.role_history:
    ar={}
    for run in st.session_state.role_history:
        for role,cnt in run.items(): ar[role]=ar.get(role,0)+cnt
    fig5,ax5=plt.subplots(figsize=(8,4))
    ax5.bar(list(ar.keys()),list(ar.values()),
            color=["#ff2200","#ff6600","#ffaa00","#0055ff","#8800ff","#888"][:len(ar)])
    ax5.set_title("Fraud Role Distribution (All Simulations)")
    ax5.set_ylabel("Accounts"); ax5.grid(axis="y",linestyle="--",alpha=0.4)
    plt.xticks(rotation=30,ha="right"); plt.tight_layout()
    st.pyplot(fig5); plt.close(fig5)
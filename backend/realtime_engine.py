import math
import random
import threading
import time
from collections import Counter, deque
from datetime import datetime

import pandas as pd

from backend.config import ATTACK_POOL_SIZE, ATTACK_PREFER_SUS_PCT, MAX_TX_MEMORY, TX_INTERVAL_SEC, TX_STEP_COUNT
from backend.generator import CHANNELS, generate_normal_transactions
from backend.simulation import reset_simulation


class RealTimeEngine:
    FRAUD_THRESHOLD = 0.84
    DECAY = 0.92
    SIGNAL_DECAY = 0.88
    DECAY_PERIOD = 12.0
    WARNING_PERCENTILE = 0.90
    MIN_WARNING_PCT = 0.01
    MAX_WARNING_PCT = 0.06
    MIN_WARNING_THRESHOLD = 0.40
    MAX_WARNING_THRESHOLD = 0.68
    WARNING_ENTER_SIGNALS = 2
    WARNING_RETAIN_SIGNALS = 1
    WARNING_RETAIN_FACTOR = 0.78
    WARNING_RETAIN_FLOOR = 0.18
    WARNING_TX_PER_STEP = 20.0
    WARNING_MAX_CREDIT = 8.0
    NOISE_RANGE = 0.014
    BURST_SEC = 45.0
    SHORT_GAP_SEC = 8.0
    DORMANT_SEC = 120.0
    HISTORY_SEC = 600.0
    BASELINE_AMOUNT = 7500.0
    SIGNAL_LABELS = {
        "new": "New account with unusually fast activity",
        "velocity": "High transaction velocity",
        "high_value": "High-value transaction",
        "trend": "Increasing transaction trend",
        "short_gap": "Short interval transactions",
        "repeat": "Repeated amounts",
        "target_bias": "Single target bias",
        "fan_in": "Early fan-in pattern",
        "fan_out": "Early fan-out pattern",
        "dormant": "Dormant account activation",
        "neighbor": "Connected to a suspicious neighbor",
        "device": "Shared device cluster",
        "attack": "Confirmed attack-path transaction",
    }

    def __init__(self):
        self.accounts_df, self.transactions_df = reset_simulation()
        self.lock = threading.RLock()
        self.banned_accounts = set()
        self.attack_time = None
        self.last_attack_name = None
        self._attacking = False
        self._tps = 0.0
        self._tx_timestamps = deque(maxlen=1200)
        self._acc_counter = None
        self._risk = {}
        self._meta = {}
        self._device_sizes = {}
        self._hot = set()
        self._events = deque(maxlen=80)
        self._amount_ema = self.BASELINE_AMOUNT
        self._warning_threshold_ema = 0.0
        self._warning_ids = set()
        self._warning_adjust_credit = 10.0
        self._warning_context_cache = None
        self._warning_context_cached_at = 0.0
        self._rebuild(self.transactions_df.copy())

    def _ts(self, value=None):
        stamp = pd.Timestamp(value if value is not None else datetime.now())
        return stamp if stamp.tzinfo is None else stamp.tz_convert(None)

    def _blank_signals(self):
        return {key: 0.0 for key in self.SIGNAL_LABELS}

    def _blank_state(self, account_id, created_at):
        return {
            "id": str(account_id),
            "risk": 0.0,
            "status": "normal",
            "signals": self._blank_signals(),
            "reasons": [],
            "recent": deque(maxlen=48),
            "last": None,
            "decay_at": self._ts(created_at),
            "fraud_until": None,
        }

    def _sync_accounts(self):
        frame = self.accounts_df.copy()
        if frame.empty:
            self._risk, self._meta, self._device_sizes = {}, {}, {}
            self._hot.clear()
            return
        frame["creation_time"] = pd.to_datetime(frame["creation_time"], errors="coerce")
        self._device_sizes = frame["device_id"].astype(str).value_counts().to_dict()
        seen = set()
        for row in frame.itertuples(index=False):
            aid = str(row.account_id)
            created_at = self._ts(row.creation_time)
            self._meta[aid] = {
                "creation_time": created_at,
                "device_id": str(getattr(row, "device_id", "")),
                "channel": str(getattr(row, "channel", "")),
                "ip_address": str(getattr(row, "ip_address", "")),
                "is_fraud": bool(getattr(row, "is_fraud", 0)),
                "is_active": bool(getattr(row, "is_active", True)),
            }
            if aid not in self._risk:
                self._risk[aid] = self._blank_state(aid, created_at)
            seen.add(aid)
        for aid in list(self._risk.keys()):
            if aid not in seen:
                self._risk.pop(aid, None)
                self._hot.discard(aid)
        self._sync_flags()

    def _top_reasons(self, state):
        ranked = sorted(((k, v) for k, v in state["signals"].items() if v >= 0.06), key=lambda item: item[1], reverse=True)
        return [self.SIGNAL_LABELS[k] for k, _ in ranked[:4]]

    def _clamp_risk(self, value):
        return max(0.0, min(1.0, float(value)))

    def _warning_selection_locked(self):
        if (
            self._warning_context_cache is not None
            and (time.monotonic() - self._warning_context_cached_at) < 0.35
        ):
            cached = self._warning_context_cache
            return {
                "warning_ids": set(cached["warning_ids"]),
                "threshold": cached["threshold"],
                "warning_pct": cached["warning_pct"],
                "max_count": cached["max_count"],
            }

        ranked_rows = []
        for aid, state in self._risk.items():
            meta = self._meta.get(aid, {})
            if not meta.get("is_active", True):
                continue
            if meta.get("is_fraud", False):
                continue
            if state.get("status") == "fraud":
                continue
            signal_count = sum(1 for value in state.get("signals", {}).values() if float(value) >= 0.04)
            ranked_rows.append(
                {
                    "account_id": aid,
                    "risk_score": self._clamp_risk(state.get("risk", 0.0)),
                    "signal_count": signal_count,
                }
            )

        if not ranked_rows:
            return {
                "warning_ids": set(),
                "threshold": 0.0,
                "warning_pct": self.MIN_WARNING_PCT,
                "max_count": 0,
            }

        risks = pd.Series([row["risk_score"] for row in ranked_rows])
        percentile_threshold = float(risks.quantile(self.WARNING_PERCENTILE))
        percentile_threshold = max(
            self.MIN_WARNING_THRESHOLD,
            min(self.MAX_WARNING_THRESHOLD, percentile_threshold),
        )
        if self._warning_threshold_ema <= 0:
            self._warning_threshold_ema = percentile_threshold
        else:
            self._warning_threshold_ema = (self._warning_threshold_ema * 0.80) + (percentile_threshold * 0.20)
        smoothed_threshold = max(
            self.MIN_WARNING_THRESHOLD,
            min(self.MAX_WARNING_THRESHOLD, float(self._warning_threshold_ema)),
        )
        median_risk = float(risks.quantile(0.50))
        dispersion = max(smoothed_threshold - median_risk, 0.0)
        warning_pct = min(
            self.MAX_WARNING_PCT,
            max(self.MIN_WARNING_PCT, self.MIN_WARNING_PCT + (dispersion * 0.10)),
        )
        max_count = max(1, math.ceil(len(ranked_rows) * self.MAX_WARNING_PCT))
        target_count = max(1, math.ceil(len(ranked_rows) * warning_pct))
        enter_threshold = smoothed_threshold
        retain_threshold = max(self.WARNING_RETAIN_FLOOR, smoothed_threshold * self.WARNING_RETAIN_FACTOR)

        retained_rows = sorted(
            [
                row for row in ranked_rows
                if row["account_id"] in self._warning_ids
                and row["signal_count"] >= self.WARNING_RETAIN_SIGNALS
                and row["risk_score"] >= retain_threshold
            ],
            key=lambda item: item["risk_score"],
            reverse=True,
        )
        entering_rows = sorted(
            [
                row for row in ranked_rows
                if row["signal_count"] >= self.WARNING_ENTER_SIGNALS
                and row["risk_score"] >= enter_threshold
            ],
            key=lambda item: item["risk_score"],
            reverse=True,
        )
        if len(entering_rows) < target_count:
            fallback_rows = sorted(
                [
                    row for row in ranked_rows
                    if row["signal_count"] >= self.WARNING_ENTER_SIGNALS
                    and row["risk_score"] >= max(retain_threshold, median_risk + 0.02)
                ],
                key=lambda item: item["risk_score"],
                reverse=True,
            )
            seen_ids = {row["account_id"] for row in entering_rows}
            for row in fallback_rows:
                if row["account_id"] in seen_ids:
                    continue
                entering_rows.append(row)
                seen_ids.add(row["account_id"])
                if len(entering_rows) >= target_count:
                    break

        prev_count = len(self._warning_ids)
        if target_count > prev_count:
            allowed_delta = max(1, int(self._warning_adjust_credit))
            next_count = min(target_count, prev_count + allowed_delta)
        elif target_count < prev_count:
            allowed_delta = max(1, int(self._warning_adjust_credit * 0.5))
            next_count = max(target_count, prev_count - allowed_delta)
        else:
            allowed_delta = 0
            next_count = target_count
        next_count = min(next_count, max_count)
        consumed = abs(next_count - prev_count)
        if consumed > 0:
            self._warning_adjust_credit = max(0.0, self._warning_adjust_credit - consumed)

        selected_rows = []
        selected_ids = set()
        for pool in (retained_rows, entering_rows):
            for row in pool:
                if row["account_id"] in selected_ids:
                    continue
                selected_rows.append(row)
                selected_ids.add(row["account_id"])
                if len(selected_rows) >= next_count:
                    break
            if len(selected_rows) >= next_count:
                break

        self._warning_ids = selected_ids
        context = {
            "warning_ids": set(self._warning_ids),
            "threshold": round(smoothed_threshold, 4),
            "warning_pct": round(warning_pct, 4),
            "max_count": max_count,
        }
        self._warning_context_cache = {
            "warning_ids": set(context["warning_ids"]),
            "threshold": context["threshold"],
            "warning_pct": context["warning_pct"],
            "max_count": context["max_count"],
        }
        self._warning_context_cached_at = time.monotonic()
        return context

    def _trim_transactions(self, frame: pd.DataFrame) -> pd.DataFrame:
        if MAX_TX_MEMORY is None:
            return frame.reset_index(drop=True)
        return frame.tail(MAX_TX_MEMORY).reset_index(drop=True)

    def _sync_flags(self):
        now_ts = self._ts()
        for aid, meta in self._meta.items():
            state = self._risk[aid]
            if meta["is_fraud"]:
                state["risk"] = max(state["risk"], 0.97)
                state["signals"]["attack"] = max(state["signals"]["attack"], 0.75)
                state["fraud_until"] = now_ts + pd.Timedelta(seconds=90)
                self._hot.add(aid)
            else:
                state["fraud_until"] = None
            self._set_status(aid, now_ts)

    def _set_status(self, aid, now_ts):
        meta = self._meta[aid]
        state = self._risk[aid]
        prev = state["status"]
        hard_fraud = meta["is_fraud"] or state["risk"] >= self.FRAUD_THRESHOLD or (state["fraud_until"] is not None and now_ts <= state["fraud_until"])
        if hard_fraud:
            state["status"] = "fraud"
            state["risk"] = max(state["risk"], 0.86)
        else:
            state["status"] = "normal"
        state["reasons"] = self._top_reasons(state)
        if state["status"] != prev and state["status"] == "fraud":
            self._events.appendleft({"account_id": aid, "status": state["status"], "risk_score": round(float(state["risk"]), 4), "reasons": list(state["reasons"]), "timestamp": now_ts.isoformat()})

    def _decay_one(self, aid, now_ts):
        state = self._risk.get(aid)
        meta = self._meta.get(aid)
        if not state or not meta:
            return
        elapsed = max((now_ts - state["decay_at"]).total_seconds(), 0.0)
        if elapsed <= 0:
            self._set_status(aid, now_ts)
            return
        risk_decay = math.pow(self.DECAY, elapsed / self.DECAY_PERIOD)
        signal_decay = math.pow(self.SIGNAL_DECAY, elapsed / self.DECAY_PERIOD)
        if not meta["is_fraud"]:
            state["risk"] = self._clamp_risk(
                (state["risk"] * risk_decay) + random.uniform(-self.NOISE_RANGE, self.NOISE_RANGE)
            )
        for key, value in list(state["signals"].items()):
            value *= signal_decay
            state["signals"][key] = 0.0 if value < 0.015 else round(value, 5)
        state["decay_at"] = now_ts
        self._set_status(aid, now_ts)
        if state["risk"] < 0.02 and not any(v >= 0.04 for v in state["signals"].values()) and not meta["is_fraud"]:
            self._hot.discard(aid)

    def _decay_hot(self, now_ts=None):
        now_ts = now_ts or self._ts()
        self._warning_context_cache = None
        self._warning_context_cached_at = 0.0
        for aid in list(self._hot):
            self._decay_one(aid, now_ts)

    def _recent(self, state, now_ts, seconds, direction=None):
        items = []
        while state["recent"] and (now_ts - state["recent"][0]["ts"]).total_seconds() > self.HISTORY_SEC:
            state["recent"].popleft()
        for item in state["recent"]:
            if direction and item["dir"] != direction:
                continue
            if (now_ts - item["ts"]).total_seconds() <= seconds:
                items.append(item)
        return items

    def _bucket(self, amount):
        amount = float(amount)
        if amount >= 10000:
            return round(amount / 5000.0) * 5000
        if amount >= 1000:
            return round(amount / 500.0) * 500
        return round(amount / 100.0) * 100

    def _signals(self, aid, cp, now_ts, amount, direction, is_attack):
        state = self._risk[aid]
        meta = self._meta[aid]
        recent_short = self._recent(state, now_ts, self.BURST_SEC)
        recent_out = self._recent(state, now_ts, 180.0, "out")
        recent_in = self._recent(state, now_ts, 180.0, "in")
        age_sec = max((now_ts - meta["creation_time"]).total_seconds(), 0.0)
        gap = max((now_ts - state["last"]).total_seconds(), 0.0) if state["last"] is not None else None
        baseline = max(self.BASELINE_AMOUNT, self._amount_ema, (sum(item["amount"] for item in recent_short) / len(recent_short)) if recent_short else self.BASELINE_AMOUNT)
        amount_bucket = self._bucket(amount)
        repeated = sum(1 for item in state["recent"] if self._bucket(item["amount"]) == amount_bucket)
        trend_window = [item["amount"] for item in list(state["recent"])[-6:]] + [amount]
        device_size = int(self._device_sizes.get(meta["device_id"], 1))
        signals = {}

        if age_sec <= 7 * 24 * 3600 and (len(recent_short) >= 1 or amount >= baseline * 1.5):
            newness = 1.0 - min(age_sec / (7 * 24 * 3600), 1.0)
            signals["new"] = min(0.26, 0.12 + 0.10 * newness + 0.02 * len(recent_short))
        if gap is not None and gap >= self.DORMANT_SEC and amount >= baseline * 1.25:
            signals["dormant"] = min(0.22, 0.10 + min(gap / 600.0, 1.0) * 0.12)
        if len(recent_short) + 1 >= 4:
            signals["velocity"] = min(0.24, 0.08 + 0.03 * max((len(recent_short) + 1) - 3, 0))
        if gap is not None and gap <= self.SHORT_GAP_SEC:
            signals["short_gap"] = min(0.18, 0.07 + ((self.SHORT_GAP_SEC - gap) / self.SHORT_GAP_SEC) * 0.11)
        if amount >= baseline * 2.1:
            signals["high_value"] = min(0.28, 0.10 + min((amount / max(baseline, 1.0)) - 2.1, 3.0) * 0.06)
        if len(trend_window) >= 6:
            prev_avg = sum(trend_window[:-3]) / max(len(trend_window[:-3]), 1)
            last_avg = sum(trend_window[-3:]) / 3.0
            if prev_avg > 0 and last_avg >= prev_avg * 1.45:
                signals["trend"] = min(0.18, 0.07 + min((last_avg / prev_avg) - 1.45, 2.0) * 0.05)
        if repeated >= 2:
            signals["repeat"] = min(0.16, 0.06 + repeated * 0.03)
        if direction == "out":
            targets = [item["cp"] for item in recent_out] + [cp]
            if len(targets) >= 4:
                ratio = max(Counter(targets).values()) / len(targets)
                if ratio >= 0.7:
                    signals["target_bias"] = min(0.18, 0.07 + (ratio - 0.7) * 0.35)
            burst_targets = {item["cp"] for item in self._recent(state, now_ts, 70.0, "out")}
            burst_targets.add(cp)
            if len(burst_targets) >= 3 and len(self._recent(state, now_ts, 70.0, "out")) + 1 >= 4:
                signals["fan_out"] = min(0.26, 0.09 + len(burst_targets) * 0.03)
        if direction == "in":
            burst_sources = {item["cp"] for item in self._recent(state, now_ts, 70.0, "in")}
            burst_sources.add(cp)
            if len(burst_sources) >= 3 and len(self._recent(state, now_ts, 70.0, "in")) + 1 >= 4:
                signals["fan_in"] = min(0.26, 0.09 + len(burst_sources) * 0.03)
        cp_state = self._risk.get(cp)
        if cp_state and (cp_state["risk"] >= 0.32 or cp_state["status"] in {"early", "fraud"}):
            signals["neighbor"] = min(0.22, 0.05 + min(cp_state["risk"], 1.0) * 0.18)
        if device_size >= 3 and (len(recent_short) >= 1 or amount >= baseline * 1.2):
            signals["device"] = min(0.16, 0.04 + min(device_size, 8) * 0.015)
        if is_attack:
            signals["attack"] = 0.58
        strong = bool(is_attack or (sum(1 for key in ("velocity", "high_value", "fan_in", "fan_out", "target_bias", "neighbor") if signals.get(key, 0.0) >= 0.10) >= 3 and sum(signals.values()) >= 0.42))
        return signals, strong

    def _apply_tx(self, aid, cp, now_ts, amount, direction, channel, is_attack):
        if aid not in self._meta:
            return
        state = self._risk[aid]
        self._decay_one(aid, now_ts)
        signals, strong = self._signals(aid, cp, now_ts, amount, direction, is_attack)
        state["recent"].append({"ts": now_ts, "amount": float(amount), "cp": str(cp), "dir": direction, "channel": str(channel), "attack": bool(is_attack)})
        delta = 0.0
        for key, value in signals.items():
            state["signals"][key] = min(1.4, state["signals"].get(key, 0.0) + value)
            delta += value
        if delta > 0:
            state["risk"] = self._clamp_risk(
                state["risk"] + (delta * (1.12 if strong else 1.0)) + random.uniform(-0.004, 0.012)
            )
            self._hot.add(aid)
        if strong:
            state["risk"] = self._clamp_risk(max(state["risk"], 0.92))
            state["fraud_until"] = now_ts + pd.Timedelta(seconds=30)
        state["last"] = now_ts
        self._set_status(aid, now_ts)

    def _ingest(self, tx_df, update_tps=True):
        if tx_df is None or tx_df.empty:
            return
        self._warning_context_cache = None
        self._warning_context_cached_at = 0.0
        frame = tx_df.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.sort_values("timestamp")
        for row in frame.itertuples(index=False):
            sender, receiver = str(getattr(row, "sender", "")), str(getattr(row, "receiver", ""))
            amount = float(getattr(row, "amount", 0) or 0)
            now_ts = self._ts(getattr(row, "timestamp", datetime.now()))
            channel = str(getattr(row, "channel", "TXN"))
            is_attack = bool(getattr(row, "is_attack", False))
            self._amount_ema = (self._amount_ema * 0.94) + (amount * 0.06)
            if sender in self._meta:
                self._apply_tx(sender, receiver, now_ts, amount, "out", channel, is_attack)
            if receiver in self._meta:
                self._apply_tx(receiver, sender, now_ts, amount, "in", channel, is_attack)
            if update_tps:
                self._tx_timestamps.append(time.time())
        self._warning_adjust_credit = min(
            self.WARNING_MAX_CREDIT,
            self._warning_adjust_credit + (len(frame) / self.WARNING_TX_PER_STEP),
        )
        if update_tps:
            now = time.time()
            while self._tx_timestamps and now - self._tx_timestamps[0] > 10:
                self._tx_timestamps.popleft()
            self._tps = len(self._tx_timestamps) / 10.0

    def _rebuild(self, tx_df=None):
        self._risk, self._meta, self._device_sizes = {}, {}, {}
        self._hot.clear()
        self._events.clear()
        self._amount_ema = self.BASELINE_AMOUNT
        self._warning_threshold_ema = 0.0
        self._warning_ids = set()
        self._warning_adjust_credit = 10.0
        self._warning_context_cache = None
        self._warning_context_cached_at = 0.0
        self._tx_timestamps = deque(maxlen=1200)
        self._tps = 0.0
        self._sync_accounts()
        if tx_df is not None and not tx_df.empty:
            self._ingest(tx_df.tail(500), update_tps=False)
        self._sync_flags()

    def _warmup_tx(self, account_id):
        active_ids = [str(value) for value in self.accounts_df[self.accounts_df["is_active"] == True]["account_id"].astype(str).tolist() if str(value) != str(account_id)]
        if not active_ids:
            return pd.DataFrame()
        cp = random.choice(active_ids)
        new_row = self.accounts_df[self.accounts_df["account_id"].astype(str) == str(account_id)].iloc[0]
        cp_row = self.accounts_df[self.accounts_df["account_id"].astype(str) == str(cp)].iloc[0]
        amount = random.randint(900, 5500)
        sender, receiver = (str(account_id), cp) if random.random() < 0.55 else (cp, str(account_id))
        sender_balance = float(self.accounts_df.loc[self.accounts_df["account_id"].astype(str) == sender, "balance"].iloc[0])
        if sender_balance < amount:
            sender, receiver = receiver, sender
        tx_row = new_row if sender == str(account_id) else cp_row
        self.accounts_df.loc[self.accounts_df["account_id"].astype(str) == sender, "balance"] -= amount
        self.accounts_df.loc[self.accounts_df["account_id"].astype(str) == receiver, "balance"] += amount
        return pd.DataFrame([{"transaction_id": f"T{int(time.time() * 1000)}{random.randint(100,999)}", "sender": sender, "receiver": receiver, "amount": amount, "timestamp": datetime.now(), "channel": str(tx_row.get("channel", random.choice(CHANNELS))), "device_id": str(tx_row.get("device_id", "")), "ip_address": str(tx_row.get("ip_address", "")), "is_attack": False}])

    def create_account(self):
        with self.lock:
            if self._acc_counter is None:
                nums = []
                for value in self.accounts_df["account_id"].tolist():
                    try:
                        nums.append(int(str(value).lstrip("A")))
                    except ValueError:
                        pass
                self._acc_counter = max(nums, default=0) + 1
            else:
                self._acc_counter += 1
            account_id = f"A{str(self._acc_counter).zfill(4)}"
            row = {"account_id": account_id, "creation_time": datetime.now(), "device_id": f"D{str(random.randint(1, 50)).zfill(3)}", "ip_address": f"192.168.{random.randint(0,255)}.{random.randint(1,254)}", "balance": random.randint(5000, 50000), "channel": random.choice(CHANNELS), "is_fraud": 0, "is_active": True}
            self.accounts_df = pd.concat([self.accounts_df, pd.DataFrame([row])], ignore_index=True)
            self._sync_accounts()
            warm_tx = self._warmup_tx(account_id)
            if not warm_tx.empty:
                self.transactions_df = self._trim_transactions(pd.concat([self.transactions_df, warm_tx], ignore_index=True))
                self._ingest(warm_tx)
            return account_id

    def step(self):
        if self._attacking:
            return
        with self.lock:
            self._decay_hot(self._ts())
            new_tx = generate_normal_transactions(self.accounts_df, TX_STEP_COUNT)
            if new_tx.empty:
                return
            self.transactions_df = self._trim_transactions(pd.concat([self.transactions_df, new_tx], ignore_index=True))
            self._ingest(new_tx)

    def compute_suspicion_scores(self):
        with self.lock:
            self._decay_hot(self._ts())
            return {aid: round(float(state["risk"]), 4) for aid, state in self._risk.items()}

    def get_suspicion_scores(self):
        return self.compute_suspicion_scores()

    def get_risk_snapshot(self):
        with self.lock:
            self._decay_hot(self._ts())
            warning_context = self._warning_selection_locked()
            warning_ids = warning_context["warning_ids"]
            snapshot = {}
            for aid, state in self._risk.items():
                meta = self._meta.get(aid, {})
                if not meta.get("is_active", True):
                    status = "banned"
                elif state["status"] == "fraud":
                    status = "fraud"
                elif aid in warning_ids:
                    status = "early"
                else:
                    status = "normal"
                breakdown = {key: round(float(value), 4) for key, value in state["signals"].items() if value >= 0.04}
                snapshot[aid] = {"account_id": aid, "risk_score": round(self._clamp_risk(state["risk"]), 4), "status": status, "reasons": list(state["reasons"]), "signal_breakdown": breakdown, "signal_count": len(breakdown), "last_activity": state["last"].isoformat() if state["last"] is not None else None}
            return snapshot

    def get_warning_accounts(self):
        return sorted([value for value in self.get_risk_snapshot().values() if value["status"] in {"early", "fraud"}], key=lambda item: (item["status"] != "fraud", -item["risk_score"]))

    def get_early_warning_accounts(self):
        return sorted([value for value in self.get_risk_snapshot().values() if value["status"] == "early"], key=lambda item: item["risk_score"], reverse=True)

    def get_suspicious_accounts(self, top_pct=None):
        ranked = sorted(self.get_risk_snapshot().values(), key=lambda item: item["risk_score"], reverse=True)
        if top_pct is not None:
            ranked = ranked[: max(1, int(len(ranked) * float(top_pct)))]
        return [item["account_id"] for item in ranked if item["status"] in {"early", "fraud"}]

    def get_warning_summary(self):
        with self.lock:
            self._decay_hot(self._ts())
            context = self._warning_selection_locked()
            return {
                "threshold": context["threshold"],
                "warning_pct": context["warning_pct"],
                "count": len(context["warning_ids"]),
                "max_count": context["max_count"],
            }

    def get_recent_warning_events(self):
        with self.lock:
            return list(self._events)

    def get_early_warning_explainer(self):
        snapshot = self.get_risk_snapshot()
        summary = self.get_warning_summary()
        yellow = sum(1 for value in snapshot.values() if value["status"] == "early")
        red = sum(1 for value in snapshot.values() if value["status"] == "fraud")
        sample = next((event for event in self.get_recent_warning_events() if event["status"] in {"early", "fraud"}), None)
        return {"threshold": round(float(summary["threshold"]), 3), "warning_pct": round(float(summary["warning_pct"]) * 100, 1), "decay_factor": round(float(self.DECAY), 3), "sample_account": sample["account_id"] if sample else "--", "sample_score": round(float(sample["risk_score"]), 3) if sample else 0.52, "steps": [{"title": "Signals activate per transaction", "caption": "Every transfer updates only the sender, receiver, and their local graph neighborhood.", "items": ["New account activity", "Velocity spikes", "High-value transactions", "Fan-in and fan-out behavior"]}, {"title": "Risk score builds continuously", "caption": "Weighted signals stack into a living risk score that changes on every transaction.", "items": sample["reasons"] if sample else ["High transaction velocity", "Connected to a suspicious neighbor", "New account with unusually fast activity"]}, {"title": "Top-ranked risk turns the node yellow", "caption": f"Accounts above the live 90th percentile are capped to roughly the top {round(float(summary['warning_pct']) * 100, 1)}% of active nodes.", "items": [f"Yellow nodes: {yellow}", f"Red nodes: {red}"]}, {"title": "Decay cools risk back toward blue", "caption": f"Every {int(self.DECAY_PERIOD)} seconds the score decays by roughly {self.DECAY}.", "items": ["Fast rise on bursts", "Slow fall on normal behavior", "No full-graph recomputation"]}]}

    def trigger_attack(self, attack_index: int):
        from backend.attacks import attack_registry
        self._attacking = True
        try:
            with self.lock:
                active_ids = self.accounts_df[self.accounts_df["is_active"] == True]["account_id"].astype(str).tolist()
                old_tx_count = len(self.transactions_df)
            if len(active_ids) < ATTACK_POOL_SIZE:
                self._attacking = False
                return None, None
            suspicious = [aid for aid in self.get_suspicious_accounts(top_pct=0.20) if aid in active_ids]
            preferred_count = int(ATTACK_POOL_SIZE * ATTACK_PREFER_SUS_PCT)
            pool = list(suspicious[:preferred_count])
            remaining = [aid for aid in active_ids if aid not in pool]
            if remaining:
                pool.extend(random.sample(remaining, min(ATTACK_POOL_SIZE - len(pool), len(remaining))))
            with self.lock:
                self.accounts_df["is_fraud"] = 0
                accounts_copy = self.accounts_df.copy()
                transactions_copy = self.transactions_df.copy()
            attack_fn = attack_registry[attack_index % len(attack_registry)]
            updated_accounts, updated_transactions, attack_name, attack_time = attack_fn(accounts_copy, transactions_copy, preferred_ids=pool)
            with self.lock:
                self.accounts_df = updated_accounts.reset_index(drop=True)
                self.transactions_df = self._trim_transactions(updated_transactions)
                self.attack_time = pd.Timestamp(attack_time)
                self.last_attack_name = attack_name
                self._sync_accounts()
                delta = self.transactions_df.iloc[old_tx_count:].copy()
                if delta.empty and "is_attack" in self.transactions_df.columns:
                    delta = self.transactions_df[self.transactions_df["is_attack"] == True].tail(40).copy()
                self._ingest(delta)
                self._sync_flags()
            return attack_name, pd.Timestamp(attack_time)
        finally:
            self._attacking = False

    def get_transactions(self):
        with self.lock:
            return self.transactions_df.tail(300).to_dict(orient="records")

    def get_all_transactions(self):
        with self.lock:
            return self.transactions_df.copy()

    def get_accounts(self):
        with self.lock:
            return self.accounts_df.copy()

    def get_fraud_accounts(self):
        with self.lock:
            if "is_fraud" not in self.accounts_df.columns:
                return []
            return self.accounts_df[self.accounts_df["is_fraud"] == 1]["account_id"].astype(str).tolist()

    def get_active_count(self):
        with self.lock:
            return int(self.accounts_df["is_active"].sum()) if "is_active" in self.accounts_df.columns else len(self.accounts_df)

    def get_real_tps(self):
        with self.lock:
            now = time.time()
            while self._tx_timestamps and now - self._tx_timestamps[0] > 1.0:
                self._tx_timestamps.popleft()
            self._tps = float(len(self._tx_timestamps))
            return round(self._tps, 2)

    def ban_accounts(self, account_ids: list):
        ids = [str(value) for value in account_ids]
        with self.lock:
            self.banned_accounts.update(ids)
            target_mask = self.accounts_df["account_id"].astype(str).isin(ids)
            self.accounts_df.loc[target_mask, "is_active"] = False
            if "is_fraud" in self.accounts_df.columns:
                self.accounts_df.loc[target_mask, "is_fraud"] = 0
            self.last_attack_name = None
            self.attack_time = None
            self._sync_accounts()

    def reset_bans(self):
        with self.lock:
            self.banned_accounts.clear()
            if "is_active" in self.accounts_df.columns:
                self.accounts_df["is_active"] = True
            self._sync_accounts()

    def reset_state(self):
        with self.lock:
            self.accounts_df, self.transactions_df = reset_simulation()
            self.attack_time = None
            self.last_attack_name = None
            self._tps = 0.0
            self._acc_counter = None
            self.banned_accounts.clear()
            self._rebuild(self.transactions_df.copy())

    def run(self):
        while True:
            self.step()
            time.sleep(TX_INTERVAL_SEC)

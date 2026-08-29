import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backend.generator import CHANNELS

# START_DATE kept for any external references but NOT used for timestamps
START_DATE = datetime.now() - timedelta(days=30)


def _now_ts(offset_minutes=0):
    """Real current timestamp with optional offset in minutes."""
    return datetime.now() + timedelta(minutes=offset_minutes)


# ── Weighted sampling helpers ───────────────────────────────────────
def _pick_weighted(df, preferred_ids=None, n=1, weight=8.0):
    """
    Sample n rows from df with higher probability for preferred_ids.
    preferred_ids accounts get `weight`x higher chance of being selected.
    Falls back to uniform sampling if preferred_ids is None/empty.
    """
    if df.empty:
        return df
    n = min(n, len(df))
    if preferred_ids and len(preferred_ids) > 0:
        pref_set = set(str(p) for p in preferred_ids)
        weights = df["account_id"].apply(
            lambda x: weight if str(x) in pref_set else 1.0
        ).values.astype(float)
        weights = weights / weights.sum()
        idx = np.random.choice(len(df), size=n, replace=False, p=weights)
        return df.iloc[idx]
    return df.sample(n)


def _pick_single(df, preferred_ids=None, weight=8.0):
    """Pick one row with preference."""
    return _pick_weighted(df, preferred_ids, n=1, weight=weight).iloc[0]


# ── Fan-In Attack ──────────────────────────────────────────────────
def fan_in_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Fan-In Pattern")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 6:
        return accounts_df, transactions_df, "Fan-In Pattern", datetime.now()

    mule_account = _pick_single(active, preferred_ids)
    mule_id      = mule_account["account_id"]
    rest         = active[active["account_id"] != mule_id]
    feeders      = _pick_weighted(rest, preferred_ids, n=min(5, len(rest)), weight=5.0)

    attack_transactions = []
    tx_id    = int(datetime.now().timestamp() * 1000)
    base_time = datetime.now()

    accounts_df = accounts_df.set_index("account_id")

    for _, feeder in feeders.iterrows():
        feeder_id = feeder["account_id"]
        amount    = random.randint(20000, 50000)
        if accounts_df.loc[feeder_id, "balance"] < amount:
            continue
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": feeder_id, "receiver": mule_id,
            "amount": amount,
            "timestamp": base_time + timedelta(minutes=random.randint(0, 5)),
            "channel": random.choice(CHANNELS),
            "device_id": feeder["device_id"],
            "ip_address": feeder["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[feeder_id, "balance"] -= amount
        accounts_df.loc[mule_id,   "balance"] += amount
        tx_id += 1

    # Mule moves out 90%
    others = [a for a in accounts_df.index if a != mule_id]
    if others:
        receiver_id = random.choice(others)
        out_amount  = int(accounts_df.loc[mule_id, "balance"] * 0.9)
        if out_amount > 0:
            attack_transactions.append({
                "transaction_id": f"T{tx_id}",
                "sender": mule_id, "receiver": receiver_id,
                "amount": out_amount,
                "timestamp": base_time + timedelta(minutes=6),
                "channel": random.choice(CHANNELS),
                "device_id": mule_account["device_id"],
                "ip_address": mule_account["ip_address"],
                "is_attack": True,
            })
            accounts_df.loc[mule_id,     "balance"] -= out_amount
            accounts_df.loc[receiver_id, "balance"] += out_amount

    accounts_df.loc[mule_id, "is_fraud"] = 1
    for _, f in feeders.iterrows():
        accounts_df.loc[f["account_id"], "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    attack_df   = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)
    return accounts_df, transactions_df, "Fan-In Pattern", base_time


# ── Fan-Out Attack ─────────────────────────────────────────────────
def fan_out_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Fan-Out Pattern")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 6:
        return accounts_df, transactions_df, "Fan-Out Pattern", datetime.now()

    mule_account = _pick_single(active, preferred_ids)
    mule_id      = mule_account["account_id"]
    rest         = active[active["account_id"] != mule_id]
    recipients   = _pick_weighted(rest, preferred_ids, n=min(5, len(rest)), weight=5.0)

    accounts_df = accounts_df.set_index("account_id")
    accounts_df.loc[mule_id, "balance"] += random.randint(100000, 200000)

    attack_transactions = []
    tx_id     = int(datetime.now().timestamp() * 1000)
    base_time = datetime.now()

    for _, rec in recipients.iterrows():
        rec_id = rec["account_id"]
        amount = random.randint(20000, 50000)
        if accounts_df.loc[mule_id, "balance"] < amount:
            continue
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": mule_id, "receiver": rec_id,
            "amount": amount,
            "timestamp": base_time + timedelta(minutes=random.randint(0, 5)),
            "channel": random.choice(CHANNELS),
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[mule_id, "balance"] -= amount
        accounts_df.loc[rec_id,  "balance"] += amount
        tx_id += 1

    accounts_df.loc[mule_id, "is_fraud"] = 1
    for _, r in recipients.iterrows():
        accounts_df.loc[r["account_id"], "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    attack_df   = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)
    return accounts_df, transactions_df, "Fan-Out Pattern", base_time


# ── Circular Ring ──────────────────────────────────────────────────
def circular_ring_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Circular Ring")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 4:
        return accounts_df, transactions_df, "Circular Ring", datetime.now()

    ring      = _pick_weighted(active, preferred_ids, n=min(4, len(active)), weight=6.0)
    ring_ids  = list(ring["account_id"])
    amount    = random.randint(20000, 40000)
    base_time = datetime.now()

    accounts_df = accounts_df.set_index("account_id")
    for rid in ring_ids:
        if accounts_df.loc[rid, "balance"] < amount:
            accounts_df.loc[rid, "balance"] += amount

    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(len(ring_ids)):
        s = ring_ids[i]; r = ring_ids[(i+1) % len(ring_ids)]
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": s, "receiver": r, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": accounts_df.loc[s, "device_id"],
            "ip_address": accounts_df.loc[s, "ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[s, "balance"] -= amount
        accounts_df.loc[r, "balance"] += amount
        tx_id += 1

    for rid in ring_ids:
        accounts_df.loc[rid, "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Circular Transaction Ring", base_time


# ── Velocity Chain ─────────────────────────────────────────────────
def velocity_chain_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Velocity Chain")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 5:
        return accounts_df, transactions_df, "Velocity Chain", datetime.now()

    chain     = list(_pick_weighted(active, preferred_ids, n=min(5, len(active)), weight=6.0)["account_id"])
    amount    = random.randint(50000, 80000)
    base_time = datetime.now()

    accounts_df = accounts_df.set_index("account_id")
    if accounts_df.loc[chain[0], "balance"] < amount:
        accounts_df.loc[chain[0], "balance"] += amount

    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(len(chain) - 1):
        s = chain[i]; r = chain[i+1]
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": s, "receiver": r, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": accounts_df.loc[s, "device_id"],
            "ip_address": accounts_df.loc[s, "ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[s, "balance"] -= amount
        accounts_df.loc[r, "balance"] += amount
        amount = int(amount * 0.9)
        tx_id += 1

    for cid in chain:
        accounts_df.loc[cid, "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "High-Velocity Transfer Chain", base_time


# ── Cross-Channel Burst ────────────────────────────────────────────
def cross_channel_burst_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Cross-Channel Burst")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 5:
        return accounts_df, transactions_df, "Cross-Channel Burst", datetime.now()

    mule_account = _pick_single(active, preferred_ids)
    mule_id      = mule_account["account_id"]
    rest         = active[active["account_id"] != mule_id]
    recipients   = list(_pick_weighted(rest, preferred_ids, n=min(4, len(rest)), weight=5.0)["account_id"])
    amount       = random.randint(20000, 40000)
    base_time    = datetime.now()

    accounts_df = accounts_df.set_index("account_id")
    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i, rec_id in enumerate(recipients):
        if accounts_df.loc[mule_id, "balance"] < amount:
            break
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": mule_id, "receiver": rec_id, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": CHANNELS[i % len(CHANNELS)],
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[mule_id, "balance"] -= amount
        accounts_df.loc[rec_id,  "balance"] += amount
        tx_id += 1

    accounts_df.loc[mule_id, "is_fraud"] = 1
    for rid in recipients:
        accounts_df.loc[rid, "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Cross-Channel Burst Behavior", base_time


# ── Shared Device Cluster ──────────────────────────────────────────
def shared_device_cluster_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Shared Device Cluster")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 4:
        return accounts_df, transactions_df, "Shared Device Cluster", datetime.now()

    cluster    = list(_pick_weighted(active, preferred_ids, n=min(4, len(active)), weight=6.0)["account_id"])
    shared_dev = "D999"
    base_time  = datetime.now()

    accounts_df = accounts_df.set_index("account_id")
    for cid in cluster:
        accounts_df.loc[cid, "device_id"] = shared_dev

    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(len(cluster)):
        s = cluster[i]; r = cluster[(i+1) % len(cluster)]
        amount = random.randint(15000, 30000)
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": s, "receiver": r, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": shared_dev,
            "ip_address": accounts_df.loc[s, "ip_address"],
            "is_attack": True,
        })
        tx_id += 1

    for cid in cluster:
        accounts_df.loc[cid, "is_fraud"] = 1

    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Shared Device Cluster", base_time


# ── Behavioral Drift ───────────────────────────────────────────────
def behavioral_drift_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Behavioral Drift")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 2:
        return accounts_df, transactions_df, "Behavioral Drift", datetime.now()

    account   = _pick_single(active, preferred_ids)
    acc_id    = account["account_id"]
    base_time = datetime.now()
    others    = [a for a in active["account_id"].tolist() if a != acc_id]

    accounts_df = accounts_df.set_index("account_id")
    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(8):
        if not others: break
        receiver_id = random.choice(others)
        amount      = random.randint(30000, 60000)
        if accounts_df.loc[acc_id, "balance"] < amount:
            break
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": acc_id, "receiver": receiver_id, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": account["device_id"],
            "ip_address": account["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[acc_id,      "balance"] -= amount
        accounts_df.loc[receiver_id, "balance"] += amount
        tx_id += 1

    accounts_df.loc[acc_id, "is_fraud"] = 1
    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Sudden Behavioral Drift", base_time


# ── Early Volume Spike ─────────────────────────────────────────────
def early_volume_spike_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Early Volume Spike")

    # Add a brand-new account to the pool — this attack is always new-account based
    new_id = f"A_NEW_{random.randint(1000,9999)}"
    new_account = pd.DataFrame([{
        "account_id": new_id,
        "creation_time": datetime.now(),
        "device_id": f"D{str(random.randint(1,25)).zfill(3)}",
        "ip_address": f"192.168.{random.randint(0,255)}.{random.randint(1,254)}",
        "balance": 100000, "is_fraud": 1, "is_active": True,
    }])
    accounts_df = pd.concat([accounts_df, new_account], ignore_index=True)
    accounts_df = accounts_df.set_index("account_id")

    # Prefer early-warning accounts as recipients
    active_ids = [a for a in accounts_df.index if a != new_id]
    pref_set   = set(str(p) for p in (preferred_ids or []))
    pref_ids   = [a for a in active_ids if str(a) in pref_set]
    non_pref   = [a for a in active_ids if str(a) not in pref_set]
    # Build weighted receiver list: preferred first, then random fill
    n_pref = min(len(pref_ids), 3)
    n_rand = max(0, 6 - n_pref)
    receivers = (random.sample(pref_ids, n_pref) if pref_ids else []) + \
                (random.sample(non_pref, min(n_rand, len(non_pref))) if non_pref else [])

    base_time  = datetime.now()
    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i, receiver_id in enumerate(receivers[:6]):
        amount = random.randint(20000, 40000)
        if accounts_df.loc[new_id, "balance"] < amount:
            break
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": new_id, "receiver": receiver_id, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": accounts_df.loc[new_id, "device_id"],
            "ip_address": accounts_df.loc[new_id, "ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[new_id,      "balance"] -= amount
        accounts_df.loc[receiver_id, "balance"] += amount
        tx_id += 1

    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Early-Stage Volume Spike", base_time


# ── Smurfing ───────────────────────────────────────────────────────
def smurfing_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Smurfing")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 2:
        return accounts_df, transactions_df, "Smurfing Pattern", datetime.now()

    mule_account = _pick_single(active, preferred_ids)
    mule_id      = mule_account["account_id"]
    others       = active[active["account_id"] != mule_id]
    # Pick receiver preferentially too
    receiver_id  = _pick_single(others, preferred_ids, weight=5.0)["account_id"]
    base_time    = datetime.now()

    accounts_df = accounts_df.set_index("account_id")
    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(15):
        amount = random.randint(2000, 5000)
        if accounts_df.loc[mule_id, "balance"] < amount:
            break
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": mule_id, "receiver": receiver_id, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[mule_id,     "balance"] -= amount
        accounts_df.loc[receiver_id, "balance"] += amount
        tx_id += 1

    accounts_df.loc[mule_id,     "is_fraud"] = 1
    accounts_df.loc[receiver_id, "is_fraud"] = 1
    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Smurfing Pattern", base_time


# ── Dormant Activation ─────────────────────────────────────────────
def dormant_activation_attack(accounts_df, transactions_df, preferred_ids=None):
    print("\n[Attack] Dormant Account Activation")

    active = accounts_df[accounts_df.get("is_active", pd.Series(True, index=accounts_df.index)) != False]
    if len(active) < 2:
        return accounts_df, transactions_df, "Dormant Activation", datetime.now()

    account   = _pick_single(active, preferred_ids)
    acc_id    = account["account_id"]
    base_time = datetime.now()
    others    = [a for a in active["account_id"].tolist() if a != acc_id]

    accounts_df = accounts_df.set_index("account_id")
    attack_transactions = []
    tx_id = int(datetime.now().timestamp() * 1000)

    for i in range(6):
        if not others: break
        receiver_id = random.choice(others)
        amount      = random.randint(40000, 70000)
        if accounts_df.loc[acc_id, "balance"] < amount:
            break
        attack_transactions.append({
            "transaction_id": f"T{tx_id}",
            "sender": acc_id, "receiver": receiver_id, "amount": amount,
            "timestamp": base_time + timedelta(minutes=i),
            "channel": random.choice(CHANNELS),
            "device_id": account["device_id"],
            "ip_address": account["ip_address"],
            "is_attack": True,
        })
        accounts_df.loc[acc_id,      "balance"] -= amount
        accounts_df.loc[receiver_id, "balance"] += amount
        tx_id += 1

    accounts_df.loc[acc_id, "is_fraud"] = 1
    accounts_df = accounts_df.reset_index()
    transactions_df = pd.concat([transactions_df, pd.DataFrame(attack_transactions)], ignore_index=True)
    return accounts_df, transactions_df, "Dormant Account Activation", base_time


# ── Registry ───────────────────────────────────────────────────────
attack_registry = [
    fan_in_attack,
    fan_out_attack,
    circular_ring_attack,
    velocity_chain_attack,
    cross_channel_burst_attack,
    shared_device_cluster_attack,
    behavioral_drift_attack,
    early_volume_spike_attack,
    smurfing_attack,
    dormant_activation_attack,
]

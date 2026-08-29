import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

# -----------------------------
# CONFIG
# -----------------------------
NUM_ACCOUNTS = 1000
START_DATE = datetime(2024, 1, 1)

# -----------------------------
# Generate Accounts
# -----------------------------

def generate_accounts(num_accounts):
    accounts = []

    for i in range(num_accounts):
        account_id = f"A{str(i+1).zfill(4)}"

        # Random account creation date within 1 year
        creation_time = START_DATE + timedelta(days=random.randint(0, 365))

        # Random device ID (some overlap allowed)
        device_id = f"D{random.randint(1, 300)}"

        # Random IP (simple simulation)
        ip_address = f"192.168.{random.randint(0,255)}.{random.randint(1,254)}"

        # Initial balance between 10k to 2 lakh
        balance = random.randint(10000, 200000)

        account = {
            "account_id": account_id,
            "creation_time": creation_time,
            "device_id": device_id,
            "ip_address": ip_address,
            "balance": balance,
            "is_fraud": 0  # initially all normal
        }

        accounts.append(account)

    return pd.DataFrame(accounts)

# -----------------------------
# CONFIG FOR TRANSACTIONS
# -----------------------------

NUM_TRANSACTIONS = 10000
CHANNELS = ["UPI", "App", "ATM", "Web"]

# -----------------------------
# Generate Normal Transactions
# -----------------------------

def generate_normal_transactions(accounts_df, num_transactions):
    transactions = []
    transaction_id_counter = 1

    for _ in range(num_transactions):

        # Random sender and receiver
        sender = accounts_df.sample(1).iloc[0]
        receiver = accounts_df.sample(1).iloc[0]

        # Avoid self-transfer
        if sender["account_id"] == receiver["account_id"]:
            continue

        # Random amount between 500 and 10000
        amount = random.randint(500, 10000)

        # Check if sender has enough balance
        if sender["balance"] < amount:
            continue

        # Random timestamp within 7 days
        timestamp = START_DATE + timedelta(
            days=random.randint(0, 7),
            minutes=random.randint(0, 1440)
        )

        # Random channel
        channel = random.choices(
            CHANNELS,
            weights=[0.4, 0.3, 0.2, 0.1]  # UPI more frequent
        )[0]

        # Create transaction record
        transaction = {
            "transaction_id": f"T{transaction_id_counter}",
            "sender": sender["account_id"],
            "receiver": receiver["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": channel,
            "device_id": sender["device_id"],
            "ip_address": sender["ip_address"]
        }

        transactions.append(transaction)

        # Update balances
        accounts_df.loc[
            accounts_df["account_id"] == sender["account_id"],
            "balance"
        ] -= amount

        accounts_df.loc[
            accounts_df["account_id"] == receiver["account_id"],
            "balance"
        ] += amount

        transaction_id_counter += 1

    return pd.DataFrame(transactions)


# -----------------------------
# Run Generator
# -----------------------------

accounts_df = generate_accounts(NUM_ACCOUNTS)
print("Total Accounts Generated:", len(accounts_df))
print(accounts_df.head())

transactions_df = generate_normal_transactions(accounts_df, NUM_TRANSACTIONS)
print("Total Transactions Generated:", len(transactions_df))
print(transactions_df.head())


# -----------------------------
# Fraud Pattern 1: Fan-In Attack
# -----------------------------

def fan_in_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Fan-In Pattern")

    mule_account = accounts_df.sample(1).iloc[0]
    mule_id = mule_account["account_id"]

    feeders = accounts_df.sample(5)

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=8)

    for i, feeder in feeders.iterrows():

        if feeder["account_id"] == mule_id:
            continue

        amount = random.randint(20000, 50000)

        if feeder["balance"] < amount:
            continue

        timestamp = base_time + timedelta(minutes=random.randint(0, 5))

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": feeder["account_id"],
            "receiver": mule_id,
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": feeder["device_id"],
            "ip_address": feeder["ip_address"]
        }

        attack_transactions.append(transaction)

        # Update balances
        accounts_df.loc[
            accounts_df["account_id"] == feeder["account_id"],
            "balance"
        ] -= amount

        accounts_df.loc[
            accounts_df["account_id"] == mule_id,
            "balance"
        ] += amount

        transaction_id_start += 1

    # Mule moves out 90%
    outgoing_receiver = accounts_df.sample(1).iloc[0]

    mule_balance = accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "balance"
    ].values[0]

    out_amount = int(mule_balance * 0.9)

    timestamp = base_time + timedelta(minutes=6)

    transaction = {
        "transaction_id": f"T{transaction_id_start}",
        "sender": mule_id,
        "receiver": outgoing_receiver["account_id"],
        "amount": out_amount,
        "timestamp": timestamp,
        "channel": random.choice(CHANNELS),
        "device_id": mule_account["device_id"],
        "ip_address": mule_account["ip_address"]
    }

    attack_transactions.append(transaction)

    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "balance"
    ] -= out_amount

    accounts_df.loc[
        accounts_df["account_id"] == outgoing_receiver["account_id"],
        "balance"
    ] += out_amount

    # Mark mule
    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)

    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Fan-In Pattern", base_time

# -----------------------------
# Fraud Pattern 2: Fan-Out Attack
# -----------------------------

def fan_out_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Fan-Out Pattern")

    mule_account = accounts_df.sample(1).iloc[0]
    mule_id = mule_account["account_id"]

    # Give mule some extra balance to distribute
    extra_amount = random.randint(100000, 200000)

    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "balance"
    ] += extra_amount

    recipients = accounts_df.sample(5)

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=9)

    for i, recipient in recipients.iterrows():

        if recipient["account_id"] == mule_id:
            continue

        amount = random.randint(20000, 50000)

        mule_balance = accounts_df.loc[
            accounts_df["account_id"] == mule_id,
            "balance"
        ].values[0]

        if mule_balance < amount:
            continue

        timestamp = base_time + timedelta(minutes=random.randint(0, 5))

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": mule_id,
            "receiver": recipient["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"]
        }

        attack_transactions.append(transaction)

        # Update balances
        accounts_df.loc[
            accounts_df["account_id"] == mule_id,
            "balance"
        ] -= amount

        accounts_df.loc[
            accounts_df["account_id"] == recipient["account_id"],
            "balance"
        ] += amount

        transaction_id_start += 1

    # Mark mule
    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)

    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Fan-Out Pattern", base_time

# -----------------------------
# Fraud Pattern 3: Circular Ring
# -----------------------------

def circular_ring_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Circular Transaction Ring")

    # Select 4 random accounts
    ring_accounts = accounts_df.sample(4)
    ring_ids = list(ring_accounts["account_id"])

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=10)

    amount = random.randint(20000, 40000)

    # Ensure all have enough balance
    for acc_id in ring_ids:
        balance = accounts_df.loc[
            accounts_df["account_id"] == acc_id,
            "balance"
        ].values[0]

        if balance < amount:
            accounts_df.loc[
                accounts_df["account_id"] == acc_id,
                "balance"
            ] += amount

    # Create circular transfers
    for i in range(len(ring_ids)):

        sender = ring_ids[i]
        receiver = ring_ids[(i + 1) % len(ring_ids)]

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": accounts_df.loc[
                accounts_df["account_id"] == sender,
                "device_id"
            ].values[0],
            "ip_address": accounts_df.loc[
                accounts_df["account_id"] == sender,
                "ip_address"
            ].values[0]
        }

        attack_transactions.append(transaction)

        # Update balances
        accounts_df.loc[
            accounts_df["account_id"] == sender,
            "balance"
        ] -= amount

        accounts_df.loc[
            accounts_df["account_id"] == receiver,
            "balance"
        ] += amount

        transaction_id_start += 1

    # Mark all ring accounts as fraud
    accounts_df.loc[
        accounts_df["account_id"].isin(ring_ids),
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)

    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Circular Transaction Ring", base_time

# -----------------------------
# Fraud Pattern 4: High-Velocity Transfer Chain
# -----------------------------

def velocity_chain_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] High-Velocity Transfer Chain")

    chain_accounts = accounts_df.sample(5)
    chain_ids = list(chain_accounts["account_id"])

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=11)

    initial_amount = random.randint(50000, 80000)

    # Ensure first account has enough balance
    first_balance = accounts_df.loc[
        accounts_df["account_id"] == chain_ids[0],
        "balance"
    ].values[0]

    if first_balance < initial_amount:
        accounts_df.loc[
            accounts_df["account_id"] == chain_ids[0],
            "balance"
        ] += initial_amount

    current_amount = initial_amount

    for i in range(len(chain_ids) - 1):

        sender = chain_ids[i]
        receiver = chain_ids[i + 1]

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": sender,
            "receiver": receiver,
            "amount": current_amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": accounts_df.loc[
                accounts_df["account_id"] == sender,
                "device_id"
            ].values[0],
            "ip_address": accounts_df.loc[
                accounts_df["account_id"] == sender,
                "ip_address"
            ].values[0]
        }

        attack_transactions.append(transaction)

        # Update balances
        accounts_df.loc[
            accounts_df["account_id"] == sender,
            "balance"
        ] -= current_amount

        accounts_df.loc[
            accounts_df["account_id"] == receiver,
            "balance"
        ] += current_amount

        # Forward 90%
        current_amount = int(current_amount * 0.9)

        transaction_id_start += 1

    # Mark all chain accounts as fraud
    accounts_df.loc[
        accounts_df["account_id"].isin(chain_ids),
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)

    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "High-Velocity Transfer Chain", base_time

# -----------------------------
# Fraud Pattern 5: Cross-Channel Burst
# -----------------------------

def cross_channel_burst_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Cross-Channel Burst Behavior")

    mule_account = accounts_df.sample(1).iloc[0]
    mule_id = mule_account["account_id"]

    recipients = accounts_df.sample(4)

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=12)

    amount = random.randint(20000, 40000)

    for i, recipient in recipients.iterrows():

        if recipient["account_id"] == mule_id:
            continue

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": mule_id,
            "receiver": recipient["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": CHANNELS[i % len(CHANNELS)],
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"]
        }

        attack_transactions.append(transaction)

        accounts_df.loc[
            accounts_df["account_id"] == mule_id,
            "balance"
        ] -= amount

        accounts_df.loc[
            accounts_df["account_id"] == recipient["account_id"],
            "balance"
        ] += amount

        transaction_id_start += 1

    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Cross-Channel Burst Behavior", base_time


# -----------------------------
# Fraud Pattern 6: Shared Device Cluster
# -----------------------------

def shared_device_cluster_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Shared Device Cluster")

    cluster_accounts = accounts_df.sample(4)
    cluster_ids = list(cluster_accounts["account_id"])

    shared_device = "D9999"

    accounts_df.loc[
        accounts_df["account_id"].isin(cluster_ids),
        "device_id"
    ] = shared_device

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=13)

    for i in range(len(cluster_ids)):

        sender = cluster_ids[i]
        receiver = cluster_ids[(i + 1) % len(cluster_ids)]

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": sender,
            "receiver": receiver,
            "amount": random.randint(15000, 30000),
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": shared_device,
            "ip_address": accounts_df.loc[
                accounts_df["account_id"] == sender,
                "ip_address"
            ].values[0]
        }

        attack_transactions.append(transaction)
        transaction_id_start += 1

    accounts_df.loc[
        accounts_df["account_id"].isin(cluster_ids),
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Shared Device Cluster", base_time

# -----------------------------
# Fraud Pattern 7: Sudden Behavioral Drift
# -----------------------------

def behavioral_drift_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Sudden Behavioral Drift")

    account = accounts_df.sample(1).iloc[0]
    acc_id = account["account_id"]

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1

    # Simulate sudden burst on day 14
    base_time = START_DATE + timedelta(days=14)

    for i in range(8):  # 8 rapid transactions

        receiver = accounts_df.sample(1).iloc[0]

        if receiver["account_id"] == acc_id:
            continue

        amount = random.randint(30000, 60000)

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": acc_id,
            "receiver": receiver["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": account["device_id"],
            "ip_address": account["ip_address"]
        }

        attack_transactions.append(transaction)
        transaction_id_start += 1

    accounts_df.loc[
        accounts_df["account_id"] == acc_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Sudden Behavioral Drift", base_time


# -----------------------------
# Fraud Pattern 8: Early-Stage Volume Spike
# -----------------------------

def early_volume_spike_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Early-Stage Volume Spike")

    # Create brand new account
    new_account_id = f"A_NEW_{random.randint(1000,9999)}"

    new_account = {
        "account_id": new_account_id,
        "creation_time": START_DATE + timedelta(days=15),
        "device_id": f"D{random.randint(1, 300)}",
        "ip_address": f"192.168.{random.randint(0,255)}.{random.randint(1,254)}",
        "balance": 100000,
        "is_fraud": 1
    }

    accounts_df = pd.concat(
        [accounts_df, pd.DataFrame([new_account])],
        ignore_index=True
    )

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=15)

    for i in range(6):

        receiver = accounts_df.sample(1).iloc[0]

        if receiver["account_id"] == new_account_id:
            continue

        amount = random.randint(20000, 40000)

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": new_account_id,
            "receiver": receiver["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": new_account["device_id"],
            "ip_address": new_account["ip_address"]
        }

        attack_transactions.append(transaction)
        transaction_id_start += 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Early-Stage Volume Spike", base_time

# -----------------------------
# Fraud Pattern 9: Smurfing (Structuring)
# -----------------------------

def smurfing_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Smurfing Pattern")

    mule_account = accounts_df.sample(1).iloc[0]
    mule_id = mule_account["account_id"]

    receiver = accounts_df.sample(1).iloc[0]

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1
    base_time = START_DATE + timedelta(days=16)

    # 15 small rapid transactions
    for i in range(15):

        amount = random.randint(2000, 5000)

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": mule_id,
            "receiver": receiver["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": mule_account["device_id"],
            "ip_address": mule_account["ip_address"]
        }

        attack_transactions.append(transaction)
        transaction_id_start += 1

    accounts_df.loc[
        accounts_df["account_id"] == mule_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Smurfing Pattern", base_time

# -----------------------------
# Fraud Pattern 10: Dormant Account Activation
# -----------------------------

def dormant_activation_attack(accounts_df, transactions_df):

    print("\n[Attack Injected] Dormant Account Activation")

    account = accounts_df.sample(1).iloc[0]
    acc_id = account["account_id"]

    attack_transactions = []
    transaction_id_start = len(transactions_df) + 1

    # Simulate inactivity gap (Day 20)
    base_time = START_DATE + timedelta(days=20)

    for i in range(6):

        receiver = accounts_df.sample(1).iloc[0]

        if receiver["account_id"] == acc_id:
            continue

        amount = random.randint(40000, 70000)

        timestamp = base_time + timedelta(minutes=i)

        transaction = {
            "transaction_id": f"T{transaction_id_start}",
            "sender": acc_id,
            "receiver": receiver["account_id"],
            "amount": amount,
            "timestamp": timestamp,
            "channel": random.choice(CHANNELS),
            "device_id": account["device_id"],
            "ip_address": account["ip_address"]
        }

        attack_transactions.append(transaction)
        transaction_id_start += 1

    accounts_df.loc[
        accounts_df["account_id"] == acc_id,
        "is_fraud"
    ] = 1

    attack_df = pd.DataFrame(attack_transactions)
    transactions_df = pd.concat([transactions_df, attack_df], ignore_index=True)

    return accounts_df, transactions_df, "Dormant Account Activation", base_time


# -----------------------------
# Build Transaction Graph
# -----------------------------

import networkx as nx
import matplotlib.pyplot as plt

def build_transaction_graph(accounts_df, transactions_df):

    G = nx.DiGraph()

    # Add nodes (accounts)
    for _, row in accounts_df.iterrows():
        G.add_node(
            row["account_id"],
            is_fraud=row["is_fraud"]
        )

    # Add edges (transactions)
    for _, tx in transactions_df.iterrows():
        G.add_edge(
            tx["sender"],
            tx["receiver"],
            amount=tx["amount"],
            timestamp=tx["timestamp"]
        )

    return G


# -----------------------------
# Visualize Graph
# -----------------------------

def visualize_fraud_subgraph(G):

    fraud_nodes = [n for n in G.nodes if G.nodes[n]["is_fraud"] == 1]

    if not fraud_nodes:
        return None

    nodes_to_draw = set(fraud_nodes)

    for fraud in fraud_nodes:
        nodes_to_draw.update(G.predecessors(fraud))
        nodes_to_draw.update(G.successors(fraud))

    subG = G.subgraph(nodes_to_draw)

    fig, ax = plt.subplots(figsize=(6, 4))
    pos = nx.spring_layout(subG, seed=42)

    node_colors = []
    for node in subG.nodes():
        if subG.nodes[node]["is_fraud"] == 1:
            node_colors.append("red")
        else:
            node_colors.append("skyblue")

    nx.draw(
        subG,
        pos,
        ax=ax,
        with_labels=True,
        node_size=800,
        node_color=node_colors,
        edge_color="gray",
        font_size=8
    )
    return fig


# -----------------------------
# Feature Engineering
# -----------------------------

def extract_node_features(accounts_df, transactions_df, G):

    feature_data = []

    for node in G.nodes():

        in_degree = G.in_degree(node)
        out_degree = G.out_degree(node)

        incoming_edges = G.in_edges(node, data=True)
        outgoing_edges = G.out_edges(node, data=True)

        total_in_amount = sum(edge[2]["amount"] for edge in incoming_edges)
        total_out_amount = sum(edge[2]["amount"] for edge in outgoing_edges)

        # Retention ratio
        if total_in_amount > 0:
            retention_ratio = (total_in_amount - total_out_amount) / total_in_amount
        else:
            retention_ratio = 0

        # Unique neighbors
        neighbors = set([edge[1] for edge in outgoing_edges] +
                        [edge[0] for edge in incoming_edges])
        unique_neighbors = len(neighbors)

        # Unique channels
        node_transactions = transactions_df[
            (transactions_df["sender"] == node) |
            (transactions_df["receiver"] == node)
        ]
        unique_channels = node_transactions["channel"].nunique()

        # Device cluster size
        device_id = accounts_df.loc[
            accounts_df["account_id"] == node,
            "device_id"
        ].values[0]

        device_cluster_size = accounts_df[
            accounts_df["device_id"] == device_id
        ].shape[0]

        # Transaction count
        transaction_count = node_transactions.shape[0]

        feature_data.append({
            "account_id": node,
            "in_degree": in_degree,
            "out_degree": out_degree,
            "total_in_amount": total_in_amount,
            "total_out_amount": total_out_amount,
            "retention_ratio": retention_ratio,
            "unique_neighbors": unique_neighbors,
            "unique_channels": unique_channels,
            "device_cluster_size": device_cluster_size,
            "transaction_count": transaction_count,
            "is_fraud": accounts_df.loc[
                accounts_df["account_id"] == node,
                "is_fraud"
            ].values[0]
        })

    features_df = pd.DataFrame(feature_data)

    return features_df

# -----------------------------
# Rule-Based Fraud Detection
# -----------------------------

def rule_based_detection(features_df):

    risk_results = []

    for _, row in features_df.iterrows():

        score = 0
        reasons = []

        # Fan-In
        if row["in_degree"] >= 2:
            score += 2
            reasons.append("High In-Degree")

        # Fan-Out
        if row["out_degree"] >= 2:
            score += 2
            reasons.append("High Out-Degree")

        # Money Passing Through
        if row["retention_ratio"] < 0.2 and row["total_in_amount"] > 0:
            score += 2
            reasons.append("Low Retention Ratio")

        # Shared Device
        if row["device_cluster_size"] > 2:
            score += 3
            reasons.append("Shared Device Cluster")

        # Channel Burst
        if row["unique_channels"] > 2:
            score += 2
            reasons.append("High Channel Diversity")

        # High Transaction Volume
        if row["transaction_count"] >= 3:
            score += 1
            reasons.append("High Transaction Count")

        risk_results.append({
            "account_id": row["account_id"],
            "risk_score": score,
            "reasons": reasons,
            "is_fraud": row["is_fraud"]
        })

    return pd.DataFrame(risk_results)

# -----------------------------
# ML-Based Fraud Detection
# -----------------------------

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

def ml_detection(features_df):

    feature_columns = [
        "in_degree",
        "out_degree",
        "total_in_amount",
        "total_out_amount",
        "retention_ratio",
        "unique_neighbors",
        "unique_channels",
        "device_cluster_size",
        "transaction_count"
    ]

    X = features_df[feature_columns]
    y = features_df["is_fraud"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42
    )

    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42
    )

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    print("\nML Model Performance:")
    print(confusion_matrix(y_test, y_pred))
    print(classification_report(y_test, y_pred))

    return model

# -----------------------------
# ML Prediction (Inference)
# -----------------------------

def ml_predict(model, features_df):

    feature_columns = [
        "in_degree",
        "out_degree",
        "total_in_amount",
        "total_out_amount",
        "retention_ratio",
        "unique_neighbors",
        "unique_channels",
        "device_cluster_size",
        "transaction_count"
    ]

    X = features_df[feature_columns]

    probabilities = model.predict_proba(X)[:, 1]

    results = features_df[["account_id", "is_fraud"]].copy()
    results["prediction_score"] = probabilities
    results["predicted_label"] = (probabilities > 0.5).astype(int)

    return results



# -----------------------------
# Attack Registry
# -----------------------------

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
    dormant_activation_attack
]

current_attack_index = 0

# -----------------------------
# Reset Simulation Environment
# -----------------------------

def reset_simulation():
    accounts_df = generate_accounts(NUM_ACCOUNTS)
    transactions_df = generate_normal_transactions(accounts_df, NUM_TRANSACTIONS)
    return accounts_df, transactions_df

# -----------------------------
# Coordinated Attack Controller
# -----------------------------


def simulate_coordinated_attack():
    global current_attack_index

    if current_attack_index < len(attack_registry):

        # Step 1: Reset environment
        accounts_df, transactions_df = reset_simulation()

        # Step 2: Inject selected attack
        attack_function = attack_registry[current_attack_index]

        accounts_df, transactions_df, attack_name, attack_time = attack_function(
            accounts_df, transactions_df
        )

        print(f"\nAttack Executed: {attack_name}")

        current_attack_index += 1

        return accounts_df, transactions_df, attack_time, attack_name

    else:
        print("\nAll attack patterns have been executed.")
        return None, None, None, None

# -----------------------------
# Multi-Run Dataset Builder
# -----------------------------

def build_multi_run_dataset(num_runs=20):

    all_features = []

    global current_attack_index

    current_attack_index = 0  # Reset attack sequence

    for i in range(num_runs):

        print(f"\n--- Simulation Run {i+1} ---")

        # Reset simulation
        accounts_df, transactions_df = reset_simulation()

        # Choose attack sequentially (cycle if needed)
        attack_function = attack_registry[current_attack_index % len(attack_registry)]

        accounts_df, transactions_df, attack_name, attack_time = attack_function(
            accounts_df, transactions_df
        )

        print(f"Injected: {attack_name}")

        # Filter attack transactions only
        attack_transactions = transactions_df[
            transactions_df["timestamp"] >= attack_time
        ]

        # Build graph
        G = build_transaction_graph(accounts_df, attack_transactions)

        # Extract features
        features_df = extract_node_features(accounts_df, attack_transactions, G)

        all_features.append(features_df)

        current_attack_index += 1

    # Combine all runs
    final_dataset = pd.concat(all_features, ignore_index=True)

    return final_dataset





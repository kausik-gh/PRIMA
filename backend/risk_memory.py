import networkx as nx
import numpy as np

# Global memory storage
fraud_memory = []

# ---------------------------------
# Extract structural signature
# ---------------------------------
def extract_cluster_signature(G, features_df):

    fraud_nodes = [
        n for n in G.nodes
        if G.nodes[n]["is_fraud"] == 1
    ]

    if not fraud_nodes:
        return None

    subG = G.subgraph(fraud_nodes)

    avg_in = np.mean([
        features_df.loc[
            features_df["account_id"] == n,
            "in_degree"
        ].values[0] for n in fraud_nodes
    ])

    avg_out = np.mean([
        features_df.loc[
            features_df["account_id"] == n,
            "out_degree"
        ].values[0] for n in fraud_nodes
    ])

    avg_retention = np.mean([
        features_df.loc[
            features_df["account_id"] == n,
            "retention_ratio"
        ].values[0] for n in fraud_nodes
    ])

    density = nx.density(subG)

    signature = {
        "node_count": len(fraud_nodes),
        "avg_in_degree": avg_in,
        "avg_out_degree": avg_out,
        "avg_retention": avg_retention,
        "density": density
    }

    return signature


# ---------------------------------
# Store signature
# ---------------------------------
def store_signature(signature):
    if signature:
        fraud_memory.append(signature)


# ---------------------------------
# Compare with memory
# ---------------------------------
def compare_signature(new_signature):

    if not fraud_memory:
        return 0

    similarities = []

    for past in fraud_memory:

        diff = 0

        for key in past:
            # ✅ Normalized difference
            denom = abs(past[key]) + 1e-6
            diff += abs(past[key] - new_signature[key]) / denom

        similarity = np.exp(-diff)
        similarities.append(similarity)

    return max(similarities)
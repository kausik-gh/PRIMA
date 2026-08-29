"""
backend/gnn.py
--------------
Graph Attention Network (GAT) layer for the Money Mule Detection System.

Architecture: 2-layer GAT
  Layer 1: 10 input features → 32 hidden units, 4 attention heads
  Layer 2: 128 units         → 1 output (fraud probability), 1 head

Exposes:
  gnn_predict(G, features_df, model_path) → DataFrame[account_id, gnn_score]

Integrates into detection.py ml_predict() as a 3rd signal:
  final_score = 0.5 * ml_score + 0.3 * rule_score_norm + 0.2 * gnn_score
"""

import torch
import torch.nn.functional as F
import numpy as np
import pandas as pd
import networkx as nx

# ---------------------------------------------------------------------------
# Graceful PyG import — clear error message if not installed
# ---------------------------------------------------------------------------
try:
    from torch_geometric.data import Data
    from torch_geometric.nn import GATConv
except ImportError:
    raise ImportError(
        "PyTorch Geometric is required for the GNN layer.\n"
        "Install with:\n"
        "  pip install torch-geometric\n"
        "See https://pytorch-geometric.readthedocs.io for CUDA-specific builds."
    )

# ---------------------------------------------------------------------------
# Feature columns — all 10 (includes account_age_days unlike RF training)
# ---------------------------------------------------------------------------
GNN_FEATURE_COLUMNS = [
    "in_degree",
    "out_degree",
    "total_in_amount",
    "total_out_amount",
    "retention_ratio",
    "unique_neighbors",
    "unique_channels",
    "device_cluster_size",
    "transaction_count",
    "account_age_days",
]

# ---------------------------------------------------------------------------
# GAT Model Definition
# ---------------------------------------------------------------------------

class FraudGAT(torch.nn.Module):
    """
    2-layer Graph Attention Network for node-level fraud classification.

    Layer 1: GATConv(10 → 32, heads=4, concat=True)  → 128-dim per node
    Layer 2: GATConv(128 → 1,  heads=1, concat=False) → scalar per node

    Output: sigmoid-activated fraud probability per node.
    """

    def __init__(
        self,
        in_channels: int = 10,
        hidden_channels: int = 32,
        heads: int = 4,
        dropout: float = 0.3,
    ):
        super().__init__()

        self.dropout = dropout

        # Layer 1 — multi-head attention, concatenate heads
        self.conv1 = GATConv(
            in_channels=in_channels,
            out_channels=hidden_channels,
            heads=heads,
            dropout=dropout,
            concat=True,           # output dim = hidden_channels * heads = 128
        )

        # Layer 2 — single head, no concat → scalar logit
        self.conv2 = GATConv(
            in_channels=hidden_channels * heads,
            out_channels=1,
            heads=1,
            dropout=dropout,
            concat=False,
        )

    def forward(self, x, edge_index):
        # Layer 1
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.conv1(x, edge_index)
        x = F.elu(x)

        # Layer 2
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.conv2(x, edge_index)

        # Sigmoid → probability in [0, 1]
        return torch.sigmoid(x).squeeze(-1)


# ---------------------------------------------------------------------------
# Helper: NetworkX DiGraph → PyG Data object
# ---------------------------------------------------------------------------

def graph_to_pyg(G: nx.DiGraph, features_df: pd.DataFrame) -> Data:
    """
    Convert a NetworkX DiGraph + features_df into a PyG Data object.

    Node ordering follows G.nodes() iteration order.
    Edges are bidirectional (original + reversed) so each node aggregates
    from both upstream senders and downstream receivers — essential for
    detecting Entry→Collector→Distributor→Exit chains.

    Args:
        G:           NetworkX DiGraph from build_transaction_graph()
        features_df: DataFrame from extract_node_features(), contains
                     GNN_FEATURE_COLUMNS + 'account_id' + optionally 'is_fraud'

    Returns:
        PyG Data object with:
            x           — node feature matrix [N, 10]
            edge_index  — bidirectional COO edge index [2, 2E]
            y           — fraud labels [N] (float, 0/1), if present
            node_ids    — list of account_ids in node order
    """

    nodes = list(G.nodes())
    node_index = {node: i for i, node in enumerate(nodes)}

    # -----------------------------------------------------------------------
    # Node feature matrix — normalise per feature across this graph snapshot
    # -----------------------------------------------------------------------
    feat_lookup = features_df.set_index("account_id")

    raw = []
    for node in nodes:
        if node in feat_lookup.index:
            row = feat_lookup.loc[node]
            raw.append([float(row.get(col, 0.0)) for col in GNN_FEATURE_COLUMNS])
        else:
            raw.append([0.0] * len(GNN_FEATURE_COLUMNS))

    x_np = np.array(raw, dtype=np.float32)

    # Min-max normalisation per feature (safe: avoid div-by-zero)
    col_min = x_np.min(axis=0)
    col_max = x_np.max(axis=0)
    col_range = np.where(col_max - col_min == 0, 1.0, col_max - col_min)
    x_np = (x_np - col_min) / col_range

    x = torch.tensor(x_np, dtype=torch.float)

    # -----------------------------------------------------------------------
    # Edge index — bidirectional
    # -----------------------------------------------------------------------
    src, dst = [], []
    for u, v in G.edges():
        if u in node_index and v in node_index:
            i, j = node_index[u], node_index[v]
            src.append(i);  dst.append(j)   # original direction
            src.append(j);  dst.append(i)   # reverse direction

    if src:
        edge_index = torch.tensor([src, dst], dtype=torch.long)
    else:
        # Isolated graph — no edges
        edge_index = torch.zeros((2, 0), dtype=torch.long)

    # -----------------------------------------------------------------------
    # Labels (optional — present during training, absent at inference)
    # -----------------------------------------------------------------------
    data = Data(x=x, edge_index=edge_index)
    data.node_ids = nodes

    if "is_fraud" in feat_lookup.columns:
        labels = []
        for node in nodes:
            if node in feat_lookup.index:
                labels.append(float(feat_lookup.loc[node, "is_fraud"]))
            else:
                labels.append(0.0)
        data.y = torch.tensor(labels, dtype=torch.float)

    return data


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def gnn_predict(
    G: nx.DiGraph,
    features_df: pd.DataFrame,
    model_path: str = "gnn_model.pth",
    device: str = "cpu",
) -> pd.DataFrame:
    """
    Run GAT inference on a transaction graph snapshot.

    Args:
        G:           NetworkX DiGraph (from build_transaction_graph)
        features_df: DataFrame (from extract_node_features)
        model_path:  path to saved gnn_model.pth
        device:      'cpu' or 'cuda'

    Returns:
        DataFrame with columns ['account_id', 'gnn_score']
        gnn_score is a float in [0, 1] — fraud probability from the GAT.
        Returns zeros for all nodes if model file is not found (graceful degradation).
    """

    import os
    if not os.path.exists(model_path):
        # Graceful degradation — GNN not trained yet, return neutral scores
        return pd.DataFrame({
            "account_id": list(G.nodes()),
            "gnn_score": [0.0] * G.number_of_nodes()
        })

    # Build PyG data object
    data = graph_to_pyg(G, features_df)

    # Load model
    model = FraudGAT(in_channels=len(GNN_FEATURE_COLUMNS))
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    data = data.to(device)

    with torch.no_grad():
        scores = model(data.x, data.edge_index).cpu().numpy()

    return pd.DataFrame({
        "account_id": data.node_ids,
        "gnn_score": scores.tolist()
    })

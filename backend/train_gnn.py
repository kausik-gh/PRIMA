"""
backend/train_gnn.py
--------------------
Training script for the GAT fraud detection layer.

Mirrors the existing train_model.py pattern:
  1. Calls build_multi_run_dataset() to generate simulation data
  2. Builds PyG Data objects per simulation run
  3. Trains FraudGAT with focal loss (handles class imbalance)
  4. Saves model to gnn_model.pth

Usage:
    python -m backend.train_gnn

Output:
    gnn_model.pth   (saved to project root, same as fraud_model.pkl)
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import torch
import torch.nn.functional as F
import numpy as np
from torch_geometric.data import Data

from backend.simulation import reset_simulation
from backend.attacks import attack_registry
from backend.features import build_transaction_graph, extract_node_features
from backend.gnn import FraudGAT, graph_to_pyg, GNN_FEATURE_COLUMNS

# ---------------------------------------------------------------------------
# Focal Loss — handles severe class imbalance (fraud accounts are minority)
# Standard BCE loss lets the model ignore minority class.
# Focal loss down-weights easy negatives and focuses on hard fraud examples.
# ---------------------------------------------------------------------------

def focal_loss(pred: torch.Tensor, target: torch.Tensor, gamma: float = 2.0, alpha: float = 0.8):
    """
    Binary focal loss.

    alpha: weight for positive (fraud) class — set high because fraud is rare
    gamma: focusing parameter — higher = more focus on hard examples
    """
    bce = F.binary_cross_entropy(pred, target, reduction="none")
    p_t = torch.where(target == 1, pred, 1 - pred)
    focal_weight = alpha * (1 - p_t) ** gamma
    return (focal_weight * bce).mean()


# ---------------------------------------------------------------------------
# Build PyG dataset from simulation runs
# ---------------------------------------------------------------------------

def build_gnn_dataset(num_runs: int = 40):
    """
    Generate PyG Data objects across multiple simulation runs.

    Each run:
      - Resets simulation
      - Injects a different attack pattern (cycles through attack_registry)
      - Builds transaction graph
      - Extracts node features
      - Converts to PyG Data object with labels

    Args:
        num_runs: number of simulation runs (more = better generalisation)
                  40 runs × ~50 nodes = ~2000 training nodes

    Returns:
        list of PyG Data objects, one per simulation run
    """

    dataset = []
    attack_index = 0
    fraud_total = 0
    normal_total = 0

    print(f"Building GNN dataset: {num_runs} simulation runs...")

    for run in range(num_runs):

        accounts_df, transactions_df = reset_simulation()

        attack_fn = attack_registry[attack_index % len(attack_registry)]
        accounts_df, transactions_df, attack_name, attack_time = attack_fn(
            accounts_df, transactions_df
        )

        # Use only attack-window transactions (same as training.py)
        attack_transactions = transactions_df[
            transactions_df["timestamp"] >= attack_time
        ]

        G = build_transaction_graph(accounts_df, attack_transactions)

        if G.number_of_nodes() == 0:
            attack_index += 1
            continue

        features_df = extract_node_features(accounts_df, attack_transactions, G)

        # Attach fraud label from accounts_df
        account_labels = accounts_df.set_index("account_id")["is_fraud"].to_dict()
        features_df["is_fraud"] = features_df["account_id"].map(account_labels).fillna(0)

        data = graph_to_pyg(G, features_df)

        # Skip graphs with no edges (uninformative for GAT)
        if data.edge_index.shape[1] == 0:
            attack_index += 1
            continue

        dataset.append(data)

        # Track class balance for reporting
        fraud_total += int(data.y.sum().item())
        normal_total += int((data.y == 0).sum().item())

        if (run + 1) % 10 == 0:
            print(f"  Run {run+1}/{num_runs} — attack: {attack_name}")

        attack_index += 1

    print(f"\nDataset built: {len(dataset)} graphs")
    print(f"  Fraud nodes : {fraud_total}")
    print(f"  Normal nodes: {normal_total}")
    print(f"  Fraud ratio : {fraud_total / max(fraud_total + normal_total, 1):.3f}")

    return dataset


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train_gnn(
    num_runs: int = 40,
    epochs: int = 100,
    lr: float = 1e-3,
    save_path: str = "gnn_model.pth",
    device: str = "cpu",
):
    """
    Train the FraudGAT model and save weights.

    Training strategy:
      - Iterate over all simulation graphs each epoch (full dataset pass)
      - Focal loss for class imbalance
      - Adam optimiser with weight decay (L2 regularisation)
      - Early stopping: save best model by validation loss

    Args:
        num_runs:  number of simulation runs to generate training data
        epochs:    training epochs
        lr:        learning rate
        save_path: output path for saved model weights
        device:    'cpu' or 'cuda'
    """

    print("=" * 55)
    print("  GNN Training — FraudGAT (Graph Attention Network)")
    print("=" * 55)

    # Build dataset
    dataset = build_gnn_dataset(num_runs=num_runs)

    if not dataset:
        print("ERROR: No training graphs generated. Check simulation setup.")
        return

    # Train/val split — 80/20
    split = int(0.8 * len(dataset))
    train_data = dataset[:split]
    val_data = dataset[split:] if split < len(dataset) else dataset[:5]

    print(f"\nTrain graphs: {len(train_data)} | Val graphs: {len(val_data)}")

    # Initialise model
    model = FraudGAT(in_channels=len(GNN_FEATURE_COLUMNS)).to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.StepLR(optimiser, step_size=30, gamma=0.5)

    best_val_loss = float("inf")
    best_state = None

    print(f"\nTraining for {epochs} epochs...\n")

    for epoch in range(1, epochs + 1):

        # ---------------------------------------------------------------
        # Training phase
        # ---------------------------------------------------------------
        model.train()
        train_loss_total = 0.0

        for data in train_data:
            data = data.to(device)
            optimiser.zero_grad()

            pred = model(data.x, data.edge_index)
            loss = focal_loss(pred, data.y)

            loss.backward()
            optimiser.step()
            train_loss_total += loss.item()

        scheduler.step()

        # ---------------------------------------------------------------
        # Validation phase
        # ---------------------------------------------------------------
        model.eval()
        val_loss_total = 0.0

        all_preds = []
        all_labels = []

        with torch.no_grad():
            for data in val_data:
                data = data.to(device)
                pred = model(data.x, data.edge_index)
                loss = focal_loss(pred, data.y)
                val_loss_total += loss.item()

                all_preds.append(pred.cpu())
                all_labels.append(data.y.cpu())

        avg_train = train_loss_total / len(train_data)
        avg_val = val_loss_total / len(val_data)

        # ---------------------------------------------------------------
        # Save best model
        # ---------------------------------------------------------------
        if avg_val < best_val_loss:
            best_val_loss = avg_val
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

        # ---------------------------------------------------------------
        # Progress reporting every 10 epochs
        # ---------------------------------------------------------------
        if epoch % 10 == 0 or epoch == 1:

            # Quick AUC-like metric: % fraud nodes in top predictions
            preds_cat = torch.cat(all_preds)
            labels_cat = torch.cat(all_labels)
            threshold = 0.5
            predicted = (preds_cat >= threshold).float()
            correct = (predicted == labels_cat).float().mean().item()

            print(
                f"Epoch {epoch:>3}/{epochs} | "
                f"Train Loss: {avg_train:.4f} | "
                f"Val Loss: {avg_val:.4f} | "
                f"Val Acc: {correct:.3f}"
            )

    # -----------------------------------------------------------------------
    # Save best weights
    # -----------------------------------------------------------------------
    if best_state is not None:
        torch.save(best_state, save_path)
        print(f"\n✅ Best GNN model saved → {save_path}")
        print(f"   Best val loss: {best_val_loss:.4f}")
    else:
        torch.save(model.state_dict(), save_path)
        print(f"\n✅ GNN model saved → {save_path}")

    # -----------------------------------------------------------------------
    # Final evaluation on full dataset
    # -----------------------------------------------------------------------
    print("\n--- Final Evaluation (full dataset) ---")

    model.load_state_dict(best_state or model.state_dict())
    model.eval()

    all_preds, all_labels = [], []
    with torch.no_grad():
        for data in dataset:
            data = data.to(device)
            pred = model(data.x, data.edge_index)
            all_preds.append(pred.cpu())
            all_labels.append(data.y.cpu())

    preds_cat = torch.cat(all_preds).numpy()
    labels_cat = torch.cat(all_labels).numpy()

    for thresh in [0.3, 0.4, 0.5]:
        predicted = (preds_cat >= thresh).astype(int)
        tp = ((predicted == 1) & (labels_cat == 1)).sum()
        fp = ((predicted == 1) & (labels_cat == 0)).sum()
        fn = ((predicted == 0) & (labels_cat == 1)).sum()
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-6)
        print(f"  Thresh {thresh} | P: {precision:.3f} | R: {recall:.3f} | F1: {f1:.3f}")

    return model


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    train_gnn(
        num_runs=40,
        epochs=100,
        lr=1e-3,
        save_path="gnn_model.pth",
        device="cpu",
    )

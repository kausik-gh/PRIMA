from pathlib import Path
import logging
import os
import subprocess
import threading
import warnings

import joblib
import pandas as pd
import torch

from backend.detection import load_explainer
from backend.gnn import FraudGAT, GNN_FEATURE_COLUMNS, graph_to_pyg

BASE_DIR = Path(__file__).resolve().parent.parent
RF_MODEL_PATH = BASE_DIR / "fraud_model.pkl"
GNN_MODEL_PATH = BASE_DIR / "gnn_model.pth"
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

logger = logging.getLogger(__name__)


class ModelRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.device = torch.device("cuda:0")
        self.rf_model = None
        self.explainer = None
        self.gnn_model = None
        self.loaded = False

    def load(self):
        with self.lock:
            if self.loaded:
                return

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is required but not available. Ensure NVIDIA RTX 4060 drivers/CUDA are installed.")

            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = "0"
            torch.backends.cudnn.benchmark = True
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.set_float32_matmul_precision("high")
            logger.info("ModelRuntime device=%s", self.device)
            try:
                logger.info("CUDA available=%s", torch.cuda.is_available())
                logger.info("CUDA device=%s", torch.cuda.get_device_name(0))
                logger.info("CUDA device count=%s", torch.cuda.device_count())
            except Exception:
                logger.info("CUDA device=unavailable")

            self.rf_model = joblib.load(RF_MODEL_PATH)
            self.rf_model.feature_list = getattr(
                self.rf_model, "feature_list", DEFAULT_FEATURES
            )
            try:
                self.explainer = load_explainer(self.rf_model)
            except Exception:
                self.explainer = None

            if GNN_MODEL_PATH.exists():
                self.gnn_model = FraudGAT(in_channels=len(GNN_FEATURE_COLUMNS)).to(self.device)
                state_dict = self._load_gnn_state_dict()
                self.gnn_model.load_state_dict(state_dict)
                self.gnn_model.eval()
                logger.info(
                    "GNN parameter device=%s",
                    next(self.gnn_model.parameters()).device,
                )
            else:
                self.gnn_model = None
                logger.warning("Missing GNN model at %s", GNN_MODEL_PATH)

            try:
                nvidia_smi = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=3,
                ).strip()
                logger.info("nvidia-smi: %s", nvidia_smi)
            except Exception:
                logger.info("nvidia-smi unavailable")

            self.loaded = True

    def get_rf_model(self):
        self.load()
        return self.rf_model

    def get_explainer(self):
        self.load()
        return self.explainer

    def _load_gnn_state_dict(self):
        load_kwargs = {"map_location": self.device}
        try:
            state_dict = torch.load(GNN_MODEL_PATH, weights_only=True, **load_kwargs)
        except TypeError:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="You are using `torch.load` with `weights_only=False`",
                    category=FutureWarning,
                )
                state_dict = torch.load(GNN_MODEL_PATH, **load_kwargs)

        if isinstance(state_dict, dict) and "state_dict" in state_dict and isinstance(state_dict["state_dict"], dict):
            return state_dict["state_dict"]
        return state_dict

    def gnn_predict(self, graph, features_df: pd.DataFrame) -> pd.DataFrame:
        self.load()
        if self.gnn_model is None:
            return pd.DataFrame(
                {
                    "account_id": list(graph.nodes()),
                    "gnn_score": [0.0] * graph.number_of_nodes(),
                }
            )

        data = graph_to_pyg(graph, features_df).to(self.device)
        use_amp = True
        with torch.inference_mode():
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                scores = self.gnn_model(data.x, data.edge_index)
            scores_cpu = scores.float().detach().cpu().tolist()

        return pd.DataFrame(
            {
                "account_id": data.node_ids,
                "gnn_score": scores_cpu,
            }
        )


model_runtime = ModelRuntime()

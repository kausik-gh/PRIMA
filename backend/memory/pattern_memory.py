"""Attack-shape similarity: cluster stats plus trail and context overlap."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Known category names only. Phrases never stored.
_ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {"urgency", "secrecy", "fear", "greed", "bypass_approval"}
)

_NUMERIC_KEYS: tuple[str, ...] = (
    "node_count",
    "avg_in_degree",
    "avg_out_degree",
    "avg_retention",
    "density",
)

_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "node_count": ("node_count", "n_nodes", "size"),
    "avg_in_degree": ("avg_in_degree", "in_degree"),
    "avg_out_degree": ("avg_out_degree", "out_degree"),
    "avg_retention": ("avg_retention", "retention_ratio"),
    "density": ("density",),
}

_EPS = 1e-6


@dataclass(frozen=True)
class PatternSignature:
    label: str | None
    node_count: int
    avg_in_degree: float
    avg_out_degree: float
    avg_retention: float
    density: float
    trail_shape: list[str]
    context_categories: list[str]


def extract_cluster_signature(
    graph_stats: Mapping[str, Any] | None,
    *,
    trail_shape: Sequence[str] | None = None,
    context_categories: Sequence[str] | None = None,
    label: str | None = None,
) -> PatternSignature:
    """Build a signature from precomputed cluster stats. Pure; no I/O."""
    stats = graph_stats if isinstance(graph_stats, Mapping) else {}
    return PatternSignature(
        label=str(label) if label is not None else None,
        node_count=int(_stat(stats, "node_count")),
        avg_in_degree=float(_stat(stats, "avg_in_degree")),
        avg_out_degree=float(_stat(stats, "avg_out_degree")),
        avg_retention=float(_stat(stats, "avg_retention")),
        density=float(_stat(stats, "density")),
        trail_shape=_copy_steps(trail_shape),
        context_categories=_copy_categories(context_categories),
    )


def compare_signature(a: PatternSignature, b: PatternSignature) -> float:
    """Similarity in [0, 1].

    Formula (legacy spirit: exp of minus normalised absolute diffs, plus overlap):
        numeric_diff = sum_k |a_k - b_k| / (|a_k| + 1e-6)
            for k in {node_count, avg_in_degree, avg_out_degree, avg_retention, density}
        trail_diff = 1 - Jaccard(trail_shape)
        context_diff = 1 - Jaccard(context_categories)
        similarity = exp(-(numeric_diff + trail_diff + context_diff))
    Empty vs empty token sets count as Jaccard 1 (no extra penalty).
    """
    numeric_diff = 0.0
    for key in _NUMERIC_KEYS:
        left = float(getattr(a, key))
        right = float(getattr(b, key))
        numeric_diff += abs(left - right) / (abs(left) + _EPS)
    trail_diff = 1.0 - _jaccard(a.trail_shape, b.trail_shape)
    context_diff = 1.0 - _jaccard(a.context_categories, b.context_categories)
    similarity = math.exp(-(numeric_diff + trail_diff + context_diff))
    return min(max(similarity, 0.0), 1.0)


class PatternMemory:
    """In-memory store. Empty until add(); nothing is persisted."""

    def __init__(self) -> None:
        self._items: dict[str, PatternSignature] = {}
        self._order: list[str] = []

    def add(self, signature: PatternSignature, *, signature_id: str | None = None) -> str:
        stored = _copy_signature(signature)
        sid = signature_id or uuid.uuid4().hex
        if sid not in self._items:
            self._order.append(sid)
        self._items[sid] = stored
        return sid

    def best_match(
        self, signature: PatternSignature, *, min_similarity: float = 0.5
    ) -> dict[str, Any] | None:
        if not self._items:
            return None
        best_id: str | None = None
        best_sim = -1.0
        for sid, stored in self._items.items():
            sim = compare_signature(signature, stored)
            if sim > best_sim:
                best_sim = sim
                best_id = sid
        if best_id is None or best_sim < min_similarity:
            return None
        stored = self._items[best_id]
        return {
            "signature_id": best_id,
            "label": stored.label,
            "similarity": best_sim,
        }

    def list_signatures(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid in self._order:
            stored = self._items[sid]
            out.append(
                {
                    "signature_id": sid,
                    "label": stored.label,
                    "node_count": stored.node_count,
                    "trail_shape": list(stored.trail_shape),
                    "context_categories": list(stored.context_categories),
                }
            )
        return out


def pattern_match_for_decision(
    *,
    ringwatch_stats: Mapping[str, Any] | None = None,
    trail_steps: Sequence[str] | None = None,
    context_categories: Sequence[str] | None = None,
    memory: PatternMemory,
    min_similarity: float = 0.5,
) -> dict[str, Any] | None:
    """Investigate payload: {similarity, label} or None."""
    signature = extract_cluster_signature(
        ringwatch_stats,
        trail_shape=trail_steps,
        context_categories=context_categories,
    )
    match = memory.best_match(signature, min_similarity=min_similarity)
    if match is None:
        return None
    return {"similarity": match["similarity"], "label": match["label"]}


def _stat(stats: Mapping[str, Any], canonical: str) -> float:
    for key in _STAT_ALIASES[canonical]:
        if key in stats and stats[key] is not None:
            return float(stats[key])
    return 0.0


def _copy_steps(steps: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for item in steps or ():
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _copy_categories(categories: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for item in categories or ():
        name = str(item).strip()
        if name in _ALLOWED_CATEGORIES and name not in out:
            out.append(name)
    return out


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _copy_signature(signature: PatternSignature) -> PatternSignature:
    return PatternSignature(
        label=signature.label,
        node_count=int(signature.node_count),
        avg_in_degree=float(signature.avg_in_degree),
        avg_out_degree=float(signature.avg_out_degree),
        avg_retention=float(signature.avg_retention),
        density=float(signature.density),
        trail_shape=list(signature.trail_shape),
        context_categories=list(signature.context_categories),
    )

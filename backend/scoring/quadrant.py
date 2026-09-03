"""2×2 quadrant: beneficiary network risk × sender state risk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_BENEFICIARY_THRESHOLD = 0.30
DEFAULT_SENDER_TRAIL_MIN = 0.45
DEFAULT_SENDER_CONTEXT_MIN = 0.30

Q_LOW_LOW = "low_sender_low_beneficiary"
Q_LOW_HIGH = "low_sender_high_beneficiary"
Q_HIGH_LOW = "high_sender_low_beneficiary"
Q_HIGH_HIGH = "high_sender_high_beneficiary"

PRODUCT_CELL_ID = Q_HIGH_LOW

_LABELS: dict[str, str] = {
    Q_LOW_LOW: "Ordinary",
    Q_LOW_HIGH: "Known-history payee, ordinary sender",
    Q_HIGH_LOW: "Sender state high, payee history low",
    Q_HIGH_HIGH: "Both sides elevated",
}

_DETAILS: dict[str, str] = {
    Q_LOW_LOW: (
        "Sender state and beneficiary network scores are both below the panel thresholds."
    ),
    Q_LOW_HIGH: (
        "Beneficiary network score is at or above threshold while sender state is not."
    ),
    Q_HIGH_LOW: (
        "Sender state is elevated while beneficiary network history is still low."
    ),
    Q_HIGH_HIGH: (
        "Sender state and beneficiary network scores are both at or above threshold."
    ),
}

_PANEL_KEYS: tuple[str, ...] = (
    "decision_id",
    "quadrant_id",
    "is_product_cell",
    "sender_high",
    "beneficiary_high",
    "sender_score",
    "beneficiary_score",
    "fused_score",
    "tier",
    "verdict",
    "cross_term_applied",
    "label",
    "detail",
)


@dataclass(frozen=True)
class QuadrantResult:
    quadrant_id: str
    sender_high: bool
    beneficiary_high: bool
    sender_score: float
    beneficiary_score: float
    is_product_cell: bool
    label: str
    detail: str
    fired_rules: list[dict[str, Any]]


def classify_quadrant(
    *,
    ringwatch: float,
    trailscore: float,
    contextflag: float,
    fused_score: float | None = None,
    cross_term_applied: bool = False,
    config: Mapping[str, Any] | None = None,
) -> QuadrantResult:
    """Classify one decision onto the sender × beneficiary 2×2. Pure; no I/O.

    ``fused_score`` is accepted for callers and is not used to pick the cell.
    When ``cross_term_applied`` is True, the result is the product cell
    (high sender state, low beneficiary history).
    """
    del fused_score
    ringwatch = _clamp01(ringwatch)
    trailscore = _clamp01(trailscore)
    contextflag = _clamp01(contextflag)
    beneficiary_threshold, sender_trail_min, sender_context_min = _resolve_config(config)

    sender_score = _clamp01(max(trailscore, contextflag))
    beneficiary_score = ringwatch

    if cross_term_applied:
        sender_high = True
        beneficiary_high = False
    else:
        sender_high = trailscore >= sender_trail_min or contextflag >= sender_context_min
        beneficiary_high = ringwatch >= beneficiary_threshold

    quadrant_id = _quadrant_id(sender_high, beneficiary_high)
    is_product_cell = quadrant_id == PRODUCT_CELL_ID
    label = _LABELS[quadrant_id]
    detail = _DETAILS[quadrant_id]
    fired_rules = [
        {
            "code": quadrant_id,
            "points": 1.0 if is_product_cell else 0.0,
            "detail": detail,
        }
    ]
    return QuadrantResult(
        quadrant_id=quadrant_id,
        sender_high=sender_high,
        beneficiary_high=beneficiary_high,
        sender_score=sender_score,
        beneficiary_score=beneficiary_score,
        is_product_cell=is_product_cell,
        label=label,
        detail=detail,
        fired_rules=fired_rules,
    )


def build_quadrant_panel_item(
    *,
    decision_id: str,
    ringwatch: float,
    trailscore: float,
    contextflag: float,
    fused_score: float,
    tier: int,
    verdict: str,
    cross_term_applied: bool = False,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-serializable console quadrant-panel row. No probe or ground-truth fields."""
    classified = classify_quadrant(
        ringwatch=ringwatch,
        trailscore=trailscore,
        contextflag=contextflag,
        fused_score=fused_score,
        cross_term_applied=cross_term_applied,
        config=config,
    )
    item = {
        "decision_id": str(decision_id),
        "quadrant_id": classified.quadrant_id,
        "is_product_cell": classified.is_product_cell,
        "sender_high": classified.sender_high,
        "beneficiary_high": classified.beneficiary_high,
        "sender_score": classified.sender_score,
        "beneficiary_score": classified.beneficiary_score,
        "fused_score": _clamp01(fused_score),
        "tier": int(tier),
        "verdict": str(verdict),
        "cross_term_applied": bool(cross_term_applied),
        "label": classified.label,
        "detail": classified.detail,
    }
    return {key: item[key] for key in _PANEL_KEYS}


def _quadrant_id(sender_high: bool, beneficiary_high: bool) -> str:
    if sender_high and not beneficiary_high:
        return Q_HIGH_LOW
    if sender_high and beneficiary_high:
        return Q_HIGH_HIGH
    if (not sender_high) and beneficiary_high:
        return Q_LOW_HIGH
    return Q_LOW_LOW


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _resolve_config(
    config: Mapping[str, Any] | None,
) -> tuple[float, float, float]:
    section: Mapping[str, Any] = {}
    if isinstance(config, Mapping):
        raw = config.get("quadrant")
        if isinstance(raw, Mapping):
            section = raw
    return (
        float(section.get("beneficiary_threshold", DEFAULT_BENEFICIARY_THRESHOLD)),
        float(section.get("sender_trail_min", DEFAULT_SENDER_TRAIL_MIN)),
        float(section.get("sender_context_min", DEFAULT_SENDER_CONTEXT_MIN)),
    )

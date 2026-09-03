"""Fuse RingWatch, TrailScore, and ContextFlag into one score in [0, 1]."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

DEFAULT_RINGWATCH_WEIGHT = 0.40
DEFAULT_TRAILSCORE_WEIGHT = 0.35
DEFAULT_CONTEXTFLAG_WEIGHT = 0.25

DEFAULT_CROSS_TERM_ENABLED = True
DEFAULT_CROSS_TERM_TRAIL_MIN = 0.45
DEFAULT_CROSS_TERM_RING_MAX = 0.30
DEFAULT_CROSS_TERM_BONUS = 0.15
CROSS_TERM_REASON_CODE = "SENDER_STATE_ANOMALOUS_FRESH_PAYEE"
CROSS_TERM_DETAIL = (
    "Sender sequence risk is high while the beneficiary network score is still low."
)


@dataclass(frozen=True)
class FusionResult:
    fused_score: float
    base: float
    cross_term_bonus: float
    cross_term_applied: bool
    reason_code: str | None
    contributions: list[dict[str, Any]]
    fired_rules: list[dict[str, Any]]
    ringwatch: float
    trailscore: float
    contextflag: float


def fuse(
    ringwatch: float,
    trailscore: float,
    contextflag: float,
    *,
    config: Mapping[str, Any] | None = None,
    ringwatch_rules: Sequence[Mapping[str, Any]] | None = None,
    trailscore_rules: Sequence[Mapping[str, Any]] | None = None,
    contextflag_rules: Sequence[Mapping[str, Any]] | None = None,
) -> FusionResult:
    """Weighted sum plus optional sender-state cross term. Pure; no I/O.

    All three inputs are clamped to [0, 1]. Scores without reasons are a bug:
    at least the contributing sub-scores' rules, and the cross-term rule when
    it fires, are returned in ``fired_rules``.
    """
    ringwatch = _clamp01(ringwatch)
    trailscore = _clamp01(trailscore)
    contextflag = _clamp01(contextflag)
    weights, cross = _resolve_config(config)

    contributions = [
        _contribution("ringwatch", weights["ringwatch"], ringwatch),
        _contribution("trailscore", weights["trailscore"], trailscore),
        _contribution("contextflag", weights["contextflag"], contextflag),
    ]
    base = sum(item["contribution"] for item in contributions)

    cross_term_bonus = 0.0
    cross_term_applied = False
    reason_code: str | None = None
    if (
        cross["enabled"]
        and trailscore >= cross["trail_min"]
        and ringwatch < cross["ring_max"]
    ):
        cross_term_bonus = float(cross["bonus"])
        cross_term_applied = True
        reason_code = CROSS_TERM_REASON_CODE

    fused_score = min(max(base + cross_term_bonus, 0.0), 1.0)

    fired_rules: list[dict[str, Any]] = []
    fired_rules.extend(_copy_rules(ringwatch_rules))
    fired_rules.extend(_copy_rules(trailscore_rules))
    fired_rules.extend(_copy_rules(contextflag_rules))
    if cross_term_applied:
        fired_rules.append(
            {
                "code": CROSS_TERM_REASON_CODE,
                "points": cross_term_bonus,
                "detail": CROSS_TERM_DETAIL,
            }
        )

    if fused_score > 0.0 and not fired_rules:
        fired_rules.append(
            {
                "code": "fusion_base",
                "points": fused_score,
                "detail": "Fused from sub-scores with no upstream rules supplied.",
            }
        )

    return FusionResult(
        fused_score=fused_score,
        base=base,
        cross_term_bonus=cross_term_bonus if cross_term_applied else 0.0,
        cross_term_applied=cross_term_applied,
        reason_code=reason_code,
        contributions=contributions,
        fired_rules=fired_rules,
        ringwatch=ringwatch,
        trailscore=trailscore,
        contextflag=contextflag,
    )


def _contribution(scorer: str, weight: float, value: float) -> dict[str, Any]:
    return {
        "scorer": scorer,
        "weight": weight,
        "value": value,
        "contribution": weight * value,
    }


def _copy_rules(
    rules: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not rules:
        return []
    copied: list[dict[str, Any]] = []
    for rule in rules:
        copied.append(
            {
                "code": rule["code"],
                "points": rule["points"],
                "detail": rule["detail"],
            }
        )
    return copied


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _resolve_config(
    config: Mapping[str, Any] | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    section: Mapping[str, Any] = {}
    if isinstance(config, Mapping):
        raw = config.get("fusion")
        if isinstance(raw, Mapping):
            section = raw

    weights = {
        "ringwatch": float(section.get("ringwatch_weight", DEFAULT_RINGWATCH_WEIGHT)),
        "trailscore": float(section.get("trailscore_weight", DEFAULT_TRAILSCORE_WEIGHT)),
        "contextflag": float(section.get("contextflag_weight", DEFAULT_CONTEXTFLAG_WEIGHT)),
    }

    raw_cross = section.get("cross_term")
    cross_section: Mapping[str, Any] = raw_cross if isinstance(raw_cross, Mapping) else {}
    cross = {
        "enabled": bool(cross_section.get("enabled", DEFAULT_CROSS_TERM_ENABLED)),
        "trail_min": float(cross_section.get("trail_min", DEFAULT_CROSS_TERM_TRAIL_MIN)),
        "ring_max": float(cross_section.get("ring_max", DEFAULT_CROSS_TERM_RING_MAX)),
        "bonus": float(cross_section.get("bonus", DEFAULT_CROSS_TERM_BONUS)),
    }
    return weights, cross

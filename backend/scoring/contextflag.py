"""Context scorer: lexicon/regex matches on note + call_context. No spans in the result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.context.lexicon import match_categories

DEFAULT_WEIGHTS: dict[str, float] = {
    "urgency": 0.25,
    "secrecy": 0.30,
    "fear": 0.30,
    "greed": 0.15,
    "bypass_approval": 0.30,
}


@dataclass(frozen=True)
class ContextFlagResult:
    score: float
    categories: list[dict[str, Any]]
    fired_rules: list[dict[str, Any]]


def contextflag_score(
    note: str | None = None,
    call_context: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> ContextFlagResult:
    """Score concatenated note and call_context. Public result has no matched substring."""
    weights = _resolve_weights(config)
    combined = f"{note or ''} {call_context or ''}"
    matched = match_categories(combined)

    categories: list[dict[str, Any]] = []
    fired_rules: list[dict[str, Any]] = []
    raw = 0.0
    for category in matched:
        points = float(weights[category])
        raw += points
        categories.append({"category": category, "weight": points})
        fired_rules.append(
            {
                "code": category,
                "points": points,
                "detail": (
                    f"Category {category} matched in the combined note and call context."
                ),
            }
        )

    score = min(max(raw, 0.0), 1.0)
    if score > 0.0 and not fired_rules:
        raise RuntimeError("score produced without fired_rules")

    return ContextFlagResult(
        score=score,
        categories=categories,
        fired_rules=fired_rules,
    )


def _resolve_weights(config: Mapping[str, Any] | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if not isinstance(config, Mapping):
        return weights
    section = config.get("contextflag")
    if not isinstance(section, Mapping):
        return weights
    provided = section.get("weights")
    if not isinstance(provided, Mapping):
        return weights
    for key, value in provided.items():
        if key in weights:
            weights[key] = float(value)
    return weights

"""Interrupt Ladder: fused score → tier 0..4, action, and payer verdict."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Bands are [min, max): fused < max maps to that tier. Last band catches 1.0.
DEFAULT_BANDS: tuple[tuple[int, float, str], ...] = (
    (0, 0.15, "pass_silent"),
    (1, 0.40, "inline_reason"),
    (2, 0.60, "purpose_challenge"),
    (3, 0.80, "scoped_hold_cooling"),
    (4, 1.01, "scoped_hold_plus_circuit_breaker"),
)

DEFAULT_IMMEDIATE_PAISE = 100
DEFAULT_COOLING_MINUTES = 30

VERDICT_NO_HISTORY = "no_history"
VERDICT_WATCH = "watch"
VERDICT_SUSPICIOUS = "suspicious"
VERDICT_HIGH_RISK = "high_risk"
VERDICT_KNOWN = "known"


@dataclass(frozen=True)
class LadderResult:
    tier: int
    action: str
    fused_score: float
    verdict: str
    prior_successful_payment: bool
    immediate_paise: int | None
    held_hint: bool
    cooling_minutes: int | None
    fired_rules: list[dict[str, Any]]


def ladder_decide(
    fused_score: float,
    *,
    prior_successful_payment: bool = False,
    config: Mapping[str, Any] | None = None,
    fusion_rules: Sequence[Mapping[str, Any]] | None = None,
) -> LadderResult:
    """Map fused score to tier, action, and verdict. Pure; no I/O.

    A prior successful payment to this payee is verdict ``known`` and tier 0,
    regardless of fused score. This function does not mutate balances or open
    holds; it only returns hints for later action modules.
    """
    fused_score = min(max(float(fused_score), 0.0), 1.0)
    bands, immediate_paise, cooling_minutes = _resolve_config(config)

    if prior_successful_payment:
        tier = 0
        action = "pass_silent"
        verdict = VERDICT_KNOWN
        rule_detail = "Payer has at least one prior successful payment to this payee."
        code = "prior_successful_payment"
    else:
        tier, action = _tier_for(fused_score, bands)
        verdict = _verdict_for(fused_score)
        rule_detail = f"Fused score {fused_score:.4f} maps to tier {tier} ({action})."
        code = f"tier_{tier}"

    hold_tiers = {3, 4}
    fired_rules: list[dict[str, Any]] = []
    if fusion_rules:
        for rule in fusion_rules:
            fired_rules.append(
                {
                    "code": rule["code"],
                    "points": rule["points"],
                    "detail": rule["detail"],
                }
            )
    fired_rules.append(
        {
            "code": code,
            "points": fused_score,
            "detail": rule_detail,
        }
    )

    return LadderResult(
        tier=tier,
        action=action,
        fused_score=fused_score,
        verdict=verdict,
        prior_successful_payment=prior_successful_payment,
        immediate_paise=immediate_paise if tier in hold_tiers else None,
        held_hint=tier in hold_tiers,
        cooling_minutes=cooling_minutes if tier in hold_tiers else None,
        fired_rules=fired_rules,
    )


def _tier_for(
    fused_score: float, bands: Sequence[tuple[int, float, str]]
) -> tuple[int, str]:
    for tier, max_score, action in bands:
        if fused_score < max_score:
            return tier, action
    last_tier, _, last_action = bands[-1]
    return last_tier, last_action


def _verdict_for(fused_score: float) -> str:
    if fused_score < 0.15:
        return VERDICT_NO_HISTORY
    if fused_score < 0.40:
        return VERDICT_WATCH
    if fused_score < 0.70:
        return VERDICT_SUSPICIOUS
    return VERDICT_HIGH_RISK


def _resolve_config(
    config: Mapping[str, Any] | None,
) -> tuple[tuple[tuple[int, float, str], ...], int, int]:
    bands = DEFAULT_BANDS
    immediate_paise = DEFAULT_IMMEDIATE_PAISE
    cooling_minutes = DEFAULT_COOLING_MINUTES

    if not isinstance(config, Mapping):
        return bands, immediate_paise, cooling_minutes

    raw_ladder = config.get("ladder")
    if isinstance(raw_ladder, Sequence) and not isinstance(raw_ladder, (str, bytes)):
        parsed: list[tuple[int, float, str]] = []
        for row in raw_ladder:
            if not isinstance(row, Mapping):
                continue
            parsed.append(
                (int(row["tier"]), float(row["max"]), str(row["action"]))
            )
        if parsed:
            parsed.sort(key=lambda item: item[0])
            bands = tuple(parsed)

    hold = config.get("scoped_hold")
    if isinstance(hold, Mapping):
        if "immediate_paise" in hold:
            immediate_paise = int(hold["immediate_paise"])
        if "cooling_minutes" in hold:
            cooling_minutes = int(hold["cooling_minutes"])

    return bands, immediate_paise, cooling_minutes

"""Pure scoring orchestrator: TrailScore → ContextFlag → fuse → ladder → probe → quadrant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.memory.pattern_memory import pattern_match_for_decision
from backend.scoring.comprehension_probe import build_comprehension_probe
from backend.scoring.contextflag import contextflag_score
from backend.scoring.fusion import fuse
from backend.scoring.ladder import ladder_decide
from backend.scoring.quadrant import build_quadrant_panel_item, classify_quadrant
from backend.scoring.trailscore import trailscore_score


@dataclass(frozen=True)
class ScoringPipelineResult:
    trailscore: float
    contextflag: float
    ringwatch: float
    fused_score: float
    cross_term_applied: bool
    cross_term_bonus: float
    tier: int
    verdict: str
    action: str
    trail_result: Any
    context_result: Any
    fusion_result: Any
    ladder_result: Any
    probe: Any | None
    quadrant: Any
    quadrant_panel_item: dict
    pattern_match: dict | None
    fired_rules: list[dict]
    immediate_paise: int | None
    cooling_minutes: int | None


def evaluate_sender_context(
    *,
    events: Iterable[Any] | None,
    note: str | None = None,
    call_context: str | None = None,
    amount_paise: int | None = None,
    available_balance_paise: int | None = None,
    now: datetime | None = None,
    ringwatch: float,
    ringwatch_rules: Sequence[Mapping[str, Any]] | None = None,
    prior_successful_payment: bool = False,
    decision_id: str = "preview",
    facts: Sequence[str] | None = None,
    config: Mapping[str, Any] | None = None,
    pattern_memory: Any | None = None,
    ringwatch_stats: Mapping[str, Any] | None = None,
    include_transfer_attempted: bool = True,
    probe_rng_seed: int | None = None,
) -> ScoringPipelineResult:
    """Run P2 scorers in locked order. Pure; no I/O.

    RingWatch is an input from the network scorer. Facts are caller-supplied;
    this function does not generate ReasonLine copy.
    """
    trail = trailscore_score(
        events,
        now=now,
        amount_paise=amount_paise,
        available_balance_paise=available_balance_paise,
        include_transfer_attempted=include_transfer_attempted,
        config=config,
    )
    context = contextflag_score(note=note, call_context=call_context, config=config)
    fused = fuse(
        ringwatch,
        trail.score,
        context.score,
        config=config,
        ringwatch_rules=ringwatch_rules,
        trailscore_rules=trail.fired_rules,
        contextflag_rules=context.fired_rules,
    )
    ladder = ladder_decide(
        fused.fused_score,
        prior_successful_payment=prior_successful_payment,
        config=config,
        fusion_rules=fused.fired_rules,
    )
    facts_for_probe: list[str] = list(facts) if facts is not None else []
    probe = build_comprehension_probe(
        verdict=ladder.verdict,
        tier=ladder.tier,
        facts=facts_for_probe,
        fused_score=fused.fused_score,
        rng_seed=probe_rng_seed,
    )
    quadrant = classify_quadrant(
        ringwatch=fused.ringwatch,
        trailscore=trail.score,
        contextflag=context.score,
        fused_score=fused.fused_score,
        cross_term_applied=fused.cross_term_applied,
        config=config,
    )
    panel = build_quadrant_panel_item(
        decision_id=decision_id,
        ringwatch=fused.ringwatch,
        trailscore=trail.score,
        contextflag=context.score,
        fused_score=fused.fused_score,
        tier=ladder.tier,
        verdict=ladder.verdict,
        cross_term_applied=fused.cross_term_applied,
        config=config,
    )
    match = None
    if pattern_memory is not None:
        match = pattern_match_for_decision(
            ringwatch_stats=ringwatch_stats,
            trail_steps=trail.steps_present,
            context_categories=[item["category"] for item in context.categories],
            memory=pattern_memory,
        )

    return ScoringPipelineResult(
        trailscore=trail.score,
        contextflag=context.score,
        ringwatch=fused.ringwatch,
        fused_score=fused.fused_score,
        cross_term_applied=fused.cross_term_applied,
        cross_term_bonus=fused.cross_term_bonus,
        tier=ladder.tier,
        verdict=ladder.verdict,
        action=ladder.action,
        trail_result=trail,
        context_result=context,
        fusion_result=fused,
        ladder_result=ladder,
        probe=probe,
        quadrant=quadrant,
        quadrant_panel_item=dict(panel),
        pattern_match=match,
        fired_rules=list(ladder.fired_rules),
        immediate_paise=ladder.immediate_paise,
        cooling_minutes=ladder.cooling_minutes,
    )

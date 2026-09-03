from backend.scoring.fusion import fuse
from backend.scoring.ladder import ladder_decide


def test_tier_boundaries_exclusive_max():
    assert ladder_decide(0.0).tier == 0
    assert ladder_decide(0.1499).tier == 0
    assert ladder_decide(0.15).tier == 1
    assert ladder_decide(0.3999).tier == 1
    assert ladder_decide(0.40).tier == 2
    assert ladder_decide(0.5999).tier == 2
    assert ladder_decide(0.60).tier == 3
    assert ladder_decide(0.7999).tier == 3
    assert ladder_decide(0.80).tier == 4
    assert ladder_decide(1.0).tier == 4


def test_actions_match_spec():
    assert ladder_decide(0.0).action == "pass_silent"
    assert ladder_decide(0.20).action == "inline_reason"
    assert ladder_decide(0.50).action == "purpose_challenge"
    assert ladder_decide(0.70).action == "scoped_hold_cooling"
    assert ladder_decide(0.90).action == "scoped_hold_plus_circuit_breaker"


def test_verdict_bands():
    assert ladder_decide(0.0).verdict == "no_history"
    assert ladder_decide(0.15).verdict == "watch"
    assert ladder_decide(0.40).verdict == "suspicious"
    split = ladder_decide(0.65)
    assert split.verdict == "suspicious"
    assert split.tier == 3
    assert ladder_decide(0.70).verdict == "high_risk"


def test_prior_payment_forces_known_tier_zero():
    result = ladder_decide(0.95, prior_successful_payment=True)
    assert result.tier == 0
    assert result.verdict == "known"
    assert result.action == "pass_silent"
    assert result.held_hint is False
    assert result.immediate_paise is None


def test_hold_hints_only_on_tier_3_and_4():
    low = ladder_decide(0.20)
    assert low.held_hint is False
    assert low.immediate_paise is None
    assert low.cooling_minutes is None
    high = ladder_decide(0.85)
    assert high.held_hint is True
    assert high.immediate_paise == 100
    assert high.cooling_minutes == 30


def test_act3_fused_lands_tier_4():
    fused = fuse(0.20, 1.0, 1.0)
    result = ladder_decide(fused.fused_score, fusion_rules=fused.fired_rules)
    assert result.tier == 4
    assert result.verdict == "high_risk"
    assert result.action == "scoped_hold_plus_circuit_breaker"
    assert result.fired_rules


def test_quiet_payment_is_tier_zero():
    fused = fuse(0.05, 0.0, 0.0)
    result = ladder_decide(fused.fused_score)
    assert result.tier == 0
    assert result.verdict == "no_history"

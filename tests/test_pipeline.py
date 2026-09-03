from datetime import datetime, timedelta, timezone

from backend.context.lexicon import categories, sample_text_for_categories
from backend.memory.pattern_memory import PatternMemory, extract_cluster_signature
from backend.scoring.pipeline import evaluate_sender_context

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

_PANEL_KEYS = {
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
}

_ACT3_FACTS = (
    "This account was opened 6 days ago.",
    "14 different people have sent it money today.",
)


def _event(event_type: str, minutes_ago: float) -> dict:
    return {
        "event_type": event_type,
        "ts": _NOW - timedelta(minutes=minutes_ago),
    }


def _ordered_chain() -> list[dict]:
    return [
        _event("login_new_device", 8),
        _event("credential_changed", 6),
        _event("payee_added", 4),
        _event("limit_raised", 2),
    ]


def test_quiet_path_is_tier_zero():
    result = evaluate_sender_context(
        events=[],
        ringwatch=0.05,
        now=_NOW,
        include_transfer_attempted=False,
    )
    assert result.tier == 0
    assert result.verdict == "no_history"
    assert result.probe is None
    assert result.quadrant.is_product_cell is False
    assert result.fused_score < 0.15
    assert result.cross_term_applied is False


def test_act3_path_reaches_high_tier_and_product_cell():
    call_context = sample_text_for_categories(list(categories()))
    result = evaluate_sender_context(
        events=_ordered_chain(),
        call_context=call_context,
        ringwatch=0.20,
        now=_NOW,
        amount_paise=40000000,
        available_balance_paise=40000000,
        facts=_ACT3_FACTS,
        decision_id="d_act3",
        probe_rng_seed=3,
        include_transfer_attempted=True,
    )
    assert result.trailscore >= 0.75
    assert result.cross_term_applied is True
    assert result.fused_score >= 0.80
    assert result.tier >= 3
    assert result.probe is not None
    assert len(result.probe.options) == 3
    assert result.quadrant.is_product_cell is True
    assert result.quadrant_panel_item["is_product_cell"] is True


def test_prior_payment_forces_known_tier_zero():
    call_context = sample_text_for_categories(list(categories()))
    result = evaluate_sender_context(
        events=_ordered_chain(),
        call_context=call_context,
        ringwatch=0.20,
        now=_NOW,
        prior_successful_payment=True,
        facts=_ACT3_FACTS,
        include_transfer_attempted=True,
    )
    assert result.tier == 0
    assert result.verdict == "known"
    assert result.action == "pass_silent"
    assert result.probe is None


def test_seeded_pattern_memory_does_not_crash():
    memory = PatternMemory()
    memory.add(
        extract_cluster_signature(
            {
                "node_count": 4,
                "avg_in_degree": 2.0,
                "avg_out_degree": 1.5,
                "avg_retention": 0.2,
                "density": 0.4,
            },
            trail_shape=("login_new_device", "payee_added"),
            context_categories=("urgency", "secrecy"),
            label="sequence_takeover",
        )
    )
    result = evaluate_sender_context(
        events=_ordered_chain(),
        ringwatch=0.20,
        now=_NOW,
        pattern_memory=memory,
        ringwatch_stats={"node_count": 4, "avg_in_degree": 2.0},
        include_transfer_attempted=True,
    )
    assert result.pattern_match is None or set(result.pattern_match) <= {
        "similarity",
        "label",
    }
    if result.pattern_match is not None:
        assert 0.0 <= result.pattern_match["similarity"] <= 1.0

    quiet = evaluate_sender_context(
        events=[],
        ringwatch=0.05,
        now=_NOW,
        pattern_memory=memory,
        include_transfer_attempted=False,
    )
    assert quiet.pattern_match is None or "similarity" in quiet.pattern_match


def test_fired_rules_present_when_fused_positive():
    result = evaluate_sender_context(
        events=_ordered_chain(),
        ringwatch=0.20,
        now=_NOW,
        include_transfer_attempted=True,
    )
    assert result.fused_score > 0.0
    assert result.fired_rules


def test_panel_item_has_required_keys_and_no_secrets():
    result = evaluate_sender_context(
        events=_ordered_chain(),
        ringwatch=0.20,
        now=_NOW,
        decision_id="d_panel",
        include_transfer_attempted=True,
    )
    item = result.quadrant_panel_item
    assert set(item) == _PANEL_KEYS
    assert "correct_index" not in item
    assert not any("ground_truth" in key for key in item)
    assert "probe_id" not in item


def test_pipeline_module_has_no_forbidden_tokens():
    from pathlib import Path

    text = Path("backend/scoring/pipeline.py").read_text(encoding="utf-8")
    lowered = text.casefold()
    assert "freeze" not in lowered
    assert "razorpay" not in lowered
    assert "ground_truth_role" not in text
    from backend.context.lexicon import iter_trigger_phrases

    hits = 0
    for phrase in iter_trigger_phrases():
        if phrase in text:
            hits += 1
    assert hits == 0

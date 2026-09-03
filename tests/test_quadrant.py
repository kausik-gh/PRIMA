from backend.context.lexicon import iter_trigger_phrases
from backend.scoring.fusion import fuse
from backend.scoring.quadrant import (
    PRODUCT_CELL_ID,
    Q_HIGH_HIGH,
    Q_HIGH_LOW,
    Q_LOW_HIGH,
    Q_LOW_LOW,
    build_quadrant_panel_item,
    classify_quadrant,
)

_BANNED = ("fraud", "mule", "criminal", "scam")
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
_SECRET_KEYS = {
    "probe_id",
    "correct_index",
    "options",
    "matched_span",
}


def test_four_cells_with_explicit_scores():
    low_low = classify_quadrant(ringwatch=0.10, trailscore=0.10, contextflag=0.0)
    assert low_low.quadrant_id == Q_LOW_LOW
    assert low_low.sender_high is False
    assert low_low.beneficiary_high is False
    assert low_low.is_product_cell is False

    low_high = classify_quadrant(ringwatch=0.50, trailscore=0.10, contextflag=0.0)
    assert low_high.quadrant_id == Q_LOW_HIGH
    assert low_high.sender_high is False
    assert low_high.beneficiary_high is True
    assert low_high.is_product_cell is False

    high_low = classify_quadrant(ringwatch=0.20, trailscore=0.50, contextflag=0.0)
    assert high_low.quadrant_id == Q_HIGH_LOW
    assert high_low.sender_high is True
    assert high_low.beneficiary_high is False
    assert high_low.is_product_cell is True

    high_high = classify_quadrant(ringwatch=0.50, trailscore=0.50, contextflag=0.0)
    assert high_high.quadrant_id == Q_HIGH_HIGH
    assert high_high.sender_high is True
    assert high_high.beneficiary_high is True
    assert high_high.is_product_cell is False

    via_context = classify_quadrant(ringwatch=0.10, trailscore=0.10, contextflag=0.30)
    assert via_context.quadrant_id == Q_HIGH_LOW
    assert via_context.sender_high is True


def test_cross_term_applied_forces_product_cell():
    result = classify_quadrant(
        ringwatch=0.90,
        trailscore=0.10,
        contextflag=0.0,
        cross_term_applied=True,
    )
    assert result.quadrant_id == PRODUCT_CELL_ID
    assert result.is_product_cell is True
    assert result.sender_high is True
    assert result.beneficiary_high is False


def test_fusion_sender_high_ring_low_is_product_cell():
    fused = fuse(0.20, 0.50, 0.0)
    result = classify_quadrant(
        ringwatch=fused.ringwatch,
        trailscore=fused.trailscore,
        contextflag=fused.contextflag,
        fused_score=fused.fused_score,
        cross_term_applied=fused.cross_term_applied,
    )
    assert fused.cross_term_applied is True
    assert result.quadrant_id == Q_HIGH_LOW
    assert result.is_product_cell is True


def test_act3_inputs_are_product_cell():
    fused = fuse(0.20, 1.0, 1.0)
    result = classify_quadrant(
        ringwatch=0.20,
        trailscore=1.0,
        contextflag=1.0,
        fused_score=fused.fused_score,
        cross_term_applied=fused.cross_term_applied,
    )
    assert result.quadrant_id == Q_HIGH_LOW
    assert result.is_product_cell is True
    assert abs(result.sender_score - 1.0) < 1e-9
    assert abs(result.beneficiary_score - 0.20) < 1e-9


def test_quiet_payment_is_low_low():
    fused = fuse(0.05, 0.0, 0.0)
    result = classify_quadrant(
        ringwatch=fused.ringwatch,
        trailscore=fused.trailscore,
        contextflag=fused.contextflag,
        fused_score=fused.fused_score,
        cross_term_applied=fused.cross_term_applied,
    )
    assert result.quadrant_id == Q_LOW_LOW
    assert result.is_product_cell is False


def test_panel_item_shape_has_no_secrets():
    item = build_quadrant_panel_item(
        decision_id="d_test",
        ringwatch=0.20,
        trailscore=1.0,
        contextflag=1.0,
        fused_score=0.83,
        tier=4,
        verdict="high_risk",
        cross_term_applied=True,
    )
    assert set(item) == _PANEL_KEYS
    assert item["decision_id"] == "d_test"
    assert item["quadrant_id"] == Q_HIGH_LOW
    assert item["is_product_cell"] is True
    assert item["tier"] == 4
    assert item["verdict"] == "high_risk"
    assert item["fused_score"] == 0.83
    for key in _SECRET_KEYS:
        assert key not in item
    assert not any("ground_truth" in key for key in item)


def test_labels_and_details_have_no_banned_words():
    samples = (
        (0.10, 0.10, 0.0),
        (0.50, 0.10, 0.0),
        (0.20, 0.50, 0.0),
        (0.50, 0.50, 0.0),
    )
    blob_parts: list[str] = []
    for ringwatch, trailscore, contextflag in samples:
        result = classify_quadrant(
            ringwatch=ringwatch, trailscore=trailscore, contextflag=contextflag
        )
        blob_parts.extend([result.label, result.detail])
        for rule in result.fired_rules:
            blob_parts.append(str(rule["detail"]))
    blob = " ".join(blob_parts).casefold()
    for word in _BANNED:
        assert word not in blob


def test_quadrant_text_has_no_lexicon_phrases():
    result = classify_quadrant(ringwatch=0.20, trailscore=1.0, contextflag=1.0)
    item = build_quadrant_panel_item(
        decision_id="d_lex",
        ringwatch=0.20,
        trailscore=1.0,
        contextflag=1.0,
        fused_score=0.83,
        tier=4,
        verdict="high_risk",
    )
    blob = "\n".join(
        [
            result.label,
            result.detail,
            item["label"],
            item["detail"],
            *(str(rule["detail"]) for rule in result.fired_rules),
        ]
    )
    hits = 0
    for phrase in iter_trigger_phrases():
        if phrase in blob:
            hits += 1
    assert hits == 0

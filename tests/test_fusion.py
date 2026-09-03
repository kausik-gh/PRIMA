from backend.scoring.fusion import CROSS_TERM_REASON_CODE, fuse


def test_weighted_base_without_cross_term():
    result = fuse(0.50, 0.20, 0.20)
    expected_base = 0.40 * 0.50 + 0.35 * 0.20 + 0.25 * 0.20
    assert abs(expected_base - 0.32) < 1e-9
    assert abs(result.base - expected_base) < 1e-9
    assert result.cross_term_applied is False
    assert result.cross_term_bonus == 0.0
    assert result.reason_code is None
    assert abs(result.fused_score - expected_base) < 1e-9
    assert result.fired_rules
    assert result.fired_rules[0]["code"] == "fusion_base"
    scorers = [item["scorer"] for item in result.contributions]
    assert scorers == ["ringwatch", "trailscore", "contextflag"]
    for item in result.contributions:
        assert set(item) == {"scorer", "weight", "value", "contribution"}


def test_cross_term_applies_when_sender_high_and_ring_low():
    result = fuse(0.20, 0.50, 0.0)
    expected_base = 0.40 * 0.20 + 0.35 * 0.50 + 0.25 * 0.0
    assert result.cross_term_applied is True
    assert result.reason_code == CROSS_TERM_REASON_CODE
    assert abs(result.cross_term_bonus - 0.15) < 1e-9
    assert abs(result.fused_score - min(expected_base + 0.15, 1.0)) < 1e-9
    codes = [rule["code"] for rule in result.fired_rules]
    assert CROSS_TERM_REASON_CODE in codes


def test_cross_term_does_not_apply_when_ringwatch_high():
    result = fuse(0.30, 0.90, 0.0)
    assert result.cross_term_applied is False
    expected = 0.40 * 0.30 + 0.35 * 0.90
    assert abs(result.fused_score - expected) < 1e-9


def test_act3_shape_reaches_tier4_band():
    result = fuse(0.20, 1.0, 1.0)
    expected_base = 0.40 * 0.20 + 0.35 * 1.0 + 0.25 * 1.0
    assert abs(expected_base - 0.68) < 1e-9
    assert result.cross_term_applied is True
    assert abs(result.fused_score - min(expected_base + 0.15, 1.0)) < 1e-9
    assert abs(result.fused_score - 0.83) < 1e-9
    assert result.fused_score >= 0.80


def test_fuse_clamps_above_one():
    result = fuse(1.0, 1.0, 1.0)
    assert result.fused_score == 1.0
    assert result.cross_term_applied is False


def test_concatenates_upstream_rules():
    result = fuse(
        0.20,
        0.50,
        0.0,
        trailscore_rules=[
            {"code": "login_new_device", "points": 0.20, "detail": "New-device login."}
        ],
    )
    codes = [rule["code"] for rule in result.fired_rules]
    assert "login_new_device" in codes
    assert CROSS_TERM_REASON_CODE in codes


def test_config_can_disable_cross_term():
    result = fuse(
        0.20,
        0.50,
        0.0,
        config={"fusion": {"cross_term": {"enabled": False}}},
    )
    assert result.cross_term_applied is False
    assert abs(result.fused_score - (0.40 * 0.20 + 0.35 * 0.50)) < 1e-9

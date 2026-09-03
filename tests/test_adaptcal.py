from backend.memory.adaptcal import AdaptCal
from backend.scoring.ladder import DEFAULT_BANDS, ladder_decide


def _enabled() -> AdaptCal:
    return AdaptCal(config={"adaptcal": {"enabled": True, "step": 0.02}})


def test_disabled_apply_does_not_change_bands():
    cal = AdaptCal()
    for _ in range(10):
        cal.observe(tier=1, is_legitimate=True, ground_truth_fraud=False)
    before = cal.current_bands()
    snapshot = cal.apply()
    assert snapshot.enabled is False
    assert snapshot.adjusted is False
    assert cal.current_bands() == before
    assert [row["max"] for row in before] == [band[1] for band in DEFAULT_BANDS]


def test_high_false_challenge_raises_early_max():
    cal = _enabled()
    for _ in range(8):
        cal.observe(tier=1, is_legitimate=True, ground_truth_fraud=False)
    rates = cal.rates()
    assert rates["false_challenge_rate"] == 1.0
    assert rates["denominators"]["legit_tx"] == 8
    before = cal.current_bands()
    snapshot = cal.apply()
    after = cal.current_bands()
    assert snapshot.adjusted is True
    assert after[0]["max"] == before[0]["max"] + 0.02
    assert after[1]["max"] == before[1]["max"] + 0.02
    assert ladder_decide(0.16).tier == 1
    assert ladder_decide(0.16, config={"ladder": after}).tier == 0


def test_low_catch_rate_moves_bands_to_hold_sooner():
    cal = _enabled()
    for _ in range(8):
        cal.observe(tier=0, is_legitimate=False, ground_truth_fraud=True)
    rates = cal.rates()
    assert rates["catch_rate"] == 0.0
    assert rates["denominators"]["fraud_tx"] == 8
    before = cal.current_bands()
    snapshot = cal.apply()
    after = cal.current_bands()
    assert snapshot.adjusted is True
    assert after[2]["max"] < before[2]["max"]
    assert after[3]["max"] < before[3]["max"]
    assert ladder_decide(0.59).tier == 2
    assert ladder_decide(0.59, config={"ladder": after}).tier == 3


def test_bands_remain_monotonic_after_apply():
    cal = _enabled()
    for _ in range(5):
        cal.observe(tier=2, is_legitimate=True, ground_truth_fraud=False)
        cal.observe(tier=0, is_legitimate=False, ground_truth_fraud=True)
    cal.apply()
    maxima = [row["max"] for row in cal.current_bands()]
    assert maxima == sorted(maxima)
    assert all(0.0 < value <= 1.01 for value in maxima)


def test_empty_denominators_yield_zero_rates():
    cal = AdaptCal()
    rates = cal.rates()
    assert rates["false_challenge_rate"] == 0.0
    assert rates["catch_rate"] == 0.0
    assert rates["denominators"]["legit_tx"] == 0
    assert rates["denominators"]["fraud_tx"] == 0
    snapshot = cal.propose()
    assert snapshot.false_challenge_rate == 0.0
    assert snapshot.catch_rate == 0.0


def test_current_bands_work_with_ladder_decide():
    cal = _enabled()
    for _ in range(3):
        cal.observe(tier=1, is_legitimate=True, ground_truth_fraud=False)
    snapshot = cal.apply()
    bands = cal.current_bands()
    result = ladder_decide(0.5, config={"ladder": bands})
    assert result.tier in range(5)
    assert result.action
    assert snapshot.ladder_bands == bands


def test_forbidden_tokens_absent_from_adaptcal_module():
    from pathlib import Path

    from backend.context.lexicon import iter_trigger_phrases

    text = Path("backend/memory/adaptcal.py").read_text(encoding="utf-8")
    lowered = text.casefold()
    assert "freeze" not in lowered
    assert "razorpay" not in lowered
    assert "ground_truth_role" not in text
    hits = 0
    for phrase in iter_trigger_phrases():
        if phrase in text:
            hits += 1
    assert hits == 0

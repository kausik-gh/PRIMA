from backend.context.lexicon import categories, sample_text_for_categories, sample_text_for_category
from backend.scoring.contextflag import contextflag_score


def test_d_empty_note_and_call_context_is_zero():
    result = contextflag_score(note="", call_context="")
    assert result.score == 0.0
    assert result.categories == []
    assert result.fired_rules == []


def test_d_none_inputs_are_zero():
    result = contextflag_score(note=None, call_context=None)
    assert result.score == 0.0
    assert result.categories == []
    assert result.fired_rules == []


def test_e_enough_categories_clamp_to_one():
    text = sample_text_for_categories(list(categories()))
    result = contextflag_score(note=text, call_context="")
    assert result.score == 1.0
    assert len(result.categories) == len(categories())
    assert result.fired_rules
    for rule in result.fired_rules:
        assert "code" in rule and "points" in rule and "detail" in rule
        assert "matched_span" not in rule
    for item in result.categories:
        assert set(item) == {"category", "weight"}


def test_each_category_sample_fires_that_category():
    for category in categories():
        text = sample_text_for_category(category)
        result = contextflag_score(note="", call_context=text)
        names = [item["category"] for item in result.categories]
        assert category in names
        assert result.score > 0.0
        assert result.fired_rules
        assert all("matched_span" not in rule for rule in result.fired_rules)


def test_public_result_has_no_span_fields():
    text = sample_text_for_category(categories()[0])
    result = contextflag_score(note=text)
    assert not hasattr(result, "matched_span")
    dumped = result.__dict__
    assert "matched_span" not in dumped

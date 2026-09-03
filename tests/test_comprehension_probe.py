from backend.context.lexicon import iter_trigger_phrases
from backend.scoring.comprehension_probe import build_comprehension_probe

_AGE_PAYER_FACTS = (
    "This account was opened 6 days ago.",
    "14 different people have sent it money today.",
)

_BANNED = ("fraud", "mule", "criminal", "scam")


def test_tier_below_two_returns_none():
    for tier in (0, 1):
        assert (
            build_comprehension_probe(
                verdict="watch",
                tier=tier,
                facts=_AGE_PAYER_FACTS,
            )
            is None
        )


def test_tier_two_and_above_return_three_options():
    for tier in (2, 3, 4):
        probe = build_comprehension_probe(
            verdict="high_risk",
            tier=tier,
            facts=_AGE_PAYER_FACTS,
            rng_seed=7,
        )
        assert probe is not None
        assert probe.question == "What did we tell you about this account?"
        assert len(probe.options) == 3
        assert probe.correct_index in (0, 1, 2)
        assert len(set(probe.options)) == 3


def test_age_and_payer_facts_are_reflected_only_in_correct_option():
    probe = build_comprehension_probe(
        verdict="high_risk",
        tier=4,
        facts=_AGE_PAYER_FACTS,
        rng_seed=3,
    )
    assert probe is not None
    correct = probe.options[probe.correct_index]
    lowered = correct.casefold()
    assert "open" in lowered or "recent" in lowered
    assert "people" in lowered or "paying" in lowered
    assert "6" not in correct
    assert "14" not in correct
    for index, option in enumerate(probe.options):
        if index == probe.correct_index:
            continue
        other = option.casefold()
        assert "opened" not in other
        assert "people" not in other
        assert "paying" not in other


def test_same_seed_is_deterministic():
    kwargs = dict(
        verdict="suspicious",
        tier=2,
        facts=_AGE_PAYER_FACTS,
        rng_seed=42,
    )
    first = build_comprehension_probe(**kwargs)
    second = build_comprehension_probe(**kwargs)
    assert first is not None and second is not None
    assert first.options == second.options
    assert first.correct_index == second.correct_index
    assert first.question == second.question


def test_different_seed_keeps_correct_text():
    kwargs = dict(verdict="suspicious", tier=2, facts=_AGE_PAYER_FACTS)
    first = build_comprehension_probe(**kwargs, rng_seed=1)
    second = build_comprehension_probe(**kwargs, rng_seed=2)
    assert first is not None and second is not None
    assert first.options[first.correct_index] == second.options[second.correct_index]


def test_options_have_no_banned_words():
    probe = build_comprehension_probe(
        verdict="high_risk",
        tier=3,
        facts=_AGE_PAYER_FACTS,
        rng_seed=0,
    )
    assert probe is not None
    blob = " ".join([probe.question, *probe.options]).casefold()
    for word in _BANNED:
        assert word not in blob


def test_options_have_no_lexicon_phrases():
    probe = build_comprehension_probe(
        verdict="high_risk",
        tier=4,
        facts=_AGE_PAYER_FACTS,
        rng_seed=11,
    )
    assert probe is not None
    blob = "\n".join([probe.question, *probe.options])
    hits = 0
    for phrase in iter_trigger_phrases():
        if phrase in blob:
            hits += 1
    assert hits == 0


def test_empty_facts_uses_verdict_without_invented_numbers():
    probe = build_comprehension_probe(
        verdict="no_history",
        tier=2,
        facts=(),
        rng_seed=5,
    )
    assert probe is not None
    correct = probe.options[probe.correct_index]
    assert any(ch.isdigit() for ch in correct) is False

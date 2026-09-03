from backend.context.lexicon import iter_trigger_phrases
from backend.memory.pattern_memory import (
    PatternMemory,
    compare_signature,
    extract_cluster_signature,
    pattern_match_for_decision,
)

_STATS = {
    "node_count": 4,
    "avg_in_degree": 2.0,
    "avg_out_degree": 1.5,
    "avg_retention": 0.2,
    "density": 0.4,
}

_TRAIL = ("login_new_device", "payee_added", "limit_raised")
_CATEGORIES = ("urgency", "secrecy")
_ALLOWED_CATEGORIES = {"urgency", "secrecy", "fear", "greed", "bypass_approval"}


def test_extract_fills_trail_and_context():
    signature = extract_cluster_signature(
        _STATS,
        trail_shape=_TRAIL,
        context_categories=["urgency", "secrecy", "not_a_category"],
        label="sequence_takeover",
    )
    assert signature.trail_shape == list(_TRAIL)
    assert signature.context_categories == ["urgency", "secrecy"]
    assert signature.label == "sequence_takeover"
    assert signature.node_count == 4
    assert abs(signature.avg_in_degree - 2.0) < 1e-9


def test_identical_signatures_are_one():
    a = extract_cluster_signature(
        _STATS, trail_shape=_TRAIL, context_categories=_CATEGORIES
    )
    b = extract_cluster_signature(
        _STATS, trail_shape=_TRAIL, context_categories=_CATEGORIES
    )
    assert abs(compare_signature(a, b) - 1.0) < 1e-9


def test_very_different_signatures_are_low():
    a = extract_cluster_signature(
        _STATS, trail_shape=_TRAIL, context_categories=_CATEGORIES
    )
    b = extract_cluster_signature(
        {
            "node_count": 80,
            "avg_in_degree": 40.0,
            "avg_out_degree": 35.0,
            "avg_retention": 0.95,
            "density": 0.05,
        },
        trail_shape=("screen_share_active",),
        context_categories=("greed",),
    )
    assert compare_signature(a, b) < 0.2


def test_add_and_best_match_returns_label():
    memory = PatternMemory()
    stored = extract_cluster_signature(
        _STATS,
        trail_shape=_TRAIL,
        context_categories=_CATEGORIES,
        label="sequence_takeover",
    )
    signature_id = memory.add(stored, signature_id="sig_demo")
    assert signature_id == "sig_demo"
    query = extract_cluster_signature(
        _STATS, trail_shape=_TRAIL, context_categories=_CATEGORIES
    )
    match = memory.best_match(query, min_similarity=0.5)
    assert match is not None
    assert match["signature_id"] == "sig_demo"
    assert match["label"] == "sequence_takeover"
    assert match["similarity"] >= 0.5


def test_best_match_none_below_threshold():
    memory = PatternMemory()
    memory.add(
        extract_cluster_signature(
            _STATS, trail_shape=_TRAIL, context_categories=_CATEGORIES, label="fan_in_ring"
        )
    )
    query = extract_cluster_signature(
        {
            "node_count": 90,
            "avg_in_degree": 50.0,
            "avg_out_degree": 40.0,
            "avg_retention": 0.99,
            "density": 0.02,
        }
    )
    assert memory.best_match(query, min_similarity=0.5) is None
    empty = PatternMemory()
    assert empty.best_match(query) is None


def test_pattern_match_for_decision_shape():
    memory = PatternMemory()
    memory.add(
        extract_cluster_signature(
            _STATS,
            trail_shape=_TRAIL,
            context_categories=_CATEGORIES,
            label="isolation_pressure",
        )
    )
    hit = pattern_match_for_decision(
        ringwatch_stats=_STATS,
        trail_steps=_TRAIL,
        context_categories=_CATEGORIES,
        memory=memory,
    )
    assert hit is not None
    assert set(hit) == {"similarity", "label"}
    assert hit["label"] == "isolation_pressure"
    assert 0.0 <= hit["similarity"] <= 1.0

    miss = pattern_match_for_decision(
        ringwatch_stats={"node_count": 1, "avg_in_degree": 0.0},
        trail_steps=(),
        context_categories=(),
        memory=memory,
        min_similarity=0.99,
    )
    assert miss is None


def test_stored_categories_are_names_only_and_no_lexicon_phrases():
    memory = PatternMemory()
    memory.add(
        extract_cluster_signature(
            _STATS,
            trail_shape=_TRAIL,
            context_categories=["urgency", "unknown_token"],
            label="fan_in_ring",
        )
    )
    rows = memory.list_signatures()
    assert rows
    blob_parts: list[str] = []
    for row in rows:
        for category in row["context_categories"]:
            assert category in _ALLOWED_CATEGORIES
        blob_parts.append(str(row["label"]))
        blob_parts.extend(row["context_categories"])
        blob_parts.extend(row["trail_shape"])
    blob = "\n".join(blob_parts)
    hits = 0
    for phrase in iter_trigger_phrases():
        if phrase in blob:
            hits += 1
    assert hits == 0


def test_no_gateway_or_ground_truth_fields_on_public_dicts():
    memory = PatternMemory()
    memory.add(extract_cluster_signature(_STATS, label="fan_in_ring"))
    match = memory.best_match(extract_cluster_signature(_STATS))
    listed = memory.list_signatures()[0]
    public = pattern_match_for_decision(ringwatch_stats=_STATS, memory=memory)
    for payload in (match, listed, public):
        assert payload is not None
        joined = " ".join(payload.keys())
        assert "freeze" not in joined
        assert "razorpay" not in joined
        assert "ground_truth" not in joined

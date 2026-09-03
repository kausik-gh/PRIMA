"""Three-option comprehension probe for the payer surface (tier >= 2)."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Sequence

QUESTION = "What did we tell you about this account?"

_BANNED_WORDS = ("fraud", "mule", "criminal", "scam")

_VERDICT_CORRECT: dict[str, str] = {
    "no_history": "You have not paid this account before.",
    "watch": "We flagged extra checks on this payment.",
    "suspicious": "This payment needs extra confirmation from you.",
    "high_risk": "This payment was held for extra confirmation.",
    "known": "You have paid this account before.",
}

_DISTRACTORS: tuple[str, ...] = (
    "Your bank is closed for maintenance",
    "The amount is above your daily limit",
    "This payment was already completed",
    "Network fees are higher than usual today",
    "Your device software needs an update",
    "This payee is listed as a registered merchant",
)


@dataclass(frozen=True)
class ComprehensionProbe:
    question: str
    options: list[str]
    correct_index: int


def build_comprehension_probe(
    *,
    verdict: str,
    tier: int,
    facts: Sequence[str],
    fused_score: float | None = None,
    rng_seed: int | None = None,
) -> ComprehensionProbe | None:
    """Build a three-option probe, or None below tier 2. Pure; no I/O.

    ``fused_score`` is accepted for the quote-time caller and is not used to
    invent numeric claims. ``probe_id`` is assigned later by the persistence layer.
    """
    del fused_score
    if int(tier) < 2:
        return None

    cleaned = tuple(str(item).strip() for item in facts if str(item).strip())
    rng = random.Random(rng_seed)
    correct = _correct_option(cleaned, verdict)
    distractors = _pick_distractors(cleaned, correct, rng)
    options = [correct, distractors[0], distractors[1]]
    rng.shuffle(options)
    correct_index = options.index(correct)

    probe = ComprehensionProbe(
        question=QUESTION,
        options=options,
        correct_index=correct_index,
    )
    _assert_probe_clean(probe)
    return probe


def _correct_option(facts: Sequence[str], verdict: str) -> str:
    blob = " ".join(facts).casefold()
    age = _has_age(blob)
    payers = _has_payers(blob)
    if age and payers:
        return "It was opened recently and many people are paying it"
    if age:
        return "This account was opened recently."
    if payers:
        return "Many people have sent money to this account."
    if _has_never_paid(blob):
        return "You have never paid this account before."
    if _has_pass_through(blob):
        return "Money sent here usually leaves quickly."
    if _has_limit_raised(blob):
        return "Your transfer limit was raised recently."
    if _has_new_device(blob):
        return "A new device signed in to your account recently."
    return _VERDICT_CORRECT.get(verdict, "We flagged extra checks on this payment.")


def _has_age(blob: str) -> bool:
    return bool(re.search(r"opened\s+.+\s+days?\s+ago", blob)) or "opened recently" in blob


def _has_payers(blob: str) -> bool:
    if re.search(r"\d+\s+(?:different\s+)?people", blob):
        return True
    return "people" in blob and ("sent" in blob or "paying" in blob)


def _has_never_paid(blob: str) -> bool:
    return "never paid" in blob


def _has_pass_through(blob: str) -> bool:
    return "usually leaves" in blob or "leaves within" in blob


def _has_limit_raised(blob: str) -> bool:
    return "limit was raised" in blob or "limit raised" in blob


def _has_new_device(blob: str) -> bool:
    return "new device" in blob or "signed in" in blob


def _pick_distractors(
    facts: Sequence[str], correct: str, rng: random.Random
) -> tuple[str, str]:
    blob = " ".join(facts).casefold()
    pool = [item for item in _DISTRACTORS if item != correct and not _overlaps(item, blob)]
    if len(pool) < 2:
        pool = [item for item in _DISTRACTORS if item != correct]
    chosen = list(pool)
    rng.shuffle(chosen)
    return chosen[0], chosen[1]


def _overlaps(distractor: str, facts_blob: str) -> bool:
    if distractor.casefold() in facts_blob:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]+", distractor.casefold()) if len(token) > 3]
    return bool(tokens) and all(token in facts_blob for token in tokens)


def _assert_probe_clean(probe: ComprehensionProbe) -> None:
    from backend.context.lexicon import iter_trigger_phrases

    texts = [probe.question, *probe.options]
    for text in texts:
        lowered = text.casefold()
        for word in _BANNED_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                raise RuntimeError("banned word in probe text")
        for phrase in iter_trigger_phrases():
            if phrase in text:
                raise RuntimeError("lexicon phrase in probe text")
    if len(probe.options) != 3:
        raise RuntimeError("probe must have exactly three options")
    if probe.correct_index not in (0, 1, 2):
        raise RuntimeError("correct_index must be 0..2")
    if len(set(probe.options)) != 3:
        raise RuntimeError("probe options must be unique")

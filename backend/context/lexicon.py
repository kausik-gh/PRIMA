"""Trigger phrases and matchers for ContextFlag. This is the only module that may hold them."""

from __future__ import annotations

import re
from typing import Sequence

CATEGORY_ORDER: tuple[str, ...] = (
    "urgency",
    "secrecy",
    "fear",
    "greed",
    "bypass_approval",
)

_CATEGORY_PHRASES: dict[str, tuple[str, ...]] = {
    "urgency": (
        "this offer expires before midnight tonight",
        "complete the payment in the next few minutes",
        "the countdown on this request is almost over",
    ),
    "secrecy": (
        "keep this conversation strictly to yourself",
        "do not involve any family member in this",
        "handle this privately without other people",
    ),
    "fear": (
        "officers will arrive at your door shortly",
        "your accounts face immediate legal seizure",
        "you are listed as a suspect in this case",
    ),
    "greed": (
        "your principal will triple by tomorrow morning",
        "this investment returns a locked high yield",
        "collect your bonus payout after this transfer",
    ),
    "bypass_approval": (
        "skip the extra confirmation step entirely",
        "turn off the delay and send it through",
        "approve it yourself without the second checker",
    ),
}

_CATEGORY_REGEX: dict[str, tuple[re.Pattern[str], ...]] = {
    "urgency": (
        re.compile(r"\bonly\s+\d+\s+minutes?\s+remain(?:s|ing)?\b"),
    ),
    "secrecy": (
        re.compile(r"\bno\s+one\s+else\s+must\s+know\b"),
    ),
    "fear": (
        re.compile(r"\bwarrant\s+has\s+been\s+issued\b"),
    ),
    "greed": (
        re.compile(r"\bguaranteed\s+\d+\s*%\s+return\b"),
    ),
    "bypass_approval": (
        re.compile(r"\bbypass\s+the\s+(?:otp|pin|2fa)\b"),
    ),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def categories() -> tuple[str, ...]:
    return CATEGORY_ORDER


def iter_trigger_phrases() -> tuple[str, ...]:
    phrases: list[str] = []
    for category in CATEGORY_ORDER:
        phrases.extend(_CATEGORY_PHRASES[category])
    return tuple(phrases)


def sample_text_for_category(category: str) -> str:
    if category not in _CATEGORY_PHRASES:
        known = ", ".join(CATEGORY_ORDER)
        raise KeyError(f"unknown category {category!r}; expected one of {known}")
    return _CATEGORY_PHRASES[category][0]


def sample_text_for_categories(category_list: Sequence[str]) -> str:
    return " ".join(sample_text_for_category(category) for category in category_list)


def match_categories(text: str | None) -> tuple[str, ...]:
    """Return unique matched category names in stable order. No spans are returned."""
    if text is None:
        return ()
    folded = str(text).casefold()
    if not folded.strip():
        return ()
    tokens = _tokenize(folded)
    hit: list[str] = []
    for category in CATEGORY_ORDER:
        if _category_hits(category, folded, tokens):
            hit.append(category)
    return tuple(hit)


def _tokenize(folded_text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(folded_text))


def _category_hits(
    category: str, folded_text: str, tokens: tuple[str, ...]
) -> bool:
    for phrase in _CATEGORY_PHRASES[category]:
        if _contains_tokens(tokens, _tokenize(phrase.casefold())):
            return True
    for pattern in _CATEGORY_REGEX[category]:
        if pattern.search(folded_text):
            return True
    return False


def _contains_tokens(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle:
        return False
    width = len(needle)
    limit = len(haystack) - width + 1
    for index in range(limit):
        if haystack[index : index + width] == needle:
            return True
    return False

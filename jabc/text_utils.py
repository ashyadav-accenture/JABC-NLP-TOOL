"""NLP feature design (spec section 11): preprocessing, phrase-level
detection, negation handling, and intensifier handling.

Phrase rules always take precedence over isolated keyword matches (spec
30.2): "would not recommend" must override the standalone word "recommend".
This module implements that priority by tracking which character spans of
the answer text have already been "claimed" by a phrase-rule match, and
skipping keyword matches that fall inside a claimed span.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PhraseMatch:
    phrase: str
    theme: str
    direction: str  # positive | negative
    strength: float
    start: int
    end: int
    negation_detected: bool = False
    intensifier_detected: bool = False


@dataclass
class KeywordMatch:
    keyword: str
    theme: str
    direction: str
    start: int
    end: int


def clean_text(text: str) -> str:
    """Lowercase and collapse whitespace, preserving punctuation needed for
    phrase boundaries. Original text is always kept separately for evidence
    display; this is only used for matching."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _word_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _words_in_window(text: str, span: tuple[int, int], window: int) -> str:
    """Returns the text within `window` words before and after the given
    character span, for negation/intensifier scanning."""
    spans = _word_spans(text)
    idxs_before = [i for i, (s, e) in enumerate(spans) if e <= span[0]]
    idxs_after = [i for i, (s, e) in enumerate(spans) if s >= span[1]]
    before_idxs = idxs_before[-window:] if idxs_before else []
    after_idxs = idxs_after[:window] if idxs_after else []
    chosen = before_idxs + after_idxs
    if not chosen:
        return ""
    parts = [text[spans[i][0]:spans[i][1]] for i in chosen]
    return " ".join(parts)


def find_phrase_matches(
    text: str,
    phrase_rules: list[dict],
    negation_words: list[str],
    intensifier_words: list[str],
    negation_window: int = 3,
    intensifier_window: int = 3,
) -> list[PhraseMatch]:
    """Find configured multi-word phrase rules in the text, adjusting
    direction for negation and strength for intensifiers found nearby.
    """
    clean = clean_text(text)
    matches: list[PhraseMatch] = []

    neg_pattern = re.compile(
        r"\b(" + "|".join(re.escape(w.strip('"')) for w in negation_words) + r")\b"
    )
    int_pattern = re.compile(
        r"\b(" + "|".join(re.escape(w.strip('"')) for w in intensifier_words) + r")\b"
    )

    for rule in phrase_rules:
        phrase = rule["phrase"].lower()
        phrase_pattern = re.compile(r"\b" + re.escape(phrase) + r"\b")
        for m in phrase_pattern.finditer(clean):
            span = (m.start(), m.end())
            window_text = _words_in_window(clean, span, max(negation_window, intensifier_window))

            negated = bool(neg_pattern.search(window_text))
            intensified = bool(int_pattern.search(window_text))

            direction = rule["direction"]
            strength = float(rule["strength"])

            if negated:
                # A phrase rule that is itself already a negated construction
                # (e.g. "would not recommend") should NOT be double-negated
                # by a stray "not" in the window; rules are authored to
                # already encode their true polarity, so we only flip when
                # the rule's phrase does not already contain a negation word.
                phrase_already_negated = any(
                    re.search(rf"\b{re.escape(w.strip(chr(34)))}\b", phrase)
                    for w in negation_words
                )
                if not phrase_already_negated:
                    direction = "negative" if direction == "positive" else "positive"
                    strength = max(strength * 0.9, 0.5)

            if intensified:
                strength = min(1.0, strength * 1.15)

            matches.append(
                PhraseMatch(
                    phrase=phrase,
                    theme=rule["theme"],
                    direction=direction,
                    strength=round(strength, 3),
                    start=span[0],
                    end=span[1],
                    negation_detected=negated,
                    intensifier_detected=intensified,
                )
            )

    return matches


def find_keyword_matches(
    text: str,
    theme_keywords: dict[str, dict[str, list[str]]],
    claimed_spans: list[tuple[int, int]] | None = None,
) -> list[KeywordMatch]:
    """Find single/short keyword matches per theme, skipping any match whose
    span overlaps a span already claimed by a phrase-rule match (phrase
    rules take precedence -- spec 30.2).
    """
    clean = clean_text(text)
    claimed_spans = claimed_spans or []

    def _overlaps_claimed(span: tuple[int, int]) -> bool:
        return any(s <= span[0] < e or s < span[1] <= e for s, e in claimed_spans)

    matches: list[KeywordMatch] = []
    for theme, directions in theme_keywords.items():
        for direction in ("positive", "negative"):
            for kw in directions.get(direction, []):
                kw_lower = kw.lower()
                pattern = re.compile(r"\b" + re.escape(kw_lower) + r"\b")
                for m in pattern.finditer(clean):
                    span = (m.start(), m.end())
                    if _overlaps_claimed(span):
                        continue
                    matches.append(
                        KeywordMatch(keyword=kw_lower, theme=theme, direction=direction,
                                     start=span[0], end=span[1])
                    )
    return matches

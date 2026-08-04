"""Stage 5-8 (spec sections 7, 11, 12, 29.2, 30): builds structured evidence
records from raw answers, before any theme scoring happens.

For every RawAnswer this module produces zero or more EvidenceRecord objects
covering:
  - explicit numeric ratings (highest-priority signal for their theme)
  - phrase-rule matches (negation/intensifier aware, take precedence over
    isolated keywords)
  - keyword matches (only outside spans already claimed by a phrase match)
  - question-context "neutral" coverage evidence (so a theme's evidence
    coverage reflects how many relevant questions were answered, even when
    the answer content itself is not clearly directional)
  - behavioral/engagement-history signals

Sentiment is attached to every evidence record as supporting metadata
(`sentiment_support`) rather than generating its own evidence records --
per spec section 30.4, sentiment must not independently drive scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config_loader import Config, THEMES
from .models import RawAnswer, EvidenceRecord
from .sentiment import score_text
from .text_utils import find_phrase_matches, find_keyword_matches

RATING_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:/|out of|-)\s*(\d{1,2})|(?<!\d)(\d{1,2})(?!\d)"
)

SECTION_LETTER_PATTERN = re.compile(r"section\s*([a-i])\b", re.IGNORECASE)


def _match_question_rules(question_text: str, question_category: str,
                            question_rules: list[dict]) -> dict | None:
    """Finds the question_rule whose match_any phrase is the longest (most
    specific) substring match. Question text is checked first and weighted
    more heavily than category text, since category names (e.g.
    "Communication & Future Opportunities") can incidentally contain a
    generic rule's trigger word (e.g. "communication") even when the actual
    question is about something else entirely (advocacy)."""
    question_hay = question_text.lower()
    category_hay = question_category.lower()

    best_rule = None
    best_score = (-1, 0)  # (matched_in_question_text, phrase_length)

    for rule in question_rules:
        for phrase in rule.get("match_any", []):
            p = phrase.lower()
            in_question = p in question_hay
            in_category = p in category_hay
            if not in_question and not in_category:
                continue
            score = (1 if in_question else 0, len(p))
            if score > best_score:
                best_score = score
                best_rule = rule

    return best_rule


def _section_defaults(question_text: str, question_category: str,
                       section_defaults: dict) -> dict[str, float]:
    haystack = f"{question_category} {question_text}"
    m = SECTION_LETTER_PATTERN.search(haystack)
    if m:
        letter = m.group(1).upper()
        return section_defaults.get(letter, {})
    return {}


def _extract_explicit_rating(answer_text: str, scale_hint_max: int = 5) -> float | None:
    """Looks for a numeric rating in the answer text and normalizes it to a
    1-5 scale. Handles "4/5", "8 out of 10", or a bare small integer that is
    clearly a rating (e.g. answer text is JUST a number)."""
    text = answer_text.strip()
    m = RATING_PATTERN.search(text)
    if not m:
        return None

    if m.group(1) and m.group(2):
        num = float(m.group(1))
        denom = float(m.group(2))
        if denom <= 0:
            return None
        normalized = 1 + (num / denom) * 4
        return max(1.0, min(5.0, normalized))

    if m.group(3):
        # Only treat a bare number as a rating if it's essentially the whole
        # answer (a real rating question, not a number embedded in prose).
        stripped_non_digits = re.sub(r"[\d\s/\-.]", "", text)
        if stripped_non_digits:
            return None
        num = float(m.group(3))
        if num <= 5:
            normalized = num  # already on a 1-5 scale
        elif num <= 10:
            normalized = 1 + (num / 10) * 4
        else:
            return None
        return max(1.0, min(5.0, normalized))

    return None


def extract_evidence_for_answer(answer: RawAnswer, config: Config) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    answer_id = answer.answer_id()

    qtm = config.question_theme_mapping
    question_rules = qtm.get("question_rules", [])
    section_defaults = qtm.get("section_theme_defaults", {})

    matched_rule = _match_question_rules(answer.question_text, answer.question_category, question_rules)
    theme_weights: dict[str, float] = {}
    behavioral_flags: list[str] = []
    explicit_rating_theme = None

    if matched_rule:
        theme_weights = dict(matched_rule.get("theme_weights", {}))
        behavioral_flags = list(matched_rule.get("behavioral_flags", []))
        explicit_rating_theme = matched_rule.get("explicit_rating_theme")
    else:
        theme_weights = _section_defaults(answer.question_text, answer.question_category, section_defaults)

    sentiment = score_text(answer.answer_text)
    compound = sentiment["compound"]

    # --- Explicit rating evidence (highest priority for its theme) ---
    if explicit_rating_theme:
        rating = _extract_explicit_rating(answer.answer_text)
        if rating is not None:
            direction = "positive" if rating >= 3.5 else ("negative" if rating <= 2.5 else "neutral")
            # Encode the rating magnitude as a strength in [0,1] so the
            # scoring engine can recover the exact rating via
            # 3 + sign(direction) * strength * 2 (see scoring.py).
            rating_strength = round(abs(rating - 3.0) / 2.0, 3)
            records.append(EvidenceRecord(
                respondent_id=answer.respondent_id,
                source_answer_id=answer_id,
                theme=explicit_rating_theme,
                evidence_type="explicit_rating",
                direction=direction,
                strength=rating_strength,
                evidence_text=answer.answer_text[:200],
                matched_phrases=[],
                matched_keywords=[],
                question_context_weight=theme_weights.get(explicit_rating_theme, 1.0),
                sentiment_support=compound,
                source_file=answer.source_file, sheet_name=answer.sheet_name,
                question_number=answer.question_number,
                question_category=answer.question_category,
                question_text=answer.question_text,
            ))

    # --- Phrase-rule evidence (negation/intensifier aware) ---
    phrase_rules_cfg = config.phrase_rules
    phrase_matches = find_phrase_matches(
        answer.answer_text,
        phrase_rules_cfg.get("phrase_rules", []),
        phrase_rules_cfg.get("negation_words", []),
        phrase_rules_cfg.get("intensifier_words", []),
        phrase_rules_cfg.get("negation_window", 3),
        phrase_rules_cfg.get("intensifier_window", 3),
    )
    claimed_spans = [(m.start, m.end) for m in phrase_matches]

    for pm in phrase_matches:
        evidence_type = _evidence_type_for(pm.theme, pm.direction)
        records.append(EvidenceRecord(
            respondent_id=answer.respondent_id,
            source_answer_id=answer_id,
            theme=pm.theme,
            evidence_type=evidence_type,
            direction=pm.direction,
            strength=pm.strength,
            evidence_text=_excerpt_around(answer.answer_text, pm.start, pm.end),
            matched_phrases=[pm.phrase],
            matched_keywords=[],
            question_context_weight=theme_weights.get(pm.theme, 0.3),
            sentiment_support=compound,
            negation_detected=pm.negation_detected,
            intensifier_detected=pm.intensifier_detected,
            source_file=answer.source_file, sheet_name=answer.sheet_name,
            question_number=answer.question_number,
            question_category=answer.question_category,
            question_text=answer.question_text,
        ))

    # --- Keyword evidence (only outside phrase-claimed spans) ---
    keyword_matches = find_keyword_matches(answer.answer_text, config.theme_keywords, claimed_spans)
    for km in keyword_matches:
        evidence_type = _evidence_type_for(km.theme, km.direction)
        records.append(EvidenceRecord(
            respondent_id=answer.respondent_id,
            source_answer_id=answer_id,
            theme=km.theme,
            evidence_type=evidence_type,
            direction=km.direction,
            strength=0.55,
            evidence_text=_excerpt_around(answer.answer_text, km.start, km.end),
            matched_phrases=[],
            matched_keywords=[km.keyword],
            question_context_weight=theme_weights.get(km.theme, 0.3),
            sentiment_support=compound,
            source_file=answer.source_file, sheet_name=answer.sheet_name,
            question_number=answer.question_number,
            question_category=answer.question_category,
            question_text=answer.question_text,
        ))

    # --- Neutral context-coverage evidence for themes this question maps to
    #     but where nothing directional was matched in the answer text ---
    themes_with_directional_evidence = {r.theme for r in records}
    for theme, weight in theme_weights.items():
        if theme in themes_with_directional_evidence:
            continue
        records.append(EvidenceRecord(
            respondent_id=answer.respondent_id,
            source_answer_id=answer_id,
            theme=theme,
            evidence_type="neutral_signal",
            direction="neutral",
            strength=0.2,
            evidence_text=answer.answer_text[:200],
            matched_phrases=[], matched_keywords=[],
            question_context_weight=weight,
            sentiment_support=compound,
            source_file=answer.source_file, sheet_name=answer.sheet_name,
            question_number=answer.question_number,
            question_category=answer.question_category,
            question_text=answer.question_text,
        ))

    # --- Behavioral / engagement-history evidence ---
    for flag in behavioral_flags:
        records.append(EvidenceRecord(
            respondent_id=answer.respondent_id,
            source_answer_id=answer_id,
            theme="__behavioral__",
            evidence_type="behavioral_signal",
            direction=_infer_behavioral_direction(answer.answer_text, flag),
            strength=0.7,
            evidence_text=answer.answer_text[:200],
            matched_phrases=[], matched_keywords=[flag],
            question_context_weight=1.0,
            sentiment_support=compound,
            source_file=answer.source_file, sheet_name=answer.sheet_name,
            question_number=answer.question_number,
            question_category=answer.question_category,
            question_text=answer.question_text,
        ))

    return records


def _evidence_type_for(theme: str, direction: str) -> str:
    if theme == "advocacy":
        return "advocacy_signal"
    if theme == "ease_of_engagement" and direction == "negative":
        return "barrier"
    if direction == "positive":
        return "positive_signal"
    if direction == "negative":
        return "negative_signal"
    return "neutral_signal"


def _excerpt_around(text: str, start: int, end: int, pad: int = 40) -> str:
    clean = text
    lo = max(0, start - pad)
    hi = min(len(clean), end + pad)
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(clean) else ""
    return f"{prefix}{clean[lo:hi].strip()}{suffix}"


NEGATIVE_BEHAVIOR_HINTS = ["not", "no longer", "stopped", "havent", "haven't", "never", "don't", "dont"]
_NEGATIVE_HINT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(h) for h in NEGATIVE_BEHAVIOR_HINTS) + r")\b"
)


def _infer_behavioral_direction(answer_text: str, flag: str) -> str:
    """Behavioral flags are booleans, but we still record a 'direction' for
    consistency with the EvidenceRecord schema. A simple word-boundary
    negation check decides whether the flag is being affirmed or denied by
    this answer (word boundaries matter: a plain substring check would
    wrongly match "never" inside "whenever")."""
    lowered = answer_text.lower()
    if _NEGATIVE_HINT_PATTERN.search(lowered):
        return "negative"
    return "positive"

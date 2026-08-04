"""Stage 10/11 (spec sections 30, 31, 39): deterministic, configurable theme
scoring.

Theme Score =
    40% Contextual Evidence Score
  + 25% Phrase / Rule Evidence Score
  + 15% Explicit Rating Score
  + 10% Sentiment Support Score
  + 10% Behavioral / Engagement Evidence Score

Components with no available evidence are dropped from both the numerator
and denominator (a weighted-available-evidence average), so missing
evidence never artificially lowers a score. See section 30 / 31.
"""

from __future__ import annotations

from .config_loader import Config, THEMES
from .models import EvidenceRecord, ThemeScoreResult

# How many mapped questions we'd typically expect a well-answered interview
# to contribute to a single theme, used to normalize evidence_coverage into
# a 0-1 range. This is a configurable heuristic, not a hard requirement --
# tune during calibration (spec section 38) if a cohort's interview guide
# differs meaningfully from the reference JABC guide.
EXPECTED_RELEVANT_QUESTIONS_PER_THEME = 3

CONTEXT_WEIGHT_THRESHOLD = 0.5  # "high-context" question for contextual score


def _direction_sign(direction: str) -> int:
    if direction == "positive":
        return 1
    if direction == "negative":
        return -1
    return 0  # neutral / mixed / unknown contribute no directional pull


def _record_to_1_5(rec: EvidenceRecord) -> float:
    sign = _direction_sign(rec.direction)
    return 3.0 + sign * rec.strength * 2.0


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    """pairs = [(value, weight), ...]. Returns None if no positive weight."""
    total_w = sum(w for _, w in pairs if w > 0)
    if total_w <= 0:
        return None
    return sum(v * w for v, w in pairs if w > 0) / total_w


BEHAVIORAL_THEME_MAP = {
    "advocacy": [("intends_to_continue_jabc", 1.0)],
    "ease_of_engagement": [("has_current_barriers", -1.0), ("has_lapsed_jabc_engagement", -0.7)],
    "trust": [("has_current_jabc_engagement", 0.5)],
    "awareness": [("is_aware_of_jabc", 0.6), ("has_jabc_experience", 0.5)],
    "understanding": [("has_jabc_experience", 0.4)],
    "relevance": [("explores_external_programs", 0.3)],
}


def _contextual_evidence_score(records: list[EvidenceRecord]) -> tuple[float | None, float]:
    high_context = [r for r in records if r.question_context_weight >= CONTEXT_WEIGHT_THRESHOLD
                    and r.evidence_type != "explicit_rating"]
    if not high_context:
        return None, 0.0
    pairs = [(_record_to_1_5(r), r.question_context_weight * max(r.strength, 0.15)) for r in high_context]
    score = _weighted_avg(pairs)
    coverage = min(1.0, len({r.source_answer_id for r in high_context}) / EXPECTED_RELEVANT_QUESTIONS_PER_THEME)
    return score, coverage


def _phrase_rule_evidence_score(records: list[EvidenceRecord]) -> float | None:
    phrase_recs = [r for r in records if r.matched_phrases]
    if not phrase_recs:
        return None
    pairs = [(_record_to_1_5(r), r.strength) for r in phrase_recs]
    return _weighted_avg(pairs)


def _explicit_rating_score(records: list[EvidenceRecord]) -> float | None:
    rating_recs = [r for r in records if r.evidence_type == "explicit_rating"]
    if not rating_recs:
        return None
    pairs = [(_record_to_1_5(r), 1.0) for r in rating_recs]
    return _weighted_avg(pairs)


def _sentiment_support_score(records: list[EvidenceRecord], theme: str,
                              sentiment_theme_relevance: dict) -> float | None:
    relevance = sentiment_theme_relevance.get(theme, 0.0)
    if relevance <= 0:
        return None
    # Only let sentiment influence a theme's score using answers that are
    # actually relevant to that theme via the question-context mapping.
    # Without this guard, a single off-topic keyword hit (default context
    # weight ~0.3) could become the *only* available component for a theme
    # and, since the formula drops unavailable components from the
    # denominator, would end up driving the whole score at full confidence.
    relevant_records = [
        r for r in records
        if r.evidence_type != "explicit_rating" and r.question_context_weight >= 0.4
    ]
    if not relevant_records:
        return None
    compounds = [r.sentiment_support for r in relevant_records]
    avg_compound = sum(compounds) / len(compounds)
    # Scale by relevance, self-normalized against the most sentiment-relevant
    # theme, so the theme configured as most relevant (e.g. trust) gets the
    # full raw signal and lower-relevance themes are damped toward the
    # neutral midpoint -- per this module's config comment, relevance is
    # meant to apply *inside* the sentiment component, not just gate it.
    max_relevance = max(sentiment_theme_relevance.values()) or 1.0
    blend = relevance / max_relevance
    return 3.0 + avg_compound * 2.0 * blend


def _behavioral_evidence_score(theme: str, behavioral_state: dict,
                                 behavioral_detected: set) -> float | None:
    mapping = BEHAVIORAL_THEME_MAP.get(theme, [])
    mapping = [(flag, w) for flag, w in mapping if flag in behavioral_detected]
    if not mapping:
        return None
    total = 0.0
    for flag, weight in mapping:
        present = bool(behavioral_state.get(flag))
        total += weight * (1.0 if present else -1.0)
    avg = total / len(mapping)
    return max(1.0, min(5.0, 3.0 + avg * 2.0))


def _evidence_status(records: list[EvidenceRecord], coverage: float, strength: float,
                      thresholds: dict) -> str:
    if not records:
        return "unknown"

    directions = [r.direction for r in records if r.direction in ("positive", "negative")]
    n_pos = directions.count("positive")
    n_neg = directions.count("negative")
    total_dir = n_pos + n_neg

    if total_dir >= 2 and min(n_pos, n_neg) / total_dir >= thresholds.get("mixed_conflict_ratio", 0.35):
        return "mixed"

    if coverage < 0.2 and strength < thresholds.get("weak_max_strength", 0.30):
        return "insufficient"

    if strength < thresholds.get("weak_max_strength", 0.30):
        return "weak"

    if (coverage >= thresholds.get("supported_min_coverage", 0.60)
            and strength >= thresholds.get("supported_min_strength", 0.55)):
        return "supported"

    return "mixed" if total_dir >= 2 else "weak"


def score_theme(theme: str, evidence_records: list[EvidenceRecord],
                 behavioral_state: dict, config: Config,
                 behavioral_detected: set | None = None) -> ThemeScoreResult:
    theme_records = [r for r in evidence_records if r.theme == theme]
    behavioral_detected = behavioral_detected or set()

    weights = config.scoring_weights.get("theme_scoring_weights", {})
    sentiment_relevance = config.sentiment_weights.get("sentiment_theme_relevance", {})
    thresholds = config.scoring_weights.get("evidence_status_thresholds", {})
    unknown_default = config.persona_rules.get("unknown_default_score", 3.0)

    contextual_score, coverage = _contextual_evidence_score(theme_records)
    phrase_score = _phrase_rule_evidence_score(theme_records)
    explicit_score = _explicit_rating_score(theme_records)
    sentiment_score = _sentiment_support_score(theme_records, theme, sentiment_relevance)
    behavioral_score = _behavioral_evidence_score(theme, behavioral_state, behavioral_detected)

    component_scores = {
        "contextual_evidence": contextual_score,
        "phrase_rule_evidence": phrase_score,
        "explicit_rating": explicit_score,
        "sentiment_support": sentiment_score,
        "behavioral_evidence": behavioral_score,
    }

    available = {k: v for k, v in component_scores.items() if v is not None}

    if not available:
        final_score = unknown_default
        evidence_strength = 0.0
    else:
        total_weight = sum(weights.get(k, 0.0) for k in available)
        if total_weight <= 0:
            final_score = unknown_default
        else:
            final_score = sum(available[k] * weights.get(k, 0.0) for k in available) / total_weight
        strengths = [r.strength for r in theme_records if r.evidence_type != "neutral_signal"]
        evidence_strength = (sum(strengths) / len(strengths)) if strengths else 0.0

    final_score = max(1.0, min(5.0, final_score))

    status = _evidence_status(theme_records, coverage, evidence_strength, thresholds)
    if status == "unknown":
        final_score = unknown_default

    top_evidence = sorted(
        [r for r in theme_records if r.evidence_type != "neutral_signal"],
        key=lambda r: r.strength, reverse=True,
    )[:5]

    return ThemeScoreResult(
        theme=theme,
        final_score=round(final_score, 3),
        evidence_status=status,
        evidence_strength=round(evidence_strength, 3),
        evidence_coverage=round(coverage, 3),
        component_scores={k: (round(v, 3) if v is not None else None) for k, v in component_scores.items()},
        evidence=[e.to_dict() for e in top_evidence],
    )


def score_all_themes(evidence_records: list[EvidenceRecord], behavioral_state: dict,
                       config: Config, behavioral_detected: set | None = None) -> dict[str, ThemeScoreResult]:
    return {
        theme: score_theme(theme, evidence_records, behavioral_state, config, behavioral_detected)
        for theme in THEMES
    }

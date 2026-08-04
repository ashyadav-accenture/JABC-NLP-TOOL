"""Stage 14 (spec section 36): explainable confidence and uncertainty model.

confidence =
    30% evidence_coverage
  + 25% evidence_strength
  + 20% persona_margin_score
  + 15% answer_completeness
  + 10% classification_consistency
"""

from __future__ import annotations

from .config_loader import Config
from .models import ThemeScoreResult


def _classification_consistency(persona_scores: dict, config: Config) -> float:
    """How decisively one persona stands out from ALL competitors, not just
    the runner-up (persona_margin already covers the top-2 gap). Uses the
    standard deviation across every persona's raw score, normalized against
    a reference spread -- a low stdev means several personas are bunched
    together near the top even if the #1-vs-#2 gap alone looks fine."""
    values = list(persona_scores.values())
    if len(values) < 2:
        return 1.0
    mean = sum(values) / len(values)
    stdev = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    reference_stdev = config.persona_rules.get("consistency_reference_stdev", 2.5)
    if reference_stdev <= 0:
        return 1.0
    return max(0.0, min(1.0, stdev / reference_stdev))


def compute_confidence(theme_scores: dict[str, ThemeScoreResult], persona_margin: float,
                         answer_completeness: float, persona_scores: dict,
                         config: Config) -> tuple[float, dict]:
    weights = config.scoring_weights.get("confidence_weights", {
        "evidence_coverage": 0.30, "evidence_strength": 0.25, "persona_margin": 0.20,
        "answer_completeness": 0.15, "classification_consistency": 0.10,
    })

    coverages = [ts.evidence_coverage for ts in theme_scores.values()]
    strengths = [ts.evidence_strength for ts in theme_scores.values()]

    evidence_coverage = sum(coverages) / len(coverages) if coverages else 0.0
    evidence_strength = sum(strengths) / len(strengths) if strengths else 0.0
    persona_margin_score = max(0.0, min(1.0, persona_margin))
    completeness = max(0.0, min(1.0, answer_completeness))
    classification_consistency = _classification_consistency(persona_scores, config)

    factors = {
        "evidence_coverage": round(evidence_coverage, 3),
        "evidence_strength": round(evidence_strength, 3),
        "persona_margin": round(persona_margin_score, 3),
        "answer_completeness": round(completeness, 3),
        "classification_consistency": round(classification_consistency, 3),
    }

    confidence = (
        weights.get("evidence_coverage", 0.30) * evidence_coverage
        + weights.get("evidence_strength", 0.25) * evidence_strength
        + weights.get("persona_margin", 0.20) * persona_margin_score
        + weights.get("answer_completeness", 0.15) * completeness
        + weights.get("classification_consistency", 0.10) * classification_consistency
    )

    return round(max(0.0, min(1.0, confidence)), 3), factors


def compute_classification_confidence(persona_margin: float, persona_scores: dict,
                                        gate_satisfied: bool, supporting_flag_count: int,
                                        config: Config) -> tuple[float, dict]:
    """Confidence in the PERSONA assignment alone.

    Deliberately built from only the three things that bear on which persona
    was chosen -- whether an engagement gate was satisfied, how far the winner
    sits from the runner-up, and how spread out the field is -- and not from
    theme-evidence volume. A respondent can have a thin interview and still be
    an unambiguous Brand Newbie; conversely a chatty interview with no
    engagement signal at all is a genuinely uncertain classification no matter
    how much text it contains.
    """
    weights = config.scoring_weights.get("classification_confidence_weights", {
        "engagement_gate": 0.45, "persona_margin": 0.35,
        "classification_consistency": 0.20,
    })

    # A satisfied gate is the definition being met outright; each corroborating
    # supporting flag ("would run it again", "already recommends it") adds a
    # little more, capped at full credit.
    if gate_satisfied:
        gate_factor = min(1.0, 0.70 + 0.15 * supporting_flag_count)
    else:
        gate_factor = 0.0

    margin_score = max(0.0, min(1.0, persona_margin))
    consistency = _classification_consistency(persona_scores, config)

    factors = {
        "engagement_gate": round(gate_factor, 3),
        "persona_margin": round(margin_score, 3),
        "classification_consistency": round(consistency, 3),
    }

    score = (
        weights.get("engagement_gate", 0.45) * gate_factor
        + weights.get("persona_margin", 0.35) * margin_score
        + weights.get("classification_consistency", 0.20) * consistency
    )
    return round(max(0.0, min(1.0, score)), 3), factors

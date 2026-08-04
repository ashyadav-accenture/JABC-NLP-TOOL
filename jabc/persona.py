"""Stage 12/13: independent Brand Persona classification.

The personas are relationship states, so classification is gate-first:

    engagement gate (config/persona_rules.yaml -> personas.*.engagement_gate)
        decides WHICH persona, using the structured engagement flags produced
        by engagement.py -- JABC history, whether that history is live or
        lapsed, and (for respondents with no JABC history) whether they
        actively and happily run other external programs.

    theme-score fit
        decides HOW WELL the respondent sits inside that persona. It sets the
        classification margin, feeds confidence, and is the sole basis for the
        decision when an interview carries no usable engagement evidence.

This ordering is what separates the pairs that no threshold arrangement can:
a Champion who is vocal about JABC's portal friction still scores low on
ease_of_engagement, and a Non-Active Supporter who remembers JABC fondly still
scores high on trust. Classification never uses average theme score alone.

The original worksheet persona label is never used as ground truth; it is
carried through purely as metadata for the validation report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config_loader import Config, PERSONAS, PERSONA_DISPLAY_NAMES
from .models import ThemeScoreResult


@dataclass
class PersonaResult:
    brand_persona: str
    persona_display_name: str
    persona_scores: dict
    persona_margin: float
    classification_reasoning: str
    manual_review_flag: bool
    manual_review_reason: str
    gate_satisfied: bool = False
    supporting_flag_count: int = 0
    engagement_summary: str = ""
    persona_gates: dict = field(default_factory=dict)


def _theme_value(theme_scores: dict[str, ThemeScoreResult], theme: str) -> float:
    ts = theme_scores.get(theme)
    return ts.final_score if ts else 3.0


def _range_fit(value: float, low: float, high: float) -> float:
    """1.0 if value is within [low, high]; decays linearly outside it."""
    if low <= value <= high:
        return 1.0
    dist = (low - value) if value < low else (value - high)
    return max(0.0, 1.0 - dist / 2.0)


def _fit_score(rules: dict, theme_scores: dict[str, ThemeScoreResult]) -> float:
    """Mean per-theme fit against the persona's typical ranges, on a 0-5 scale."""
    typical = rules.get("typical_range", {})
    if not typical:
        return 3.0
    fits = [
        _range_fit(_theme_value(theme_scores, theme), low, high)
        for theme, (low, high) in typical.items()
    ]
    return (sum(fits) / len(fits)) * 5.0


def _evaluate_gate(rules: dict, behavioral_state: dict) -> tuple[bool, list[str]]:
    """Evaluates one persona's engagement gate.

    Returns (satisfied, reasons). A gate with no conditions at all is treated
    as unsatisfied rather than trivially true -- an unconfigured persona must
    not silently absorb every respondent.
    """
    gate = rules.get("engagement_gate", {}) or {}
    all_of = list(gate.get("all_of", []))
    none_of = list(gate.get("none_of", []))
    any_of = list(gate.get("any_of", []))

    if not (all_of or none_of or any_of):
        return False, ["no engagement gate configured"]

    reasons: list[str] = []
    satisfied = True

    for flag in all_of:
        if not behavioral_state.get(flag, False):
            satisfied = False
            reasons.append(f"requires {flag}")

    for flag in none_of:
        if behavioral_state.get(flag, False):
            satisfied = False
            reasons.append(f"excluded by {flag}")

    if any_of and not any(behavioral_state.get(f, False) for f in any_of):
        satisfied = False
        reasons.append(f"requires any of {any_of}")

    return satisfied, reasons


def _has_any_engagement_evidence(behavioral_state: dict) -> bool:
    """True when at least one engagement flag is affirmatively set.

    An interview where every flag is False carries no relationship evidence at
    all (an empty or unparseable sheet), and must fall back to theme-score fit
    plus a manual-review flag rather than being handed to whichever persona's
    gate is written as a pure exclusion.
    """
    gate_flags = [
        "has_jabc_experience", "has_current_jabc_engagement",
        "has_lapsed_jabc_engagement", "intends_to_continue_jabc",
        "runs_external_programs", "explores_external_programs",
        "has_positive_external_experience", "has_negative_external_experience",
        "is_hesitant_about_external_programs", "has_no_external_experience",
        # Legacy names, so a caller supplying only the older flags still counts
        # as having evidence.
        "has_prior_jabc_engagement", "has_advocated_for_jabc",
        "has_reduced_or_stopped_engagement", "has_used_competing_programs",
        "is_open_to_external_programming",
    ]
    return any(behavioral_state.get(f, False) for f in gate_flags)


def classify_persona(theme_scores: dict[str, ThemeScoreResult], behavioral_state: dict,
                       config: Config, engagement_summary: str = "") -> PersonaResult:
    persona_rules = config.persona_rules.get("personas", {})
    margin_threshold = config.persona_rules.get("classification_margin_threshold", 0.20)
    gate_bonus = config.persona_rules.get("gate_bonus", 6.0)
    support_bonus = config.persona_rules.get("supporting_flag_bonus", 0.5)
    precedence = config.persona_rules.get("gate_precedence", list(PERSONAS))

    behavioral_state = _with_derived_flags(behavioral_state)
    has_evidence = _has_any_engagement_evidence(behavioral_state)

    scores: dict[str, float] = {}
    gates: dict[str, bool] = {}
    gate_reasons: dict[str, list[str]] = {}
    support_counts: dict[str, int] = {}

    for persona_key in PERSONAS:
        rules = persona_rules.get(persona_key, {})
        gate_ok, reasons = _evaluate_gate(rules, behavioral_state)
        # With no engagement evidence anywhere, a gate built purely from
        # `none_of` would "pass" on absence alone. Suppress every gate in that
        # case so the decision falls through to theme-score fit.
        if not has_evidence:
            gate_ok = False
            reasons = ["no engagement evidence in this interview"]

        n_support = sum(
            1 for flag in rules.get("supporting_flags", [])
            if behavioral_state.get(flag, False)
        )

        fit = _fit_score(rules, theme_scores)
        scores[persona_key] = fit + (gate_bonus if gate_ok else 0.0) + support_bonus * n_support
        gates[persona_key] = gate_ok
        gate_reasons[persona_key] = reasons
        support_counts[persona_key] = n_support

    satisfied = [p for p in precedence if p in PERSONAS and gates.get(p)]

    if satisfied:
        top = satisfied[0]
        # Rank the rest by score so the runner-up (and therefore the margin)
        # reflects the nearest competing persona.
        others = sorted((p for p in PERSONAS if p != top), key=lambda p: scores[p], reverse=True)
        ranked = [top] + others
    else:
        ranked = sorted(PERSONAS, key=lambda p: scores[p], reverse=True)
        top = ranked[0]

    second = ranked[1]
    max_spread = gate_bonus + 5.0 + support_bonus * 3
    margin = round(max(0.0, scores[top] - scores[second]) / max_spread, 3)

    manual_review = False
    manual_review_reason = ""

    if not gates.get(top):
        manual_review = True
        why = "; ".join(gate_reasons[top]) or "n/a"
        manual_review_reason = (
            f"No persona's engagement gate was satisfied; closest match by theme-score fit "
            f"was {PERSONA_DISPLAY_NAMES[top]} ({why})."
        )
    elif len(satisfied) > 1:
        manual_review = True
        manual_review_reason = (
            f"More than one engagement gate was satisfied "
            f"({', '.join(PERSONA_DISPLAY_NAMES[p] for p in satisfied)}); "
            f"resolved to {PERSONA_DISPLAY_NAMES[top]} by gate precedence."
        )
    elif margin < margin_threshold:
        manual_review = True
        manual_review_reason = (
            f"Classification margin {margin:.2f} is below the threshold "
            f"{margin_threshold}: {PERSONA_DISPLAY_NAMES[top]} vs {PERSONA_DISPLAY_NAMES[second]}."
        )

    reasoning_bits = [
        f"{PERSONA_DISPLAY_NAMES[p]}={scores[p]:.2f}"
        f"{' [gate]' if gates.get(p) else ''}"
        f"{f' [+{support_counts[p]} support]' if support_counts[p] else ''}"
        for p in ranked
    ]
    basis = "engagement gate" if gates.get(top) else "theme-score fit (no gate satisfied)"
    classification_reasoning = (
        f"Selected {PERSONA_DISPLAY_NAMES[top]} via {basis} (margin={margin:.2f}). "
        f"Persona scores: {', '.join(reasoning_bits)}."
    )
    if engagement_summary:
        classification_reasoning += f" Engagement state: {engagement_summary}"

    return PersonaResult(
        brand_persona=top,
        persona_display_name=PERSONA_DISPLAY_NAMES[top],
        persona_scores={p: round(scores[p], 3) for p in PERSONAS},
        persona_margin=margin,
        classification_reasoning=classification_reasoning,
        manual_review_flag=manual_review,
        manual_review_reason=manual_review_reason,
        gate_satisfied=bool(gates.get(top)),
        supporting_flag_count=support_counts[top],
        engagement_summary=engagement_summary,
        persona_gates=gates,
    )


def _with_derived_flags(behavioral_state: dict) -> dict:
    """Fills in engagement flags that a caller may only have supplied under
    their legacy names, so classify_persona can be called with either
    vocabulary (the pipeline supplies both; unit tests supply the old ones)."""
    state = dict(behavioral_state)

    if "has_jabc_experience" not in state:
        state["has_jabc_experience"] = bool(
            state.get("has_prior_jabc_engagement")
            or state.get("has_current_jabc_engagement")
            or state.get("has_reduced_or_stopped_engagement")
        )
    if "has_lapsed_jabc_engagement" not in state:
        state["has_lapsed_jabc_engagement"] = bool(
            state.get("has_reduced_or_stopped_engagement")
        )
    if "has_current_jabc_engagement" not in state:
        state["has_current_jabc_engagement"] = bool(
            state.get("has_jabc_experience") and not state.get("has_lapsed_jabc_engagement")
        )
    if "intends_to_continue_jabc" not in state:
        state["intends_to_continue_jabc"] = bool(state.get("has_advocated_for_jabc"))
    if "runs_external_programs" not in state:
        state["runs_external_programs"] = bool(state.get("has_used_competing_programs"))
    if "explores_external_programs" not in state:
        state["explores_external_programs"] = bool(
            state.get("runs_external_programs") or state.get("is_open_to_external_programming")
        )

    return state

"""Stage 19: Brand Health Matrix aggregation.

Averages respondent theme scores within each *reported* Brand Persona -- the
two merged personas (Established Supporters, Potential Adopters), not the four
classification personas that feed them. Every group always appears in the
matrix, even with zero respondents (spec section 14.3 / 43 "Output" tests).

The averages are taken over the group's respondents directly, not as a mean of
the two member personas' means: averaging means would silently weight a
one-respondent Champion row equally with a five-respondent Non-Active Supporter
row.
"""

from __future__ import annotations

import pandas as pd

from .config_loader import (
    THEMES,
    persona_group_display_names,
    persona_groups,
)
from .models import RespondentProfile

MATRIX_COLUMNS = [
    "Brand Persona", "Awareness", "Understanding", "Trust", "Relevance",
    "Ease of Engagement", "Advocacy", "Average Score", "Respondent Count",
    "Reliability Flag",
]

THEME_DISPLAY = {
    "awareness": "Awareness",
    "understanding": "Understanding",
    "trust": "Trust",
    "relevance": "Relevance",
    "ease_of_engagement": "Ease of Engagement",
    "advocacy": "Advocacy",
}

# Floor applied to a respondent's confidence when used as an aggregation
# weight, so a near-zero-confidence respondent is heavily down-weighted
# rather than fully erased (and never causes a division-by-zero-adjacent
# all-weights-zero case).
MIN_CONFIDENCE_WEIGHT = 0.05

LOW_N_THRESHOLD_DEFAULT = 3

# Theme cells that are left blank for a given persona because the question was
# never meaningfully put to them. Declared per classification persona and
# lifted to the reported groups by group_not_applicable_themes(); both members
# of Potential Adopters carry the same suppression, so the merged row blanks
# the same two cells its parts did.
#
# Brand Prospects and Brand Newbies have no JABC participation history by
# definition, so they were never routed through Section E (JABC experience) or
# asked Q9.3 (would you recommend it). Any ease_of_engagement or advocacy score
# they carry is therefore built from the "unknown defaults to neutral 3.0" rule
# plus incidental keyword matches on answers about *other* programs -- it
# measures the absence of evidence, not the educator's view of JABC. Reporting
# it next to a Champion's score, which comes from someone who actually
# registered for a program and decided whether to recommend it, invites a
# comparison that the underlying data cannot support.
#
# Suppressed cells are excluded from that persona's Average Score and from the
# column's cross-persona average, so no blanked number leaks back in through an
# aggregate. Overridable per persona via `not_applicable_themes` in
# persona_rules.yaml.
NOT_APPLICABLE_THEMES = {
    "brand_prospect": ["ease_of_engagement", "advocacy"],
    "brand_newbie": ["ease_of_engagement", "advocacy"],
}


def not_applicable_themes(config=None) -> dict[str, list[str]]:
    """Resolves the suppression map, letting persona_rules.yaml override the
    built-in default. The default applies even when no config is passed, so a
    caller that forgets to thread it through cannot silently start publishing
    the blanked scores."""
    if config is None:
        return dict(NOT_APPLICABLE_THEMES)

    resolved = dict(NOT_APPLICABLE_THEMES)
    personas = (getattr(config, "persona_rules", {}) or {}).get("personas", {})
    for persona_key, rules in personas.items():
        if "not_applicable_themes" in (rules or {}):
            resolved[persona_key] = list(rules["not_applicable_themes"] or [])
    return resolved


def group_not_applicable_themes(config=None) -> dict[str, list[str]]:
    """The suppression map lifted to the reported groups. A theme is blanked
    for a group only when it is not applicable to EVERY member persona -- if
    one member was genuinely asked the question, the group's average carries
    real evidence and must be published. (Today both pairs agree, so this is a
    guard against a future regrouping quietly hiding a scored cell.)"""
    per_persona = not_applicable_themes(config)
    resolved = {}
    for group_key, members in persona_groups(config).items():
        if not members:
            resolved[group_key] = []
            continue
        common = set(per_persona.get(members[0], []))
        for member in members[1:]:
            common &= set(per_persona.get(member, []))
        resolved[group_key] = [t for t in THEMES if t in common]
    return resolved


def suppressed_cells(config=None) -> set[tuple[str, str]]:
    """The suppression map as {(reported persona display name, theme display
    name)}, which is the form the exporters need."""
    display = persona_group_display_names(config)
    return {
        (display[group_key], THEME_DISPLAY[theme])
        for group_key, themes in group_not_applicable_themes(config).items()
        if group_key in display
        for theme in themes
        if theme in THEME_DISPLAY
    }


def _theme_average(persona_profiles: list[RespondentProfile], theme: str,
                     weight_by_confidence: bool) -> float | None:
    pairs = [(p.theme_scores[theme].final_score, max(p.confidence, MIN_CONFIDENCE_WEIGHT))
             for p in persona_profiles if theme in p.theme_scores]
    if not pairs:
        return None
    if not weight_by_confidence:
        return round(sum(v for v, _ in pairs) / len(pairs), 2)
    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        return round(sum(v for v, _ in pairs) / len(pairs), 2)
    return round(sum(v * w for v, w in pairs) / total_weight, 2)


def build_brand_health_matrix(profiles: list[RespondentProfile], weight_by_confidence: bool = False,
                                low_n_threshold: int = LOW_N_THRESHOLD_DEFAULT,
                                config=None) -> pd.DataFrame:
    """`weight_by_confidence=False` (the default) reproduces the original
    plain-mean behavior exactly. When True, each respondent's theme score is
    weighted by their own `confidence` in the per-persona average, so a
    low-confidence respondent influences the reported average less than a
    high-confidence one. Regardless of weighting, a "Reliability Flag" notes
    when a persona's average rests on too few respondents (< low_n_threshold)
    to be treated as a stable estimate."""
    not_applicable = group_not_applicable_themes(config)
    display = persona_group_display_names(config)

    rows = []
    for group_key, members in persona_groups(config).items():
        persona_profiles = [p for p in profiles if p.brand_persona in members]
        blanked = set(not_applicable.get(group_key, []))
        row = {"Brand Persona": display[group_key]}
        for theme in THEMES:
            row[THEME_DISPLAY[theme]] = (
                None if theme in blanked
                else _theme_average(persona_profiles, theme, weight_by_confidence)
            )
        # Suppressed cells drop out of the row average here by virtue of being
        # None, so a persona's Average Score is the mean of the themes that
        # were actually asked about -- never a blend of real scores with the
        # neutral placeholders the blanking exists to hide.
        theme_avgs = [row[THEME_DISPLAY[t]] for t in THEMES if row[THEME_DISPLAY[t]] is not None]
        row["Average Score"] = round(sum(theme_avgs) / len(theme_avgs), 2) if theme_avgs else None
        n = len(persona_profiles)
        row["Respondent Count"] = n
        row["Reliability Flag"] = f"Low N (n={n}) -- treat with caution" if 0 < n < low_n_threshold else ""
        rows.append(row)

    return pd.DataFrame(rows, columns=MATRIX_COLUMNS)

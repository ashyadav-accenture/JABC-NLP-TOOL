"""Stage 15/18 (spec section 38): calibration and human validation.

Expects a human-review CSV with one row per (respondent, theme):

    respondent_id, theme, human_score, human_persona

`human_persona` may be repeated identically across a respondent's theme
rows for convenience. Calibration data and reports are kept entirely
separate from the production respondent/evidence/matrix outputs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .models import RespondentProfile

logger = logging.getLogger(__name__)

CALIBRATION_COLUMNS = [
    "respondent_id", "theme", "human_score", "automated_score", "absolute_difference",
    "human_persona", "automated_persona", "persona_match",
]


def _dedupe_persona_rows(report_df: pd.DataFrame) -> pd.DataFrame:
    """One row per respondent (not per theme row), so a respondent with more
    theme rows in the human-review CSV doesn't get counted multiple times
    when computing persona_match_rate."""
    rows = []
    for rid, grp in report_df.groupby("respondent_id", sort=False):
        human_personas = grp["human_persona"].unique()
        if len(human_personas) > 1:
            logger.warning(
                "Calibration: respondent '%s' has inconsistent human_persona values "
                "across theme rows: %s; using the first.", rid, list(human_personas),
            )
        rows.append({
            "respondent_id": rid,
            "human_persona": grp["human_persona"].iloc[0],
            "automated_persona": grp["automated_persona"].iloc[0],
            "persona_match": grp["persona_match"].iloc[0],
        })
    return pd.DataFrame(rows, columns=["respondent_id", "human_persona", "automated_persona", "persona_match"])


def run_calibration(profiles: list[RespondentProfile], human_review_csv: str | Path,
                     theme_match_tolerance: float = 0.5) -> tuple[pd.DataFrame, dict]:
    human_review_csv = Path(human_review_csv)
    if not human_review_csv.exists():
        raise FileNotFoundError(f"Human review file not found: {human_review_csv}")

    human_df = pd.read_csv(human_review_csv)
    required = {"respondent_id", "theme", "human_score", "human_persona"}
    missing = required - set(human_df.columns)
    if missing:
        raise ValueError(f"Human review CSV is missing required columns: {missing}")

    profiles_by_id = {p.respondent_id: p for p in profiles}

    rows = []
    for _, hrow in human_df.iterrows():
        respondent_id = str(hrow["respondent_id"])
        theme = str(hrow["theme"])
        human_score = float(hrow["human_score"])
        human_persona = str(hrow["human_persona"])

        profile = profiles_by_id.get(respondent_id)
        if profile is None:
            logger.warning("Calibration: no automated profile found for respondent '%s'.", respondent_id)
            continue

        ts = profile.theme_scores.get(theme)
        automated_score = ts.final_score if ts else None
        automated_persona = profile.persona_display_name

        abs_diff = abs(human_score - automated_score) if automated_score is not None else None
        persona_match = human_persona.strip().lower() == automated_persona.strip().lower()

        rows.append({
            "respondent_id": respondent_id,
            "theme": theme,
            "human_score": human_score,
            "automated_score": automated_score,
            "absolute_difference": round(abs_diff, 3) if abs_diff is not None else None,
            "human_persona": human_persona,
            "automated_persona": automated_persona,
            "persona_match": persona_match,
        })

    report_df = pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)

    valid_diffs = report_df["absolute_difference"].dropna()
    mean_absolute_error = float(valid_diffs.mean()) if not valid_diffs.empty else None
    theme_match_rate = float((valid_diffs <= theme_match_tolerance).mean()) if not valid_diffs.empty else None

    # Computed per-respondent (deduped), not per theme row, so a respondent
    # with more theme rows in the CSV isn't overweighted in the match rate.
    persona_rows = _dedupe_persona_rows(report_df)
    persona_match_rate = float(persona_rows["persona_match"].mean()) if not persona_rows.empty else None
    confusion_matrix = (
        pd.crosstab(persona_rows["human_persona"], persona_rows["automated_persona"]).to_dict()
        if not persona_rows.empty else {}
    )

    summary = {
        "mean_absolute_error": round(mean_absolute_error, 3) if mean_absolute_error is not None else None,
        "theme_match_rate": round(theme_match_rate, 3) if theme_match_rate is not None else None,
        "persona_match_rate": round(persona_match_rate, 3) if persona_match_rate is not None else None,
        "n_theme_rows": len(report_df),
        "n_respondents": report_df["respondent_id"].nunique() if not report_df.empty else 0,
        "confusion_matrix": confusion_matrix,
    }

    return report_df, summary

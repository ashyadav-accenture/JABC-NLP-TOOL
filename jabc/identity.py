"""Stage 3 (spec section 32): Respondent identity resolution.

Hierarchy, from most to least confident:
  1. Explicit respondent ID cell in the workbook (e.g. "Respondent ID: R014")
  2. Explicit respondent/interviewee name in workbook metadata
  3. Workbook-level respondent identifier (e.g. a "Cover" sheet field)
  4. Filename-derived identifier
  5. Sheet-level grouping (last resort; flags manual review)

The system never silently merges what might be different respondents: if
identity can only be established at low confidence, `manual_review_flag`
is set True by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

NAME_LABEL_PATTERNS = [
    r"respondent\s*id",
    r"respondent\s*name",
    r"interviewee",
    r"participant\s*name",
    r"^name$",
    r"educator\s*name",
]

MAX_METADATA_SCAN_ROWS = 15
MAX_METADATA_SCAN_COLS = 8

# Interview workbook filenames follow "Interview_<First>_<Last>_<Date>_<Role>_<Status>",
# e.g. "Interview_Amanda_Reid_July15_Teacher_Unfamiliar". The 2nd and 3rd words are the
# interviewee's first/last name, whether the file uses underscores or spaces as
# separators (e.g. "Interview_Karina Thygesen_July21_Teacher_Active").
INTERVIEW_FILENAME_NAME_RE = re.compile(
    r"^interview[_\s]+([A-Za-z'\-]+)[_\s]+([A-Za-z'\-]+)", re.IGNORECASE
)


def _extract_name_from_filename(stem: str) -> str | None:
    """Prune an interview filename stem down to just the interviewee's name."""
    match = INTERVIEW_FILENAME_NAME_RE.match(stem.strip())
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    return f"{first}_{last}"


@dataclass
class RespondentIdentity:
    respondent_id: str
    respondent_id_source: str  # "explicit_id" | "explicit_name" | "workbook_metadata" |
                                # "filename" | "sheet_grouping"
    respondent_id_confidence: float


def _sanitize_id(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^\w\-]", "", text)
    return text or "UNKNOWN"


MAX_PLAUSIBLE_NAME_LENGTH = 60


def _looks_like_name(text: str) -> bool:
    """Reject metadata-scan matches that are clearly not a short name/ID --
    e.g. an entire bio-plus-interview-transcript pasted into the cell next to
    a 'Name' label. Without this guard that whole cell gets treated as the
    respondent's name."""
    if not text or len(text) > MAX_PLAUSIBLE_NAME_LENGTH:
        return False
    if text.count(".") > 1:
        return False
    return True


def _scan_sheet_for_name(df: pd.DataFrame) -> str | None:
    """Look in the top-left corner of a sheet for a 'Name:'-style metadata
    field and return the adjacent value, if any."""
    n_rows = min(MAX_METADATA_SCAN_ROWS, len(df))
    n_cols = min(MAX_METADATA_SCAN_COLS, df.shape[1])
    for r in range(n_rows):
        for c in range(n_cols):
            val = df.iat[r, c] if c < df.shape[1] else None
            if val is None:
                continue
            text = str(val).strip().lower()
            if any(re.search(p, text) for p in NAME_LABEL_PATTERNS):
                # Prefer the same cell after a colon, else the next cell to
                # the right, else the cell below.
                if ":" in text:
                    after = str(val).split(":", 1)[1].strip()
                    if after:
                        return after
                if c + 1 < df.shape[1]:
                    neighbor = df.iat[r, c + 1] if r < len(df) else None
                    if neighbor is not None and str(neighbor).strip():
                        return str(neighbor).strip()
                if r + 1 < len(df):
                    below = df.iat[r + 1, c]
                    if below is not None and str(below).strip():
                        return str(below).strip()
    return None


def resolve_workbook_identity(path: Path, sheets: dict[str, pd.DataFrame]) -> RespondentIdentity:
    """Attempt to resolve one respondent identity for an entire workbook by
    scanning all of its sheets for explicit name/ID metadata before falling
    back to the filename.
    """
    for sheet_name, df in sheets.items():
        name = _scan_sheet_for_name(df)
        if name and _looks_like_name(name):
            return RespondentIdentity(
                respondent_id=_sanitize_id(name),
                respondent_id_source="workbook_metadata",
                respondent_id_confidence=0.9,
            )

    stem = path.stem
    name = _extract_name_from_filename(stem)
    return RespondentIdentity(
        respondent_id=_sanitize_id(name or stem),
        respondent_id_source="filename",
        respondent_id_confidence=0.70,
    )


def resolve_sheet_level_identity(path: Path, sheet_name: str) -> RespondentIdentity:
    """Last-resort fallback: group by file + sheet name. Lower confidence;
    callers should set manual_review_flag when this path is used.
    """
    name = _extract_name_from_filename(path.stem)
    combined = f"{name or path.stem}__{sheet_name}"
    return RespondentIdentity(
        respondent_id=_sanitize_id(combined),
        respondent_id_source="sheet_grouping",
        respondent_id_confidence=0.45,
    )

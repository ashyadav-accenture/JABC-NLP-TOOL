"""Stage 2: Sheet classifier.

Determines, for each sheet in a workbook, whether it is:
  - a completed interview-response sheet (has question/answer columns with
    at least one non-blank, non-template answer), or
  - a reference-only sheet (question bank, persona guide, flow guide,
    methodology notes), which is excluded from scoring unless explicitly
    requested via --include_reference_sheets.

Design principle (section 22): do not overfit to one workbook's exact sheet
names or column headers. Detect column roles heuristically by scanning for
header-like text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

REFERENCE_SHEET_NAME_PATTERNS = [
    r"question\s*bank",
    r"persona",
    r"goals?",
    r"flow",
    r"methodolog",
    r"instructions?",
    r"read\s*me",
    r"cover",
]

QUESTION_COL_PATTERNS = [r"^question$", r"question\s*text", r"^q$"]
QUESTION_NUM_PATTERNS = [r"question\s*(no\.?|number|#)", r"^q\s*#$", r"^#$"]
CATEGORY_COL_PATTERNS = [r"question\s*category", r"^category$", r"^section$"]
ANSWER_COL_PATTERNS = [r"answer", r"response"]
NOTES_COL_PATTERNS = [r"notes?", r"comments?"]

MAX_HEADER_SCAN_ROWS = 20

# Values that look like an answer field but really mean "no answer given".
TEMPLATE_PLACEHOLDER_PATTERNS = [
    r"^record answer.*here$",
    r"^\[.*\]$",
    r"^n/?a$",
    r"^tbd$",
    r"^-+$",
    r"^\.+$",
]


def _clean_header_text(val) -> str:
    if val is None:
        return ""
    text = str(val).strip().lower()
    return text


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


@dataclass
class SheetSchema:
    sheet_name: str
    header_row_index: int
    question_num_col: int | None
    question_col: int | None
    category_col: int | None
    answer_col: int | None
    notes_col: int | None
    is_reference_only: bool
    is_completed_response_sheet: bool
    reason: str = ""


def _looks_like_reference_sheet_name(sheet_name: str) -> bool:
    name = sheet_name.strip().lower()
    return _matches_any(name, REFERENCE_SHEET_NAME_PATTERNS)


def _detect_header_row(df: pd.DataFrame) -> tuple[int | None, dict[str, int]]:
    """Scan the first N rows for a header row containing recognizable column
    labels. Returns (header_row_index, {"question_num":col, "question":col,
    "category":col, "answer":col, "notes":col}) using -1 for cols not found.
    """
    n_rows = min(MAX_HEADER_SCAN_ROWS, len(df))
    best_row = None
    best_cols: dict[str, int] = {}
    best_score = 0

    for row_idx in range(n_rows):
        row = df.iloc[row_idx]
        cols_found: dict[str, int] = {}
        for col_idx, val in enumerate(row):
            text = _clean_header_text(val)
            if not text:
                continue
            if "question_num" not in cols_found and _matches_any(text, QUESTION_NUM_PATTERNS):
                cols_found["question_num"] = col_idx
            elif "question" not in cols_found and _matches_any(text, QUESTION_COL_PATTERNS):
                cols_found["question"] = col_idx
            if "category" not in cols_found and _matches_any(text, CATEGORY_COL_PATTERNS):
                cols_found["category"] = col_idx
            if "answer" not in cols_found and _matches_any(text, ANSWER_COL_PATTERNS):
                cols_found["answer"] = col_idx
            if "notes" not in cols_found and _matches_any(text, NOTES_COL_PATTERNS):
                cols_found["notes"] = col_idx

        # A usable header row needs at minimum a question-like column and an
        # answer-like column.
        score = len(cols_found)
        has_question = "question" in cols_found or "question_num" in cols_found
        has_answer = "answer" in cols_found
        if has_question and has_answer and score > best_score:
            best_score = score
            best_row = row_idx
            best_cols = cols_found

    return best_row, best_cols


def _is_template_placeholder(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    return _matches_any(t, TEMPLATE_PLACEHOLDER_PATTERNS)


def classify_sheet(sheet_name: str, df: pd.DataFrame,
                    include_reference_sheets: bool = False) -> SheetSchema:
    name_is_reference = _looks_like_reference_sheet_name(sheet_name)

    header_row, cols = _detect_header_row(df)

    if header_row is None:
        reason = "no recognizable question/answer header row found"
        return SheetSchema(
            sheet_name=sheet_name, header_row_index=-1,
            question_num_col=None, question_col=None, category_col=None,
            answer_col=None, notes_col=None,
            is_reference_only=name_is_reference or not include_reference_sheets,
            is_completed_response_sheet=False,
            reason=reason,
        )

    answer_col = cols.get("answer")
    has_completed_answer = False
    if answer_col is not None:
        for row_idx in range(header_row + 1, len(df)):
            val = df.iat[row_idx, answer_col] if answer_col < df.shape[1] else None
            text = "" if val is None else str(val).strip()
            if text and not _is_template_placeholder(text):
                has_completed_answer = True
                break

    is_reference_only = name_is_reference and not has_completed_answer
    is_completed = has_completed_answer and not (name_is_reference and not include_reference_sheets)

    reason_bits = []
    if name_is_reference:
        reason_bits.append("sheet name matches reference-sheet pattern")
    if not has_completed_answer:
        reason_bits.append("no completed (non-template) answers found")
    reason = "; ".join(reason_bits) if reason_bits else "completed interview-response sheet detected"

    return SheetSchema(
        sheet_name=sheet_name,
        header_row_index=header_row,
        question_num_col=cols.get("question_num"),
        question_col=cols.get("question"),
        category_col=cols.get("category"),
        answer_col=answer_col,
        notes_col=cols.get("notes"),
        is_reference_only=is_reference_only,
        is_completed_response_sheet=is_completed,
        reason=reason,
    )


def classify_workbook_sheets(sheets: dict[str, pd.DataFrame],
                              include_reference_sheets: bool = False) -> dict[str, SheetSchema]:
    result = {}
    for sheet_name, df in sheets.items():
        result[sheet_name] = classify_sheet(sheet_name, df, include_reference_sheets)
    return result

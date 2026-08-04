"""Stage 3/4: Question-answer extraction and respondent grouping.

Turns a classified, completed interview-response sheet into a list of
RawAnswer records, skipping blank/template-only rows (spec section 1.4/22).
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from .models import RawAnswer
from .sheet_classifier import SheetSchema, _is_template_placeholder

logger = logging.getLogger(__name__)


def _clean_cell(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    text = str(val).strip()
    return text


def _normalize_question_number(val, fallback_seq: int) -> str:
    """Fixes floating point artifacts like '4.0999999999999996' -> '4.1',
    and whole floats like '3.0' -> '3'. Falls back to a sequential id when
    no usable value is present.
    """
    text = _clean_cell(val)
    if not text:
        return f"Q{fallback_seq}"
    try:
        num = float(text)
        rounded = round(num, 2)
        if rounded == int(rounded):
            return str(int(rounded))
        return f"{rounded:g}"
    except ValueError:
        return text


def count_applicable_questions(df: pd.DataFrame, schema: SheetSchema,
                                 answered_sections: set[str], section_of_row) -> int:
    """Counts the questions this respondent was actually asked.

    The interview guide is a single 50-row template that branches by persona:
    a currently-active teacher is never routed into Section F (lapsed
    engagement) or Section G (never ran an external program), and a
    superintendent-only Section H never applies to them at all. Measuring
    answer completeness against all 50 rows therefore puts every respondent
    around 0.2 and trips the "most answers are blank" review flag for
    everyone, which makes the flag useless.

    So the denominator is restricted to rows that (a) carry real question text
    -- not section banners or blank spacers -- and (b) sit in a section this
    respondent engaged with at all. What remains is the question this flag is
    actually meant to answer: of the questions they were asked, how many did
    they answer?
    """
    if schema.question_col is None:
        return 0

    count = 0
    for row_idx in range(schema.header_row_index + 1, len(df)):
        if schema.question_col >= df.shape[1]:
            break
        question_text = _clean_cell(df.iat[row_idx, schema.question_col])
        if not question_text or question_text.upper().startswith("SECTION"):
            continue

        q_num_raw = None
        if schema.question_num_col is not None and schema.question_num_col < df.shape[1]:
            q_num_raw = df.iat[row_idx, schema.question_num_col]
        question_number = _normalize_question_number(q_num_raw, row_idx)

        section = section_of_row(question_number, question_text)
        if answered_sections and section is not None and section not in answered_sections:
            continue
        count += 1

    return count


def extract_answers_from_sheet(
    source_file: str,
    sheet_name: str,
    df: pd.DataFrame,
    schema: SheetSchema,
    respondent_id: str,
    respondent_id_source: str,
    respondent_id_confidence: float,
) -> list[RawAnswer]:
    """Extract RawAnswer rows from one completed response sheet."""
    if not schema.is_completed_response_sheet or schema.answer_col is None:
        return []

    answers: list[RawAnswer] = []
    seq = 0

    for row_idx in range(schema.header_row_index + 1, len(df)):
        answer_val = df.iat[row_idx, schema.answer_col] if schema.answer_col < df.shape[1] else None
        answer_text = _clean_cell(answer_val)

        if not answer_text or _is_template_placeholder(answer_text):
            continue  # blank / template-only row (spec 1.4)

        seq += 1

        q_num_raw = None
        if schema.question_num_col is not None and schema.question_num_col < df.shape[1]:
            q_num_raw = df.iat[row_idx, schema.question_num_col]
        question_number = _normalize_question_number(q_num_raw, seq)

        question_text = ""
        if schema.question_col is not None and schema.question_col < df.shape[1]:
            question_text = _clean_cell(df.iat[row_idx, schema.question_col])

        category = ""
        if schema.category_col is not None and schema.category_col < df.shape[1]:
            category = _clean_cell(df.iat[row_idx, schema.category_col])

        notes = ""
        if schema.notes_col is not None and schema.notes_col < df.shape[1]:
            notes = _clean_cell(df.iat[row_idx, schema.notes_col])

        if not question_text and not category:
            # A row with an answer but no discoverable question context is
            # still preserved -- unknown context, not an error -- but is
            # logged so it can be reviewed.
            logger.debug(
                "Row %d in sheet '%s' (%s) has an answer with no question "
                "text/category context.", row_idx, sheet_name, source_file,
            )

        answers.append(
            RawAnswer(
                respondent_id=respondent_id,
                source_file=source_file,
                sheet_name=sheet_name,
                question_number=question_number,
                question_category=category,
                question_text=question_text,
                answer_text=answer_text,
                notes=notes,
                original_persona_sheet_label=sheet_name,
                respondent_id_source=respondent_id_source,
                respondent_id_confidence=respondent_id_confidence,
                row_index=row_idx,
            )
        )

    return answers

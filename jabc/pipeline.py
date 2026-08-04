"""Orchestrates the full analytical flow (spec section 28):

Raw Interview Evidence
    -> Structured Evidence Extraction
    -> Theme Evidence Aggregation
    -> Theme Scoring
    -> Behavioral / Engagement State Detection
    -> Persona Classification
    -> Confidence and Uncertainty Evaluation
    -> Brand Health Matrix
"""

from __future__ import annotations

import logging
import re

from .behavioral import detect_behavioral_state
from .config_loader import Config
from .confidence import compute_classification_confidence, compute_confidence
from .engagement import detect_engagement_state, merge_into_behavioral_state, section_for_answer
from .evidence import extract_evidence_for_answer
from .excel_loader import load_all_workbooks
from .extractor import count_applicable_questions, extract_answers_from_sheet
from .identity import resolve_sheet_level_identity, resolve_workbook_identity
from .models import RawAnswer, RespondentProfile
from .persona import classify_persona
from .scoring import score_all_themes
from .sentiment import label_for_compound, score_text
from .sheet_classifier import classify_workbook_sheets

logger = logging.getLogger(__name__)

ROLE_PATTERN = re.compile(r"teacher|superintendent|principal|educator|administrator", re.IGNORECASE)


def _infer_role(sheet_name: str) -> str:
    m = ROLE_PATTERN.search(sheet_name)
    return m.group(0).title() if m else ""


def run_pipeline(input_dir: str, config: Config,
                  include_reference_sheets: bool = False) -> list[RespondentProfile]:
    profiles: list[RespondentProfile] = []

    for wb in load_all_workbooks(input_dir):
        schemas = classify_workbook_sheets(wb.sheets, include_reference_sheets)
        completed_sheets = {name: s for name, s in schemas.items() if s.is_completed_response_sheet}

        if not completed_sheets:
            logger.info("No completed interview-response sheets found in '%s'.", wb.filename)
            continue

        if len(completed_sheets) == 1:
            sheet_name = next(iter(completed_sheets))
            identity = resolve_workbook_identity(wb.path, wb.sheets)
            profile = _build_profile_for_sheet(
                wb, sheet_name, schemas[sheet_name], identity, config,
                manual_review_seed=False,
            )
            if profile:
                profiles.append(profile)
        else:
            # Multiple completed response sheets in one workbook: we cannot
            # safely assume they represent the same respondent, so each is
            # treated as its own respondent at reduced identity confidence
            # and flagged for manual review (spec section 32).
            logger.warning(
                "Workbook '%s' has %d completed response sheets; treating each as a "
                "separate respondent and flagging for manual review.",
                wb.filename, len(completed_sheets),
            )
            for sheet_name in completed_sheets:
                identity = resolve_sheet_level_identity(wb.path, sheet_name)
                profile = _build_profile_for_sheet(
                    wb, sheet_name, schemas[sheet_name], identity, config,
                    manual_review_seed=True,
                    manual_review_reason="Multiple completed response sheets in the same "
                                          "workbook; respondent identity resolved at the "
                                          "sheet level.",
                )
                if profile:
                    profiles.append(profile)

    return profiles


def _build_profile_for_sheet(wb, sheet_name, schema, identity, config: Config,
                               manual_review_seed: bool,
                               manual_review_reason: str = "") -> RespondentProfile | None:
    df = wb.sheets[sheet_name]
    raw_answers = extract_answers_from_sheet(
        source_file=wb.filename,
        sheet_name=sheet_name,
        df=df,
        schema=schema,
        respondent_id=identity.respondent_id,
        respondent_id_source=identity.respondent_id_source,
        respondent_id_confidence=identity.respondent_id_confidence,
    )

    if not raw_answers:
        return None

    profile = RespondentProfile(
        respondent_id=identity.respondent_id,
        respondent_id_source=identity.respondent_id_source,
        respondent_id_confidence=identity.respondent_id_confidence,
        source_file=wb.filename,
        sheet_name=sheet_name,
        inferred_role=_infer_role(sheet_name),
        original_persona_sheet_label=sheet_name,
        raw_answers=raw_answers,
    )

    # --- Evidence extraction ---
    evidence_records = []
    for answer in raw_answers:
        evidence_records.extend(extract_evidence_for_answer(answer, config))
    profile.evidence_records = evidence_records

    # --- Behavioral state ---
    # Two passes, deliberately: detect_behavioral_state reads keyword/question
    # matches out of the evidence records, while detect_engagement_state reads
    # the raw answers so it can still see interview structure (which section an
    # answer sits in) and whether an answer names JABC at all -- both of which
    # are destroyed once an answer is shredded into per-theme evidence. The
    # engagement flags take precedence where the two overlap.
    behavioral_state, behavioral_detected = detect_behavioral_state(evidence_records)
    engagement = detect_engagement_state(raw_answers, config)
    profile.behavioral_state, behavioral_detected = merge_into_behavioral_state(
        behavioral_state, behavioral_detected, engagement
    )
    profile.engagement_signals = engagement.signals
    profile.engagement_evidence = engagement.evidence
    profile.sections_answered = sorted(engagement.sections_answered)

    # --- Overall sentiment aggregation (supporting metadata only) ---
    compounds = []
    pos_n = neg_n = mixed_n = 0
    for answer in raw_answers:
        s = score_text(answer.answer_text)
        compounds.append(s["compound"])
        label = label_for_compound(s["compound"])
        if label == "positive":
            pos_n += 1
        elif label == "negative":
            neg_n += 1
        elif label == "mixed":
            mixed_n += 1
    avg_compound = sum(compounds) / len(compounds) if compounds else 0.0
    profile.overall_sentiment_score = round(avg_compound, 3)
    profile.overall_sentiment_label = label_for_compound(avg_compound)
    profile.positive_answer_count = pos_n
    profile.negative_answer_count = neg_n
    profile.mixed_answer_count = mixed_n

    # --- Answer completeness: answered questions vs questions actually asked ---
    def _section_of_row(question_number: str, question_text: str) -> str | None:
        probe = RawAnswer(
            respondent_id="", source_file="", sheet_name="",
            question_number=question_number, question_category="",
            question_text=question_text, answer_text="",
        )
        return section_for_answer(probe, config.engagement_rules or {})

    applicable = count_applicable_questions(
        df, schema, engagement.sections_answered, _section_of_row
    )
    denominator = max(1, applicable or (len(df) - (schema.header_row_index + 1)))
    profile.answer_completeness = round(min(1.0, len(raw_answers) / denominator), 3)

    # --- Theme scoring ---
    profile.theme_scores = score_all_themes(
        evidence_records, profile.behavioral_state, config, behavioral_detected
    )

    # --- Persona classification ---
    persona_result = classify_persona(
        profile.theme_scores, profile.behavioral_state, config,
        engagement_summary=engagement.summary(),
    )
    profile.engagement_gate_satisfied = persona_result.gate_satisfied
    profile.brand_persona = persona_result.brand_persona
    profile.persona_display_name = persona_result.persona_display_name
    profile.persona_scores = persona_result.persona_scores
    profile.persona_margin = persona_result.persona_margin
    profile.classification_reasoning = persona_result.classification_reasoning
    profile.manual_review_flag = manual_review_seed or persona_result.manual_review_flag
    profile.manual_review_reason = "; ".join(
        r for r in [manual_review_reason, persona_result.manual_review_reason] if r
    )

    # Low identity confidence or very low answer completeness also triggers
    # manual review (spec sections 13, 32).
    if identity.respondent_id_confidence < 0.6:
        profile.manual_review_flag = True
        profile.manual_review_reason = (profile.manual_review_reason + "; " if profile.manual_review_reason
                                          else "") + "Low respondent identity confidence."
    if profile.answer_completeness < 0.3:
        profile.manual_review_flag = True
        profile.manual_review_reason = (profile.manual_review_reason + "; " if profile.manual_review_reason
                                          else "") + "Most answers are blank or unusable."

    # --- Confidence ---
    confidence, factors = compute_confidence(
        profile.theme_scores, profile.persona_margin, profile.answer_completeness,
        profile.persona_scores, config,
    )
    profile.confidence = confidence
    profile.confidence_factors = factors
    profile.classification_consistency = factors["classification_consistency"]

    classification_confidence, class_factors = compute_classification_confidence(
        profile.persona_margin, profile.persona_scores,
        persona_result.gate_satisfied, persona_result.supporting_flag_count, config,
    )
    profile.classification_confidence = classification_confidence
    profile.classification_confidence_factors = class_factors

    # Manual review is a statement about the PERSONA, so it keys off
    # classification confidence rather than overall confidence. Overall
    # confidence stays on the output as an evidence-quality measure -- it is
    # legitimately low for thin interviews, and routing review off it flagged
    # every single respondent, which is the same as flagging none of them.
    manual_review_threshold = config.persona_rules.get("manual_review_threshold", 0.55)
    if classification_confidence < manual_review_threshold and not profile.manual_review_flag:
        profile.manual_review_flag = True
        profile.manual_review_reason = (
            (profile.manual_review_reason + "; " if profile.manual_review_reason else "")
            + f"Classification confidence {classification_confidence:.2f} is below the "
              f"manual review threshold {manual_review_threshold}."
        )

    return profile

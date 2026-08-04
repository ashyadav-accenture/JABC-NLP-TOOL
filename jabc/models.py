"""Structured intermediate data models (section 29 of the build spec).

The pipeline never jumps directly from raw text to a final score. It always
passes through these explicit, serializable representations so that every
number in the final output can be traced back to the interview answer(s)
that produced it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class RawAnswer:
    """One extracted question/answer row (section 29.1)."""

    respondent_id: str
    source_file: str
    sheet_name: str
    question_number: str
    question_category: str
    question_text: str
    answer_text: str
    notes: str = ""
    original_persona_sheet_label: str = ""
    respondent_id_source: str = ""
    respondent_id_confidence: float = 0.0
    row_index: int = -1

    def answer_id(self) -> str:
        return f"{self.respondent_id}-{self.question_number}"

    def to_dict(self) -> dict:
        return asdict(self)


# Allowed evidence_type values (section 29.2)
EVIDENCE_TYPES = {
    "explicit_rating",
    "positive_signal",
    "negative_signal",
    "barrier",
    "behavioral_signal",
    "engagement_history",
    "advocacy_signal",
    "neutral_signal",
    "unknown",
}

# Allowed direction values (section 29.2)
EVIDENCE_DIRECTIONS = {"positive", "negative", "mixed", "neutral", "unknown"}


@dataclass
class EvidenceRecord:
    """Structured evidence extracted from a single answer, before scoring."""

    respondent_id: str
    source_answer_id: str
    theme: str
    evidence_type: str
    direction: str
    strength: float  # 0..1
    evidence_text: str
    matched_phrases: list = field(default_factory=list)
    matched_keywords: list = field(default_factory=list)
    question_context_weight: float = 0.0
    sentiment_support: float = 0.0
    negation_detected: bool = False
    intensifier_detected: bool = False
    source_file: str = ""
    sheet_name: str = ""
    question_number: str = ""
    question_category: str = ""
    question_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThemeScoreResult:
    """Final explainable theme score for one respondent/theme (section 39)."""

    theme: str
    final_score: float
    evidence_status: str  # supported | mixed | weak | insufficient | unknown
    evidence_strength: float
    evidence_coverage: float
    component_scores: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)  # list of evidence dict summaries

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RespondentProfile:
    """Everything known about one respondent, built up across the pipeline."""

    respondent_id: str
    respondent_id_source: str
    respondent_id_confidence: float
    source_file: str
    sheet_name: str
    inferred_role: str = ""
    original_persona_sheet_label: str = ""

    raw_answers: list = field(default_factory=list)          # list[RawAnswer]
    evidence_records: list = field(default_factory=list)      # list[EvidenceRecord]
    theme_scores: dict = field(default_factory=dict)          # theme -> ThemeScoreResult

    behavioral_state: dict = field(default_factory=dict)      # flag -> bool

    # Engagement / relationship state (engagement.py), kept alongside the
    # behavioral flags so the persona decision stays auditable: the continuous
    # signals show *how far* a respondent sat from each gate, and the evidence
    # map cites the answer excerpts that set each flag.
    engagement_signals: dict = field(default_factory=dict)    # signal -> float
    engagement_evidence: dict = field(default_factory=dict)   # flag -> list[str]
    sections_answered: list = field(default_factory=list)     # interview section letters
    engagement_gate_satisfied: bool = False

    overall_sentiment_label: str = "neutral"
    overall_sentiment_score: float = 0.0
    positive_answer_count: int = 0
    negative_answer_count: int = 0
    mixed_answer_count: int = 0

    answer_completeness: float = 0.0

    brand_persona: str = ""
    persona_display_name: str = ""
    persona_scores: dict = field(default_factory=dict)
    persona_margin: float = 0.0
    classification_reasoning: str = ""
    manual_review_flag: bool = False
    manual_review_reason: str = ""

    confidence: float = 0.0
    confidence_factors: dict = field(default_factory=dict)
    # Confidence in the persona assignment specifically, as opposed to the
    # evidence behind the whole profile. Drives the manual-review flag.
    classification_confidence: float = 0.0
    classification_confidence_factors: dict = field(default_factory=dict)
    classification_consistency: float = 1.0

    def average_score(self) -> Optional[float]:
        if not self.theme_scores:
            return None
        vals = [ts.final_score for ts in self.theme_scores.values()]
        return sum(vals) / len(vals) if vals else None

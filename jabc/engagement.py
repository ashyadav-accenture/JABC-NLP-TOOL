"""Stage 9a: Engagement / Relationship State detection.

This module answers the three questions that actually define which Brand
Persona an educator belongs to:

  1. Do they have any JABC history at all?
  2. If so, is it live or has it lapsed?
  3. If not, how do they feel about external classroom programming in general?

It runs on RawAnswers rather than EvidenceRecords because two of its
strongest signals are structural, not lexical:

  * which interview section an answer sits in -- the guide routes respondents
    into Section E (JABC experience), Section F (lapsed engagement) and
    Section G (never ran an external program) by persona, so a substantively
    answered Section F is direct evidence of lapse no matter what words it
    uses; and
  * whether an answer names JABC at all -- "last year we did a leadership
    program" is evidence of *external* engagement, not JABC engagement, and
    the distinction is invisible once an answer has been shredded into
    per-theme evidence records.

Everything it emits is a boolean flag plus a continuous diagnostic signal, so
persona.py can gate on the booleans and fall back to the continuous values
when the booleans are silent. Cue lexicons and thresholds live in
config/engagement_rules.yaml -- nothing here is hard-coded.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .models import RawAnswer
from .sentiment import score_text

SECTION_LETTERS = "ABCDEFGHIJ"

_LETTER_PREFIX_RE = re.compile(r"^\s*([A-J])\s*\d", re.IGNORECASE)
_NUMERIC_PREFIX_RE = re.compile(r"^\s*(\d{1,2})")

# Flags the detector is guaranteed to emit. Persona rules may only reference
# names from this list (validated at config load).
ENGAGEMENT_FLAGS = [
    "has_jabc_experience",
    "has_current_jabc_engagement",
    "has_lapsed_jabc_engagement",
    "intends_to_continue_jabc",
    "is_aware_of_jabc",
    "runs_external_programs",
    "has_positive_external_experience",
    "has_negative_external_experience",
    "is_hesitant_about_external_programs",
    "has_no_external_experience",
    "explores_external_programs",
]

# Older flag names kept alive so theme scoring (scoring.py) and any existing
# persona rules keep resolving. These are derived, never detected directly.
LEGACY_FLAG_ALIASES = {
    "has_prior_jabc_engagement": "has_jabc_experience",
    "has_reduced_or_stopped_engagement": "has_lapsed_jabc_engagement",
    "has_advocated_for_jabc": "intends_to_continue_jabc",
    "is_open_to_external_programming": "explores_external_programs",
    "has_used_competing_programs": "runs_external_programs",
}


@dataclass
class EngagementState:
    """Structured relationship state for one respondent."""

    flags: dict[str, bool] = field(default_factory=dict)
    detected: set = field(default_factory=set)
    signals: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    sections_answered: set = field(default_factory=set)

    def summary(self) -> str:
        live = [f for f, v in self.flags.items() if v and f in ENGAGEMENT_FLAGS]
        return (
            f"sections={''.join(sorted(self.sections_answered)) or '-'}; "
            f"flags={', '.join(sorted(live)) or 'none'}; "
            f"jabc_recency={self.signals.get('jabc_recency', 0.0):+.2f}; "
            f"external_disposition={self.signals.get('external_disposition', 0.0):+.2f}"
        )


def section_for_answer(answer: RawAnswer, rules: dict) -> str | None:
    """Recovers the interview-section letter for an answer.

    Tries the question number first ("E1" or "5.1" -> E), then falls back to
    matching the question category/text against `section_category_fallback`.
    Returns None when the section genuinely cannot be established -- callers
    must treat that as unknown, never as a default section.
    """
    qnum = (answer.question_number or "").strip()

    m = _LETTER_PREFIX_RE.match(qnum)
    if m:
        return m.group(1).upper()

    m = _NUMERIC_PREFIX_RE.match(qnum)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(SECTION_LETTERS):
            return SECTION_LETTERS[idx - 1]

    haystack = f"{answer.question_category} {answer.question_text}".lower()
    for entry in rules.get("section_category_fallback", []):
        needle = str(entry.get("match", "")).lower()
        if needle and needle in haystack:
            return str(entry.get("section", "")).upper() or None

    return None


def _compile_cues(rules: dict) -> dict[str, list[re.Pattern]]:
    compiled: dict[str, list[re.Pattern]] = {}
    for name, patterns in rules.get("cues", {}).items():
        compiled[name] = [re.compile(p, re.IGNORECASE) for p in patterns]
    return compiled


def _matches(cues: list[re.Pattern], text: str) -> list[str]:
    """Returns the matched substrings for every cue that fires in `text`."""
    hits = []
    for pattern in cues:
        m = pattern.search(text)
        if m:
            hits.append(m.group(0).strip())
    return hits


def _squash(count: float, saturation: float) -> float:
    if saturation <= 0:
        return 0.0
    return math.tanh(count / saturation)


def _is_anchor(answer: RawAnswer, spec: dict) -> bool:
    """True when this answer belongs to one of the named anchor questions."""
    if not spec:
        return False
    qnum = (answer.question_number or "").strip().upper()
    if qnum in {str(n).upper() for n in spec.get("question_numbers", [])}:
        return True
    haystack = (answer.question_text or "").lower()
    return any(needle.lower() in haystack for needle in spec.get("question_text_any", []))


def _denies_familiarity(text: str, patterns: list[re.Pattern]) -> bool:
    """Interprets the answer to the JABC familiarity question as a denial of any
    prior awareness. Handles both the prose forms ("not at all", "never heard
    of it") and a bare 1 on the question's own 1-5 scale."""
    stripped = text.strip()
    leading_number = re.match(r"^\s*([1-5])\b", stripped)
    if leading_number and leading_number.group(1) == "1":
        return True
    if re.fullmatch(r"[1-5]", stripped):
        return stripped == "1"
    return any(p.search(stripped) for p in patterns)


def detect_engagement_state(raw_answers: list[RawAnswer], config) -> EngagementState:
    """Builds the EngagementState for one respondent from their raw answers."""
    rules = getattr(config, "engagement_rules", {}) or {}
    cues = _compile_cues(rules)
    thresholds = rules.get("thresholds", {})

    min_chars = thresholds.get("min_substantive_answer_chars", 20)
    cue_saturation = thresholds.get("cue_saturation", 2.0)
    cue_w = thresholds.get("disposition_cue_weight", 0.65)
    sent_w = thresholds.get("disposition_sentiment_weight", 0.35)
    disposition_threshold = thresholds.get("external_disposition_threshold", 0.0)
    lapse_margin = thresholds.get("lapse_over_current_margin", 0.5)

    jabc_context_sections = set(rules.get("jabc_context_sections", []))
    external_sections = set(rules.get("external_context_sections", []))
    experience_sections = set(rules.get("jabc_experience_sections", []))
    lapsed_sections = set(rules.get("lapsed_engagement_sections", []))
    never_ran_sections = set(rules.get("never_ran_external_sections", []))

    anchor_spec = rules.get("jabc_experience_anchor", {})
    familiarity_spec = rules.get("jabc_familiarity_question", {})
    denial_patterns = [re.compile(p, re.IGNORECASE) for p in rules.get("familiarity_denial", [])]

    state = EngagementState()
    evidence: dict[str, list[str]] = {}

    def note(flag: str, excerpt: str) -> None:
        evidence.setdefault(flag, []).append(excerpt[:180])

    current_hits = lapsed_hits = intent_hits = unaware_hits = 0
    ext_pos = ext_neg = ext_hes = ext_none = 0
    external_compounds: list[float] = []
    substantive_sections: set[str] = set()
    jabc_named_anywhere = False
    external_answer_count = 0
    answered_experience_anchor = False
    jabc_named_in_experience_section = False
    familiarity_denied = False

    for answer in raw_answers:
        text = (answer.answer_text or "").strip()
        if not text:
            continue

        section = section_for_answer(answer, rules)
        substantive = len(text) >= min_chars
        if section and substantive:
            substantive_sections.add(section)

        # --- Anchor questions ---
        if substantive and _is_anchor(answer, anchor_spec):
            answered_experience_anchor = True
            note("has_jabc_experience", f"[{answer.question_number}] {text[:150]}")

        if _is_anchor(answer, familiarity_spec) and _denies_familiarity(text, denial_patterns):
            familiarity_denied = True
            note("is_aware_of_jabc", f"[{answer.question_number}] (denied) {text[:120]}")

        names_jabc = bool(_matches(cues.get("jabc_mention", []), text))
        if names_jabc:
            jabc_named_anywhere = True
            if section in experience_sections and substantive:
                jabc_named_in_experience_section = True
                note("has_jabc_experience", f"[{answer.question_number}] {text[:150]}")

        # --- JABC relationship recency (only in JABC-relevant answers) ---
        in_jabc_context = names_jabc or (section in jabc_context_sections)
        if in_jabc_context:
            for hit in _matches(cues.get("jabc_current", []), text):
                current_hits += 1
                note("has_current_jabc_engagement", f"[{answer.question_number}] …{hit}… {text[:90]}")
            for hit in _matches(cues.get("jabc_lapsed", []), text):
                lapsed_hits += 1
                note("has_lapsed_jabc_engagement", f"[{answer.question_number}] …{hit}… {text[:90]}")
            for hit in _matches(cues.get("jabc_intent_continue", []), text):
                intent_hits += 1
                note("intends_to_continue_jabc", f"[{answer.question_number}] …{hit}… {text[:90]}")

        for hit in _matches(cues.get("jabc_unaware", []), text):
            unaware_hits += 1
            note("is_aware_of_jabc", f"[{answer.question_number}] (negated) …{hit}…")

        # --- Disposition toward NON-JABC external programming ---
        # An answer that names JABC tells us about JABC, not about how this
        # educator feels about outside providers generally, so it is excluded.
        if section in external_sections and not names_jabc and substantive:
            external_answer_count += 1
            external_compounds.append(score_text(text)["compound"])
            for hit in _matches(cues.get("external_positive", []), text):
                ext_pos += 1
                note("has_positive_external_experience", f"[{answer.question_number}] …{hit}… {text[:90]}")
            for hit in _matches(cues.get("external_negative", []), text):
                ext_neg += 1
                note("has_negative_external_experience", f"[{answer.question_number}] …{hit}… {text[:90]}")
            for hit in _matches(cues.get("external_hesitancy", []), text):
                ext_hes += 1
                note("is_hesitant_about_external_programs", f"[{answer.question_number}] …{hit}… {text[:90]}")
            for hit in _matches(cues.get("external_none", []), text):
                ext_none += 1
                note("has_no_external_experience", f"[{answer.question_number}] …{hit}… {text[:90]}")

    # ------------------------------------------------------------------
    # JABC history
    # ------------------------------------------------------------------
    # Establishing evidence: the retrospective Section E anchor question, or the
    # lapsed-engagement section, or explicit JABC recency/lapse language. Merely
    # having *some* content in Section E is not enough -- respondents who had
    # never heard of JABC still answered its follow-up prompts prospectively.
    answered_lapsed_section = bool(substantive_sections & lapsed_sections)
    touched_experience_section = bool(substantive_sections & experience_sections)

    named_section_e = jabc_named_in_experience_section and rules.get(
        "jabc_experience_from_named_section_e", True
    )

    has_experience = (
        answered_experience_anchor
        or answered_lapsed_section
        or named_section_e
        or (jabc_named_anywhere and (current_hits or lapsed_hits))
    )

    if familiarity_denied:
        # Hard override. "I had never heard of JABC before today" and "I ran a
        # JABC program" cannot both be true; the direct answer to the
        # familiarity question wins over any inferred signal.
        has_experience = False
        note("has_jabc_experience",
             "(suppressed) respondent denied any prior familiarity with JABC")

    # ------------------------------------------------------------------
    # Current vs lapsed
    # ------------------------------------------------------------------
    current_signal = _squash(current_hits, cue_saturation)
    lapsed_signal = _squash(lapsed_hits, cue_saturation)
    if answered_lapsed_section:
        # Being routed into the lapsed-engagement section is itself strong
        # evidence, on par with a couple of explicit lapse phrases.
        lapsed_signal = min(1.0, lapsed_signal + 0.5)

    recency = current_signal - lapsed_signal

    if not has_experience:
        is_current = is_lapsed = False
    elif lapsed_signal > 0 and recency <= -lapse_margin * _squash(1.0, cue_saturation):
        is_current, is_lapsed = False, True
    elif lapsed_signal > 0 and current_signal <= 0:
        is_current, is_lapsed = False, True
    else:
        # Has JABC history, was never routed to the lapsed section, and nothing
        # says the relationship ended -- read as live. "Not mentioned" must not
        # become "stopped".
        is_current, is_lapsed = True, False

    # ------------------------------------------------------------------
    # External-programming disposition
    # ------------------------------------------------------------------
    cue_balance = _squash(ext_pos, cue_saturation) - _squash(ext_neg + ext_hes, cue_saturation)
    mean_compound = (sum(external_compounds) / len(external_compounds)) if external_compounds else 0.0
    disposition = cue_w * cue_balance + sent_w * mean_compound

    answered_never_ran = bool(substantive_sections & never_ran_sections)
    runs_external = external_answer_count > 0 and ext_none == 0 and not answered_never_ran
    no_external = (external_answer_count == 0) or (ext_none > 0 and ext_pos == 0) or answered_never_ran

    explores_external = bool(runs_external and disposition >= disposition_threshold)

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    flags = {
        "has_jabc_experience": has_experience,
        "has_current_jabc_engagement": is_current,
        "has_lapsed_jabc_engagement": is_lapsed,
        "intends_to_continue_jabc": intent_hits > 0,
        "is_aware_of_jabc": bool(
            not familiarity_denied
            and (has_experience or (jabc_named_anywhere and unaware_hits == 0))
        ),
        "runs_external_programs": runs_external,
        "has_positive_external_experience": ext_pos > 0 and disposition >= disposition_threshold,
        "has_negative_external_experience": ext_neg > 0,
        "is_hesitant_about_external_programs": ext_hes > 0,
        "has_no_external_experience": no_external,
        "explores_external_programs": explores_external,
    }

    # Which flags had *any* supporting signal, as opposed to defaulting to
    # False. Theme scoring must only consume a flag when it was actually
    # observed (spec section 31: unknown is not the same as low).
    detected: set[str] = set()
    if has_experience:
        detected.update(["has_jabc_experience", "has_current_jabc_engagement",
                          "has_lapsed_jabc_engagement"])
    if current_hits or lapsed_hits:
        detected.update(["has_current_jabc_engagement", "has_lapsed_jabc_engagement"])
    if intent_hits:
        detected.add("intends_to_continue_jabc")
    if jabc_named_anywhere or unaware_hits or familiarity_denied:
        detected.add("is_aware_of_jabc")
    if external_answer_count:
        detected.update(["runs_external_programs", "has_positive_external_experience",
                          "has_negative_external_experience",
                          "is_hesitant_about_external_programs",
                          "has_no_external_experience", "explores_external_programs"])

    state.flags = flags
    state.detected = detected
    state.evidence = evidence
    state.sections_answered = substantive_sections
    state.signals = {
        "jabc_current_cues": float(current_hits),
        "jabc_lapsed_cues": float(lapsed_hits),
        "jabc_intent_cues": float(intent_hits),
        "jabc_recency": round(recency, 3),
        "answered_experience_anchor": float(answered_experience_anchor),
        "jabc_named_in_experience_section": float(jabc_named_in_experience_section),
        "touched_experience_section": float(touched_experience_section),
        "familiarity_denied": float(familiarity_denied),
        "external_positive_cues": float(ext_pos),
        "external_negative_cues": float(ext_neg),
        "external_hesitancy_cues": float(ext_hes),
        "external_answer_count": float(external_answer_count),
        "external_sentiment": round(mean_compound, 3),
        "external_disposition": round(disposition, 3),
    }
    return state


def merge_into_behavioral_state(behavioral_state: dict, detected: set,
                                  engagement: EngagementState) -> tuple[dict, set]:
    """Folds engagement flags (and their legacy aliases) into the behavioral
    state dict consumed by theme scoring and persona classification.

    Engagement flags win over the older keyword-derived behavioral flags for
    the four keys they overlap on: they are derived from interview structure
    plus JABC-scoped language, whereas the older flags fire on any question
    whose text happens to match a `behavioral_flags` rule.
    """
    merged = dict(behavioral_state)
    merged_detected = set(detected)

    merged.update(engagement.flags)
    merged_detected |= engagement.detected

    for legacy, source in LEGACY_FLAG_ALIASES.items():
        if source in engagement.flags:
            merged[legacy] = engagement.flags[source]
            if source in engagement.detected:
                merged_detected.add(legacy)
            else:
                merged_detected.discard(legacy)

    # Derived convenience negations used by persona_rules.yaml.
    merged["has_current_jabc_engagement_false"] = not merged.get("has_current_jabc_engagement", False)
    merged["has_prior_jabc_engagement_false"] = not merged.get("has_jabc_experience", False)
    merged["limited_jabc_engagement"] = not merged.get("has_jabc_experience", False)

    return merged, merged_detected

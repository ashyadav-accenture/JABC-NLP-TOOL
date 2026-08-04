"""Stage 9 (spec sections 30.5, 34): Behavioral / engagement state detector.

Aggregates the "__behavioral__" evidence records produced by evidence.py
into the seven structured boolean flags required by the spec, kept
deliberately separate from the six perception theme scores.

Design note: unlike theme scores (where "unknown" defaults to a neutral
3.0, never to a negative interpretation), these are simple booleans used
for persona eligibility checks. Where a workbook never raises a topic at
all (e.g. a Brand-Newbie interview that never asks about prior engagement)
we default to False rather than leaving it unset, because for these
specific engagement flags "not mentioned" and "did not happen" are the
same in practice for this interview guide. This assumption is documented
here and should be revisited during calibration (section 38) if it proves
wrong for a given cohort.
"""

from __future__ import annotations

from .models import EvidenceRecord

CANONICAL_FLAGS = [
    "has_prior_jabc_engagement",
    "has_current_jabc_engagement",
    "has_reduced_or_stopped_engagement",
    "has_used_competing_programs",
    "is_open_to_external_programming",
    "has_advocated_for_jabc",
    "has_current_barriers",
]


def detect_behavioral_state(evidence_records: list[EvidenceRecord]) -> tuple[dict[str, bool], set[str]]:
    """Returns (state, detected_flags).

    `state` defaults every canonical flag to False so persona eligibility
    checks (which need a concrete True/False to test `required_behavioral`
    / `required_any_behavioral`) always have a value to read.

    `detected_flags` records which flags actually had supporting evidence
    in this respondent's answers. Theme scoring (scoring.py) must only use
    a flag's *behavioral evidence* contribution when it is in this set --
    otherwise an un-discussed topic (e.g. a Champion interview that never
    happens to ask about prior engagement) would silently count as
    *negative* evidence, which violates the "unknown is not the same as
    low" principle (spec section 31).
    """
    state: dict[str, bool] = {flag: False for flag in CANONICAL_FLAGS}
    seen: dict[str, bool] = {}
    detected: set[str] = set()

    for rec in evidence_records:
        if rec.theme != "__behavioral__":
            continue
        for flag in rec.matched_keywords:
            if flag not in CANONICAL_FLAGS:
                continue
            detected.add(flag)
            affirmed = rec.direction != "negative"
            # If any answer affirms the flag, treat it as True (an educator
            # only needs to mention advocating once to count as an advocate).
            seen[flag] = seen.get(flag, False) or affirmed

    for flag, value in seen.items():
        state[flag] = value

    # Derived convenience flags used by persona_rules.yaml's
    # `required_any_behavioral` lists.
    state["has_current_jabc_engagement_false"] = not state["has_current_jabc_engagement"]
    state["has_prior_jabc_engagement_false"] = not state["has_prior_jabc_engagement"]
    state["limited_jabc_engagement"] = (
        not state["has_current_jabc_engagement"] and not state["has_prior_jabc_engagement"]
    )

    return state, detected

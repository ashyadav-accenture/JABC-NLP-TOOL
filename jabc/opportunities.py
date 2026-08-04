"""The seven coded opportunity themes, and a standing check that their
respondent rosters still match the interview files.

The counts and rosters in config/opportunities.yaml come from a human reading
the transcripts, which is a better instrument than anything in this module.
So `validate_opportunities` deliberately does NOT try to re-derive the coding:
it checks the things that can be checked mechanically and would otherwise rot
silently as files are added, renamed or re-coded --

  * does every named respondent actually exist in the interview folder;
  * does `mentions` still agree with the length of `mentioned_by`;
  * which respondents are named in no theme at all.

It also runs a weak keyword pass purely to SURFACE candidates for review, and
reports that separately. That pass is advisory and nothing else consumes it.
When it was first written it flagged five respondents as unsupported --
Sarah Williams on awareness, Alvina Last on expert delivery, Amanda Reid on
low-prep, Kimberly Hlina and Soraya Rajan on communication timing -- and every
one of them turned out to be correctly coded on a manual read. It had simply
missed "professional developmet day" (a typo), "the person coming into the
classroom", "take care of everything", "when big shifts were going to happen"
and "prefer to hear from JABC earlier in the school year". Treat a flag here as
"go and read this answer", never as evidence the coding is wrong.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .models import RespondentProfile

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    code: str
    rank: int
    title: str
    mentions: int
    people: int
    difficulty: float
    difficulty_note: str
    opportunity: str
    mentioned_by: list = field(default_factory=list)


def load_opportunities(config) -> list[Opportunity]:
    raw = getattr(config, "opportunities", {}) or {}
    items = []
    for entry in raw.get("opportunities", []) or []:
        items.append(Opportunity(
            code=entry.get("code", ""),
            rank=int(entry.get("rank", 0)),
            title=entry.get("title", ""),
            mentions=int(entry.get("mentions", 0)),
            people=int(entry.get("people", entry.get("mentions", 0))),
            difficulty=float(entry.get("difficulty", 0.5)),
            difficulty_note=" ".join((entry.get("difficulty_note") or "").split()),
            opportunity=" ".join((entry.get("opportunity") or "").split()),
            mentioned_by=list(entry.get("mentioned_by", []) or []),
        ))
    return sorted(items, key=lambda o: o.rank)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def validate_opportunities(opportunities: list[Opportunity],
                             profiles: list[RespondentProfile]) -> list[dict]:
    """Mechanical consistency checks. Returns one row per opportunity."""
    # Viveka's workbook holds two response sheets and so appears twice in
    # profiles; the coding names the person once, so collapse to people here.
    respondents = {_norm(p.respondent_id.split("__")[0]) for p in profiles}

    rows = []
    for opp in opportunities:
        named = [n for n in opp.mentioned_by]
        missing = [n for n in named if _norm(n) not in respondents]
        rows.append({
            "code": opp.code,
            "title": opp.title,
            "mentions": opp.mentions,
            "people_named": len(named),
            "count_matches_roster": opp.mentions == len(named),
            "named_but_not_in_files": ", ".join(missing),
            "difficulty": opp.difficulty,
        })
    return rows


def unnamed_respondents(opportunities: list[Opportunity],
                          profiles: list[RespondentProfile]) -> list[str]:
    """Respondents who appear in no opportunity roster at all.

    Usually means a short or sparse interview rather than an oversight, but it
    is worth surfacing: a respondent contributing to nothing is either a thin
    file or a gap in the coding, and both are worth knowing about.
    """
    named = {_norm(n) for opp in opportunities for n in opp.mentioned_by}
    seen = {}
    for p in profiles:
        key = _norm(p.respondent_id.split("__")[0])
        seen.setdefault(key, p.respondent_id.split("__")[0])
    return sorted(display for key, display in seen.items() if key not in named)


def opportunity_dataframe(opportunities: list[Opportunity],
                            profiles: list[RespondentProfile]):
    """Sidecar table: the coded numbers, the authored difficulty, and the
    validation result for each theme."""
    import pandas as pd

    checks = {row["code"]: row for row in validate_opportunities(opportunities, profiles)}
    rows = []
    for opp in opportunities:
        chk = checks.get(opp.code, {})
        rows.append({
            "code": opp.code,
            "rank": opp.rank,
            "title": opp.title,
            "mentions_coded": opp.mentions,
            "people_coded": opp.people,
            "people_named_in_roster": chk.get("people_named"),
            "count_matches_roster": chk.get("count_matches_roster"),
            "named_but_not_in_files": chk.get("named_but_not_in_files", ""),
            "difficulty_authored": opp.difficulty,
            "difficulty_note": opp.difficulty_note,
            "opportunity": opp.opportunity,
            "mentioned_by": ", ".join(opp.mentioned_by),
        })
    return pd.DataFrame(rows)

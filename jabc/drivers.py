"""Motivator / barrier detection for the circumplex chart.

The seven motivators and seven barriers come from the human-coded interview
analysis (config/motivators_barriers.yaml). Their `frequency` values are
authoritative and are never recomputed here -- re-counting them by keyword
matching would produce numbers that quietly disagree with the published table.

This module derives exactly one thing the coded table does not carry: how each
item's mentions split across the four Brand Personas, which becomes the
persona-share ring around its circle.

Nothing here positions anything. The circumplex places a circle from its coded
frequency (vertical) and the authored diagram (horizontal), so an earlier
sentiment-based affect score is gone rather than left computing a number no
output reads -- it ran VADER over every answer for every item on every run.

A cue lexicon that under-matches therefore makes an item's RING less certain --
reported as `mention_count`, and drawn dashed below `min_mentions_for_ring` --
but cannot move its circle or contradict the coded frequency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .config_loader import PERSONAS
from .models import RespondentProfile

logger = logging.getLogger(__name__)


@dataclass
class DriverItem:
    """One motivator or barrier, as declared in the config."""

    key: str
    code: str
    label: str
    kind: str  # "motivator" | "barrier"
    rank: int
    frequency: int
    applies_to: str
    summary: str
    patterns: list = field(default_factory=list)


@dataclass
class DriverStats:
    """Everything the chart needs about one item."""

    item: DriverItem
    mention_count: int = 0
    respondent_count: int = 0
    persona_shares: dict = field(default_factory=dict)
    well_evidenced: bool = False


def load_driver_items(config) -> list[DriverItem]:
    """Reads motivators then barriers from config, compiling their cues."""
    raw = getattr(config, "motivators_barriers", {}) or {}
    items: list[DriverItem] = []
    for kind, section in (("motivator", "motivators"), ("barrier", "barriers")):
        for entry in raw.get(section, []) or []:
            items.append(DriverItem(
                key=entry["key"],
                code=entry.get("code", entry["key"]),
                label=entry.get("label", entry["key"]),
                kind=kind,
                rank=int(entry.get("rank", 0)),
                frequency=int(entry.get("frequency", 0)),
                applies_to=entry.get("applies_to", ""),
                summary=" ".join((entry.get("summary") or "").split()),
                patterns=[re.compile(p, re.IGNORECASE) for p in entry.get("cues", [])],
            ))
    return items


def collect_driver_hits(profiles: list[RespondentProfile], config) -> dict:
    """key -> list of detected mentions, one record per weighted hit.

    Split out of `analyze_drivers` because the chart only ever needed the
    counts, but the audit report needs to say *which interview* each detected
    mention came from and which cue fired -- the same detection pass, with the
    provenance kept instead of collapsed into a total.
    """
    raw = getattr(config, "motivators_barriers", {}) or {}
    detection = raw.get("detection", {})
    min_chars = detection.get("min_answer_chars", 25)
    one_per_answer = detection.get("one_mention_per_answer", True)

    items = load_driver_items(config)
    hits: dict[str, list[dict]] = {item.key: [] for item in items}

    for profile in profiles:
        for answer in profile.raw_answers:
            text = (answer.answer_text or "").strip()
            if len(text) < min_chars:
                continue
            for item in items:
                matched = [p.pattern for p in item.patterns if p.search(text)]
                if not matched:
                    continue
                record = {
                    "persona": profile.brand_persona,
                    "respondent_id": profile.respondent_id,
                    "source_file": answer.source_file,
                    "question_number": answer.question_number,
                    "question_text": answer.question_text,
                    "answer_text": text,
                    "matched_cues": matched,
                }
                weight = 1 if one_per_answer else len(matched)
                hits[item.key].extend([record] * weight)
    return hits


def analyze_drivers(profiles: list[RespondentProfile], config) -> list[DriverStats]:
    """Builds DriverStats for every configured motivator and barrier."""
    raw = getattr(config, "motivators_barriers", {}) or {}
    detection = raw.get("detection", {})
    min_mentions = detection.get("min_mentions_for_ring",
                                   detection.get("min_mentions_for_position", 3))

    items = load_driver_items(config)
    stats = {item.key: DriverStats(item=item) for item in items}
    hits = collect_driver_hits(profiles, config)

    for item in items:
        records = hits[item.key]
        st = stats[item.key]
        st.mention_count = len(records)
        st.respondent_count = len({r["respondent_id"] for r in records})

        if records:
            counts = {persona: 0 for persona in PERSONAS}
            for rec in records:
                if rec["persona"] in counts:
                    counts[rec["persona"]] += 1
            persona_total = sum(counts.values())
            if persona_total > 0:
                st.persona_shares = {k: v / persona_total for k, v in counts.items()}

        if not st.persona_shares:
            # No detected mentions to attribute. An even split is the honest
            # rendering of "we don't know", and the dashed outline plus the
            # low-evidence note in the key stop it reading as a real finding.
            st.persona_shares = {k: 1.0 / len(PERSONAS) for k in PERSONAS}

        st.well_evidenced = st.mention_count >= min_mentions

    ordered = sorted(items, key=lambda i: (i.kind != "motivator", i.rank))
    return [stats[i.key] for i in ordered]

"""Loads and validates all YAML configuration files used by the pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

THEMES = [
    "awareness",
    "understanding",
    "trust",
    "relevance",
    "ease_of_engagement",
    "advocacy",
]

PERSONAS = [
    "brand_champion",
    "non_active_supporter",
    "brand_prospect",
    "brand_newbie",
]

PERSONA_DISPLAY_NAMES = {
    "brand_champion": "Brand Champion",
    "non_active_supporter": "Non-Active Supporter",
    "brand_prospect": "Brand Prospect",
    "brand_newbie": "Brand Newbie",
}

# --- Reported persona groups ----------------------------------------------
# The four personas above stay the unit of CLASSIFICATION: they are the
# relationship states the engagement gates actually test for, and collapsing
# them would throw away the "currently running JABC" vs "ran it a decade ago"
# distinction that the gates are built on.
#
# Reporting, however, is done on two merged personas. The two halves of each
# pair share the reporting question ("do they have first-hand JABC experience
# or not?"), and the merged pair is what the audience is asked to act on. Each
# group is also internally consistent on which themes are answerable -- neither
# Prospects nor Newbies were ever asked about ease of engagement or advocacy --
# so no cell is blanked for half a group.
#
# Overridable via a `persona_groups` block in persona_rules.yaml.
PERSONA_GROUPS = {
    "established_supporters": ["brand_champion", "non_active_supporter"],
    "potential_adopters": ["brand_prospect", "brand_newbie"],
}

PERSONA_GROUP_DISPLAY_NAMES = {
    "established_supporters": "Established Supporters",
    "potential_adopters": "Potential Adopters",
}


def persona_groups(config=None) -> dict[str, list[str]]:
    """The group -> member personas map, in reporting order. The built-in
    default applies even when no config is passed, so a caller that forgets to
    thread config through cannot silently fall back to the unmerged personas."""
    if config is None:
        return {k: list(v) for k, v in PERSONA_GROUPS.items()}

    block = (getattr(config, "persona_rules", {}) or {}).get("persona_groups")
    if not block:
        return {k: list(v) for k, v in PERSONA_GROUPS.items()}
    return {
        key: list((rules or {}).get("includes", []))
        for key, rules in block.items()
    }


def persona_group_display_names(config=None) -> dict[str, str]:
    names = dict(PERSONA_GROUP_DISPLAY_NAMES)
    block = (getattr(config, "persona_rules", {}) or {}).get("persona_groups") if config else None
    for key, rules in (block or {}).items():
        display = (rules or {}).get("display_name")
        names[key] = display or names.get(key, key)
    return names


def group_for_persona(persona_key: str, config=None) -> str | None:
    """The group a classified persona is reported under, or None if it belongs
    to no group (which the config validation warns about)."""
    for group_key, members in persona_groups(config).items():
        if persona_key in members:
            return group_key
    return None


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


@dataclass
class Config:
    """Container for every configuration file, loaded once per run."""

    config_dir: Path
    theme_keywords: dict = field(default_factory=dict)
    phrase_rules: dict = field(default_factory=dict)
    question_theme_mapping: dict = field(default_factory=dict)
    persona_rules: dict = field(default_factory=dict)
    scoring_weights: dict = field(default_factory=dict)
    sentiment_weights: dict = field(default_factory=dict)
    engagement_rules: dict = field(default_factory=dict)
    motivators_barriers: dict = field(default_factory=dict)
    opportunities: dict = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: str | Path) -> "Config":
        config_dir = Path(config_dir)
        cfg = cls(
            config_dir=config_dir,
            theme_keywords=_load_yaml(config_dir / "theme_keywords.yaml"),
            phrase_rules=_load_yaml(config_dir / "phrase_rules.yaml"),
            question_theme_mapping=_load_yaml(config_dir / "question_theme_mapping.yaml"),
            persona_rules=_load_yaml(config_dir / "persona_rules.yaml"),
            scoring_weights=_load_yaml(config_dir / "scoring_weights.yaml"),
            sentiment_weights=_load_yaml(config_dir / "sentiment_weights.yaml"),
            engagement_rules=_load_yaml(config_dir / "engagement_rules.yaml"),
            motivators_barriers=_load_yaml(config_dir / "motivators_barriers.yaml"),
            opportunities=_load_yaml(config_dir / "opportunities.yaml"),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        weights = self.scoring_weights.get("theme_scoring_weights", {})
        total = sum(weights.values())
        if weights and abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"theme_scoring_weights must sum to 1.0, got {total:.4f}: {weights}"
            )

        for block in ("confidence_weights", "classification_confidence_weights"):
            conf_weights = self.scoring_weights.get(block, {})
            conf_total = sum(conf_weights.values())
            if conf_weights and abs(conf_total - 1.0) > 1e-6:
                raise ValueError(
                    f"{block} must sum to 1.0, got {conf_total:.4f}: {conf_weights}"
                )

        for theme in THEMES:
            if theme not in self.theme_keywords:
                logger.warning("theme_keywords.yaml is missing theme '%s'", theme)
            if theme not in self.sentiment_weights.get("sentiment_theme_relevance", {}):
                logger.warning("sentiment_weights.yaml is missing theme '%s'", theme)

        persona_defs = self.persona_rules.get("personas", {})
        for persona in PERSONAS:
            if persona not in persona_defs:
                logger.warning("persona_rules.yaml is missing persona '%s'", persona)

        # Every classified persona must be reportable under exactly one group,
        # otherwise its respondents would vanish from the matrix and the charts
        # while still being counted as classified.
        groups = persona_groups(self)
        seen: dict[str, str] = {}
        for group_key, members in groups.items():
            for member in members:
                if member not in PERSONAS:
                    raise ValueError(
                        f"persona_rules.yaml: persona group '{group_key}' includes "
                        f"unknown persona '{member}'. Known personas: {PERSONAS}"
                    )
                if member in seen:
                    raise ValueError(
                        f"persona_rules.yaml: persona '{member}' appears in both "
                        f"'{seen[member]}' and '{group_key}'; groups must partition "
                        "the personas."
                    )
                seen[member] = group_key
        for persona in PERSONAS:
            if persona not in seen:
                raise ValueError(
                    f"persona_rules.yaml: persona '{persona}' belongs to no persona "
                    f"group, so its respondents would be dropped from the matrix. "
                    f"Groups: { {k: v for k, v in groups.items()} }"
                )

        # Every flag named by an engagement gate must be one the detector can
        # actually emit; a typo here would silently make a gate unsatisfiable
        # and quietly reroute a whole persona's worth of respondents.
        from .engagement import ENGAGEMENT_FLAGS, LEGACY_FLAG_ALIASES
        from .behavioral import CANONICAL_FLAGS

        known_flags = set(ENGAGEMENT_FLAGS) | set(LEGACY_FLAG_ALIASES) | set(CANONICAL_FLAGS)
        for persona, rules in persona_defs.items():
            gate = rules.get("engagement_gate", {}) or {}
            referenced = (
                list(gate.get("all_of", []))
                + list(gate.get("any_of", []))
                + list(gate.get("none_of", []))
                + list(rules.get("supporting_flags", []))
            )
            unknown = [f for f in referenced if f not in known_flags]
            if unknown:
                raise ValueError(
                    f"persona_rules.yaml: persona '{persona}' references unknown "
                    f"engagement flag(s) {unknown}. Known flags: {sorted(known_flags)}"
                )

    def theme_weight_sum(self) -> dict[str, float]:
        return self.scoring_weights.get("theme_scoring_weights", {})

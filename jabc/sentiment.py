"""Sentiment analysis (spec section 11): a supporting NLP feature only.

Uses VADER, which is well suited to short, informal interview-style text
and requires no external API or network access.
"""

from __future__ import annotations

from functools import lru_cache

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only if dependency missing
    _VADER_AVAILABLE = False


@lru_cache(maxsize=1)
def _get_analyzer():
    if not _VADER_AVAILABLE:
        return None
    return SentimentIntensityAnalyzer()


def score_text(text: str) -> dict:
    """Returns VADER compound/pos/neu/neg scores for a piece of text.
    Falls back to neutral zeros if VADER is unavailable."""
    analyzer = _get_analyzer()
    if analyzer is None or not text or not text.strip():
        return {"compound": 0.0, "pos": 0.0, "neu": 1.0, "neg": 0.0}
    return analyzer.polarity_scores(text)


def label_for_compound(compound: float) -> str:
    if compound >= 0.35:
        return "positive"
    if compound <= -0.35:
        return "negative"
    if -0.1 <= compound <= 0.1:
        return "neutral"
    return "mixed"

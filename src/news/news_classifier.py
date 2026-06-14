"""NEWS-1 Phase 3 — News Classification Layer.

Classifies a breaking headline into a category and rates its relevance to the
NASDAQ (the instrument the bot trades). This is NOT sentiment/direction — it
answers only "what kind of event is this, and how much could it move our
market?" Read-only; never raises; never trades.

Categories: economic_release, fed, geopolitical, technology, earnings,
            government_policy, market_structure, unknown
Relevance:  none, low, medium, high, critical
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from news.breaking_news_provider import BreakingNewsEvent

CATEGORIES = (
    "economic_release", "fed", "geopolitical", "technology", "earnings",
    "government_policy", "market_structure", "unknown",
)
RELEVANCE_SCALE = ("none", "low", "medium", "high", "critical")
_REL_RANK = {r: i for i, r in enumerate(RELEVANCE_SCALE)}

# keyword → category (checked in order; first hit wins)
_CATEGORY_KEYWORDS = [
    ("market_structure", ("exchange outage", "trading halt", "halts trading",
                          "market outage", "circuit breaker", "infrastructure",
                          "clearing", "settlement failure", "feed outage")),
    ("fed", ("fomc", "fed ", "federal reserve", "powell", "rate decision",
             "rate hike", "rate cut", "interest rate", "dot plot")),
    ("economic_release", ("cpi", "ppi", "inflation", "nfp", "payroll",
                          "unemployment", "gdp", "retail sales", "ism", "jobless")),
    ("geopolitical", ("war", "invasion", "missile", "strike", "sanction",
                      "tariff", "conflict", "attack", "ceasefire", "military",
                      "geopolitic", "oil embargo", "opec")),
    ("government_policy", ("congress", "senate", "shutdown", "debt ceiling",
                           "regulation", "executive order", "treasury", "sec ",
                           "antitrust", "policy", "stimulus")),
    ("technology", ("nvidia", "apple", "microsoft", "amazon", "google",
                    "meta", "tesla", "semiconductor", "chip", "ai ",
                    "artificial intelligence", "openai", "cloud", "tech ")),
    ("earnings", ("earnings", "guidance", "revenue", "profit warning",
                  "beats estimates", "misses estimates", "quarterly results")),
]

# NASDAQ-relevance floor by category (importance can raise, never lowers below)
_CATEGORY_RELEVANCE = {
    "economic_release": "high",
    "fed": "high",
    "geopolitical": "high",
    "market_structure": "critical",
    "technology": "medium",
    "government_policy": "medium",
    "earnings": "medium",
    "unknown": "low",
}

# headline phrases that escalate to critical regardless of category
_CRITICAL_KEYWORDS = (
    "emergency", "surprise rate", "unscheduled", "halts trading",
    "exchange outage", "default", "invasion", "nuclear",
)


@dataclass
class NewsAssessment:
    headline: str
    category: str
    relevance_to_nasdaq: str          # none|low|medium|high|critical
    importance: str                   # normalized low|medium|high|critical
    summary: Optional[str]
    reasons: list

    def to_dict(self) -> dict:
        return asdict(self)


def _max_relevance(a: str, b: str) -> str:
    return a if _REL_RANK.get(a, 0) >= _REL_RANK.get(b, 0) else b


def classify_category(headline: str, hint: Optional[str] = None) -> str:
    if hint and str(hint).lower() in CATEGORIES:
        return str(hint).lower()
    h = (headline or "").lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k in h for k in kws):
            return cat
    return "unknown"


def _normalize_importance(value: Optional[str]) -> str:
    v = str(value).lower() if value else ""
    return v if v in ("low", "medium", "high", "critical") else "medium"


def classify_news(event: BreakingNewsEvent) -> NewsAssessment:
    """Classify a single breaking headline. Never raises."""
    try:
        headline = event.headline or ""
        category = classify_category(headline, event.category)
        importance = _normalize_importance(event.importance)

        relevance = _CATEGORY_RELEVANCE.get(category, "low")
        # importance can lift relevance (e.g. a critical tech headline)
        relevance = _max_relevance(relevance, importance)

        reasons = [f"category={category}", f"importance={importance}"]
        h = headline.lower()
        if any(k in h for k in _CRITICAL_KEYWORDS):
            relevance = "critical"
            reasons.append("critical_keyword_match")

        return NewsAssessment(
            headline=headline,
            category=category,
            relevance_to_nasdaq=relevance,
            importance=importance,
            summary=event.summary,
            reasons=reasons,
        )
    except Exception as exc:  # noqa: BLE001
        return NewsAssessment(
            headline=getattr(event, "headline", ""),
            category="unknown", relevance_to_nasdaq="none",
            importance="medium", summary=None,
            reasons=[f"classify_error:{exc}"])

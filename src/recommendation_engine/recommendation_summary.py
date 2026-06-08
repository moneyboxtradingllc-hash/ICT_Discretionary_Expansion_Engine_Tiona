"""
Phase 5E — Recommendation Summary.
Compact summary of recommendations for AI input, console, and snapshot store.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
from recommendation_engine.recommendation_report import build_recommendation_report


def build_recommendation_summary(rec_result: dict) -> dict:
    """
    Build compact summary from build_recommendations() output.
    Never raises.
    """
    try:
        return _build(rec_result or {})
    except Exception:
        return _safe_default()


def _build(result: dict) -> dict:
    report = build_recommendation_report(result)
    recs   = result.get("recommendations") or []

    top_rec = None
    if recs:
        top_rec = recs[0].get("recommendation")

    return {
        "enabled":                  True,
        "authority_level":          "observe_only",
        "confidence_modifier":      0,
        "recommendation_count":     len(recs),
        "top_recommendation":       top_rec,
        "recommendation_quality":   report["recommendation_quality"],
        "status":                   "human_review_required" if recs else "no_recommendations",
    }


def _safe_default() -> dict:
    return {
        "enabled":                  True,
        "authority_level":          "observe_only",
        "confidence_modifier":      0,
        "recommendation_count":     0,
        "top_recommendation":       None,
        "recommendation_quality":   "none",
        "status":                   "no_recommendations",
    }

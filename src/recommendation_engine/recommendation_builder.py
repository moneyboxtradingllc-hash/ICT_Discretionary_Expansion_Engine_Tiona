"""
Phase 5E — Recommendation Builder.
Builds evidence-backed recommendations from performance intelligence.
Phase 5E.1 — Accepts an explicit pre-built dashboard to avoid redundant disk reads.
OBSERVE_ONLY — informational only. No execution influence.
All recommendations require human review.
"""
from performance_intelligence.dashboard_builder import build_dashboard
from performance_intelligence.dashboard_summary  import build_dashboard_summary
from recommendation_engine.recommendation_rules  import check_all_rules


def build_recommendations(
    symbol: str | None = None,
    snapshot: dict | None = None,
    dashboard: dict | None = None,
) -> dict:
    """
    Build recommendations from live scan snapshot and/or trade history.
    If dashboard is provided it is used directly — no rebuild, no extra disk read.
    Never raises. Returns safe defaults on any error.
    """
    try:
        return _build(symbol, snapshot or {}, dashboard)
    except Exception as exc:
        return _empty_result(warnings=[f"recommendation build failed (non-blocking): {exc}"])


def build_recommendations_from_context(context: dict) -> dict:
    """
    Build recommendations from a pre-assembled context dict.
    Used in tests and direct pipeline calls.
    context keys: dashboard, ai_feedback, memory_search
    """
    try:
        return _build_from_context(context)
    except Exception as exc:
        return _empty_result(warnings=[f"recommendation build failed (non-blocking): {exc}"])


# ── Internal ──────────────────────────────────────────────────────────────────

def _build(symbol: str | None, snapshot: dict, provided_dashboard: dict | None) -> dict:
    # Priority: explicit parameter → snapshot._full_dashboard → snapshot summary → fresh load
    dash = (
        provided_dashboard
        or snapshot.get("performance_dashboard", {}).get("_full_dashboard")
        or snapshot.get("performance_dashboard")
        or build_dashboard(symbol)
    )
    ai_feedback = (
        snapshot.get("ai_feedback_summary")
        or (snapshot.get("experience_summary") or {}).get("ai_feedback_summary")
        or {}
    )
    memory_search = (
        snapshot.get("memory_search", {}).get("_full_result")
        or snapshot.get("memory_search")
        or {}
    )

    context = {
        "dashboard":    dash,
        "ai_feedback":  ai_feedback,
        "memory_search": memory_search,
    }
    return _build_from_context(context)


def _build_from_context(context: dict) -> dict:
    warnings: list[str] = []

    recs, notes = check_all_rules(context)

    return {
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "recommendation_count":  len(recs),
        "recommendations":       recs,
        "warnings":              warnings,
        "notes":                 notes,
    }


def _empty_result(warnings: list[str] | None = None) -> dict:
    return {
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "recommendation_count":  0,
        "recommendations":       [],
        "warnings":              warnings or [],
        "notes":                 ["Recommendation engine is observe-only."],
    }

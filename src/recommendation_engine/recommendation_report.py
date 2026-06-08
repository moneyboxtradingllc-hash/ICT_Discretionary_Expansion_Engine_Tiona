"""
Phase 5E — Recommendation Report.
Wraps raw recommendations into a structured, prioritized report.
OBSERVE_ONLY — no decision logic, no execution influence.
"""


def build_recommendation_report(rec_result: dict) -> dict:
    """
    Build structured recommendation report from build_recommendations() output.
    Never raises.
    """
    try:
        return _build(rec_result or {})
    except Exception:
        return _safe_report()


def _build(result: dict) -> dict:
    recs  = result.get("recommendations") or []
    notes = result.get("notes")           or []

    count   = len(recs)
    quality = _quality_label(count)

    # Highest priority = first 3 after sorting by severity (already sorted in builder)
    high_priority = recs[:3]

    warnings = list(result.get("warnings") or [])
    if not recs and notes:
        warnings.extend(n for n in notes if "insufficient" in n.lower())

    return {
        "recommendation_quality": quality,
        "recommendation_count":   count,
        "highest_priority":       high_priority,
        "recommendations":        recs,
        "notes":                  notes,
        "warnings":               warnings,
        "authority_level":        "observe_only",
        "confidence_modifier":    0,
    }


def _quality_label(count: int) -> str:
    if count == 0:
        return "none"
    if count == 1:
        return "limited"
    if count <= 3:
        return "developing"
    return "meaningful"


def _safe_report() -> dict:
    return {
        "recommendation_quality": "none",
        "recommendation_count":   0,
        "highest_priority":       [],
        "recommendations":        [],
        "notes":                  [],
        "warnings":               [],
        "authority_level":        "observe_only",
        "confidence_modifier":    0,
    }

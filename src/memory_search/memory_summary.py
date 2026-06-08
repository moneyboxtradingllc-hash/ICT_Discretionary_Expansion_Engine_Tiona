"""
Phase 5C — Memory Summary.
Builds compact summary of similarity search results for AI and console.
OBSERVE_ONLY — no decision logic, no execution influence.
"""


def build_memory_summary(search_result: dict) -> dict:
    """
    Compact summary derived from find_similar_setups() output.
    Never raises.
    """
    try:
        return _build(search_result or {})
    except Exception:
        return _safe_default()


def _build(result: dict) -> dict:
    match_count        = result.get("match_count", 0)
    closed_match_count = result.get("closed_match_count", 0)
    top_matches        = result.get("top_matches") or []
    outcome            = result.get("similar_outcome_summary") or {}

    best_sim = max(
        (m.get("similarity_score", 0.0) for m in top_matches), default=0.0
    )
    win_rate  = outcome.get("win_rate")
    average_r = outcome.get("average_r")

    top_reasons = list(dict.fromkeys(
        m.get("reason", "")
        for m in top_matches[:3]
        if m.get("reason")
    ))

    quality = _quality_label(closed_match_count)

    notes: list[str] = list(result.get("notes") or [])
    if "Memory result is observe-only and does not affect decisions" not in notes:
        notes.append("Memory result is observe-only and does not affect decisions")

    return {
        "enabled":             True,
        "authority_level":     "observe_only",
        "confidence_modifier": 0,
        "match_count":         match_count,
        "closed_match_count":  closed_match_count,
        "best_similarity":     round(best_sim, 4),
        "similar_win_rate":    win_rate,
        "similar_average_r":   average_r,
        "top_match_reasons":   top_reasons,
        "memory_quality":      quality,
        "notes":               notes,
    }


def _quality_label(closed_count: int) -> str:
    if closed_count == 0:
        return "none"
    if closed_count < 5:
        return "thin"
    if closed_count < 20:
        return "developing"
    return "useful"


def _safe_default() -> dict:
    return {
        "enabled":             True,
        "authority_level":     "observe_only",
        "confidence_modifier": 0,
        "match_count":         0,
        "closed_match_count":  0,
        "best_similarity":     0.0,
        "similar_win_rate":    None,
        "similar_average_r":   None,
        "top_match_reasons":   [],
        "memory_quality":      "none",
        "notes":               ["Memory result is observe-only and does not affect decisions"],
    }

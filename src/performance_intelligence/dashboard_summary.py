"""
Phase 5D — Dashboard Summary.
Compact summary of performance dashboard for AI, console, and snapshot store.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
from performance_intelligence.performance_report import build_performance_report


def build_dashboard_summary(dashboard: dict) -> dict:
    """
    Build compact summary from full dashboard dict.
    Never raises.
    """
    try:
        return _build(dashboard or {})
    except Exception:
        return _safe_default()


def _build(d: dict) -> dict:
    report = build_performance_report(d)

    return {
        "enabled":             True,
        "authority_level":     "observe_only",
        "confidence_modifier": 0,
        "performance_quality": report["performance_quality"],
        "sample_size":         d.get("closed_trades", 0),
        "win_rate":            d.get("win_rate"),
        "average_r":           d.get("average_r"),
        "best_regime":         d.get("best_regime"),
        "worst_regime":        d.get("worst_regime"),
        "best_playbook":       d.get("best_playbook"),
        "worst_playbook":      d.get("worst_playbook"),
        "best_session":        d.get("best_session"),
        "most_common_failure": d.get("most_common_failure"),
        "ai_outcome_available": d.get("ai_outcome_available", False),
        "ai_helpful_rate":     d.get("ai_helpful_rate"),
        "ai_correct_rate":     d.get("ai_correct_rate"),
        "memory_quality":      d.get("memory_quality", "none"),
        "headline_findings":   report["headline_findings"][:3],
        "strengths":           report["strengths"][:3],
        "weaknesses":          report["weaknesses"][:3],
    }


def _safe_default() -> dict:
    return {
        "enabled":             True,
        "authority_level":     "observe_only",
        "confidence_modifier": 0,
        "performance_quality": "none",
        "sample_size":         0,
        "win_rate":            None,
        "average_r":           None,
        "best_regime":         None,
        "worst_regime":        None,
        "best_playbook":       None,
        "worst_playbook":      None,
        "best_session":        None,
        "most_common_failure": None,
        "ai_outcome_available": False,
        "ai_helpful_rate":     None,
        "ai_correct_rate":     None,
        "memory_quality":      "none",
        "headline_findings":   [],
        "strengths":           [],
        "weaknesses":          [],
    }

"""
Phase 3A — Experience Report.
Quality-tiered report from experience summary.
OBSERVE_ONLY — no execution influence.

Quality thresholds:
  0–19  trades → insufficient
  20–49 trades → developing
  50+   trades → meaningful

authority_level is always 'observe_only' regardless of quality tier.
"""


def build_experience_report(summary: dict) -> dict:
    """Build quality-tiered report from an experience summary dict."""
    if not summary:
        return _empty_report()

    n       = summary.get("sample_size",        0)
    matches = summary.get("historical_matches",  0)

    return {
        "sample_size":        n,
        "historical_matches": matches,
        "experience_quality": _quality_label(n),
        "authority_level":    "observe_only",
        "win_rate":           summary.get("win_rate"),
        "average_r":          summary.get("average_r"),
        "best_session":       summary.get("best_session"),
        "worst_session":      summary.get("worst_session"),
        "best_playbook":      summary.get("best_playbook"),
        "worst_playbook":     summary.get("worst_playbook"),
        "notes":              summary.get("notes", []),
    }


def _quality_label(n: int) -> str:
    if n >= 50:
        return "meaningful"
    if n >= 20:
        return "developing"
    return "insufficient"


def _empty_report() -> dict:
    return {
        "sample_size":        0,
        "historical_matches": 0,
        "experience_quality": "insufficient",
        "authority_level":    "observe_only",
        "win_rate":           None,
        "average_r":          None,
        "best_session":       None,
        "worst_session":      None,
        "best_playbook":      None,
        "worst_playbook":     None,
        "notes":              ["No experience data available"],
    }

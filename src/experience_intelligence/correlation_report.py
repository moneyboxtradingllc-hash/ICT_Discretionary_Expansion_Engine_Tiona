"""
Phase 3B — Correlation Report.
Compact top-level summary from raw correlation data for snapshot storage and AI input.
OBSERVE_ONLY — authority_level always 'observe_only', confidence_modifier always 0.
"""
from experience_intelligence.experience_correlation import correlation_confidence


def build_correlation_report(correlation: dict) -> dict:
    """Build compact correlation report from raw correlation analysis dict."""
    if not correlation:
        return _empty_report()
    n = correlation.get("sample_size", 0)
    return {
        "enabled":                         correlation.get("enabled", True),
        "authority_level":                  "observe_only",   # ALWAYS
        "sample_size":                      n,
        "confidence_modifier":              0,                 # ALWAYS
        "correlation_confidence":           correlation_confidence(n),
        "strongest_positive_correlations":  correlation.get("strongest_positive_correlations", []),
        "strongest_negative_correlations":  correlation.get("strongest_negative_correlations", []),
        "dimension_reports":                correlation.get("dimension_reports", {}),
        "warnings":                         correlation.get("warnings", ["Insufficient sample size for correlation analysis"]),
        "notes":                            correlation.get("notes", []),
    }


def _empty_report() -> dict:
    return {
        "enabled":                         True,
        "authority_level":                  "observe_only",
        "sample_size":                      0,
        "confidence_modifier":              0,
        "correlation_confidence":           "none",
        "strongest_positive_correlations":  [],
        "strongest_negative_correlations":  [],
        "dimension_reports":                {},
        "warnings":                         ["Insufficient sample size for correlation analysis"],
        "notes":                            [],
    }

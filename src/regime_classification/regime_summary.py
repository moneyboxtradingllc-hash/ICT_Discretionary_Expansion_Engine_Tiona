"""
Phase 5A — Regime Summary.
Compact regime dict for embedding in experience intelligence and scan store.
OBSERVE_ONLY — authority_level always 'observe_only', confidence_modifier always 0.
"""

from regime_classification.regime_classifier import classify_regime


def build_regime_summary(snapshot: dict) -> dict:
    """
    Return a compact regime dict from snapshot["market_regime"] if present,
    otherwise classify fresh. Never raises.
    """
    try:
        regime = snapshot.get("market_regime") or classify_regime(snapshot)
        return {
            "regime_label":        regime.get("regime_label",    "unknown"),
            "regime_family":       regime.get("regime_family",   "unknown"),
            "confidence":          regime.get("confidence",      0),
            "volatility_state":    regime.get("volatility_state", "unknown"),
            "expansion_state":     regime.get("expansion_state",  "unknown"),
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
        }
    except Exception:
        return {
            "regime_label":        "unknown",
            "regime_family":       "unknown",
            "confidence":          0,
            "volatility_state":    "unknown",
            "expansion_state":     "unknown",
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
        }

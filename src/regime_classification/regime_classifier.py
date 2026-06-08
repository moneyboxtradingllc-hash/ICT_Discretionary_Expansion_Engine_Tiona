"""
Phase 5A — Regime Classifier.
Labels the current market environment from assembled snapshot evidence.

SAFETY INVARIANTS (immutable):
  authority_level      = "observe_only"    — never changes
  confidence_modifier  = 0                 — always 0, never non-zero

This module NEVER modifies decisions, execution, risk, or AI confidence.
"""

from regime_classification.regime_features import extract_regime_features

_AUTHORITY = "observe_only"

_FAMILIES: dict[str, str] = {
    "trend_up":         "trend",
    "trend_down":       "trend",
    "range_rotation":   "range",
    "chop":             "chop",
    "expansion_up":     "expansion",
    "expansion_down":   "expansion",
    "reversal_attempt": "reversal",
    "high_volatility":  "volatility",
    "low_volatility":   "volatility",
    "unknown":          "unknown",
}


def classify_regime(snapshot: dict, raw_data=None) -> dict:
    """
    Classify the current market regime from the assembled snapshot.
    Never raises. Returns safe 'unknown' result on any error.
    confidence_modifier is ALWAYS 0. authority_level is ALWAYS 'observe_only'.
    """
    try:
        return _classify(snapshot or {}, raw_data)
    except Exception as exc:
        return _safe_unknown([f"regime classification error: {exc}"])


def _classify(snapshot: dict, raw_data=None) -> dict:
    f = extract_regime_features(snapshot, raw_data)

    trend    = f["trend_score"]
    chop     = f["chop_score"]
    reversal = f["reversal_score"]
    vol      = f["volatility_state"]
    exp_st   = f["expansion_state"]
    exp_scr  = f["exp_score_15"]

    evidence: list[str] = []
    warnings: list[str] = []

    # ── Priority 1: reversal_attempt ──────────────────────────────────────────
    if f["sweep_reclaim_any"] and f["mss_any"] and reversal >= 50:
        label = "reversal_attempt"
        evidence.append("sweep_reclaim + mss + reversal_score >= 50")

    # ── Priority 2: high_volatility ──────────────────────────────────────────
    elif vol in ("extreme", "high") and trend < 50:
        label = "high_volatility"
        evidence.append(f"volatility_state={vol}")

    # ── Priority 3: expansion_up ─────────────────────────────────────────────
    elif (
        f["is_expanding"] and exp_scr >= 60
        and f["displacement_any"] and f["is_bullish"]
        and trend >= 50
    ):
        label = "expansion_up"
        evidence.append("expanding + displacement + bullish + trend>=50")

    # ── Priority 4: expansion_down ───────────────────────────────────────────
    elif (
        f["is_expanding"] and exp_scr >= 60
        and f["displacement_any"] and f["is_bearish"]
        and trend >= 50
    ):
        label = "expansion_down"
        evidence.append("expanding + displacement + bearish + trend>=50")

    # ── Priority 5: trend_up ─────────────────────────────────────────────────
    elif f["is_bullish"] and trend >= 55 and trend > chop + 20 and reversal < 50:
        label = "trend_up"
        evidence.append(f"bullish + trend={trend} > chop+20={chop + 20}")

    # ── Priority 6: trend_down ───────────────────────────────────────────────
    elif f["is_bearish"] and trend >= 55 and trend > chop + 20 and reversal < 50:
        label = "trend_down"
        evidence.append(f"bearish + trend={trend} > chop+20={chop + 20}")

    # ── Priority 7: low_volatility ───────────────────────────────────────────
    elif vol == "low" and trend < 40:
        label = "low_volatility"
        evidence.append("vol=low + trend<40")

    # ── Priority 8: chop ─────────────────────────────────────────────────────
    elif chop >= 55 and chop > trend:
        label = "chop"
        evidence.append(f"chop={chop} >= 55 and > trend={trend}")

    # ── Priority 9: range_rotation (catchall for low trend) ──────────────────
    elif trend < 50:
        label = "range_rotation"
        evidence.append(f"trend={trend} < 50 — catchall")

    # ── Priority 10: unknown (default) ───────────────────────────────────────
    else:
        label = "unknown"
        warnings.append("No regime pattern matched — insufficient evidence")

    return {
        "enabled":             True,
        "regime_label":        label,
        "regime_family":       _FAMILIES.get(label, "unknown"),
        "confidence":          _compute_confidence(f, label),
        "volatility_state":    vol,
        "expansion_state":     exp_st,
        "trend_score":         trend,
        "chop_score":          chop,
        "reversal_score":      reversal,
        "evidence":            evidence,
        "warnings":            warnings,
        "authority_level":     _AUTHORITY,
        "confidence_modifier": 0,
    }


def _compute_confidence(features: dict, label: str) -> int:
    if label in ("trend_up", "trend_down", "expansion_up", "expansion_down"):
        return min(features["trend_score"], 100)
    if label == "chop":
        return min(features["chop_score"], 100)
    if label == "reversal_attempt":
        return min(features["reversal_score"], 100)
    if label in ("high_volatility", "low_volatility"):
        return 50
    if label == "range_rotation":
        return max(0, 45 - features["trend_score"])
    return 0  # unknown


def _safe_unknown(warnings: list) -> dict:
    return {
        "enabled":             True,
        "regime_label":        "unknown",
        "regime_family":       "unknown",
        "confidence":          0,
        "volatility_state":    "unknown",
        "expansion_state":     "unknown",
        "trend_score":         0,
        "chop_score":          0,
        "reversal_score":      0,
        "evidence":            [],
        "warnings":            warnings,
        "authority_level":     _AUTHORITY,
        "confidence_modifier": 0,
    }

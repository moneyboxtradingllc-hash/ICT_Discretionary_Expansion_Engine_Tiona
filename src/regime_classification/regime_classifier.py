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
        # ── Hierarchy telemetry. The label alone cannot show whether a bearish
        # read survived a bullish pullback or was erased by it; this can.
        "htf_authority":       f.get("htf_authority"),
        "htf_relationship":    f.get("htf_relationship"),
        "reasoning":           f.get("htf_reasoning"),
        "swing_sequence":      f.get("swing_sequence"),
        "swing_detail":        f.get("swing_detail"),
        "bias_15m":            f.get("bias_15m"),
        "bias_5m":             f.get("bias_5m"),
        "range_state":         f.get("range_state"),
        "range_state_detail":  f.get("range_state_detail"),
        "dealing_range":       f.get("dealing_range"),
        "structure_features":  {
            "higher_highs": f.get("higher_highs"), "lower_highs": f.get("lower_highs"),
            "higher_lows":  f.get("higher_lows"),  "lower_lows":  f.get("lower_lows"),
            "range_size":   f.get("range_size"),
            "close_position_in_range": f.get("close_position_in_range"),
        },
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


def format_regime_telemetry(regime: dict) -> str:
    """Audit trail for the regime decision.

    The aggregate label hides mistakes; the component breakdown exposes them.
    Three defects this session were invisible in the label and obvious the
    moment the components were printed, so every field that fed the decision is
    rendered — including the ones that read zero.
    """
    r = regime or {}
    sf = r.get("structure_features") or {}
    dr = r.get("dealing_range") or {}
    auth = r.get("htf_authority") or {}

    lines = ["REGIME TELEMETRY:", ""]
    lines.append(f"  15m structural bias : {r.get('bias_15m')}")
    lines.append(f"  5m structural bias  : {r.get('bias_5m')}")
    lines.append(f"  swing sequence      : {r.get('swing_sequence')}  ({r.get('swing_detail')})")
    lines.append(f"    higher highs      : {sf.get('higher_highs')}")
    lines.append(f"    lower highs       : {sf.get('lower_highs')}")
    lines.append(f"    higher lows       : {sf.get('higher_lows')}")
    lines.append(f"    lower lows        : {sf.get('lower_lows')}")
    lines.append(f"  range               : {r.get('range_state')}  ({r.get('range_state_detail')})")
    lines.append(f"  dealing range       : {dr.get('low')} - {dr.get('high')} "
                 f"(mid {dr.get('midpoint')}) from {dr.get('source_tf')}")
    lines.append(f"  premium/discount    : {dr.get('zone')}  (position {dr.get('position')})")
    lines.append("")
    lines.append(f"  authority           : {auth.get('detail')}")
    lines.append(f"  relationship        : {r.get('htf_relationship')}")
    lines.append("")
    lines.append(f"  scores              : trend {r.get('trend_score')}  "
                 f"chop {r.get('chop_score')}  reversal {r.get('reversal_score')}")
    lines.append(f"  DECISION            : {r.get('regime_label')} "
                 f"(family {r.get('regime_family')}, confidence {r.get('confidence')})")
    for e in (r.get("evidence") or []):
        lines.append(f"    because           : {e}")
    for w in (r.get("warnings") or []):
        lines.append(f"    warning           : {w}")
    if r.get("reasoning"):
        lines.append("")
        lines.append(f"  reasoning           : {r['reasoning']}")
    return "\n".join(lines)

"""
Phase 3B — Experience Correlation Engine.
Analyzes completed paper trades across 10 correlation dimensions.
OBSERVE_ONLY — authority_level always 'observe_only', confidence_modifier always 0.
Never modifies decisions, execution, or confidence.
"""

_AUTHORITY = "observe_only"
_DIMENSIONS: list[str] = [
    "playbook", "preferred_tool", "session", "direction",
    "qualification_status", "risk_tier", "intent_quality",
    "ai_debate_dominant", "decision_type", "setup_lifecycle_phase",
]
_MIN_SAMPLE_RATE   = 3    # minimum trades to compute win/loss rates per group
_MIN_SAMPLE_STRONG = 10   # minimum trades for strongest correlation candidates


def build_correlation(trades: list[dict]) -> dict:
    """
    Entry point. Accepts a flat list of closed trade dicts.
    Never raises. Returns safe default on any error.
    confidence_modifier is ALWAYS 0.
    """
    try:
        return _build(trades)
    except Exception as exc:
        return _safe_default([f"correlation build error: {exc}"])


def build_correlation_for_symbol(symbol: str, days: int = 30) -> dict:
    """Convenience wrapper: loads trades for a symbol and builds correlation."""
    from experience_intelligence.experience_query import load_completed_trades
    trades = load_completed_trades(symbol, days)
    return build_correlation(trades)


def correlation_confidence(n: int) -> str:
    """Public helper — returns correlation confidence label for a sample size."""
    return _confidence_label(n)


def _build(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return _safe_default(["No completed trades available for correlation analysis"])

    dimension_reports: dict = {}
    for dim in _DIMENSIONS:
        dimension_reports[dim] = _analyze_dimension(trades, dim)

    pos_corr, neg_corr = _find_strongest(dimension_reports)

    return {
        "enabled":                         True,
        "authority_level":                  _AUTHORITY,
        "sample_size":                      n,
        "confidence_modifier":              0,
        "dimension_reports":                dimension_reports,
        "strongest_positive_correlations":  pos_corr,
        "strongest_negative_correlations":  neg_corr,
        "warnings":                         _build_warnings(n),
        "notes":                            [],
    }


def _extract_trade_attrs(trade: dict) -> dict:
    """Extract all 10 correlation dimension values from a closed trade record."""
    ss      = trade.get("snapshot_summary")  or {}
    pb      = ss.get("playbook")             or {}
    qual    = ss.get("qualification")        or {}
    risk    = ss.get("risk")                 or {}
    tb      = ss.get("toolbox")              or {}
    da      = ss.get("decision_authority")   or {}
    deb     = ss.get("ai_debate")            or {}
    sl      = ss.get("setup_lifecycle")      or {}
    iscr    = ss.get("intent_score")         or {}
    verdict = (deb.get("final_verdict") or {}) if deb.get("enabled") else {}
    return {
        "playbook":              pb.get("selected_playbook",  ""),
        "preferred_tool":        tb.get("preferred_tool",     ""),
        "session":               ss.get("session",            ""),
        "direction":             pb.get("direction",          ""),
        "qualification_status":  qual.get("status",           ""),
        "risk_tier":             risk.get("risk_tier",        ""),
        "intent_quality":        iscr.get("gated_quality",    ""),
        "ai_debate_dominant":    verdict.get("dominant_thesis", ""),
        "decision_type":         da.get("decision",           ""),
        "setup_lifecycle_phase": sl.get("current_phase",      ""),
    }


def _analyze_dimension(trades: list[dict], dimension: str) -> dict:
    """Group trades by dimension value and compute stats per group."""
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        attrs = _extract_trade_attrs(trade)
        val   = (attrs.get(dimension) or "").strip()
        if not val:
            continue
        groups.setdefault(val, []).append(trade)
    return {val: _compute_entry(dimension, val, grp) for val, grp in groups.items()}


def _compute_entry(dimension: str, value: str, trades: list[dict]) -> dict:
    """Compute win rate, loss rate, and average R for one dimension+value group."""
    n        = len(trades)
    r_values: list[float] = []
    wins     = 0

    for t in trades:
        pnl  = t.get("realized_pnl")
        risk = t.get("risk_dollars")
        if pnl is None:
            continue
        r = (pnl / risk) if (risk and risk > 0) else (
            1.0 if pnl > 0 else (-1.0 if pnl < 0 else 0.0)
        )
        r_values.append(r)
        if pnl > 0:
            wins += 1

    m         = len(r_values)
    win_rate  = round(wins / m * 100, 1)       if m >= _MIN_SAMPLE_RATE else None
    loss_rate = round((m - wins) / m * 100, 1) if m >= _MIN_SAMPLE_RATE else None
    avg_r     = round(sum(r_values) / m, 2)    if m >= _MIN_SAMPLE_RATE else None

    return {
        "dimension":    dimension,
        "value":        value,
        "sample_size":  n,
        "win_rate":     win_rate,
        "loss_rate":    loss_rate,
        "average_r":    avg_r,
        "average_mfe":  None,   # Phase 3C: requires intent-to-trade linkage
        "average_mae":  None,   # Phase 3C: requires intent-to-trade linkage
        "best_context":  "",    # Phase 3C: cross-dimension analysis
        "worst_context": "",    # Phase 3C: cross-dimension analysis
        "confidence":   _confidence_label(n),
    }


def _find_strongest(
    dimension_reports: dict,
) -> tuple[list[str], list[str]]:
    """Collect dimension+value groups meeting minimum sample, sort by win rate."""
    candidates: list[tuple] = []
    for dim, values in dimension_reports.items():
        for val, entry in values.items():
            n  = entry["sample_size"]
            wr = entry.get("win_rate")
            if n < _MIN_SAMPLE_STRONG or wr is None:
                continue
            candidates.append((dim, val, n, wr))

    pos_sorted = sorted(candidates, key=lambda x: x[3], reverse=True)
    neg_sorted = sorted(candidates, key=lambda x: x[3])

    positive = [
        f"{e[0]}={e[1]}: {e[3]:.1f}% WR over {e[2]} samples"
        for e in pos_sorted[:5] if e[3] > 50.0
    ]
    negative = [
        f"{e[0]}={e[1]}: {e[3]:.1f}% WR over {e[2]} samples"
        for e in neg_sorted[:5] if e[3] < 50.0
    ]
    return positive, negative


def _confidence_label(n: int) -> str:
    if n >= 50: return "high"
    if n >= 20: return "medium"
    if n >  0:  return "low"
    return "none"


def _build_warnings(n: int) -> list[str]:
    if n < 20:
        return [f"Low confidence — {n} trade(s) available, minimum 20 for medium confidence"]
    if n < 50:
        return [f"Medium confidence — {n} trades, minimum 50 for high confidence"]
    return []


def _safe_default(notes: list[str]) -> dict:
    return {
        "enabled":                         True,
        "authority_level":                  _AUTHORITY,
        "sample_size":                      0,
        "confidence_modifier":              0,
        "dimension_reports":                {},
        "strongest_positive_correlations":  [],
        "strongest_negative_correlations":  [],
        "warnings":                         ["Insufficient sample size for correlation analysis"],
        "notes":                            notes,
    }

"""
Phase 3B/3C — Experience Correlation Engine.
Analyzes completed paper trades across 10 correlation dimensions.
Phase 3C: optional linked_outcomes enriches per-dimension MFE/MAE and linkage counts.
OBSERVE_ONLY — authority_level always 'observe_only', confidence_modifier always 0.
Never modifies decisions, execution, or confidence.
"""

_AUTHORITY = "observe_only"
_DIMENSIONS: list[str] = [
    "playbook", "preferred_tool", "session", "direction",
    "qualification_status", "risk_tier", "intent_quality",
    "ai_debate_dominant", "decision_type", "setup_lifecycle_phase",
    "market_regime_label",           # Phase 5A — trade top-level
    "ai_agreement_with_playbook",    # Phase 5B — trade top-level
    "ai_agreement_with_risk",        # Phase 5B — trade top-level
    "ai_debate_dominant_thesis",     # Phase 5B — trade top-level
    "ai_debate_recommended_stance",  # Phase 5B — trade top-level
    "confidence_fusion_status_at_entry",  # Phase 5B — trade top-level
    "ai_value_label",                # Phase 5B — trade top-level (set after closure)
]
_MIN_SAMPLE_RATE   = 3    # minimum trades to compute win/loss rates per group
_MIN_SAMPLE_STRONG = 10   # minimum trades for strongest correlation candidates


def build_correlation(
    trades: list[dict],
    linked_outcomes: "list[dict] | None" = None,
) -> dict:
    """
    Entry point. Accepts a flat list of closed trade dicts.
    Phase 3C: optional linked_outcomes enriches per-dimension MFE/MAE and counts.
    Never raises. Returns safe default on any error.
    confidence_modifier is ALWAYS 0.
    """
    try:
        return _build(trades, linked_outcomes)
    except Exception as exc:
        return _safe_default([f"correlation build error: {exc}"])


def build_correlation_for_symbol(symbol: str, days: int = 30) -> dict:
    """
    Convenience wrapper: loads trades + runs Phase 3C linkage, builds correlation.
    """
    from experience_intelligence.experience_query        import (
        load_completed_trades, load_all_intent_records,
    )
    from experience_intelligence.intent_trade_linker     import link_intents_to_trades
    from experience_intelligence.linked_outcome_metrics  import compute_linked_metrics
    trades          = load_completed_trades(symbol, days)
    intents         = load_all_intent_records(symbol, days)
    links           = link_intents_to_trades(intents, trades)
    linked_outcomes = compute_linked_metrics(links, intents, trades)
    return build_correlation(trades, linked_outcomes)


def correlation_confidence(n: int) -> str:
    """Public helper — returns correlation confidence label for a sample size."""
    return _confidence_label(n)


def _build(
    trades: list[dict],
    linked_outcomes: "list[dict] | None" = None,
) -> dict:
    n = len(trades)
    if n == 0:
        return _safe_default(["No completed trades available for correlation analysis"])

    # Build trade_id → linked_outcome lookup for O(1) enrichment per trade
    linked_by_trade: dict = {}
    if linked_outcomes:
        for lo in linked_outcomes:
            tid = lo.get("trade_id")
            if tid and lo.get("linked"):
                linked_by_trade[tid] = lo

    dimension_reports: dict = {}
    for dim in _DIMENSIONS:
        dimension_reports[dim] = _analyze_dimension(trades, dim, linked_by_trade)

    pos_corr, neg_corr = _find_strongest(dimension_reports)

    # Top-level linked closed count for warnings
    total_linked_closed = sum(
        1 for lo in (linked_outcomes or []) if lo.get("linked") and lo.get("closed")
    )
    warnings = _build_warnings(n)
    if linked_outcomes is not None and total_linked_closed == 0:
        warnings.append("No linked closed trades available for outcome correlation")

    return {
        "enabled":                         True,
        "authority_level":                  _AUTHORITY,
        "sample_size":                      n,
        "confidence_modifier":              0,
        "dimension_reports":                dimension_reports,
        "strongest_positive_correlations":  pos_corr,
        "strongest_negative_correlations":  neg_corr,
        "warnings":                         warnings,
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
        # Phase 5A: top-level trade field, not in snapshot_summary
        "market_regime_label":          (trade.get("market_regime_label") or "").lower(),
        # Phase 5B: AI feedback fields — top-level trade fields
        "ai_agreement_with_playbook":   str(trade.get("ai_agreement_with_playbook", "")).lower(),
        "ai_agreement_with_risk":       str(trade.get("ai_agreement_with_risk",     "")).lower(),
        "ai_debate_dominant_thesis":    (trade.get("ai_debate_dominant_thesis")    or "").lower(),
        "ai_debate_recommended_stance": (trade.get("ai_debate_recommended_stance") or "").lower(),
        "confidence_fusion_status_at_entry": (
            trade.get("confidence_fusion_status_at_entry") or ""
        ).lower(),
        "ai_value_label":               (trade.get("ai_value_label") or "").lower(),
    }


def _analyze_dimension(
    trades: list[dict],
    dimension: str,
    linked_by_trade: dict | None = None,
) -> dict:
    """Group trades by dimension value and compute stats per group."""
    lbt    = linked_by_trade or {}
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        attrs = _extract_trade_attrs(trade)
        val   = (attrs.get(dimension) or "").strip()
        if not val:
            continue
        groups.setdefault(val, []).append(trade)
    return {
        val: _compute_entry(dimension, val, grp, lbt)
        for val, grp in groups.items()
    }


def _compute_entry(
    dimension: str,
    value: str,
    trades: list[dict],
    linked_by_trade: dict | None = None,
) -> dict:
    """Compute stats for one dimension+value group, enriched with linked outcomes."""
    lbt      = linked_by_trade or {}
    n        = len(trades)
    r_values: list[float] = []
    wins     = 0
    mfe_vals: list[float] = []
    mae_vals: list[float] = []
    linked_count = 0
    closed_count = 0

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

        # Phase 3C: enrich from linked outcome
        tid = _trade_id(t)
        if tid and tid in lbt:
            lo = lbt[tid]
            linked_count += 1
            if lo.get("closed"):
                closed_count += 1
            if lo.get("mfe") is not None:
                mfe_vals.append(lo["mfe"])
            if lo.get("mae") is not None:
                mae_vals.append(lo["mae"])

    m         = len(r_values)
    win_rate  = round(wins / m * 100, 1)       if m >= _MIN_SAMPLE_RATE else None
    loss_rate = round((m - wins) / m * 100, 1) if m >= _MIN_SAMPLE_RATE else None
    avg_r     = round(sum(r_values) / m, 2)    if m >= _MIN_SAMPLE_RATE else None
    avg_mfe   = round(sum(mfe_vals) / len(mfe_vals), 2) if mfe_vals else None
    avg_mae   = round(sum(mae_vals) / len(mae_vals), 2) if mae_vals else None

    return {
        "dimension":          dimension,
        "value":              value,
        "sample_size":        n,
        "win_rate":           win_rate,
        "loss_rate":          loss_rate,
        "average_r":          avg_r,
        "average_mfe":        avg_mfe,        # Phase 3C: from linked outcomes
        "average_mae":        avg_mae,         # Phase 3C: from linked outcomes
        "linked_trade_count": linked_count,   # Phase 3C
        "closed_trade_count": closed_count,   # Phase 3C
        "best_context":        "",            # Phase 3D: cross-dimension analysis
        "worst_context":       "",            # Phase 3D: cross-dimension analysis
        "confidence":          _confidence_label(n),
    }


def _trade_id(trade: dict):
    return (
        trade.get("trade_id")
        or trade.get("alpaca_order_id")
        or trade.get("order_id")
        or trade.get("id")
    )


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

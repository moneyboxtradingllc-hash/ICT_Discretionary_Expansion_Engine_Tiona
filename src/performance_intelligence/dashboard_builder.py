"""
Phase 5D — Dashboard Builder.
Builds the Performance Intelligence Dashboard from paper trade records.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
from memory_search.memory_record_builder import (
    load_memory_records_partitioned,
)
from performance_intelligence.performance_metrics import (
    calculate_trade_metrics,
    calculate_regime_metrics,
    calculate_session_metrics,
    calculate_playbook_metrics,
    calculate_ai_metrics,
    calculate_memory_metrics,
    find_best_worst,
    most_common_failure,
)


def build_dashboard(symbol: str | None = None, memory_summary: dict | None = None) -> dict:
    """
    Build performance intelligence dashboard for the given symbol.
    Never raises. Returns safe defaults on any error.
    """
    try:
        return _build(symbol, memory_summary)
    except Exception as exc:
        return _empty_dashboard(warnings=[f"dashboard build failed (non-blocking): {exc}"])


def build_dashboard_from_records(
    records: list[dict],
    memory_summary: dict | None = None,
) -> dict:
    """Build dashboard from pre-loaded normalized records. Used in tests and pipeline."""
    try:
        return _build_from_records(records, memory_summary)
    except Exception as exc:
        return _empty_dashboard(warnings=[f"dashboard build failed (non-blocking): {exc}"])


# ── Internal ──────────────────────────────────────────────────────────────────

def _build(symbol: str | None, memory_summary: dict | None) -> dict:
    # DASHBOARD-BASELINE — active baseline = post-epoch only; the pre-epoch
    # count is carried for the CLEAN_BASELINE audit line.
    records, pre_epoch = load_memory_records_partitioned(symbol)
    dash = _build_from_records(records, memory_summary)
    dash["pre_epoch_excluded"] = len(pre_epoch)
    return dash


def _build_from_records(records: list[dict], memory_summary: dict | None) -> dict:
    warnings: list[str] = []
    notes:    list[str] = []

    # Overall trade metrics
    trade_m  = calculate_trade_metrics(records)
    closed   = trade_m["closed_trades"]

    # Dimension metrics
    regime_m   = calculate_regime_metrics(records)
    session_m  = calculate_session_metrics(records)
    playbook_m = calculate_playbook_metrics(records)

    best_regime,   worst_regime   = find_best_worst(regime_m)
    best_session,  worst_session  = find_best_worst(session_m)
    best_playbook, worst_playbook = find_best_worst(playbook_m)

    # AI metrics
    ai_m = calculate_ai_metrics(records)

    # Memory metrics
    mem_m = calculate_memory_metrics(memory_summary)

    # Most common failure
    failure = most_common_failure(records)

    if closed == 0:
        notes.append("No closed trades available for analysis.")
    notes.append("Dashboard is observe-only and does not affect decisions.")

    return {
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "pre_epoch_excluded":    0,   # DASHBOARD-BASELINE (set by _build)

        "total_trades":          trade_m["total_trades"],
        "closed_trades":         closed,
        "wins":                  trade_m["wins"],
        "losses":                trade_m["losses"],
        "breakeven":             trade_m["breakeven"],

        "win_rate":              trade_m["win_rate"],
        "average_r":             trade_m["average_r"],
        "average_pnl":           trade_m["average_pnl"],
        "largest_win_r":         trade_m["largest_win_r"],
        "largest_loss_r":        trade_m["largest_loss_r"],

        "best_playbook":         best_playbook,
        "worst_playbook":        worst_playbook,
        "playbook_metrics":      playbook_m,

        "best_regime":           best_regime,
        "worst_regime":          worst_regime,
        "regime_metrics":        regime_m,

        "best_session":          best_session,
        "worst_session":         worst_session,
        "session_metrics":       session_m,

        "most_common_failure":   failure,

        "ai_outcome_available":  ai_m["ai_outcome_available"],
        "ai_agreement_rate":     ai_m["ai_agreement_rate"],
        "ai_disagreement_rate":  ai_m["ai_disagreement_rate"],
        "ai_correct_rate":       ai_m["ai_correct_rate"],
        "ai_incorrect_rate":     ai_m["ai_incorrect_rate"],
        "ai_helpful_rate":       ai_m["ai_helpful_rate"],
        "ai_harmful_rate":       ai_m["ai_harmful_rate"],

        "memory_quality":        mem_m["memory_quality"],
        "closed_match_count":    mem_m["closed_match_count"],
        "best_similarity":       mem_m["best_similarity"],

        "warnings":              warnings,
        "notes":                 notes,
    }


def _empty_dashboard(warnings: list[str] | None = None) -> dict:
    return {
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "pre_epoch_excluded":    0,   # DASHBOARD-BASELINE
        "total_trades":          0,
        "closed_trades":         0,
        "wins":                  0,
        "losses":                0,
        "breakeven":             0,
        "win_rate":              None,
        "average_r":             None,
        "average_pnl":           None,
        "largest_win_r":         None,
        "largest_loss_r":        None,
        "best_playbook":         None,
        "worst_playbook":        None,
        "playbook_metrics":      {},
        "best_regime":           None,
        "worst_regime":          None,
        "regime_metrics":        {},
        "best_session":          None,
        "worst_session":         None,
        "session_metrics":       {},
        "most_common_failure":   None,
        "ai_outcome_available":  False,
        "ai_agreement_rate":     None,
        "ai_disagreement_rate":  None,
        "ai_correct_rate":       None,
        "ai_incorrect_rate":     None,
        "ai_helpful_rate":       None,
        "ai_harmful_rate":       None,
        "memory_quality":        "none",
        "closed_match_count":    0,
        "best_similarity":       0.0,
        "warnings":              warnings or [],
        "notes":                 ["Dashboard is observe-only and does not affect decisions."],
    }

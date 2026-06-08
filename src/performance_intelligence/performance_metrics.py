"""
Phase 5D — Performance Metrics.
Pure helper functions for computing trade analytics.
OBSERVE_ONLY — no decision logic, no execution influence.
"""

_CLOSED_OUTCOMES = {"win", "loss", "breakeven"}
_MIN_DIM_TRADES  = 3  # minimum trades per dimension value to compute stats

_FAILURE_KEYWORDS: list[tuple[str, str]] = [
    ("stop",      "stop_loss"),
    ("loss",      "stop_loss"),
    ("reversal",  "reversal_failure"),
    ("chop",      "chop_participation"),
    ("late",      "late_continuation"),
    ("fade",      "late_continuation"),
    ("whipsaw",   "volatility_whipsaw"),
    ("expire",    "setup_expired"),
]

_REGIME_FAILURE_MAP: dict[str, str] = {
    "chop":              "chop_participation",
    "reversal_attempt":  "reversal_failure",
    "high_volatility":   "volatility_whipsaw",
    "trend_up":          "late_continuation",
    "trend_down":        "late_continuation",
    "range_rotation":    "late_continuation",
}


def calculate_trade_metrics(trades: list[dict]) -> dict:
    """Compute overall trade statistics from normalized records."""
    closed   = [t for t in trades if t.get("outcome") in _CLOSED_OUTCOMES]
    wins     = [t for t in closed  if t.get("outcome") == "win"]
    losses   = [t for t in closed  if t.get("outcome") == "loss"]
    be_trades = [t for t in closed if t.get("outcome") == "breakeven"]

    rs   = [t["realized_r"]   for t in closed if t.get("realized_r")   is not None]
    pnls = [t["realized_pnl"] for t in closed if t.get("realized_pnl") is not None]

    win_r_vals  = [t["realized_r"] for t in wins   if t.get("realized_r") is not None]
    loss_r_vals = [t["realized_r"] for t in losses if t.get("realized_r") is not None]

    return {
        "total_trades":    len(trades),
        "closed_trades":   len(closed),
        "wins":            len(wins),
        "losses":          len(losses),
        "breakeven":       len(be_trades),
        "win_rate":        round(len(wins) / len(closed) * 100, 1) if closed else None,
        "average_r":       round(sum(rs)   / len(rs),   2)         if rs   else None,
        "average_pnl":     round(sum(pnls) / len(pnls), 2)         if pnls else None,
        "largest_win_r":   round(max(win_r_vals),  2)              if win_r_vals  else None,
        "largest_loss_r":  round(min(loss_r_vals), 2)              if loss_r_vals else None,
    }


def calculate_dimension_metrics(
    trades: list[dict],
    dimension: str,
    min_trades: int = _MIN_DIM_TRADES,
) -> dict[str, dict]:
    """
    Group closed trades by a categorical dimension and compute per-group stats.
    Returns {value: {win_rate, sample_size, average_r}}.
    Groups with fewer than min_trades are excluded.
    """
    groups: dict[str, list] = {}
    for t in trades:
        if t.get("outcome") not in _CLOSED_OUTCOMES:
            continue
        val = (t.get(dimension) or "").lower().strip()
        if not val or val == "unknown":
            continue
        groups.setdefault(val, []).append(t)

    result: dict[str, dict] = {}
    for val, group in groups.items():
        if len(group) < min_trades:
            continue
        wins = sum(1 for t in group if t.get("outcome") == "win")
        rs   = [t["realized_r"] for t in group if t.get("realized_r") is not None]
        result[val] = {
            "win_rate":    round(wins / len(group) * 100, 1),
            "sample_size": len(group),
            "average_r":   round(sum(rs) / len(rs), 2) if rs else None,
        }
    return result


def calculate_regime_metrics(trades: list[dict]) -> dict[str, dict]:
    return calculate_dimension_metrics(trades, "market_regime_label")


def calculate_session_metrics(trades: list[dict]) -> dict[str, dict]:
    return calculate_dimension_metrics(trades, "session")


def calculate_playbook_metrics(trades: list[dict]) -> dict[str, dict]:
    return calculate_dimension_metrics(trades, "playbook")


def calculate_ai_metrics(trades: list[dict]) -> dict:
    """AI outcome statistics from normalized trade records."""
    scored = [t for t in trades if t.get("outcome") in _CLOSED_OUTCOMES]
    if not scored:
        return {
            "ai_outcome_available":  False,
            "ai_agreement_rate":     None,
            "ai_disagreement_rate":  None,
            "ai_correct_rate":       None,
            "ai_incorrect_rate":     None,
            "ai_helpful_rate":       None,
            "ai_harmful_rate":       None,
        }

    helpful   = [t for t in scored if t.get("ai_value_label") == "helpful"]
    harmful   = [t for t in scored if t.get("ai_value_label") == "harmful"]
    ai_scored = [t for t in scored if t.get("ai_value_label") not in ("unknown", None, "")]

    directional = [
        t for t in scored
        if t.get("ai_was_directionally_correct") is not None
    ]
    correct = [t for t in directional if t.get("ai_was_directionally_correct") is True]

    with_agree = [
        t for t in scored
        if t.get("ai_agreement_with_playbook") is not None
    ]
    agreed = [t for t in with_agree if t.get("ai_agreement_with_playbook") is True]

    return {
        "ai_outcome_available":  len(ai_scored) > 0,
        "ai_agreement_rate":     round(len(agreed)  / len(with_agree) * 100, 1) if with_agree  else None,
        "ai_disagreement_rate":  round((len(with_agree) - len(agreed)) / len(with_agree) * 100, 1) if with_agree else None,
        "ai_correct_rate":       round(len(correct)  / len(directional) * 100, 1) if directional else None,
        "ai_incorrect_rate":     round((len(directional) - len(correct)) / len(directional) * 100, 1) if directional else None,
        "ai_helpful_rate":       round(len(helpful) / len(ai_scored) * 100, 1) if ai_scored else None,
        "ai_harmful_rate":       round(len(harmful) / len(ai_scored) * 100, 1) if ai_scored else None,
    }


def calculate_memory_metrics(memory_summary: dict | None) -> dict:
    """Pass-through of memory search summary fields for the dashboard."""
    ms = memory_summary or {}
    return {
        "memory_quality":      ms.get("memory_quality",      "none"),
        "closed_match_count":  ms.get("closed_match_count",  0),
        "best_similarity":     ms.get("best_similarity",     0.0),
    }


def find_best_worst(
    dim_metrics: dict[str, dict],
) -> tuple[str | None, str | None]:
    """Return (best_key, worst_key) by win_rate from a dimension metrics dict."""
    if not dim_metrics:
        return None, None
    sorted_keys = sorted(
        dim_metrics,
        key=lambda k: (dim_metrics[k]["win_rate"], dim_metrics[k]["sample_size"]),
        reverse=True,
    )
    best  = sorted_keys[0]  if sorted_keys else None
    worst = sorted_keys[-1] if len(sorted_keys) > 1 else None
    # Only report worst if actually worse than best
    if best and worst and best == worst:
        worst = None
    return best, worst


def most_common_failure(trades: list[dict]) -> str | None:
    """
    Identify the most common failure pattern from losing trades.
    Uses close_reason if available, falls back to regime-based inference.
    """
    losses = [t for t in trades if t.get("outcome") == "loss"]
    if len(losses) < 3:
        return None

    counts: dict[str, int] = {}
    for t in losses:
        cat = _categorize_failure(t.get("close_reason"), t.get("market_regime_label"))
        counts[cat] = counts.get(cat, 0) + 1

    if not counts:
        return "unknown"
    return max(counts, key=lambda k: counts[k])


def _categorize_failure(close_reason: str | None, regime: str | None) -> str:
    if close_reason:
        low = close_reason.lower()
        for kw, cat in _FAILURE_KEYWORDS:
            if kw in low:
                return cat
    if regime:
        low_r = regime.lower()
        for pat, cat in _REGIME_FAILURE_MAP.items():
            if pat in low_r:
                return cat
    return "unknown"

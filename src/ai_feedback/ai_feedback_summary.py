"""
Phase 5B — AI Feedback Summary.
Aggregates AI outcome scores across closed trades.
OBSERVE_ONLY — authority_level always 'observe_only', confidence_modifier always 0.
"""

_MIN_RATE_SAMPLE = 3   # minimum trades to compute rate metrics


def build_ai_feedback_summary(closed_trades: list) -> dict:
    """
    Aggregate AI outcome scores across closed trades.
    Never raises. Returns safe empty summary on any error.
    confidence_modifier is ALWAYS 0. authority_level is ALWAYS 'observe_only'.
    """
    try:
        return _build(closed_trades or [])
    except Exception as exc:
        return _empty_summary([f"ai feedback summary error: {exc}"])


def _build(trades: list) -> dict:
    n = len(trades)

    if n == 0:
        return _empty_summary(["Insufficient AI outcome sample size"])

    helpful_count  = 0
    harmful_count  = 0
    neutral_count  = 0
    unknown_count  = 0
    agree_wins     = 0
    agree_total    = 0
    disagree_wins  = 0
    disagree_total = 0
    ext_wins       = 0
    ext_total      = 0
    fb_wins        = 0
    fb_total       = 0

    condition_buckets: dict[str, list[float]] = {}

    for t in trades:
        label        = (t.get("ai_value_label")       or "unknown").lower()
        agree_pb     = t.get("ai_agreement_with_playbook")
        ext_used     = bool(t.get("ai_external_used",  False))
        fallback     = bool(t.get("ai_fallback_used",  False))
        realized_r   = t.get("realized_r")
        fusion_st    = (t.get("confidence_fusion_status_at_entry") or "").lower()
        dom_thesis   = (t.get("ai_debate_dominant_thesis")         or "").lower()
        stance       = (t.get("ai_debate_recommended_stance")      or "").lower()

        if label == "helpful":  helpful_count  += 1
        elif label == "harmful": harmful_count  += 1
        elif label == "neutral": neutral_count  += 1
        else:                    unknown_count  += 1

        if realized_r is not None:
            r = float(realized_r)
            won = r > 0

            if agree_pb is True:
                agree_wins  += (1 if won else 0)
                agree_total += 1
            elif agree_pb is False:
                disagree_wins  += (1 if won else 0)
                disagree_total += 1

            if ext_used:
                ext_wins  += (1 if won else 0)
                ext_total += 1

            if fallback:
                fb_wins  += (1 if won else 0)
                fb_total += 1

            # Condition buckets for best/worst
            if fusion_st:
                condition_buckets.setdefault(f"fusion={fusion_st}", []).append(r)
            if dom_thesis:
                condition_buckets.setdefault(f"thesis={dom_thesis}", []).append(r)
            if stance:
                condition_buckets.setdefault(f"stance={stance}", []).append(r)

    scored_n = helpful_count + harmful_count + neutral_count
    ai_helpful_rate  = _rate(helpful_count,  scored_n)
    ai_harmful_rate  = _rate(harmful_count,  scored_n)
    agreement_wr     = _win_rate(agree_wins,     agree_total)
    disagreement_wr  = _win_rate(disagree_wins,  disagree_total)
    external_wr      = _win_rate(ext_wins,        ext_total)
    fallback_wr      = _win_rate(fb_wins,         fb_total)

    best_cond, worst_cond = _best_worst_condition(condition_buckets)

    if n < 20:
        notes = [f"Insufficient AI outcome sample — {n} trade(s), minimum 20 for rates"]
    elif n < 50:
        notes = [f"Developing: {n} trades — minimum 50 for meaningful AI feedback statistics"]
    else:
        notes = [f"Meaningful: {n} trades available for AI feedback analysis"]

    return {
        "enabled":              True,
        "authority_level":      "observe_only",
        "confidence_modifier":  0,
        "sample_size":          n,
        "ai_helpful_count":     helpful_count,
        "ai_harmful_count":     harmful_count,
        "ai_neutral_count":     neutral_count,
        "ai_unknown_count":     unknown_count,
        "ai_helpful_rate":      ai_helpful_rate,
        "ai_harmful_rate":      ai_harmful_rate,
        "agreement_win_rate":   agreement_wr,
        "disagreement_win_rate": disagreement_wr,
        "external_ai_win_rate": external_wr,
        "fallback_ai_win_rate": fallback_wr,
        "best_ai_condition":    best_cond,
        "worst_ai_condition":   worst_cond,
        "notes":                notes,
    }


def _rate(count: int, total: int):
    if total < _MIN_RATE_SAMPLE:
        return None
    return round(count / total * 100, 1)


def _win_rate(wins: int, total: int):
    if total < _MIN_RATE_SAMPLE:
        return None
    return round(wins / total * 100, 1)


def _best_worst_condition(buckets: dict) -> tuple:
    rates = {}
    for key, rs in buckets.items():
        if len(rs) >= 2:
            rates[key] = sum(1 for r in rs if r > 0) / len(rs)
    if not rates:
        return None, None
    return max(rates, key=rates.get), min(rates, key=rates.get)


def _empty_summary(notes: list) -> dict:
    return {
        "enabled":              True,
        "authority_level":      "observe_only",
        "confidence_modifier":  0,
        "sample_size":          0,
        "ai_helpful_count":     0,
        "ai_harmful_count":     0,
        "ai_neutral_count":     0,
        "ai_unknown_count":     0,
        "ai_helpful_rate":      None,
        "ai_harmful_rate":      None,
        "agreement_win_rate":   None,
        "disagreement_win_rate": None,
        "external_ai_win_rate": None,
        "fallback_ai_win_rate": None,
        "best_ai_condition":    None,
        "worst_ai_condition":   None,
        "notes":                notes,
    }

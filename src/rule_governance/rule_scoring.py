"""
Phase 5H.4 — Rule Scoring.

Per-rule metrics from resolved divergence-ledger events:

  protected_loss_R     = sum(|r|) over fired events with r < 0
  missed_opportunity_R = sum(r)   over fired events with r > 0
  net_protected_R      = protected - missed
  efficiency           = protected / (protected + missed)
  fire_rate            = fired-on-opportunity events / opportunity scans seen
                         (approximated from ledger: events ARE opportunity
                          firings; the denominator is supplied by the caller
                          from daily digests when available)

Promotion bar (architecture §9) and demotion bar (§10) are evaluated here;
the OUTPUT is a recommendation in a report — promotion itself remains a
human-reviewed code change. OBSERVE ONLY. Never raises.
"""

PROMOTION_BAR = {
    "min_resolved":          20,
    "min_fills":             5,     # OR min_sessions met (caller supplies)
    "min_sessions_fallback": 20,
    "min_efficiency":        0.60,
    "max_fire_rate":         0.60,
    "max_indeterminate":     0.25,
}

DEMOTION_BAR = {
    "window":         30,
    "min_window":     10,
    "min_efficiency": 0.40,
    "max_fire_rate":  0.75,
}


def _resolved(events: list) -> list:
    return [
        e for e in events
        if (e.get("resolution") or {}).get("state") == "resolved"
    ]


def score_rule(rule_id: str, events: list, opportunities_seen: int = 0,
               sessions_seen: int = 0) -> dict:
    """
    Score one rule from its ledger events. Never raises.
    `events` should be pre-filtered to this rule (the function also filters).
    """
    try:
        mine     = [e for e in events if e.get("rule_id") == rule_id]
        resolved = _resolved(mine)

        protected = missed = 0.0
        fills = proxies = indeterminate = 0
        rs = []

        for e in resolved:
            res = e["resolution"]
            r   = float(res.get("r", 0.0))
            rs.append(r)
            if res.get("source") == "fill":
                fills += 1
            else:
                proxies += 1
            if res.get("low_confidence"):
                indeterminate += 1
            if r < 0:
                protected += abs(r)
            elif r > 0:
                missed += r

        net   = round(protected - missed, 4)
        gross = protected + missed
        efficiency = round(protected / gross, 4) if gross > 0 else None

        fire_rate = (
            round(len(mine) / opportunities_seen, 4)
            if opportunities_seen > 0 else None
        )
        indeterminate_share = (
            round(indeterminate / len(resolved), 4) if resolved else 0.0
        )

        # Outlier robustness: net with the single best (most negative r,
        # i.e. most protective) event removed
        net_excl_best = net
        if rs:
            most_protective = min(rs)
            if most_protective < 0:
                net_excl_best = round(net - abs(most_protective), 4)

        return {
            "rule_id":              rule_id,
            "events_total":         len(mine),
            "events_resolved":      len(resolved),
            "fills":                fills,
            "proxies":              proxies,
            "protected_loss_R":     round(protected, 4),
            "missed_opportunity_R": round(missed, 4),
            "net_protected_R":      net,
            "net_excl_best_R":      net_excl_best,
            "efficiency":           efficiency,
            "fire_rate":            fire_rate,
            "indeterminate_share":  indeterminate_share,
            "sessions_seen":        sessions_seen,
            "promotion":            _evaluate_promotion(
                len(resolved), fills, sessions_seen, net, net_excl_best,
                efficiency, fire_rate, indeterminate_share,
            ),
            "demotion":             _evaluate_demotion(
                len(resolved), net, efficiency, fire_rate,
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"rule_id": rule_id, "error": f"scoring error: {exc}"}


def _evaluate_promotion(n_resolved, fills, sessions, net, net_excl_best,
                        efficiency, fire_rate, indeterminate_share) -> dict:
    bar     = PROMOTION_BAR
    checks  = {
        "sample_size":    n_resolved >= bar["min_resolved"],
        "fill_evidence":  (fills >= bar["min_fills"]
                           or sessions >= bar["min_sessions_fallback"]),
        "net_positive":   net > 0,
        "outlier_robust": net_excl_best > 0,
        "efficiency":     efficiency is not None and efficiency >= bar["min_efficiency"],
        "fire_rate":      fire_rate is None or fire_rate <= bar["max_fire_rate"],
        "data_quality":   indeterminate_share <= bar["max_indeterminate"],
    }
    return {
        "eligible": all(checks.values()),
        "checks":   checks,
        "note":     "promotion is a human-reviewed code change — this is a recommendation only",
    }


def _evaluate_demotion(n_resolved, net, efficiency, fire_rate) -> dict:
    bar = DEMOTION_BAR
    if n_resolved < bar["min_window"]:
        return {"flagged": False, "checks": {}, "note": "insufficient window"}
    checks = {
        "net_negative":   net < 0,
        "efficiency_low": efficiency is not None and efficiency < bar["min_efficiency"],
        "fire_rate_high": fire_rate is not None and fire_rate > bar["max_fire_rate"],
    }
    return {
        "flagged": any(checks.values()),
        "checks":  checks,
        "note":    "two consecutive flagged weekly reports -> demotion recommendation",
    }

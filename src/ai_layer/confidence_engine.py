"""
Confidence Engine — scores trade readiness from mechanical + narrative + PO3 evidence.
Max 100 points across six weighted categories, with PO3 modifiers and hard caps.
"""

TIERS = [
    (85, "elite_setup"),
    (70, "valid_setup"),
    (50, "observe"),
    (0,  "no_trade"),
]

SESSION_SCORES = {
    "ny_open":              10,
    "morning_continuation":  9,
    "power_hour":            8,
    "afternoon":             6,
    "lunch":                 3,
    "premarket":             2,
    "after_hours":           1,
    "closed":                0,
}

ALIGNMENT_SCORES = {
    "full":    30,
    "strong":  22,
    "partial": 12,
    "mixed":    5,
    "neutral":  0,
}

PO3_ALIGNMENT_BONUS = {
    "full_distribution_alignment":  7,
    "manipulation_to_distribution": 5,
    "accumulation_building":        2,
}


# ── Category Scorers ──────────────────────────────────────────────────────────

def _structure_points(structure: dict) -> int:
    return ALIGNMENT_SCORES.get(structure.get("alignment", "neutral"), 0)


def _expansion_points(expansion: dict) -> int:
    state_15m = expansion.get("15m", {}).get("state", "")
    state_5m  = expansion.get("5m",  {}).get("state", "")
    score_15m = expansion.get("15m", {}).get("expansion_score", 0)
    score_5m  = expansion.get("5m",  {}).get("expansion_score", 0)
    avg = (score_15m + score_5m) / 2

    if state_15m == "healthy_expansion" and state_5m in ("healthy_expansion", "mature_expansion"):
        return 20
    if state_15m in ("healthy_expansion", "mature_expansion"):
        return 14
    if avg > 55:
        return 10
    if avg > 40:
        return 5
    return 0


def _liquidity_points(liquidity: dict) -> int:
    tfs     = ["15m", "5m", "3m", "1m"]
    sweep   = any(liquidity.get(tf, {}).get("sweep_detected")  for tf in tfs)
    reclaim = any(liquidity.get(tf, {}).get("reclaim_detected") for tf in tfs)
    failed  = any(liquidity.get(tf, {}).get("failed_breakout") for tf in ["5m", "3m", "1m"])

    if sweep and reclaim:
        return 15
    if failed:
        return 10
    if sweep:
        return 8
    return 5


def _volatility_points(volatility: dict) -> int:
    state = volatility.get("15m", {}).get("state", "")
    score = volatility.get("15m", {}).get("volatility_score", 50)

    if state == "expanding" and 58 <= score <= 82:
        return 15
    if state == "stable" and score > 35:
        return 12
    if state == "unstable":
        return 5
    if state in ("toxic", "explosive", "liquidity_vacuum"):
        return 0
    return 8


def _session_points(session: str) -> int:
    return SESSION_SCORES.get(session, 5)


def _exhaustion_points(expansion: dict) -> int:
    tfs  = ["15m", "5m", "3m"]
    high = sum(
        1 for tf in tfs
        if expansion.get(tf, {}).get("exhaustion_risk") == "high"
        or expansion.get(tf, {}).get("state") == "exhaustion_risk"
    )
    med = sum(1 for tf in tfs if expansion.get(tf, {}).get("exhaustion_risk") == "medium")

    if high >= 2:
        return 0
    if high == 1:
        return 4
    if med >= 2:
        return 6
    return 10


def _tier(score: int) -> str:
    for threshold, label in TIERS:
        if score >= threshold:
            return label
    return "no_trade"


# ── PO3 Modifier ──────────────────────────────────────────────────────────────

def _po3_modifier(po3: dict, narrative: dict) -> int:
    alignment = po3.get("alignment", "")
    delta = PO3_ALIGNMENT_BONUS.get(alignment, 0)

    # Conflict penalty: HTF accumulation but narrative claims active delivery
    market_narrative = narrative.get("market_narrative", "")
    phase_15m = po3.get("15m", {}).get("phase", "no_phase")
    phase_5m  = po3.get("5m",  {}).get("phase", "no_phase")

    conflict = (
        phase_15m == "accumulation"
        and phase_5m == "accumulation"
        and market_narrative in (
            "distribution_in_progress",
            "bullish_continuation",
            "bearish_continuation",
        )
    ) or (
        phase_15m == "distribution"
        and market_narrative == "accumulation_before_expansion"
    )

    if conflict:
        delta -= 5

    return delta


# ── Memory Modifier ──────────────────────────────────────────────────────────

def _memory_modifier(memory_mods: dict, narrative: dict) -> int:
    if not memory_mods:
        return 0

    delta = 0
    trend = memory_mods.get("confidence_trend", "stable")
    market_narrative = narrative.get("market_narrative", "")

    if trend == "rising":
        delta += 3
    elif trend == "falling":
        delta -= 3

    # PO3 stability bonus: HTF phase has been stable for 3+ snapshots and aligns
    stable_phases = memory_mods.get("stable_phases", {})
    for tf in ["15m", "5m"]:
        sp = stable_phases.get(tf, {})
        if sp.get("count", 0) >= 3 and sp.get("phase") in ("distribution", "manipulation"):
            if market_narrative not in ("conflicted", "neutral", "exhaustion_risk"):
                delta += 3
                break  # only credit once

    # Phase flickering penalty
    if memory_mods.get("flickering_tfs"):
        delta -= 5

    # Tier movement modifiers
    if memory_mods.get("tier_improved"):
        delta += 2
    if memory_mods.get("tier_degraded"):
        delta -= 3

    return delta


# ── Hard Caps ─────────────────────────────────────────────────────────────────

def _apply_caps(total: int, narrative: dict, volatility: dict) -> int:
    market_narrative = narrative.get("market_narrative", "")
    trade_personality = narrative.get("trade_personality", "")
    market_state = narrative.get("market_state", "")

    if market_narrative == "conflicted":
        return min(total, 49)

    if trade_personality == "no_trade_context":
        return min(total, 49)

    if market_state == "dangerous":
        # Bypass cap only when 5m and 3m are healthy — 15m alone is toxic
        vol_5m = volatility.get("5m", {}).get("state", "")
        vol_3m = volatility.get("3m", {}).get("state", "")
        only_15m_toxic = vol_5m in ("stable", "expanding") and vol_3m in ("stable", "expanding")
        if not only_15m_toxic:
            # VOL-AUTH-1: this is a volatility-derived cap. In observe_only mode
            # volatility is advisory — the cap is lifted so confidence reflects
            # the true, non-volatility evidence (the would_have_vetoed telemetry
            # is recorded downstream in qualification). Default 'enforce' keeps
            # the cap byte-identical. The conflicted / no_trade_context caps
            # above are NOT volatility and always apply.
            from volatility_authority.volatility_authority import observe_only
            if not observe_only():
                return min(total, 49)

    return total


# ── Public Entry Point ────────────────────────────────────────────────────────

def score_confidence(structure: dict, volatility: dict, expansion: dict,
                     liquidity: dict, session: str, narrative: dict, po3: dict,
                     memory_mods: dict = None) -> dict:
    total = (
        _structure_points(structure)
        + _expansion_points(expansion)
        + _liquidity_points(liquidity)
        + _volatility_points(volatility)
        + _session_points(session)
        + _exhaustion_points(expansion)
        + _po3_modifier(po3, narrative)
        + _memory_modifier(memory_mods or {}, narrative)
    )
    total = max(0, min(100, total))
    total = _apply_caps(total, narrative, volatility)

    return {
        "confidence_score": total,
        "confidence_tier":  _tier(total),
    }

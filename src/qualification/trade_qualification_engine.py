"""
Trade Qualification Engine — final decision layer.
Reads all existing snapshot intelligence and answers:
  Is there an opportunity? How good? Worth attention? Stand down?

Does NOT execute trades, size positions, or place orders.
All inputs are pre-computed snapshot dicts — no recalculation here.
"""
import os

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

# ── Scoring tables ────────────────────────────────────────────────────────────

NARRATIVE_QUALITY = {
    "bullish_continuation_after_manipulation": 25,
    "bearish_continuation_after_manipulation": 25,
    "distribution_in_progress":                22,
    "liquidity_sweep_reversal":                20,
    "bullish_continuation":                    18,
    "bearish_continuation":                    18,
    "accumulation_before_expansion":           12,
    "manipulation_without_distribution":        8,
    "range_expansion":                          8,
    "neutral":                                  3,
    "exhaustion_risk":                          0,
    "conflicted":                               0,
    "compression":                              0,
}

PO3_ALIGNMENT_QUALITY = {
    "full_distribution_alignment":  20,
    "manipulation_to_distribution": 17,
    "accumulation_building":         9,
    "mixed":                         4,
    "no_clear_alignment":            1,
}

STRUCTURE_ALIGNMENT_QUALITY = {
    "full":    15,
    "strong":  11,
    "partial":  6,
    "mixed":    2,
    "neutral":  0,
}

STATUS_TIERS = [
    (85, "elite"),
    (70, "qualified"),
    (55, "candidate"),
    (40, "watchlist"),
    (0,  "no_trade"),
]

GRADE_MAP = [
    (95, "A+"),
    (85, "A"),
    (70, "B"),
    (55, "C"),
    (40, "D"),
    (0,  "F"),
]

_NO_TRADE_NARRATIVES = {"conflicted", "exhaustion_risk", "compression"}


# ── Hard Disqualifiers ────────────────────────────────────────────────────────

def _is_disqualified(ai_context: dict, volatility: dict) -> bool:
    """
    Returns True if the environment is fundamentally unsuitable for any trade.
    The exception clause prevents auto-disqualification when only 15m is toxic
    and lower timeframes remain healthy.
    """
    market_state = ai_context.get("market_state", "")
    conf_tier    = ai_context.get("confidence_tier", "")
    narrative    = ai_context.get("market_narrative", "")

    if narrative in _NO_TRADE_NARRATIVES:
        return True

    if conf_tier == "no_trade":
        return True

    if market_state == "dangerous":
        vol_5m = volatility.get("5m", {}).get("state", "")
        vol_3m = volatility.get("3m", {}).get("state", "")
        # Bypass disqualification if only 15m is toxic
        if vol_5m in ("stable", "expanding") and vol_3m in ("stable", "expanding"):
            return False
        return True

    # Multiple HTFs toxic (15m + 5m)
    toxic = sum(
        1 for tf in ["15m", "5m"]
        if volatility.get(tf, {}).get("state") in ("toxic", "explosive")
    )
    if toxic >= 2:
        return True

    return False


# ── Opportunity Score Components ──────────────────────────────────────────────

def _narrative_pts(ai_context: dict) -> int:
    return NARRATIVE_QUALITY.get(ai_context.get("market_narrative", ""), 3)


def _po3_pts(po3: dict) -> int:
    return PO3_ALIGNMENT_QUALITY.get(po3.get("alignment", ""), 4)


def _confidence_pts(ai_context: dict) -> int:
    """Scale 0-100 confidence score to 0-20 pts."""
    return round(ai_context.get("confidence_score", 0) / 100 * 20)


def _structure_pts(structure: dict) -> int:
    return STRUCTURE_ALIGNMENT_QUALITY.get(structure.get("alignment", "neutral"), 0)


def _memory_pts(memory: dict) -> int:
    """10 pts max — based on confidence trend and PO3 stability."""
    if not memory or not memory.get("available"):
        return 5  # no history — neutral credit

    g    = memory.get("global",     {}) or {}
    tfs  = memory.get("timeframes", {}) or {}
    pts  = 5
    trend = g.get("confidence_trend", "stable")

    if trend == "rising":
        pts += 3
    elif trend == "falling":
        pts -= 3

    # Stable HTF phase bonus — up to +2
    stable_htf = sum(
        1 for tf in ["15m", "5m"]
        if tfs.get(tf, {}).get("po3_stability_count", 0) >= 3
        and tfs.get(tf, {}).get("stable_po3_phase") in ("distribution", "manipulation", "accumulation")
    )
    pts += min(stable_htf, 2)

    # Flickering penalty (multiple HTFs changed phase and have low stability)
    flickering = sum(
        1 for tf in TIMEFRAMES
        if tfs.get(tf, {}).get("po3_phase_changed")
        and tfs.get(tf, {}).get("po3_stability_count", 0) <= 1
    )
    if flickering >= 2:
        pts -= 3

    return max(0, min(10, pts))


def _liquidity_pts(liquidity: dict) -> int:
    """10 pts max — quality of liquidity event."""
    tfs     = TIMEFRAMES
    sweep   = any(liquidity.get(tf, {}).get("sweep_detected")  for tf in tfs)
    reclaim = any(liquidity.get(tf, {}).get("reclaim_detected") for tf in tfs)
    failed  = any(liquidity.get(tf, {}).get("failed_breakout") for tf in ["5m", "3m", "1m"])

    if sweep and reclaim:
        return 10
    if failed:
        return 8
    if sweep:
        return 5
    return 3  # no event — stability credit


def _opportunity_score(snapshot: dict) -> int:
    ai_ctx    = snapshot.get("ai_context", {})
    po3       = snapshot.get("po3", {})
    structure = snapshot.get("structure", {})
    liquidity = snapshot.get("liquidity", {})
    memory    = snapshot.get("memory", {})

    raw = (
        _narrative_pts(ai_ctx)
        + _po3_pts(po3)
        + _confidence_pts(ai_ctx)
        + _structure_pts(structure)
        + _memory_pts(memory)
        + _liquidity_pts(liquidity)
    )
    return max(0, min(100, raw))


# ── Direction ─────────────────────────────────────────────────────────────────

def _direction_conflict_enabled() -> bool:
    """Phase FC-0A — June 11 direction-conflict veto. Rollback: env false."""
    return os.getenv("DIRECTION_CONFLICT_VETO", "true").lower().strip() == "true"


def _sweep_semantic_direction(liquidity: dict) -> "str | None":
    """
    Phase FC-0A — ICT sweep semantics on the highest timeframe with a
    confirmed sweep + reclaim:
      below_low  (sell stops raided, close back above) -> bullish delivery
      above_high (buy stops raided, close back below)  -> bearish delivery
    Same semantics as playbook_classifier._direction step 2 — which structure
    bias silently pre-empted on June 11.
    """
    for tf in TIMEFRAMES:
        liq = (liquidity or {}).get(tf, {}) or {}
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            sweep_dir = liq.get("sweep_direction", "")
            if sweep_dir == "below_low":
                return "bullish"
            if sweep_dir == "above_high":
                return "bearish"
    return None


def _direction_with_source(ai_context: dict, structure: dict, po3: dict,
                           liquidity: "dict | None" = None) -> tuple:
    """
    Phase AB-2A — returns (direction, direction_source).
    Firewall ON (default): structure bias is a WITNESS; only non-structure
    sources may author direction. Firewall OFF: legacy structure-rooted path.
    """
    from generation_firewall.authorship import (
        firewall_enabled, authored_direction, SOURCE_LEGACY,
    )
    bias = ai_context.get("directional_bias", "neutral")
    if firewall_enabled():
        return authored_direction(bias, po3, liquidity or {})
    return _direction(ai_context, structure, po3, liquidity), SOURCE_LEGACY


def _direction(ai_context: dict, structure: dict, po3: dict,
               liquidity: "dict | None" = None) -> str:
    bias = ai_context.get("directional_bias", "neutral")

    if bias in ("bullish", "bearish"):
        # Phase FC-0A — sweep-semantics veto (June 11 root cause):
        # a confirmed sweep+reclaim whose ICT meaning contradicts the
        # structure bias is a direction conflict, not a tiebreak loss.
        if _direction_conflict_enabled():
            sweep_dir = _sweep_semantic_direction(liquidity or {})
            if sweep_dir is not None and sweep_dir != bias:
                return "conflicted"
        # Look for PO3 conflict
        po3_dir = (
            po3.get("15m", {}).get("distribution_direction")
            or po3.get("5m",  {}).get("distribution_direction")
        )
        if po3_dir and po3_dir not in (None, bias):
            return "conflicted"
        return bias

    if bias == "conflicted":
        return "conflicted"

    # Neutral bias — try to infer from PO3
    for tf in ["15m", "5m"]:
        d = po3.get(tf, {}).get("distribution_direction")
        if d in ("bullish", "bearish"):
            return d
    for tf in ["15m", "5m"]:
        m = po3.get(tf, {}).get("manipulation_direction")
        if m in ("bullish", "bearish"):
            return m

    # Infer from narrative label
    narrative = ai_context.get("market_narrative", "")
    if "bullish" in narrative:
        return "bullish"
    if "bearish" in narrative:
        return "bearish"

    return "neutral"


# ── Trade Type ────────────────────────────────────────────────────────────────

def _trade_type(ai_context: dict) -> str:
    narrative   = ai_context.get("market_narrative", "")
    personality = ai_context.get("trade_personality", "no_trade_context")

    _generic = {
        "neutral", "conflicted", "exhaustion_risk", "compression",
        "manipulation_without_distribution", "accumulation_before_expansion",
    }
    if narrative and narrative not in _generic:
        return narrative
    if personality != "no_trade_context":
        return personality
    return narrative or "no_trade_context"


# ── Status and Grade ──────────────────────────────────────────────────────────

def _status(score: int, disqualified: bool) -> str:
    if disqualified:
        return "no_trade"
    for threshold, label in STATUS_TIERS:
        if score >= threshold:
            return label
    return "no_trade"


def _grade(score: int, disqualified: bool) -> str:
    if disqualified:
        return "F"
    for threshold, label in GRADE_MAP:
        if score >= threshold:
            return label
    return "F"


# ── Reasons ───────────────────────────────────────────────────────────────────

def _reasons(snapshot: dict, direction: str) -> list:
    r          = []
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    liquidity  = snapshot.get("liquidity", {})
    expansion  = snapshot.get("expansion", {})
    volatility = snapshot.get("volatility", {})
    po3        = snapshot.get("po3", {})
    memory     = snapshot.get("memory", {})

    narrative = ai_context.get("market_narrative", "")
    po3_align = po3.get("alignment", "")
    alignment = structure.get("alignment", "neutral")

    # Lead with the narrative driver
    if narrative and narrative not in _NO_TRADE_NARRATIVES:
        r.append(f"Narrative: {narrative.replace('_', ' ')}")

    # Structure
    if alignment in ("full", "strong"):
        r.append(f"MTF structure alignment: {alignment}")
    for tf in ["15m", "5m"]:
        if structure.get(tf, {}).get("bos"):
            r.append(f"{tf} break of structure confirmed")
            break
    for tf in ["15m", "5m"]:
        if structure.get(tf, {}).get("mss"):
            r.append(f"{tf} market structure shift detected")
            break

    # Liquidity event
    for tf in TIMEFRAMES:
        liq = liquidity.get(tf, {})
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            r.append(f"Liquidity sweep + reclaim confirmed on {tf}")
            break
    for tf in ["5m", "3m", "1m"]:
        if liquidity.get(tf, {}).get("failed_breakout"):
            r.append(f"Failed breakout detected on {tf}")
            break

    # PO3
    if po3_align == "manipulation_to_distribution":
        r.append("PO3 manipulation transitioning to distribution")
    elif po3_align == "full_distribution_alignment":
        r.append("PO3 full distribution alignment across timeframes")
    elif po3_align == "accumulation_building":
        r.append("PO3 accumulation building on higher timeframes")

    # Expansion
    for tf in ["15m", "5m"]:
        state = expansion.get(tf, {}).get("state", "")
        if state == "healthy_expansion":
            r.append(f"{tf} healthy expansion in progress")
            break
        if state == "mature_expansion":
            r.append(f"{tf} mature expansion detected")
            break

    if any(expansion.get(tf, {}).get("displacement_detected") for tf in ["15m", "5m"]):
        r.append("Displacement candle confirmed on higher timeframe")

    # Volatility — only mention when healthy
    vol_state = volatility.get("15m", {}).get("state", "")
    if vol_state in ("expanding", "stable"):
        r.append(f"15m volatility {vol_state} — healthy environment")

    # Memory
    if memory and memory.get("available"):
        g    = memory.get("global", {}) or {}
        tfs  = memory.get("timeframes", {}) or {}
        if g.get("confidence_trend") == "rising":
            r.append(f"Confidence rising +{g.get('confidence_delta', 0)} from prior snapshot")
        for tf in ["15m", "5m"]:
            count = tfs.get(tf, {}).get("po3_stability_count", 0)
            phase = tfs.get(tf, {}).get("stable_po3_phase", "")
            if count >= 3 and phase in ("distribution", "manipulation"):
                r.append(f"{tf} PO3 {phase} held stable for {count} snapshots")
                break

    return r


# ── Warnings ──────────────────────────────────────────────────────────────────

def _qual_warnings(snapshot: dict, opportunity_score: int) -> list:
    w          = []
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    volatility = snapshot.get("volatility", {})
    expansion  = snapshot.get("expansion", {})
    po3        = snapshot.get("po3", {})
    memory     = snapshot.get("memory", {})

    po3_align = po3.get("alignment", "")

    # Volatility
    vol_15m = volatility.get("15m", {}).get("state", "")
    if vol_15m in ("toxic", "explosive"):
        w.append("15m volatility classified as toxic — elevated risk environment")
    elif vol_15m == "unstable":
        w.append("15m volatility unstable — expect choppy conditions")

    if volatility.get("15m", {}).get("range_acceleration", 1.0) > 1.5:
        w.append("Range accelerating rapidly on 15m — volatility expanding fast")

    # Expansion exhaustion
    for tf in ["15m", "5m"]:
        exp = expansion.get(tf, {})
        if exp.get("exhaustion_risk") == "high" or exp.get("state") == "exhaustion_risk":
            w.append(f"{tf} expansion showing high exhaustion risk")
            break
        if exp.get("exhaustion_risk") == "medium" and exp.get("state") == "mature_expansion":
            w.append(f"{tf} mature expansion with medium exhaustion risk")
            break

    # Structure vs expansion
    if structure.get("15m", {}).get("state") == "range_bound":
        if ai_context.get("market_narrative") in (
            "distribution_in_progress", "range_expansion",
            "bullish_continuation", "bearish_continuation",
        ):
            w.append("Expansion occurring inside range-bound 15m structure")

    # PO3 alignment quality
    if po3_align in ("mixed", "no_clear_alignment"):
        w.append(f"PO3 alignment is {po3_align} — delivery direction unclear")

    # Coherence
    coherence = ai_context.get("coherence", {})
    if coherence.get("structure_expansion_alignment") == "conflicted":
        w.append("Structure and expansion conflicted on 15m")
    ve = coherence.get("volatility_expansion_alignment", "")
    if ve in ("mismatched", "dangerous"):
        w.append(f"Volatility/expansion alignment: {ve}")

    # Memory
    if memory and memory.get("available"):
        g   = memory.get("global", {}) or {}
        tfs = memory.get("timeframes", {}) or {}
        if g.get("confidence_trend") == "falling":
            w.append("Confidence trend deteriorating across snapshots")
        changed = [
            tf for tf in ["15m", "5m"]
            if tfs.get(tf, {}).get("po3_phase_changed")
        ]
        if changed:
            w.append(f"PO3 phase recently changed on {', '.join(changed)} — needs confirmation")

    return w


# ── Primary Driver (for formatter) ────────────────────────────────────────────

def _primary_driver(snapshot: dict, po3_align: str) -> str:
    narrative = snapshot.get("ai_context", {}).get("market_narrative", "")
    if narrative in ("bullish_continuation_after_manipulation",
                     "bearish_continuation_after_manipulation"):
        return "manipulation-to-distribution with directional delivery"
    if narrative == "liquidity_sweep_reversal":
        return "confirmed liquidity sweep with reclaim"
    if narrative == "distribution_in_progress":
        return "active distribution across timeframes"
    if po3_align == "manipulation_to_distribution":
        return "PO3 manipulation-to-distribution transition"
    if po3_align == "full_distribution_alignment":
        return "PO3 full distribution alignment"
    alignment = snapshot.get("structure", {}).get("alignment", "")
    if alignment in ("full", "strong"):
        return f"{alignment} MTF structure alignment"
    return narrative.replace("_", " ") if narrative else "mechanical evidence convergence"


# ── Public Entry Point ────────────────────────────────────────────────────────

def qualify_trade(snapshot: dict) -> dict:
    """
    Reads the full assembled snapshot (including ai_context and memory)
    and returns a qualification verdict.
    """
    ai_context = snapshot.get("ai_context", {})
    structure  = snapshot.get("structure", {})
    volatility = snapshot.get("volatility", {})
    po3        = snapshot.get("po3", {})

    disqualified    = _is_disqualified(ai_context, volatility)
    opp_score       = 0 if disqualified else _opportunity_score(snapshot)
    status          = _status(opp_score, disqualified)
    grade           = _grade(opp_score, disqualified)
    direction, direction_source = _direction_with_source(
        ai_context, structure, po3, snapshot.get("liquidity", {}))
    trade_type      = _trade_type(ai_context)
    reasons         = _reasons(snapshot, direction)
    warnings        = _qual_warnings(snapshot, opp_score)
    primary_driver  = _primary_driver(snapshot, po3.get("alignment", ""))

    # AB-2A — structure conflict/lag surfaced as a WITNESS warning (not authority)
    structure_bias = ai_context.get("directional_bias", "neutral")
    if (direction_source in ("delivery_vs_structure_conflict", "structure_witness_only")
            and structure_bias in ("bullish", "bearish")):
        warnings = list(warnings) + [
            f"structure witness bias={structure_bias} did not author direction "
            f"(source={direction_source})"
        ]

    return {
        "status":            status,
        "grade":             grade,
        "direction":         direction,
        "direction_source":  direction_source,   # AB-2A
        "trade_type":        trade_type,
        "opportunity_score": opp_score,
        "primary_driver":    primary_driver,
        "reasons":           reasons,
        "warnings":          warnings,
    }

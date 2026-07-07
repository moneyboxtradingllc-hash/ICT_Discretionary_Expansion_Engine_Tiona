"""
Narrative Builder — reads mechanical evidence + PO3 and produces an interpreted market picture.
No AI API calls. Pure deterministic logic on snapshot dicts.
"""


# ── Directional Bias ──────────────────────────────────────────────────────────

def _directional_bias(structure: dict) -> str:
    """15m anchors bias. 5m confirms or creates conflict."""
    tfs = ["15m", "5m", "3m", "1m"]
    biases = [structure.get(tf, {}).get("bias", "neutral") for tf in tfs]

    htf = biases[0]
    mtf = biases[1]

    if htf != "neutral" and mtf != "neutral":
        return htf if htf == mtf else "conflicted"

    directional = [b for b in biases if b != "neutral"]
    if not directional:
        return "neutral"

    return directional[0] if len(set(directional)) == 1 else "conflicted"


# ── Market State ──────────────────────────────────────────────────────────────

def _market_state(structure: dict, volatility: dict, expansion: dict, liquidity: dict) -> str:
    vol_15m    = volatility.get("15m", {}).get("state", "")
    exp_states = {tf: expansion.get(tf, {}).get("state", "") for tf in ["15m", "5m", "3m"]}

    if vol_15m in ("toxic", "explosive"):
        return "dangerous"

    exhaustion_high = sum(
        1 for tf in ["15m", "5m", "3m"]
        if expansion.get(tf, {}).get("exhaustion_risk") == "high"
        or exp_states[tf] == "exhaustion_risk"
    )
    if exhaustion_high >= 2:
        return "dangerous"

    mss = any(structure.get(tf, {}).get("mss", False) for tf in ["15m", "5m", "3m"])
    sweep_reclaim = any(
        liquidity.get(tf, {}).get("sweep_detected") and liquidity.get(tf, {}).get("reclaim_detected")
        for tf in ["5m", "3m", "1m"]
    )
    if mss or sweep_reclaim:
        return "reversing"

    alignment = structure.get("alignment", "neutral")
    bos_htf   = structure.get("15m", {}).get("bos", False) or structure.get("5m", {}).get("bos", False)
    healthy   = any(exp_states[tf] in ("healthy_expansion", "mature_expansion") for tf in ["15m", "5m"])
    if alignment in ("full", "strong") and bos_htf and healthy:
        return "trending"

    range_count = sum(
        1 for tf in ["15m", "5m"] if structure.get(tf, {}).get("state") == "range_bound"
    )
    comp_count = sum(1 for tf in ["15m", "5m", "3m"] if exp_states[tf] == "compression")
    if range_count >= 1 and comp_count >= 1:
        return "ranging"

    if comp_count >= 2:
        return "compressing"

    exp_active = sum(
        1 for tf in ["15m", "5m", "3m"]
        if exp_states[tf] in ("early_expansion", "healthy_expansion", "mature_expansion")
    )
    if exp_active >= 2:
        return "expanding"

    return "neutral"


# ── Market Narrative ──────────────────────────────────────────────────────────

def _market_narrative(bias: str, market_state: str, structure: dict,
                       liquidity: dict, expansion: dict, po3: dict) -> str:
    # Highest priority: sweep + reclaim (regardless of PO3)
    sweep_tf = next(
        (tf for tf in ["15m", "5m", "3m", "1m"]
         if liquidity.get(tf, {}).get("sweep_detected")
         and liquidity.get(tf, {}).get("reclaim_detected")),
        None,
    )
    if sweep_tf:
        return "liquidity_sweep_reversal"

    # Exhaustion blocks everything
    if any(expansion.get(tf, {}).get("state") == "exhaustion_risk" for tf in ["15m", "5m", "3m"]):
        return "exhaustion_risk"

    # Dangerous state: PO3 can still describe what's happening but no trade narrative
    if market_state == "dangerous":
        return "conflicted"

    # ── PO3 refinements (only when environment is safe to interpret) ──────────
    po3_align = po3.get("alignment", "")

    if po3_align == "manipulation_to_distribution":
        manip_dir = (
            po3.get("15m", {}).get("manipulation_direction")
            or po3.get("5m",  {}).get("manipulation_direction")
        )
        if manip_dir == "bearish":
            return "bullish_continuation_after_manipulation"   # swept lows → delivering up
        if manip_dir == "bullish":
            return "bearish_continuation_after_manipulation"  # swept highs → delivering down
        # direction unclear — fall through to base narrative

    if po3_align == "full_distribution_alignment":
        return "distribution_in_progress"

    if po3_align == "accumulation_building":
        return "accumulation_before_expansion"

    # Single-TF manipulation without LTF distribution yet
    manip_tfs = [tf for tf in ["15m", "5m"] if po3.get(tf, {}).get("phase") == "manipulation"]
    dist_tfs  = [
        tf for tf in ["3m", "1m"]
        if po3.get(tf, {}).get("phase") in ("distribution", "transition")
    ]
    if manip_tfs and not dist_tfs:
        return "manipulation_without_distribution"

    # ── Base directional narratives ───────────────────────────────────────────
    if bias == "bullish" and market_state in ("trending", "expanding", "reversing"):
        return "bullish_continuation"
    if bias == "bearish" and market_state in ("trending", "expanding", "reversing"):
        return "bearish_continuation"
    if bias == "conflicted":
        return "conflicted"

    if market_state in ("compressing", "ranging"):
        comp_count = sum(
            1 for tf in ["15m", "5m", "3m"]
            if expansion.get(tf, {}).get("state") == "compression"
        )
        return "compression" if comp_count >= 2 else "neutral"

    if market_state == "expanding":
        return "range_expansion"

    return "neutral"


# ── Trade Personality ─────────────────────────────────────────────────────────

def _trade_personality(narrative: str, market_state: str, bias: str,
                        liquidity: dict, session: str) -> str:
    # SCAR-TISSUE (2026-07-07): "distribution_in_progress" — ACTIVE directional
    # delivery, and the SECOND-HIGHEST tradeable narrative in the qualification
    # scoring tables (22 pts) — was on this no-trade blacklist (pre-AI scar;
    # the same category error found in Tiona's bot). The personality fed
    # confidence_engine._apply_caps, which hard-capped confidence at 49 (one
    # point below the observe tier) -> confidence_tier "no_trade" ->
    # qualification disqualified -> risk hard block -> toolbox demoted, and it
    # ALSO labeled active distribution "no_trade_context" inside the Brain's
    # own input payload. Live proof: 2026-07-07 10:43 carried full MTF
    # alignment + 15m BOS + PO3 full distribution + confirmed displacement and
    # scored EXACTLY 49. Distribution in progress is delivery continuation —
    # it now carries the trend_continuation personality. The genuine no-trade
    # environments below keep the blacklist and the cap; no threshold changed.
    _no_trade = (
        "conflicted", "exhaustion_risk", "compression", "neutral",
        "manipulation_without_distribution", "accumulation_before_expansion",
    )
    if narrative in _no_trade:
        return "no_trade_context"

    if narrative == "distribution_in_progress":
        return "trend_continuation"

    if narrative in ("liquidity_sweep_reversal",
                     "bullish_continuation_after_manipulation",
                     "bearish_continuation_after_manipulation"):
        return "liquidity_sweep_reversal"

    failed_bo = any(liquidity.get(tf, {}).get("failed_breakout") for tf in ["5m", "3m", "1m"])
    if failed_bo:
        return "failed_breakout_reversal"

    if session == "ny_open" and market_state in ("trending", "expanding"):
        return "opening_drive"

    if narrative in ("bullish_continuation", "bearish_continuation"):
        return "trend_continuation"

    if narrative == "range_expansion":
        return "range_expansion"

    return "no_trade_context"


# ── Coherence ─────────────────────────────────────────────────────────────────

def _coherence(structure: dict, volatility: dict, expansion: dict, liquidity: dict) -> dict:
    struct_15m = structure.get("15m", {}).get("state", "")
    exp_15m    = expansion.get("15m", {}).get("state", "")
    vol_15m    = volatility.get("15m", {}).get("state", "")
    exhaust_15 = expansion.get("15m", {}).get("exhaustion_risk", "low")

    # Structure vs Expansion
    if struct_15m == "range_bound" and exp_15m in ("healthy_expansion", "mature_expansion"):
        se_align = "conflicted"
    elif struct_15m in ("bullish_continuation", "bearish_continuation") \
         and exp_15m in ("healthy_expansion", "mature_expansion"):
        se_align = "aligned"
    elif struct_15m in ("bullish_reversal", "bearish_reversal") \
         and exp_15m in ("early_expansion", "healthy_expansion"):
        se_align = "aligned"
    else:
        se_align = "neutral"

    # Volatility vs Expansion
    if vol_15m in ("toxic", "explosive") and exp_15m == "healthy_expansion":
        ve_align = "mismatched"
    elif vol_15m in ("toxic", "explosive") and exhaust_15 == "high":
        ve_align = "dangerous"
    elif vol_15m in ("expanding", "stable") and exp_15m in ("healthy_expansion", "mature_expansion"):
        ve_align = "healthy"
    elif vol_15m == "liquidity_vacuum":
        ve_align = "dangerous"
    else:
        ve_align = "neutral"

    # Liquidity vs Structure (ICT PO3 logic)
    sweep_tf = next(
        (tf for tf in ["5m", "3m", "1m"] if liquidity.get(tf, {}).get("sweep_detected")),
        None,
    )
    if not sweep_tf:
        ls_align = "neutral"
    else:
        sweep_dir = liquidity.get(sweep_tf, {}).get("sweep_direction", "")
        reclaim   = liquidity.get(sweep_tf, {}).get("reclaim_detected", False)
        htf_bias  = structure.get("15m", {}).get("bias", "neutral")

        if not reclaim:
            ls_align = "neutral"
        elif sweep_dir == "below_low" and htf_bias == "bullish":
            ls_align = "aligned"
        elif sweep_dir == "above_high" and htf_bias == "bearish":
            ls_align = "aligned"
        elif htf_bias in ("bullish", "bearish"):
            ls_align = "conflicted"
        else:
            ls_align = "neutral"

    return {
        "structure_expansion_alignment":  se_align,
        "volatility_expansion_alignment": ve_align,
        "liquidity_structure_alignment":  ls_align,
    }


# ── Warnings ──────────────────────────────────────────────────────────────────

def _warnings(structure: dict, volatility: dict, expansion: dict,
               liquidity: dict, bias: str, po3: dict,
               memory_mods: dict = None) -> list:
    w = []

    if structure.get("15m", {}).get("state") == "range_bound" and \
       expansion.get("15m", {}).get("state") in ("healthy_expansion", "mature_expansion"):
        w.append("Expansion detected inside range-bound structure on 15m")

    if volatility.get("15m", {}).get("state") in ("toxic", "explosive") and \
       expansion.get("15m", {}).get("displacement_detected"):
        w.append("Volatility classified as toxic despite displacement — handle with care")

    ltf_expanding = any(
        expansion.get(tf, {}).get("state") in ("healthy_expansion", "mature_expansion")
        for tf in ["3m", "1m"]
    )
    htf_weak = structure.get("15m", {}).get("state") in ("range_bound", "neutral", "insufficient_data")
    if ltf_expanding and htf_weak:
        w.append("Lower timeframe expansion lacks higher timeframe structural confirmation")

    if bias == "conflicted":
        w.append("Directional bias is conflicted across timeframes — no clear edge")

    exhaustion_high = sum(
        1 for tf in ["15m", "5m", "3m"]
        if expansion.get(tf, {}).get("exhaustion_risk") == "high"
        or expansion.get(tf, {}).get("state") == "exhaustion_risk"
    )
    exhaustion_med = sum(
        1 for tf in ["15m", "5m", "3m"]
        if expansion.get(tf, {}).get("exhaustion_risk") == "medium"
    )
    if exhaustion_high >= 1 or exhaustion_med >= 2:
        w.append("Exhaustion risk elevated across multiple timeframes")

    if any(
        liquidity.get(tf, {}).get("sweep_detected") and
        not liquidity.get(tf, {}).get("reclaim_detected")
        for tf in ["15m", "5m", "3m", "1m"]
    ):
        w.append("Liquidity sweep detected but no reclaim confirmed — watch for failed sweep")

    if volatility.get("15m", {}).get("state") == "liquidity_vacuum":
        w.append("Liquidity vacuum on 15m — no meaningful participation")

    # PO3 warnings
    po3_align = po3.get("alignment", "")
    phase_15m = po3.get("15m", {}).get("phase", "no_phase")
    phase_5m  = po3.get("5m",  {}).get("phase", "no_phase")
    phase_3m  = po3.get("3m",  {}).get("phase", "no_phase")
    phase_1m  = po3.get("1m",  {}).get("phase", "no_phase")

    if phase_1m == "distribution" and phase_15m == "accumulation":
        w.append("1m delivering while 15m still accumulating — early signal, lacks HTF confirmation")

    if po3_align == "manipulation_to_distribution" and not any(
        liquidity.get(tf, {}).get("sweep_detected") for tf in ["15m", "5m", "3m", "1m"]
    ):
        w.append("PO3 suggests manipulation-to-distribution but no liquidity sweep confirmed")

    # Memory-based warnings
    if memory_mods:
        if memory_mods.get("confidence_trend") == "falling":
            w.append("Confidence degrading across snapshots — opportunity quality declining")

        flickering = memory_mods.get("flickering_tfs", [])
        if flickering:
            w.append(f"PO3 phase unstable on {', '.join(flickering)} — flickering between phases")

    return w


# ── Public Entry Point ────────────────────────────────────────────────────────

def build_narrative(structure: dict, volatility: dict, expansion: dict,
                    liquidity: dict, po3: dict, session: str,
                    memory_mods: dict = None) -> dict:
    bias      = _directional_bias(structure)
    state     = _market_state(structure, volatility, expansion, liquidity)
    narrative = _market_narrative(bias, state, structure, liquidity, expansion, po3)
    personality = _trade_personality(narrative, state, bias, liquidity, session)
    coherence = _coherence(structure, volatility, expansion, liquidity)
    warnings  = _warnings(structure, volatility, expansion, liquidity, bias, po3, memory_mods)

    return {
        "market_narrative":  narrative,
        "market_state":      state,
        "directional_bias":  bias,
        "trade_personality": personality,
        "coherence":         coherence,
        "warnings":          warnings,
    }

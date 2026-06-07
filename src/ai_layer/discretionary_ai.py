"""
Discretionary AI Engine — Phase 1N.
Orchestrates deterministic internal AI and optional external API adapter.
No execution, no order routing, no broker connections.

Modes (AI_MODE environment variable):
  internal : deterministic rule-based engine only (default)
  external : attempt external AI call; fall back to deterministic on failure
  hybrid   : run both; prefer external if valid; store deterministic as backup

Returns:
  - ai_discretionary : interpretation dict (with full metadata)
  - confidence_fusion: mechanical vs AI confidence alignment dict
"""

import os

from ai_layer.ai_input_builder   import build_compact_ai_input
from ai_layer.ai_api_adapter     import call_external_ai, get_ai_config
from ai_layer.ai_response_schema import validate_ai_response
from ai_layer.ai_debate_engine   import build_debate

_TFS = ["15m", "5m", "3m", "1m"]

# ── Scoring tables ────────────────────────────────────────────────────────────

_NARRATIVE_PTS = {
    "bullish_continuation_after_manipulation": 15,
    "bearish_continuation_after_manipulation": 15,
    "distribution_in_progress":                12,
    "liquidity_sweep_reversal":                10,
    "bullish_continuation":                     8,
    "bearish_continuation":                     8,
    "accumulation_before_expansion":            4,
    "manipulation_without_distribution":        2,
    "range_expansion":                          2,
    "neutral":                                 -5,
    "conflicted":                             -15,
    "exhaustion_risk":                        -10,
    "compression":                            -12,
}

_PO3_PTS = {
    "full_distribution_alignment":  12,
    "manipulation_to_distribution": 10,
    "accumulation_building":         4,
    "mixed":                        -5,
    "no_clear_alignment":           -8,
}

_ALIGN_PTS = {
    "full":    10,
    "strong":   7,
    "partial":  3,
    "mixed":   -3,
    "neutral": -2,
}

_QUAL_PTS = {
    "elite":     10,
    "qualified":  6,
    "candidate":  0,
    "watchlist": -8,
    "no_trade": -15,
}

_RAW_STATUS_PTS = {
    "actionable": 8,
    "ready":      5,
    "forming":    2,
    "no_tool":   -5,
}

_TREND_PTS = {
    "rising":  8,
    "stable":  0,
    "falling": -8,
}

_NARRATIVE_OPENERS = {
    "liquidity_sweep_reversal":
        "Market executed a liquidity sweep and reclaimed the level, signaling a directional reversal.",
    "bullish_continuation_after_manipulation":
        "Price completed a bullish manipulation phase and is now expanding after reclaiming the swept level.",
    "bearish_continuation_after_manipulation":
        "Price completed a bearish manipulation phase and is now expanding lower after rejecting the sweep.",
    "distribution_in_progress":
        "Active price distribution is underway across multiple timeframes.",
    "bullish_continuation":
        "Market continues expanding in a bullish structure with higher highs and higher lows.",
    "bearish_continuation":
        "Market continues expanding in a bearish structure with lower highs and lower lows.",
    "accumulation_before_expansion":
        "Market is consolidating in an accumulation phase, building energy ahead of a potential expansion.",
    "range_expansion":
        "Price is breaking out of a prior range with early expansion signals developing.",
    "manipulation_without_distribution":
        "A sweep has occurred but distribution has not followed — manipulation phase may still be active.",
    "conflicted":
        "Market signals are conflicted — no clear directional narrative has established itself.",
    "compression":
        "Market is in a compressed, low-energy state without directional conviction.",
    "exhaustion_risk":
        "Current expansion is showing exhaustion signals — the move may be over-extended.",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _preferred_candidate(snapshot: dict) -> dict:
    """Return the preferred tool candidate dict, or empty dict."""
    tb   = snapshot.get("toolbox", {})
    pref = tb.get("preferred_tool", "")
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c["tool"] == pref), {}) if cands else {}


# ── Direction ─────────────────────────────────────────────────────────────────

def _ai_direction(snapshot: dict) -> str:
    """
    Vote-based directional synthesis across all available evidence sources.
    Returns "bullish", "bearish", or "neutral".
    """
    ai_ctx = snapshot.get("ai_context", {})
    struct = snapshot.get("structure",  {})
    po3    = snapshot.get("po3",        {})
    pb     = snapshot.get("playbook",   {})
    qual   = snapshot.get("qualification", {})
    tb     = snapshot.get("toolbox",    {})

    votes = {"bullish": 0, "bearish": 0}

    # Narrative engine directional bias (already synthesizes many signals)
    bias = ai_ctx.get("directional_bias", "neutral")
    if bias in ("bullish", "bearish"):
        votes[bias] += 3

    # MTF structure bias count
    bull_s = sum(1 for tf in _TFS if struct.get(tf, {}).get("bias") == "bullish")
    bear_s = sum(1 for tf in _TFS if struct.get(tf, {}).get("bias") == "bearish")
    if bull_s > bear_s:
        votes["bullish"] += 2
    elif bear_s > bull_s:
        votes["bearish"] += 2

    # PO3 distribution direction (HTF weighted more)
    for tf, w in [("15m", 2), ("5m", 1)]:
        d = po3.get(tf, {}).get("distribution_direction")
        if d in ("bullish", "bearish"):
            votes[d] += w

    # Playbook direction
    pb_dir = pb.get("direction", "neutral")
    if pb_dir in ("bullish", "bearish"):
        votes[pb_dir] += 2

    # Qualification direction
    q_dir = qual.get("direction", "neutral")
    if q_dir in ("bullish", "bearish"):
        votes[q_dir] += 2

    # Preferred tool direction
    pref = tb.get("preferred_tool", "") or ""
    if pref.startswith("bullish_"):   votes["bullish"] += 1
    elif pref.startswith("bearish_"): votes["bearish"] += 1

    if votes["bullish"] > votes["bearish"]: return "bullish"
    if votes["bearish"] > votes["bullish"]: return "bearish"
    return "neutral"


# ── Confidence ────────────────────────────────────────────────────────────────

def _ai_confidence(snapshot: dict, direction: str) -> int:
    """
    Build an 0–100 confidence score from weighted evidence signals.
    Base = 50; adjusted by narrative quality, existing confidence engine,
    PO3/structure alignment, liquidity, memory, qualification, risk, and tool state.
    """
    ai_ctx = snapshot.get("ai_context",    {})
    struct = snapshot.get("structure",     {})
    po3    = snapshot.get("po3",           {})
    liq    = snapshot.get("liquidity",     {})
    mem    = snapshot.get("memory",        {})
    qual   = snapshot.get("qualification", {})
    risk   = snapshot.get("risk",          {})
    tb     = snapshot.get("toolbox",       {})

    score = 50

    score += _NARRATIVE_PTS.get(ai_ctx.get("market_narrative", ""), 0)

    # Blend existing confidence engine output (30% weight on its deviation from 50)
    score += round((ai_ctx.get("confidence_score", 50) - 50) * 0.25)

    score += _PO3_PTS.get(po3.get("alignment", ""), 0)
    score += _ALIGN_PTS.get(struct.get("alignment", "neutral"), 0)

    if any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS): score += 4
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): score += 4

    if mem and mem.get("available"):
        g = mem.get("global") or {}
        score += _TREND_PTS.get(g.get("confidence_trend", "stable"), 0)

    score += _QUAL_PTS.get(qual.get("status", ""), 0)

    if not risk.get("trade_allowed", True): score -= 6

    score += _RAW_STATUS_PTS.get(tb.get("best_available_raw_status", "no_tool"), 0)

    # Penalise if preferred zone is invalidated
    pref_c = _preferred_candidate(snapshot)
    if pref_c.get("price_level", {}).get("invalidated"): score -= 8

    if direction == "neutral": score -= 10

    return max(0, min(100, score))


# ── Text generators ───────────────────────────────────────────────────────────

def _market_story(snapshot: dict, direction: str) -> str:
    ai_ctx = snapshot.get("ai_context", {})
    po3    = snapshot.get("po3",        {})
    struct = snapshot.get("structure",  {})
    exp    = snapshot.get("expansion",  {})
    mem    = snapshot.get("memory",     {})

    narrative = ai_ctx.get("market_narrative", "neutral")
    po3_align = po3.get("alignment", "")
    align     = struct.get("alignment", "neutral")

    exp_state = ""
    for tf in ["15m", "5m"]:
        s = exp.get(tf, {}).get("state", "")
        if s in ("healthy_expansion", "mature_expansion", "early_expansion"):
            exp_state = s
            break

    parts = [_NARRATIVE_OPENERS.get(
        narrative,
        "Market is in a neutral state without a defined directional narrative."
    )]

    if po3_align == "manipulation_to_distribution":
        parts.append("PO3 is transitioning from manipulation to distribution phase.")
    elif po3_align == "full_distribution_alignment":
        parts.append("PO3 shows full distribution alignment across timeframes.")
    elif po3_align == "accumulation_building":
        parts.append("PO3 accumulation is building on higher timeframes ahead of a potential expansion.")

    if align in ("full", "strong"):
        parts.append(f"MTF structure alignment is {align}, reinforcing the {direction} directional bias.")
    elif align in ("mixed", "neutral"):
        parts.append(f"Structure alignment is {align} — multi-timeframe confluence not yet confirmed.")

    if exp_state == "healthy_expansion":
        parts.append("Higher timeframe expansion is healthy — directional momentum is intact.")
    elif exp_state == "mature_expansion":
        parts.append("Higher timeframe expansion is maturing — a pullback or retest may be developing.")
    elif exp_state == "early_expansion":
        parts.append("Expansion is in its early stage — the directional move is beginning to develop.")

    if mem and mem.get("available"):
        g = mem.get("global") or {}
        trend = g.get("confidence_trend", "stable")
        if trend == "rising":
            parts.append("Confidence has been building across recent snapshots.")
        elif trend == "falling":
            parts.append("Confidence has been deteriorating across recent snapshots — momentum is fading.")

    return " ".join(parts)


def _primary_thesis(snapshot: dict, direction: str, ai_confidence: int) -> str:
    qual   = snapshot.get("qualification", {})
    pb     = snapshot.get("playbook",      {})
    tb     = snapshot.get("toolbox",       {})
    ai_ctx = snapshot.get("ai_context",    {})

    if direction == "neutral" or ai_confidence < 25:
        return "No clear directional thesis — market conditions do not support a defined bias."

    driver    = qual.get("primary_driver", "")
    pb_name   = pb.get("selected_playbook", "no_playbook")
    pref      = tb.get("preferred_tool", "") or ""
    narrative = ai_ctx.get("market_narrative", "")

    if not driver or driver == "mechanical evidence convergence":
        driver = narrative.replace("_", " ") if narrative else ""

    pieces = []
    if driver:
        pieces.append(f"Primary driver: {driver}.")
    if pb_name not in ("no_playbook", ""):
        pieces.append(f"Playbook: {pb_name.replace('_', ' ')}.")
    if pref:
        pieces.append(
            f"Preferred entry tool: {pref.replace('_', ' ')} — "
            f"waiting for price to enter zone."
        )

    if not pieces:
        return (
            f"Directional bias is {direction} at {ai_confidence}/100 — "
            "specific evidence narrative insufficient for full thesis."
        )
    return " ".join(pieces)


def _concerns(snapshot: dict) -> list:
    concerns = []
    qual   = snapshot.get("qualification", {})
    risk   = snapshot.get("risk",          {})
    mem    = snapshot.get("memory",        {})
    vol    = snapshot.get("volatility",    {})
    ai_ctx = snapshot.get("ai_context",    {})
    pref_c = _preferred_candidate(snapshot)

    qs = qual.get("status", "")
    if qs in ("no_trade", "watchlist"):
        concerns.append(f"Qualification is {qs} — environment quality does not support engagement")
    elif qs == "candidate":
        concerns.append("Qualification is candidate — opportunity not yet fully confirmed")

    if not risk.get("trade_allowed", True):
        blocks = risk.get("blocks", [])
        if blocks:
            # Block messages are prefixed with "blocked: " — strip it to avoid duplication
            block_msg = blocks[0].removeprefix("blocked: ").strip()
            concerns.append(f"Risk Governor blocked: {block_msg}")
        else:
            concerns.append("Risk Governor blocked — conditions do not permit execution")

    if mem and mem.get("available"):
        g = mem.get("global") or {}
        if g.get("confidence_trend") == "falling":
            concerns.append("Confidence trend is deteriorating across recent snapshots")

    v15 = vol.get("15m", {}).get("state", "")
    if v15 in ("toxic", "explosive"):
        concerns.append(f"15m volatility is {v15} — adverse entry timing conditions")
    elif v15 == "unstable":
        concerns.append("15m volatility is unstable — expect choppy price action")

    if pref_c:
        if pref_c.get("price_level", {}).get("invalidated"):
            concerns.append("Preferred tool price zone is invalidated by current price action")
        prereqs = pref_c.get("readiness", {}).get("prerequisites_missing", [])
        if prereqs:
            concerns.append(
                f"Preferred tool has {len(prereqs)} unmet prerequisite(s): {prereqs[0]}"
            )

    coherence = ai_ctx.get("coherence", {})
    if coherence.get("structure_expansion_alignment") == "conflicted":
        concerns.append("Structure and expansion are conflicted on the higher timeframe")

    return concerns[:5]


def _missing_evidence(snapshot: dict) -> list:
    missing = []
    po3    = snapshot.get("po3",        {})
    struct = snapshot.get("structure",  {})
    liq    = snapshot.get("liquidity",  {})
    pref_c = _preferred_candidate(snapshot)

    if pref_c:
        readiness = pref_c.get("readiness", {})
        for p in readiness.get("prerequisites_missing", [])[:2]:
            missing.append(p)
        for g in readiness.get("score_gaps", [])[:2]:
            missing.append(g)
        confs = pref_c.get("trigger_prep", {}).get("confirmation_needed", [])
        if confs and confs[0] not in missing:
            missing.append(confs[0])

    # Guard against duplicates already captured via readiness score_gaps
    if po3.get("alignment") not in ("full_distribution_alignment", "manipulation_to_distribution"):
        if not any("PO3 distribution" in m for m in missing):
            missing.append("Higher timeframe PO3 distribution alignment not yet confirmed")

    align = struct.get("alignment", "neutral")
    if align not in ("full", "strong"):
        if not any("MTF structure alignment" in m for m in missing):
            missing.append(f"MTF structure alignment is {align} — strong or full not yet established")

    if not any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS):
        if not any("reclaim" in m.lower() for m in missing):
            missing.append("Liquidity reclaim not yet confirmed on any timeframe")

    return missing[:5]


def _invalidation_thesis(snapshot: dict, direction: str) -> str:
    struct = snapshot.get("structure", {})
    pref_c = _preferred_candidate(snapshot)
    parts  = []

    pl = pref_c.get("price_level", {})
    inv_level = pl.get("invalidation_level")
    if inv_level:
        side = "below" if direction == "bullish" else "above"
        parts.append(f"Close {side} {inv_level} violates the primary entry zone.")

    for tf in ["5m", "15m"]:
        if direction == "bullish":
            sl = struct.get(tf, {}).get("last_swing_low")
            if sl:
                parts.append(
                    f"Close below {tf} structural low ({sl}) would confirm a bearish shift."
                )
                break
        else:
            sh = struct.get(tf, {}).get("last_swing_high")
            if sh:
                parts.append(
                    f"Close above {tf} structural high ({sh}) would confirm a bullish shift."
                )
                break

    invals = pref_c.get("trigger_prep", {}).get("invalidation_conditions", [])
    if invals:
        candidate = invals[0]
        # Skip if this condition merely restates the zone level already in parts[0]
        already_stated = inv_level is not None and str(inv_level) in candidate
        if not already_stated:
            parts.append(candidate)

    # Deduplicate: remove exact duplicates while preserving order
    seen: set = set()
    deduped = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return (
        " ".join(deduped) if deduped
        else "No defined invalidation thesis — do not engage without a clear stop reference."
    )


def _preferred_scenario(snapshot: dict, direction: str) -> str:
    tb = snapshot.get("toolbox",  {})
    pb = snapshot.get("playbook", {})

    pb_name = pb.get("selected_playbook", "no_playbook")
    pref    = tb.get("preferred_tool", "") or ""

    if direction == "neutral" or not pref:
        return "No preferred scenario — market does not support a directional setup."

    pref_c    = _preferred_candidate(snapshot)
    pl        = pref_c.get("price_level", {})
    zl, zh    = pl.get("zone_low"), pl.get("zone_high")
    zone_str  = f" ({zl}-{zh})" if zl else ""
    tool_name = pref.replace("_", " ")
    pb_str    = pb_name.replace("_", " ") if pb_name != "no_playbook" else "identified setup"

    return (
        f"Price retraces into the {tool_name} zone{zone_str} and shows a {direction} reaction. "
        f"This confirms the {pb_str}. "
        f"{direction.capitalize()} expansion develops from the zone with follow-through."
    )


def _alternative_scenario(snapshot: dict, direction: str) -> str:
    opp    = "bearish" if direction == "bullish" else "bullish"
    struct = snapshot.get("structure", {})

    swing, swing_tf = None, None
    for tf in ["5m", "15m"]:
        if direction == "bullish":
            sl = struct.get(tf, {}).get("last_swing_low")
            if sl:
                swing, swing_tf = sl, tf
                break
        else:
            sh = struct.get(tf, {}).get("last_swing_high")
            if sh:
                swing, swing_tf = sh, tf
                break

    swing_str = f" through the {swing_tf} structural level ({swing})" if swing else ""

    return (
        f"Price fails to react at the entry zone and displaces{swing_str} "
        f"in the {opp} direction. "
        f"Setup is abandoned — look for opposing playbook confirmation before re-engaging."
    )


# ── Agreement checks ──────────────────────────────────────────────────────────

def _agreement_with_playbook(snapshot: dict, ai_direction: str) -> bool:
    pb     = snapshot.get("playbook", {})
    pb_dir = pb.get("direction", "neutral")
    pb_name = pb.get("selected_playbook", "no_playbook")

    if pb_name == "no_playbook":
        return ai_direction == "neutral"
    if pb_dir in ("neutral", "conflicted"):
        return ai_direction == "neutral"
    return ai_direction == pb_dir


def _agreement_with_risk(snapshot: dict, ai_direction: str, ai_confidence: int) -> bool:
    risk          = snapshot.get("risk", {})
    trade_allowed = risk.get("trade_allowed", False)

    if trade_allowed     and ai_confidence >= 55: return True   # both say go
    if trade_allowed     and ai_confidence <  40: return False  # risk go, AI doubtful
    if not trade_allowed and ai_confidence <  55: return True   # both cautious
    if not trade_allowed and ai_confidence >= 70: return False  # risk no, AI confident
    return True


# ── Confidence fusion ─────────────────────────────────────────────────────────

def _confidence_fusion(snapshot: dict, ai_confidence: int) -> dict:
    qual       = snapshot.get("qualification", {})
    mechanical = qual.get("opportunity_score", 0)
    combined   = round((mechanical + ai_confidence) / 2)
    diff       = abs(mechanical - ai_confidence)

    if diff <= 15:   status = "agreement"
    elif diff <= 30: status = "mild_disagreement"
    else:            status = "strong_disagreement"

    return {
        "mechanical_score":    mechanical,
        "ai_confidence":       ai_confidence,
        "combined_confidence": combined,
        "fusion_status":       status,
    }


# ── Deterministic content builder ────────────────────────────────────────────

def _build_deterministic_content(snapshot: dict, direction: str, confidence: int) -> dict:
    """
    Build narrative/analysis fields from the internal rule-based engine.
    Returns content fields only — caller applies metadata on top.
    """
    return {
        "agreement_with_playbook": _agreement_with_playbook(snapshot, direction),
        "agreement_with_risk":     _agreement_with_risk(snapshot, direction, confidence),
        "ai_direction":            direction,
        "ai_confidence":           confidence,
        "market_story":            _market_story(snapshot, direction),
        "primary_thesis":          _primary_thesis(snapshot, direction, confidence),
        "concerns":                _concerns(snapshot),
        "missing_evidence":        _missing_evidence(snapshot),
        "invalidation_thesis":     _invalidation_thesis(snapshot, direction),
        "preferred_scenario":      _preferred_scenario(snapshot, direction),
        "alternative_scenario":    _alternative_scenario(snapshot, direction),
    }


def _metadata(
    mode: str, cfg: dict,
    external_connected: bool,
    fallback_used: bool,
    fallback_reason: str | None,
    latency_ms: int | None,
) -> dict:
    """Build the standard metadata block for ai_discretionary."""
    return {
        "ai_mode":               mode,
        "external_ai_connected": external_connected,
        "provider":              cfg["provider"] if external_connected else None,
        "model":                 cfg["model"]    if external_connected else None,
        "fallback_used":         fallback_used,
        "fallback_reason":       fallback_reason,
        "latency_ms":            latency_ms,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def run_discretionary_ai(snapshot: dict, mode_override: str = None) -> tuple:
    """
    Phase 1N/1S — AI Discretionary Engine orchestrator.
    Returns (ai_discretionary: dict, confidence_fusion: dict, ai_debate: dict).

    Reads AI_MODE env var:
      internal (default) — deterministic engine only
      external           — attempt external API; fall back on failure
      hybrid             — run both; prefer external if valid

    mode_override: if provided (e.g. "internal"), overrides AI_MODE for this call only.
    Used by the Phase 1P scan loop to skip external AI on cache-reuse iterations.

    Phase 1S adds ai_debate — a deterministic multi-thesis debate built from the
    assembled snapshot + ai_discretionary output. No second external AI call.
    """
    ai_mode = (mode_override or os.getenv("AI_MODE", "internal")).lower()
    cfg     = get_ai_config()

    # Step 1: Always build the deterministic baseline
    det_dir     = _ai_direction(snapshot)
    det_conf    = _ai_confidence(snapshot, det_dir)
    det_content = _build_deterministic_content(snapshot, det_dir, det_conf)

    # Step 2: Internal mode — return immediately, no external call
    if ai_mode == "internal":
        meta   = _metadata("internal", cfg,
                           external_connected=False,
                           fallback_used=False,
                           fallback_reason=None,
                           latency_ms=None)
        fusion = _confidence_fusion(snapshot, det_conf)
        disc   = {**meta, **det_content}
        return disc, fusion, build_debate(snapshot, disc)

    # Step 3: Build compact input for external call (external / hybrid)
    compact_input = build_compact_ai_input(snapshot)

    # Step 4: Attempt external call
    adapter      = call_external_ai(compact_input)
    ext_resp     = adapter.get("response")
    fallback_req = adapter.get("fallback_required", True)
    fb_reason    = adapter.get("fallback_reason")
    latency_ms   = adapter.get("latency_ms")
    model_used   = adapter.get("model_used") or cfg["model"]

    # Step 5: Validate external response if received
    if not fallback_req and ext_resp is not None:
        valid, invalid_reason = validate_ai_response(ext_resp)
        if not valid:
            fallback_req = True
            fb_reason    = f"invalid_schema: {invalid_reason}"
            ext_resp     = None

    # Step 6: Fall back to deterministic if external failed or invalid
    if fallback_req or ext_resp is None:
        meta   = _metadata(ai_mode, cfg,
                           external_connected=False,
                           fallback_used=True,
                           fallback_reason=fb_reason,
                           latency_ms=latency_ms)
        fusion = _confidence_fusion(snapshot, det_conf)
        disc   = {**meta, **det_content}
        return disc, fusion, build_debate(snapshot, disc)

    # Step 7: External response is valid — build output from it
    ext_conf    = ext_resp.get("ai_confidence", det_conf)
    ext_content = {
        "agreement_with_playbook": ext_resp.get("agreement_with_playbook"),
        "agreement_with_risk":     ext_resp.get("agreement_with_risk"),
        "ai_direction":            ext_resp.get("ai_direction"),
        "ai_confidence":           ext_conf,
        "market_story":            ext_resp.get("market_story",         ""),
        "primary_thesis":          ext_resp.get("primary_thesis",       ""),
        "concerns":                ext_resp.get("concerns",             []),
        "missing_evidence":        ext_resp.get("missing_evidence",     []),
        "invalidation_thesis":     ext_resp.get("invalidation_thesis",  ""),
        "preferred_scenario":      ext_resp.get("preferred_scenario",   ""),
        "alternative_scenario":    ext_resp.get("alternative_scenario", ""),
    }

    # Build metadata manually for external success — uses actual model returned by adapter
    meta = {
        "ai_mode":               ai_mode,
        "external_ai_connected": True,
        "provider":              cfg["provider"],
        "model":                 model_used,
        "fallback_used":         False,
        "fallback_reason":       None,
        "latency_ms":            latency_ms,
    }
    fusion = _confidence_fusion(snapshot, ext_conf)
    disc   = {**meta, **ext_content}

    # Step 8: In hybrid mode, store deterministic output for audit trail
    if ai_mode == "hybrid":
        det_meta = _metadata("hybrid_deterministic", cfg,
                             external_connected=False,
                             fallback_used=False,
                             fallback_reason=None,
                             latency_ms=None)
        disc["deterministic_output"] = {**det_meta, **det_content}

    return disc, fusion, build_debate(snapshot, disc)

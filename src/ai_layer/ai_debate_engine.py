"""
Phase 1S — Multi-Thesis AI Debate Engine.
Evaluates bullish, bearish, and neutral stances deterministically from
the assembled snapshot + already-computed ai_discretionary output.

No external AI call. No execution. No orders. No broker actions.
"""

_TFS = ["15m", "5m", "3m", "1m"]


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def _trigger_status(snapshot: dict) -> str:
    pref_c = _preferred_candidate(snapshot)
    return (pref_c.get("trigger_prep", {}).get("effective_trigger_status") or "n/a").lower()


def _tool_eff_pts(snapshot: dict) -> tuple[int, str]:
    """Return (points, status_label) for the best available effective tool status."""
    status = (snapshot.get("toolbox", {}).get("best_available_effective_status") or "no_tool").lower()
    pts = {"actionable": 8, "ready": 5, "forming": 2, "no_tool": 0}
    return pts.get(status, 0), status


def _struct_counts(snapshot: dict) -> tuple[int, int]:
    """Return (bullish_tf_count, bearish_tf_count) across all four timeframes."""
    struct = snapshot.get("structure", {})
    bull   = sum(1 for tf in _TFS if struct.get(tf, {}).get("bias") == "bullish")
    bear   = sum(1 for tf in _TFS if struct.get(tf, {}).get("bias") == "bearish")
    return bull, bear


def _liq_sweep(snapshot: dict, direction: str) -> tuple[bool, bool]:
    """Return (sweep_detected, reclaim_detected) for the given sweep direction."""
    liq = snapshot.get("liquidity", {})
    swept   = any(
        liq.get(tf, {}).get("sweep_detected")
        and liq.get(tf, {}).get("sweep_direction") == direction
        for tf in _TFS
    )
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    return swept, reclaim


# ── Bullish thesis ────────────────────────────────────────────────────────────

def _score_bullish(snapshot: dict, ai_disc: dict) -> tuple[int, list, list, str, str]:
    pts       = 0
    evidence  = []
    weakness  = []

    pb     = snapshot.get("playbook",      {})
    tb     = snapshot.get("toolbox",       {})
    risk   = snapshot.get("risk",          {})
    qual   = snapshot.get("qualification", {})
    ai_ctx = snapshot.get("ai_context",    {})
    po3    = snapshot.get("po3",           {})
    mem    = snapshot.get("memory",        {})
    st     = snapshot.get("state_transition", {})
    sl     = snapshot.get("setup_lifecycle",  {})
    struct = snapshot.get("structure",     {})

    pref_tool   = tb.get("preferred_tool", "") or ""
    qs          = (qual.get("status") or "no_trade").lower()
    qdir        = (qual.get("direction") or "neutral").lower()
    pb_dir      = (pb.get("direction") or "neutral").lower()
    pb_name     = (pb.get("selected_playbook") or "no_playbook").lower()
    session     = snapshot.get("session", "unknown")

    # Playbook direction
    if pb_dir == "bullish":
        pts += 20
        evidence.append(f"Playbook {pb_name.replace('_', ' ')} is bullish")
    elif pb_dir != "neutral":
        weakness.append(f"Playbook direction is {pb_dir}")

    # Preferred tool direction
    if pref_tool.startswith("bullish_"):
        pts += 10
        evidence.append(f"Preferred tool {pref_tool.replace('_', ' ')} is bullish")
    elif pref_tool.startswith("bearish_"):
        weakness.append(f"Preferred tool {pref_tool.replace('_', ' ')} opposes bullish bias")

    # Tool readiness
    tool_pts, tool_status = _tool_eff_pts(snapshot)
    if pref_tool.startswith("bullish_") and tool_pts > 0:
        pts += tool_pts
        evidence.append(f"Bullish tool readiness: {tool_status}")

    # Liquidity sweep below + reclaim (bullish reversal)
    swept, reclaim = _liq_sweep(snapshot, "below")
    if swept:
        pts += 8
        if reclaim:
            pts += 6
            evidence.append("Liquidity sweep below with reclaim — bullish reversal signal")
        else:
            evidence.append("Liquidity sweep below detected — reclaim pending")

    # Structure alignment
    bull_s, bear_s = _struct_counts(snapshot)
    if bull_s >= 3:
        pts += 10
        evidence.append(f"Bullish structure on {bull_s}/4 timeframes")
    elif bull_s == 2:
        pts += 5
        evidence.append(f"Partial bullish structure ({bull_s}/4 timeframes)")
    else:
        weakness.append(f"Only {bull_s}/4 timeframes bullish structure")

    # AI directional bias
    ai_dir = (ai_disc.get("ai_direction") or "neutral").lower()
    ai_conf = ai_disc.get("ai_confidence", 0)
    if ai_dir == "bullish":
        pts += 10
        evidence.append(f"AI direction bullish (confidence {ai_conf})")
    elif ai_dir == "bearish":
        weakness.append("AI direction is bearish — opposes this thesis")

    ctx_bias = (ai_ctx.get("directional_bias") or "neutral").lower()
    if ctx_bias == "bullish" and ai_dir != "bullish":
        pts += 5
        evidence.append("Narrative directional bias: bullish")

    # Confidence trend
    if mem and mem.get("available"):
        trend = ((mem.get("global") or {}).get("confidence_trend") or "stable").lower()
        if trend == "rising":
            pts += 8
            evidence.append("Confidence trend rising")
        elif trend == "falling":
            weakness.append("Confidence trend falling")

    # Trigger status for bullish tool
    trig = _trigger_status(snapshot)
    if pref_tool.startswith("bullish_"):
        if trig in ("confirmed", "retest_in_progress"):
            pts += 10
            evidence.append(f"Bullish trigger: {trig.replace('_', ' ')}")
        elif trig == "waiting_for_retest":
            pts += 5
            evidence.append("Awaiting bullish retest entry")

    # Qualification
    if qs in ("qualified", "elite") and qdir == "bullish":
        pts += 8
        evidence.append(f"Qualification {qs} bullish")
    elif qs == "candidate" and qdir == "bullish":
        pts += 4
        evidence.append("Qualification: candidate bullish")

    # PO3 bullish distribution
    for tf in ["15m", "5m"]:
        if po3.get(tf, {}).get("distribution_direction") == "bullish":
            pts += 8
            evidence.append(f"PO3 {tf} distribution: bullish")
            break

    # Setup lifecycle
    if sl and sl.get("active"):
        phase = sl.get("current_phase", "")
        if phase in ("maturing", "actionable"):
            pts += 5
            evidence.append(f"Setup lifecycle: {phase}")

    # State transition upgrade
    if st.get("transition_type") == "upgrade":
        pts += 5
        evidence.append("State transition: upgrade")

    # Weaknesses
    if not risk.get("trade_allowed", False):
        weakness.append(f"Risk blocked — {risk.get('risk_tier', 'blocked')}")
    if qs in ("no_trade", "watchlist"):
        weakness.append(f"Qualification only {qs}")

    # Argument
    if pts >= 30 and evidence:
        arg = (
            f"Bullish case driven by {evidence[0].lower()}. "
            f"Session: {session}. Setup: {pb_name.replace('_', ' ')}."
        )
    elif evidence:
        arg = f"Weak bullish signals: {evidence[0].lower()}. Full confirmation lacking."
    else:
        arg = "No compelling bullish evidence in current market structure."

    # Invalidation
    pref_c  = _preferred_candidate(snapshot)
    inv_lvl = pref_c.get("price_level", {}).get("invalidation_level")
    if inv_lvl:
        inv = f"Close below {inv_lvl} invalidates bullish setup"
    else:
        sl5 = struct.get("5m", {}).get("last_swing_low") or struct.get("15m", {}).get("last_swing_low")
        inv = (
            f"Break below swing low ({sl5}) invalidates bullish bias"
            if sl5
            else "Bearish structural shift or failed reclaim invalidates bullish bias"
        )

    return max(0, min(100, pts)), evidence[:5], weakness[:4], arg, inv


# ── Bearish thesis ────────────────────────────────────────────────────────────

def _score_bearish(snapshot: dict, ai_disc: dict) -> tuple[int, list, list, str, str]:
    pts      = 0
    evidence = []
    weakness = []

    pb     = snapshot.get("playbook",      {})
    tb     = snapshot.get("toolbox",       {})
    risk   = snapshot.get("risk",          {})
    qual   = snapshot.get("qualification", {})
    ai_ctx = snapshot.get("ai_context",    {})
    po3    = snapshot.get("po3",           {})
    mem    = snapshot.get("memory",        {})
    st     = snapshot.get("state_transition", {})
    sl     = snapshot.get("setup_lifecycle",  {})
    struct = snapshot.get("structure",     {})

    pref_tool = tb.get("preferred_tool", "") or ""
    qs        = (qual.get("status") or "no_trade").lower()
    qdir      = (qual.get("direction") or "neutral").lower()
    pb_dir    = (pb.get("direction") or "neutral").lower()
    pb_name   = (pb.get("selected_playbook") or "no_playbook").lower()
    session   = snapshot.get("session", "unknown")

    # Playbook direction
    if pb_dir == "bearish":
        pts += 20
        evidence.append(f"Playbook {pb_name.replace('_', ' ')} is bearish")
    elif pb_dir != "neutral":
        weakness.append(f"Playbook direction is {pb_dir}")

    # Preferred tool direction
    if pref_tool.startswith("bearish_"):
        pts += 10
        evidence.append(f"Preferred tool {pref_tool.replace('_', ' ')} is bearish")
    elif pref_tool.startswith("bullish_"):
        weakness.append(f"Preferred tool {pref_tool.replace('_', ' ')} opposes bearish bias")

    # Tool readiness
    tool_pts, tool_status = _tool_eff_pts(snapshot)
    if pref_tool.startswith("bearish_") and tool_pts > 0:
        pts += tool_pts
        evidence.append(f"Bearish tool readiness: {tool_status}")

    # Liquidity sweep above + reject (bearish reversal)
    swept, reclaim = _liq_sweep(snapshot, "above")
    if swept:
        pts += 8
        if reclaim:
            pts += 6
            evidence.append("Liquidity sweep above with rejection — bearish reversal signal")
        else:
            evidence.append("Liquidity sweep above detected — rejection pending")

    # Structure alignment
    bull_s, bear_s = _struct_counts(snapshot)
    if bear_s >= 3:
        pts += 10
        evidence.append(f"Bearish structure on {bear_s}/4 timeframes")
    elif bear_s == 2:
        pts += 5
        evidence.append(f"Partial bearish structure ({bear_s}/4 timeframes)")
    else:
        weakness.append(f"Only {bear_s}/4 timeframes bearish structure")

    # AI directional bias
    ai_dir  = (ai_disc.get("ai_direction") or "neutral").lower()
    ai_conf = ai_disc.get("ai_confidence", 0)
    if ai_dir == "bearish":
        pts += 10
        evidence.append(f"AI direction bearish (confidence {ai_conf})")
    elif ai_dir == "bullish":
        weakness.append("AI direction is bullish — opposes this thesis")

    ctx_bias = (ai_ctx.get("directional_bias") or "neutral").lower()
    if ctx_bias == "bearish" and ai_dir != "bearish":
        pts += 5
        evidence.append("Narrative directional bias: bearish")

    # Confidence trend
    if mem and mem.get("available"):
        trend = ((mem.get("global") or {}).get("confidence_trend") or "stable").lower()
        if trend == "rising":
            pts += 8
            evidence.append("Confidence trend rising")
        elif trend == "falling":
            weakness.append("Confidence trend falling")

    # Trigger status for bearish tool
    trig = _trigger_status(snapshot)
    if pref_tool.startswith("bearish_"):
        if trig in ("confirmed", "retest_in_progress"):
            pts += 10
            evidence.append(f"Bearish trigger: {trig.replace('_', ' ')}")
        elif trig == "waiting_for_retest":
            pts += 5
            evidence.append("Awaiting bearish retest entry")

    # Qualification
    if qs in ("qualified", "elite") and qdir == "bearish":
        pts += 8
        evidence.append(f"Qualification {qs} bearish")
    elif qs == "candidate" and qdir == "bearish":
        pts += 4
        evidence.append("Qualification: candidate bearish")

    # PO3 bearish distribution
    for tf in ["15m", "5m"]:
        if po3.get(tf, {}).get("distribution_direction") == "bearish":
            pts += 8
            evidence.append(f"PO3 {tf} distribution: bearish")
            break

    # Setup lifecycle
    if sl and sl.get("active"):
        phase = sl.get("current_phase", "")
        if phase in ("maturing", "actionable"):
            pts += 5
            evidence.append(f"Setup lifecycle: {phase}")

    # State transition upgrade
    if st.get("transition_type") == "upgrade":
        pts += 5
        evidence.append("State transition: upgrade")

    # Weaknesses
    if not risk.get("trade_allowed", False):
        weakness.append(f"Risk blocked — {risk.get('risk_tier', 'blocked')}")
    if qs in ("no_trade", "watchlist"):
        weakness.append(f"Qualification only {qs}")

    # Argument
    if pts >= 30 and evidence:
        arg = (
            f"Bearish case driven by {evidence[0].lower()}. "
            f"Session: {session}. Setup: {pb_name.replace('_', ' ')}."
        )
    elif evidence:
        arg = f"Weak bearish signals: {evidence[0].lower()}. Full confirmation lacking."
    else:
        arg = "No compelling bearish evidence in current market structure."

    # Invalidation
    pref_c  = _preferred_candidate(snapshot)
    inv_lvl = pref_c.get("price_level", {}).get("invalidation_level")
    if inv_lvl:
        inv = f"Close above {inv_lvl} invalidates bearish setup"
    else:
        sh5 = struct.get("5m", {}).get("last_swing_high") or struct.get("15m", {}).get("last_swing_high")
        inv = (
            f"Break above swing high ({sh5}) invalidates bearish bias"
            if sh5
            else "Bullish structural shift or failed rejection invalidates bearish bias"
        )

    return max(0, min(100, pts)), evidence[:5], weakness[:4], arg, inv


# ── Neutral thesis ────────────────────────────────────────────────────────────

def _score_neutral(snapshot: dict, ai_disc: dict) -> tuple[int, list, list, str, str]:
    pts      = 0
    evidence = []
    weakness = []

    pb     = snapshot.get("playbook",         {})
    risk   = snapshot.get("risk",             {})
    qual   = snapshot.get("qualification",    {})
    ai_ctx = snapshot.get("ai_context",       {})
    struct = snapshot.get("structure",        {})
    po3    = snapshot.get("po3",              {})
    mem    = snapshot.get("memory",           {})
    st     = snapshot.get("state_transition", {})
    sl     = snapshot.get("setup_lifecycle",  {})
    session = snapshot.get("session", "unknown")

    qs       = (qual.get("status") or "no_trade").lower()
    pb_name  = (pb.get("selected_playbook") or "no_playbook").lower()
    ai_conf  = ai_disc.get("ai_confidence", 0)
    narrative = (ai_ctx.get("market_narrative") or "neutral").lower()

    # Risk blocked
    if not risk.get("trade_allowed", False):
        pts += 25
        evidence.append(f"Risk Governor blocked — {risk.get('risk_tier', 'blocked')}")

    # Qualification: no_trade
    if qs == "no_trade":
        pts += 20
        evidence.append("Qualification: no_trade — no opportunity identified")
    elif qs == "watchlist":
        pts += 10
        evidence.append("Qualification: watchlist — setup forming but unconfirmed")

    # Session
    if session in ("premarket", "after_hours", "closed", "overnight"):
        pts += 15
        evidence.append(f"Session: {session} — reduced market reliability")

    # Setup lifecycle decaying or invalidated
    if sl and sl.get("active"):
        phase = sl.get("current_phase", "")
        if phase in ("decaying", "invalidated"):
            pts += 15
            evidence.append(f"Setup lifecycle: {phase}")
    elif not (sl and sl.get("active")):
        pts += 8
        evidence.append("No active setup")

    # State transition decay/invalidation
    trans = (st.get("transition_type") or "stable").lower()
    if trans in ("decay", "invalidation"):
        pts += 15
        evidence.append(f"State transition: {trans}")

    # PO3 mixed or no alignment
    po3_align = (po3.get("alignment") or "").lower()
    if po3_align in ("mixed", "no_clear_alignment"):
        pts += 10
        evidence.append(f"PO3 alignment: {po3_align.replace('_', ' ')}")

    # Conflicting structure
    bull_s, bear_s = _struct_counts(snapshot)
    if abs(bull_s - bear_s) <= 1 and (bull_s + bear_s) >= 2:
        pts += 8
        evidence.append(f"Conflicting structure: {bull_s} bullish vs {bear_s} bearish TFs")

    # AI confidence low
    if ai_conf < 30:
        pts += 10
        evidence.append(f"AI confidence low: {ai_conf}/100")

    # Confidence trend falling
    if mem and mem.get("available"):
        trend = ((mem.get("global") or {}).get("confidence_trend") or "stable").lower()
        if trend == "falling":
            pts += 8
            evidence.append("Confidence trend: falling")

    # No active playbook
    if pb_name == "no_playbook":
        pts += 8
        evidence.append("No active playbook")

    # Market narrative conflicted/neutral/compression
    if narrative in ("conflicted", "compression", "neutral"):
        pts += 8
        evidence.append(f"Market narrative: {narrative}")

    # Weaknesses (things that argue against standing down)
    if risk.get("trade_allowed", False):
        weakness.append("Risk Governor allows trade")
    if qs in ("qualified", "elite", "candidate"):
        weakness.append(f"Qualification is {qs}")
    if sl and sl.get("active") and sl.get("current_phase") not in ("decaying", "invalidated", None):
        weakness.append(f"Active setup: {sl.get('current_phase', '?')}")

    # Argument
    if pts >= 40 and evidence:
        arg = (
            f"Stand-down recommended: {evidence[0].lower()}. "
            f"Multiple conditions unfavorable. Session: {session}."
        )
    elif pts >= 20:
        arg = "Market is in a transitional or watchful state. Monitor for improvement."
    else:
        arg = "Minor neutral signals present. Conditions may support engagement on other metrics."

    inv = (
        "Neutral stance invalidated when risk clears, qualification reaches candidate+, "
        "and tool readiness improves to ready or actionable."
    )

    return max(0, min(100, pts)), evidence[:5], weakness[:3], arg, inv


# ── Final verdict ─────────────────────────────────────────────────────────────

def _final_verdict(
    snapshot: dict,
    ai_disc: dict,
    bull_score: int,
    bear_score: int,
    neut_score: int,
) -> dict:
    risk          = snapshot.get("risk", {})
    trade_allowed = risk.get("trade_allowed", False)
    sl            = snapshot.get("setup_lifecycle", {})
    lifecycle_phase = (sl.get("current_phase") or "dormant") if sl.get("active") else "dormant"
    trig          = _trigger_status(snapshot)
    trig_active   = trig in ("confirmed", "retest_in_progress", "confirmation_needed")

    scores   = {"bullish": bull_score, "bearish": bear_score, "neutral": neut_score}
    dominant = max(scores, key=lambda k: scores[k])
    verdict_confidence = scores[dominant]
    required_evidence: list[str] = []

    if lifecycle_phase == "invalidated":
        stance = "stand_down"
        reason = "Setup lifecycle is invalidated — wait for a fresh setup to form."
        required_evidence = ["New active playbook with qualified tool required before re-engagement"]

    elif dominant == "neutral":
        if trade_allowed:
            stance = "monitor"
            reason = (
                f"Neutral thesis dominant at {neut_score} but risk is open. "
                "Watching for directional conviction."
            )
            required_evidence = [
                "Qualification must reach candidate or above",
                "Active directional playbook required",
            ]
        else:
            stance = "stand_down"
            reason = f"Neutral thesis dominant at {neut_score} and risk is blocked."
            required_evidence = [
                "Risk Governor must clear",
                "Qualification must improve beyond watchlist",
            ]

    elif dominant == "bullish":
        if trade_allowed and trig_active:
            stance = "prepare_long"
            reason = (
                f"Bullish thesis dominant at {bull_score} "
                "with risk allowed and trigger active."
            )
        elif trade_allowed:
            stance = "bullish_bias"
            reason = (
                f"Bullish thesis dominant at {bull_score} "
                "with risk allowed but trigger not yet active."
            )
            required_evidence = ["Trigger must reach retest_in_progress or confirmed"]
        else:
            stance = "monitor"
            reason = f"Bullish thesis dominant at {bull_score} but risk is blocked."
            required_evidence = [
                "Risk Governor must clear the block",
                "Watch for qualification upgrade",
            ]

    elif dominant == "bearish":
        if trade_allowed and trig_active:
            stance = "prepare_short"
            reason = (
                f"Bearish thesis dominant at {bear_score} "
                "with risk allowed and trigger active."
            )
        elif trade_allowed:
            stance = "bearish_bias"
            reason = (
                f"Bearish thesis dominant at {bear_score} "
                "with risk allowed but trigger not yet active."
            )
            required_evidence = ["Trigger must reach retest_in_progress or confirmed"]
        else:
            stance = "monitor"
            reason = f"Bearish thesis dominant at {bear_score} but risk is blocked."
            required_evidence = [
                "Risk Governor must clear the block",
                "Watch for qualification upgrade",
            ]

    else:
        stance = "stand_down"
        reason = "No dominant thesis — market conditions unclear."
        required_evidence = ["Wait for clearer market structure"]

    return {
        "recommended_stance":              stance,
        "dominant_thesis":                 dominant,
        "verdict_confidence":              verdict_confidence,
        "reason":                          reason,
        "required_evidence_to_change_view": required_evidence,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def build_debate(snapshot: dict, ai_disc: dict) -> dict:
    """
    Build a deterministic multi-thesis ai_debate dict.
    snapshot must be fully assembled (including state_transition + setup_lifecycle).
    ai_disc is the already-computed ai_discretionary result.
    No external AI call.
    """
    bull_score, bull_ev, bull_wk, bull_arg, bull_inv = _score_bullish(snapshot, ai_disc)
    bear_score, bear_ev, bear_wk, bear_arg, bear_inv = _score_bearish(snapshot, ai_disc)
    neut_score, neut_ev, neut_wk, neut_arg, neut_inv = _score_neutral(snapshot, ai_disc)

    verdict = _final_verdict(snapshot, ai_disc, bull_score, bear_score, neut_score)

    return {
        "enabled":          True,
        "mode":             "deterministic_internal_debate",
        "external_ai_used": False,
        "bullish_thesis": {
            "case_strength":      bull_score,
            "argument":           bull_arg,
            "supporting_evidence": bull_ev,
            "weaknesses":         bull_wk,
            "invalidation":       bull_inv,
        },
        "bearish_thesis": {
            "case_strength":      bear_score,
            "argument":           bear_arg,
            "supporting_evidence": bear_ev,
            "weaknesses":         bear_wk,
            "invalidation":       bear_inv,
        },
        "neutral_thesis": {
            "case_strength":      neut_score,
            "argument":           neut_arg,
            "supporting_evidence": neut_ev,
            "weaknesses":         neut_wk,
            "invalidation":       neut_inv,
        },
        "final_verdict": verdict,
    }

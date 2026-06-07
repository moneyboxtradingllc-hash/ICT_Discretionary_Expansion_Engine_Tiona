"""
Tool Readiness Analyzer — Phase 1K.1.
For each tool candidate, answers:
  - prerequisites_missing : evidence without which the setup is not yet valid
  - score_gaps            : evidence that would increase confidence but is not required
  - promotion_criteria    : what would move the tool to the next raw_status tier
  - invalidation_criteria : what would remove this tool from consideration entirely

No execution, no order routing, no indicator recalculation.
All inputs are pre-computed snapshot dicts.
"""

_TFS = ["15m", "5m", "3m", "1m"]

_NEXT_STATUS = {"forming": "ready", "ready": "actionable", "actionable": None}


def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


# ── Per-family readiness checkers ─────────────────────────────────────────────
# Each returns (prerequisites_missing, score_gaps, promotion_criteria, invalidation_criteria).
# prerequisites_missing : setup not valid without these
# score_gaps            : would improve confidence score but setup can still form without them

def _readiness_ifvg(snap: dict, direction: str, score: int, raw_status: str):
    liq = snap.get("liquidity", {})
    exp = snap.get("expansion", {})
    po3 = snap.get("po3",       {})

    sweep     = any(liq.get(tf, {}).get("sweep_detected")  for tf in _TFS)
    reclaim   = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    ltf_exp   = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["3m", "1m"]
    )
    ltf_po3   = any(
        po3.get(tf, {}).get("phase") in ("manipulation", "transition")
        for tf in ["3m", "1m"]
    )
    full_dist = po3.get("alignment") == "full_distribution_alignment"

    prereqs = []
    gaps    = []
    promote = []

    if not sweep:
        prereqs.append("Liquidity sweep not detected — IFVG concept requires a liquidity grab")
        promote.append("Sweep detected — price raids an established liquidity pool")
    if sweep and not reclaim:
        prereqs.append("Reclaim not confirmed — price has not closed back through the sweep origin")
        promote.append("Reclaim confirmed — price closes back through the sweep level")
    if not ltf_exp:
        gaps.append("Lower timeframe expansion (3m/1m) not yet initiated — reduces entry timing confidence")
        if sweep and reclaim:
            promote.append("3m or 1m enters early or healthy expansion state")
    if not ltf_po3:
        gaps.append("Lower timeframe PO3 not in manipulation or transition phase — reduces phase alignment score")
        if sweep and reclaim:
            promote.append("3m or 1m PO3 shifts into manipulation or transition phase")
    if full_dist:
        prereqs.append("PO3 full distribution alignment active — IFVG delivery window likely already closed")

    invalidation = [
        "PO3 full distribution alignment — tool already delivered, entry window closed",
        "No liquidity event after multiple snapshots — manipulation leg absent",
        "Price continues directionally without reclaim — sweep not being absorbed",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_breaker(snap: dict, direction: str, score: int, raw_status: str):
    liq    = snap.get("liquidity",  {})
    struct = snap.get("structure",  {})

    sweep   = any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS)
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    failed  = any(liq.get(tf, {}).get("failed_breakout")  for tf in _TFS)
    mss     = any(struct.get(tf, {}).get("mss")           for tf in _TFS)
    bos     = any(struct.get(tf, {}).get("bos")           for tf in _TFS)

    prereqs = []
    gaps    = []
    promote = []

    if not failed:
        prereqs.append("Failed breakout not confirmed — the reversal through the break level has not occurred")
        promote.append("Failed breakout confirmed — price recrosses its break level from the wrong side")
    if not sweep:
        prereqs.append("Liquidity sweep not detected — manipulation leg required for breaker context")
        promote.append("Sweep detected — confirms manipulation before the structural reversal")
    if sweep and not reclaim:
        gaps.append("Reclaim not confirmed — sweep reversal not yet validated by price closing back through")
        promote.append("Reclaim confirmed — breaker context solidified with price returning into range")
    if not mss:
        gaps.append("Market structure shift (MSS) not yet present — structural reversal not confirmed")
        if failed and sweep:
            promote.append("MSS confirmed — structural reversal adds conviction to the breaker")
    if not bos and not mss:
        gaps.append("No break of structure (BOS) yet — structural momentum not established")

    invalidation = [
        "Price continues through the breaker level without reversing — structure invalidated",
        "No failed breakout evidence — breaker concept never activates",
        "Sweep continues deeper without reclaim — price accepting the new range",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_rejection_block(snap: dict, direction: str, score: int, raw_status: str):
    liq = snap.get("liquidity", {})
    exp = snap.get("expansion", {})

    sweep           = any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS)
    reclaim         = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    exhaustion_high = any(exp.get(tf, {}).get("exhaustion_risk") == "high"   for tf in ["15m", "5m"])
    exhaustion_med  = any(exp.get(tf, {}).get("exhaustion_risk") == "medium" for tf in ["15m", "5m"])

    prereqs = []
    gaps    = []
    promote = []

    if not sweep:
        prereqs.append("Liquidity sweep not detected — wick rejection zone requires a sweep to define it")
        promote.append("Sweep detected — creates the wick that defines the rejection block boundary")
    if sweep and not reclaim:
        prereqs.append("Reclaim not confirmed — wick rejection not yet validated as a reversal point")
        promote.append("Reclaim confirmed — wick zone defined and price has returned through it")
    if not exhaustion_high and not exhaustion_med:
        gaps.append(
            "No expansion exhaustion signal on 15m/5m — "
            "rejection probability lower without an extended prior move"
        )
        if sweep and reclaim:
            promote.append(
                "15m or 5m expansion reaches medium or high exhaustion — ideal rejection block context"
            )

    invalidation = [
        "Price closes through the wick/rejection zone without reversing — block violated",
        "Expansion continues without exhaustion — structure shifts to trend continuation setup",
        "No sweep occurs — rejection block never initializes",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_fvg(snap: dict, direction: str, score: int, raw_status: str):
    exp = snap.get("expansion", {})
    liq = snap.get("liquidity", {})

    disp   = any(exp.get(tf, {}).get("displacement_detected") for tf in ["15m", "5m"])
    exp_ok = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["15m", "5m"]
    )
    sweep  = any(liq.get(tf, {}).get("sweep_detected") for tf in _TFS)

    prereqs = []
    gaps    = []
    promote = []

    if not disp:
        prereqs.append(
            "Displacement candle not confirmed on 15m/5m — "
            "FVG imbalance has not yet been created"
        )
        promote.append("Displacement candle fires on 15m or 5m — creates the three-candle imbalance gap")
    if not exp_ok:
        gaps.append("15m/5m expansion not in early or healthy state — directional momentum not confirmed")
        if disp:
            promote.append("15m or 5m enters early or healthy expansion state")
    if sweep:
        gaps.append(
            "Liquidity sweep present — clean FVG directional context disrupted "
            "(reduces score by 5 pts)"
        )

    invalidation = [
        "FVG filled before price returns to test — imbalance resolved, setup gone",
        "Expansion shifts to exhaustion_risk state — late entry risk too high",
        "15m volatility toxic or explosive — FVG entry timing becomes unreliable",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_order_block(snap: dict, direction: str, score: int, raw_status: str):
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})
    po3    = snap.get("po3",       {})

    align   = struct.get("alignment", "neutral")
    exp_ok  = any(
        exp.get(tf, {}).get("state") in ("healthy_expansion", "mature_expansion")
        for tf in ["15m", "5m"]
    )
    dist    = any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"])
    exhaust = any(exp.get(tf, {}).get("exhaustion_risk") == "high" for tf in ["15m", "5m"])

    prereqs = []
    gaps    = []
    promote = []

    if align not in ("full", "strong"):
        gaps.append(
            f"MTF structure alignment is {align} — strong or full alignment adds up to 20 pts"
        )
        promote.append("Structure alignment improves to strong or full — confirms directional delivery context")
    if not exp_ok:
        gaps.append(
            "15m/5m not in healthy or mature expansion — "
            "move from the block not yet confirmed"
        )
        if align in ("full", "strong"):
            promote.append("15m or 5m enters healthy or mature expansion — validates price delivered from this block")
    if not dist:
        gaps.append("HTF PO3 distribution phase not active — order block not yet in confirmed delivery")
        promote.append("15m or 5m PO3 enters distribution phase — confirms block is in delivery")
    if exhaust:
        gaps.append("Expansion exhaustion risk high — order block entry would chase an extended move")

    invalidation = [
        "Expansion exhaustion risk high — block entry is over-extended",
        "Structure alignment weakens to neutral or mixed — directional bias lost",
        "Price closes through the order block candle — block violated",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_ote_retracement(snap: dict, direction: str, score: int, raw_status: str):
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})
    po3    = snap.get("po3",       {})

    align  = struct.get("alignment", "neutral")
    mature = any(
        exp.get(tf, {}).get("state") in ("mature_expansion", "healthy_expansion")
        for tf in ["15m", "5m"]
    )
    dist   = any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"])

    prereqs = []
    gaps    = []
    promote = []

    if not mature:
        prereqs.append(
            "15m/5m expansion not yet mature or healthy — "
            "the impulse leg that defines the OTE zone has not completed"
        )
        promote.append(
            "15m or 5m enters mature or healthy expansion — "
            "creates the swing leg that defines the OTE retracement zone"
        )
    if align not in ("full", "strong"):
        gaps.append(
            f"Structure alignment is {align} — strong or full alignment adds up to 15 pts "
            "and confirms pullback will find demand/supply at OTE"
        )
        if mature:
            promote.append("Structure alignment improves to strong or full")
    if not dist:
        gaps.append(
            "HTF PO3 distribution not active — continuation after retracement not confirmed"
        )
        if mature:
            promote.append("HTF PO3 enters distribution phase — validates continuation from OTE zone")

    invalidation = [
        "Price moves through OTE zone (0.62-0.79 of swing) without reversing — level not respected",
        "Structure alignment reverses — pullback becomes a new impulsive leg, not a retracement",
        "Expansion resets to early state — the defining swing was a false move",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_mss_retest(snap: dict, direction: str, score: int, raw_status: str):
    struct = snap.get("structure", {})
    liq    = snap.get("liquidity", {})

    mss     = any(struct.get(tf, {}).get("mss") for tf in _TFS)
    bos     = any(struct.get(tf, {}).get("bos") for tf in _TFS)
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)

    prereqs = []
    gaps    = []
    promote = []

    if not mss:
        prereqs.append("MSS not confirmed — no market structure shift to retest")
        promote.append("MSS confirmed — price has shifted internal structure, creating the retest level")
    if not bos:
        gaps.append("Break of structure (BOS) not confirmed — momentum signal absent")
        if mss:
            promote.append("BOS confirmed — structural momentum supports continuation toward MSS retest")
    if not reclaim:
        gaps.append(
            "No reclaim event — price has not yet pulled back to the shifted structure level"
        )
        if mss:
            promote.append("Reclaim confirmed — price returns to MSS origin, activating the retest entry")

    invalidation = [
        "Price closes through the MSS origin without reversal — shift invalidated",
        "Consecutive MSS events in opposite directions — structure noisy, avoid",
        "Extended time at MSS level without reaction — level has lost significance",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_ote_after_reclaim(snap: dict, direction: str, score: int, raw_status: str):
    liq    = snap.get("liquidity", {})
    exp    = snap.get("expansion", {})
    struct = snap.get("structure", {})

    sweep   = any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS)
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    ltf_exp = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["3m", "1m"]
    )
    align   = struct.get("alignment", "neutral")

    prereqs = []
    gaps    = []
    promote = []

    if not sweep:
        prereqs.append("Liquidity sweep not detected — reclaim OTE setup not initiated")
        promote.append("Sweep detected — establishes the origin level for OTE entry after reclaim")
    if sweep and not reclaim:
        prereqs.append("Reclaim not confirmed — OTE zone is not yet active without price returning through sweep level")
        promote.append("Reclaim confirmed — OTE entry zone activates once price closes through sweep origin")
    if not ltf_exp:
        gaps.append("Lower timeframe expansion (3m/1m) not begun — momentum post-reclaim unconfirmed")
        if sweep and reclaim:
            promote.append("3m or 1m enters early or healthy expansion — confirms directional momentum post-reclaim")
    if align == "full":
        gaps.append("Structure alignment full — trend continuation tools may score higher in this context")

    invalidation = [
        "Price fails to reclaim and continues through sweep origin — setup abandoned",
        "Structure alignment strengthens to full — trend continuation tools take priority",
        "Lower timeframe expansion never initiates after reclaim — momentum absent",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_opening_fvg(snap: dict, direction: str, score: int, raw_status: str):
    exp     = snap.get("expansion",  {})
    vol     = snap.get("volatility", {})
    session = snap.get("session",    "")

    in_session = session == "ny_open"
    disp       = any(exp.get(tf, {}).get("displacement_detected") for tf in ["1m", "3m", "5m"])
    exp_ok     = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["1m", "3m", "5m"]
    )
    vol_state = vol.get("15m", {}).get("state", "")
    toxic     = vol_state in ("toxic", "explosive")

    prereqs = []
    gaps    = []
    promote = []

    if not in_session:
        prereqs.append(
            f"Session is '{session}' — opening FVG requires ny_open session gate"
        )
        promote.append("Session advances to ny_open — unlocks the opening FVG window")
    if not disp:
        prereqs.append("Displacement candle not detected on 1m/3m/5m — opening FVG not yet created")
        if in_session:
            promote.append("Displacement candle fires at open — creates the imbalance gap")
    if not exp_ok:
        gaps.append("1m/3m/5m expansion not in early or healthy state")
        if in_session and disp:
            promote.append("Lower timeframe expansion begins at open — confirms directional drive")
    if toxic:
        prereqs.append(f"15m volatility is {vol_state} — opening FVG entry context unsafe")

    invalidation = [
        "Session closes or advances past ny_open — time-of-day gate expires",
        "15m volatility toxic or explosive — dangerous to enter FVG at open",
        "Opening FVG filled before the entry setup completes — imbalance resolved",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_opening_order_block(snap: dict, direction: str, score: int, raw_status: str):
    struct  = snap.get("structure",  {})
    vol     = snap.get("volatility", {})
    exp     = snap.get("expansion",  {})
    session = snap.get("session",    "")

    in_session = session == "ny_open"
    align      = struct.get("alignment", "neutral")
    vol_state  = vol.get("15m", {}).get("state", "")
    toxic      = vol_state in ("toxic", "explosive")
    exp_ok     = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["1m", "3m", "5m"]
    )

    prereqs = []
    gaps    = []
    promote = []

    if not in_session:
        prereqs.append(
            f"Session is '{session}' — opening order block requires ny_open session gate"
        )
        promote.append("Session advances to ny_open — unlocks the opening order block window")
    if align not in ("full", "strong"):
        gaps.append(
            f"Structure alignment is {align} — strong or full alignment adds up to 15 pts"
        )
        if in_session:
            promote.append("Structure alignment improves to strong or full — confirms directional opening bias")
    if not exp_ok:
        gaps.append("Lower timeframe expansion not yet begun — block not in delivery")
        if in_session and align in ("full", "strong"):
            promote.append("1m/3m/5m enters early expansion — confirms drive from the block at open")
    if toxic:
        prereqs.append(f"15m volatility is {vol_state} — opening order block context unsafe")

    invalidation = [
        "Session closes or advances past ny_open — time-of-day gate expires",
        "15m volatility toxic or explosive — dangerous to enter at open",
        "Price closes through the order block without reversing — block violated",
    ]
    return prereqs, gaps, promote, invalidation


def _readiness_range_break_retest(snap: dict, direction: str, score: int, raw_status: str):
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})

    was_range = struct.get("15m", {}).get("state") in ("range_bound", "neutral")
    bos       = any(struct.get(tf, {}).get("bos") for tf in _TFS)
    mss       = any(struct.get(tf, {}).get("mss") for tf in _TFS)
    ltf_exp   = any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in ["1m", "3m", "5m"]
    )

    prereqs = []
    gaps    = []
    promote = []

    if not was_range:
        prereqs.append(
            "15m structure not range-bound or neutral — range break context requires prior consolidation"
        )
        promote.append("15m structure consolidates to range_bound or neutral — establishes the range to break")
    if not bos:
        prereqs.append("Break of structure not confirmed — the range has not yet been breached")
        if was_range:
            promote.append("BOS confirmed — price breaks out of the established range")
    if not ltf_exp:
        gaps.append(
            "Lower timeframe expansion not active after break — retest timing premature"
        )
        if was_range and bos:
            promote.append("Lower timeframe enters early expansion after BOS — confirms break intent")
    if not mss:
        gaps.append("No MSS yet — retest of the broken level not yet structurally set up")
        if was_range and bos:
            promote.append("MSS confirms direction — price retests the broken level creating the entry point")

    invalidation = [
        "Price closes back inside the range — breakout failed, setup abandoned",
        "BOS occurs in the opposite direction — directional bias inverted",
        "Range expands without offering a retest — entry level never presented",
    ]
    return prereqs, gaps, promote, invalidation


_FAMILY_CHECKERS = {
    "fvg":                 _readiness_fvg,
    "ifvg":                _readiness_ifvg,
    "order_block":         _readiness_order_block,
    "breaker":             _readiness_breaker,
    "rejection_block":     _readiness_rejection_block,
    "ote_retracement":     _readiness_ote_retracement,
    "mss_retest":          _readiness_mss_retest,
    "ote_after_reclaim":   _readiness_ote_after_reclaim,
    "opening_fvg":         _readiness_opening_fvg,
    "opening_order_block": _readiness_opening_order_block,
    "range_break_retest":  _readiness_range_break_retest,
}


# ── Context score gaps (never prerequisites) ──────────────────────────────────

def _context_score_gaps(snapshot: dict) -> list:
    """Returns items that reduce the shared context score (0-20 pts)."""
    struct = snapshot.get("structure",  {})
    exp    = snapshot.get("expansion",  {})
    vol    = snapshot.get("volatility", {})
    mem    = snapshot.get("memory",     {})
    gaps   = []

    align = struct.get("alignment", "neutral")
    if align not in ("full", "strong"):
        gaps.append(
            f"MTF structure alignment is {align} — "
            "full or strong alignment adds up to 8 pts to context score"
        )

    if not any(
        exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
        for tf in _TFS
    ):
        gaps.append("No active expansion on any timeframe — expansion context score is zero")

    if vol.get("15m", {}).get("state") in ("toxic", "explosive"):
        gaps.append(
            "15m volatility toxic/explosive — volatility context score zeroed, "
            "entry timing critical"
        )

    if mem and mem.get("available"):
        g = mem.get("global") or {}
        trend = g.get("confidence_trend", "stable")
        if trend != "rising":
            gaps.append(
                f"Confidence trend is {trend} — rising trend required for full memory context score"
            )

    return gaps


# ── Public entry point ────────────────────────────────────────────────────────

def analyze_readiness(tool: str, snapshot: dict, score: int, raw_status: str) -> dict:
    """
    Phase 1K.1 — Tool Readiness Analysis.
    Returns prerequisites_missing, score_gaps, promotion_criteria, invalidation_criteria.
    raw_status is the score-only verdict (no risk override applied).
    """
    fam       = _family(tool)
    direction = "bullish" if tool.startswith("bullish_") else "bearish"
    checker   = _FAMILY_CHECKERS.get(fam)

    if checker is None:
        return {
            "next_status":           None,
            "prerequisites_missing": ["No readiness checker available for this tool family"],
            "score_gaps":            [],
            "promotion_criteria":    [],
            "invalidation_criteria": [],
        }

    prereqs, gaps, promote, invalidation = checker(snapshot, direction, score, raw_status)

    # Append context score gaps not already present in family-level gaps
    for item in _context_score_gaps(snapshot):
        if item not in gaps:
            gaps.append(item)

    next_status = _NEXT_STATUS.get(raw_status)

    # Nothing left to promote once already actionable
    if raw_status == "actionable":
        promote = []

    return {
        "next_status":           next_status,
        "prerequisites_missing": prereqs,
        "score_gaps":            gaps,
        "promotion_criteria":    promote,
        "invalidation_criteria": invalidation,
    }

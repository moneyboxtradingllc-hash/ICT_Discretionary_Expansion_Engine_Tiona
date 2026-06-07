"""
Phase 1Q — State Transition Engine.
Detects setup lifecycle events between consecutive scan snapshots.
Pure observation only. No execution. No orders.
"""

_QUAL_ORDER = {
    "elite":       4,
    "qualified":   3,
    "candidate":   2,
    "watchlist":   1,
    "no_trade":    0,
    "decay":      -1,
    "invalidated": -2,
}

_TOOL_ORDER = {
    "actionable": 3,
    "ready":      2,
    "forming":    1,
    "no_tool":    0,
}

_TRIG_ORDER = {
    "confirmed":          3,
    "retest_in_progress": 2,
    "waiting_for_retest": 1,
    "n/a":                0,
    "invalidated":       -1,
}

_DECAY_BARS_THRESHOLD = 5
_CONF_FALL_THRESHOLD  = 8


def _qual_rank(status: str) -> int:
    return _QUAL_ORDER.get((status or "no_trade").lower(), 0)


def _tool_rank(status: str) -> int:
    return _TOOL_ORDER.get((status or "no_tool").lower(), 0)


def _trig_rank(status: str) -> int:
    return _TRIG_ORDER.get((status or "n/a").lower(), 0)


def _get_qual_status(snapshot: dict) -> str:
    return (snapshot.get("qualification", {}).get("status") or "no_trade").lower()


def _get_tool_status(snapshot: dict) -> str:
    tb = snapshot.get("toolbox", {})
    return (tb.get("best_available_effective_status") or "no_tool").lower()


def _get_trigger_status(snapshot: dict) -> str:
    tb = snapshot.get("toolbox", {})
    preferred = tb.get("preferred_tool")
    candidates = tb.get("tool_candidates", [])
    if preferred:
        pref_c = next((c for c in candidates if c.get("tool") == preferred), {})
        tp = pref_c.get("trigger_prep", {})
        return (tp.get("effective_trigger_status") or "n/a").lower()
    return "n/a"


def _get_confidence(snapshot: dict) -> int:
    return snapshot.get("ai_context", {}).get("confidence_score") or 0


def _setup_lifecycle(
    qual: str,
    tool_status: str,
    trig_status: str,
    trade_allowed: bool,
    transition_type: str,
) -> str:
    if transition_type == "invalidation" or qual == "invalidated":
        return "invalidated"
    if qual == "decay":
        return "dormant"
    if qual == "no_trade":
        return "dormant"
    if qual == "watchlist":
        return "forming"
    if qual in ("candidate", "qualified", "elite"):
        if tool_status == "actionable" and trig_status in ("confirmed", "retest_in_progress"):
            return "actionable_candidate" if trade_allowed else "blocked_by_risk"
        if tool_status in ("ready", "actionable"):
            return "maturing"
        return "forming"
    return "dormant"


def analyze_transition(current: dict, previous: dict | None, bars_in_state: int = 1) -> dict:
    """
    Compare current snapshot to previous to detect state transitions.
    Returns a state_transition dict with full lifecycle context.
    bars_in_state is the count of consecutive scans at the current qual status.
    """
    cur_qual  = _get_qual_status(current)
    cur_tool  = _get_tool_status(current)
    cur_trig  = _get_trigger_status(current)
    cur_conf  = _get_confidence(current)
    trade_ok  = current.get("risk", {}).get("trade_allowed", False)

    warnings: list[str] = []

    if previous is None:
        transition      = "new_setup"
        transition_type = "new_setup"
        prev_qual       = "none"
        upgrade         = cur_qual not in ("no_trade", "decay", "invalidated")
        downgrade       = False
        invalidated     = cur_qual == "invalidated"
        reason          = f"First scan -- {cur_qual}"
    else:
        prev_qual   = _get_qual_status(previous)
        prev_conf   = _get_confidence(previous)
        prev_tool   = _get_tool_status(previous)
        prev_trig   = _get_trigger_status(previous)

        cur_rank    = _qual_rank(cur_qual)
        prev_rank   = _qual_rank(prev_qual)
        cur_tr      = _tool_rank(cur_tool)
        prev_tr     = _tool_rank(prev_tool)
        cur_trig_r  = _trig_rank(cur_trig)
        prev_trig_r = _trig_rank(prev_trig)

        upgrade     = cur_rank > prev_rank
        downgrade   = cur_rank < prev_rank and prev_rank > 0
        invalidated = cur_qual == "invalidated"
        conf_fall   = (prev_conf - cur_conf) >= _CONF_FALL_THRESHOLD

        if invalidated:
            transition_type = "invalidation"
            transition      = "invalidation"
            reason          = f"Qualification invalidated: {prev_qual} -> {cur_qual}"
        elif cur_qual == "decay" or (
            prev_qual not in ("no_trade", "decay", "invalidated")
            and cur_qual == "no_trade"
            and bars_in_state >= _DECAY_BARS_THRESHOLD
        ):
            transition_type = "decay"
            transition      = "decay"
            reason          = f"Setup decaying: {prev_qual} -> {cur_qual} after {bars_in_state} bars"
        elif upgrade:
            transition_type = "upgrade"
            transition      = "upgrade"
            reason          = f"Qualification upgraded: {prev_qual} -> {cur_qual}"
        elif downgrade:
            transition_type = "downgrade"
            transition      = "downgrade"
            reason          = f"Qualification degraded: {prev_qual} -> {cur_qual}"
        else:
            # Same qual level — check tool/trigger momentum for sub-transitions
            if cur_tr > prev_tr:
                transition_type = "upgrade"
                transition      = "upgrade"
                reason          = f"Tool readiness improved: {prev_tool} -> {cur_tool}"
            elif cur_trig_r > prev_trig_r:
                transition_type = "upgrade"
                transition      = "upgrade"
                reason          = f"Trigger progressed: {prev_trig} -> {cur_trig}"
            elif cur_trig_r < prev_trig_r and prev_trig_r > 0:
                transition_type = "downgrade"
                transition      = "downgrade"
                reason          = f"Trigger regressed: {prev_trig} -> {cur_trig}"
            else:
                transition_type = "stable"
                transition      = "stable"
                reason          = f"No change: {cur_qual}"

        if conf_fall and transition_type not in ("decay", "invalidation"):
            warnings.append(
                f"Confidence fell {prev_conf - cur_conf} pts ({prev_conf}->{cur_conf})"
            )
        if (
            bars_in_state >= _DECAY_BARS_THRESHOLD
            and cur_qual not in ("no_trade", "decay", "invalidated")
        ):
            warnings.append(
                f"Setup in same state for {bars_in_state} bars -- watch for staleness"
            )

    if   transition_type in ("upgrade",):              setup_momentum = "improving"
    elif transition_type in ("downgrade",):            setup_momentum = "deteriorating"
    elif transition_type in ("decay", "invalidation"): setup_momentum = "failing"
    elif transition_type == "new_setup":               setup_momentum = "initializing"
    else:                                              setup_momentum = "holding"

    lifecycle = _setup_lifecycle(cur_qual, cur_tool, cur_trig, trade_ok, transition_type)

    return {
        "previous_state":     prev_qual,
        "current_state":      cur_qual,
        "transition":         transition,
        "transition_type":    transition_type,
        "setup_momentum":     setup_momentum,
        "setup_lifecycle":    lifecycle,
        "bars_in_state":      bars_in_state,
        "upgrade_detected":   upgrade,
        "downgrade_detected": downgrade,
        "invalidated":        invalidated,
        "reason":             reason,
        "warnings":           warnings,
    }

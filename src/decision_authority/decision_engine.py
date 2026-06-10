"""
Phase 1T — Decision Authority Layer.
Combines all prior layers into a single final decision.

trade_authorized is ALWAYS False in Phase 1T.
This layer is decision readiness only — no execution, no orders,
no broker actions, no paper trades, no TradingClient.
"""

_QUAL_ACTIVE = frozenset({"candidate", "qualified", "elite"})
_QUAL_WEAK   = frozenset({"watchlist"})
_TOOL_READY  = frozenset({"ready", "actionable"})
_TRIG_ACTIVE = frozenset({"waiting_for_retest", "retest_in_progress", "confirmation_needed"})
_TRIG_FULL   = frozenset({"confirmed"})

# Phase 5F.4 — decision state rename.
# "ready_for_execution" replaces the legacy "trade_authorized_false" GO-ready state.
READY_FOR_EXECUTION = "ready_for_execution"
_LEGACY_READY       = "trade_authorized_false"


def normalize_decision(decision: str | None) -> str:
    """
    Phase 5F.4 — Normalize a decision string.
    Maps the legacy 'trade_authorized_false' label (old snapshots, old journals)
    to 'ready_for_execution'. All other values pass through lowercased.
    """
    d = (decision or "stand_down").lower().strip()
    return READY_FOR_EXECUTION if d == _LEGACY_READY else d


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def _raw_tool_status(snapshot: dict) -> str:
    tb     = snapshot.get("toolbox", {})
    pref_c = _preferred_candidate(snapshot)
    return (
        pref_c.get("raw_status")
        or tb.get("best_available_raw_status")
        or "no_tool"
    ).lower()


def _trigger_raw(snapshot: dict) -> str:
    pref_c = _preferred_candidate(snapshot)
    return (pref_c.get("trigger_prep", {}).get("raw_trigger_status") or "n/a").lower()


def _execution_ready(snapshot: dict) -> bool:
    pref_c = _preferred_candidate(snapshot)
    return bool(pref_c.get("trigger_prep", {}).get("execution_ready", False))


def _lifecycle_phase(snapshot: dict) -> str:
    sl = snapshot.get("setup_lifecycle", {})
    if sl.get("active"):
        return (sl.get("current_phase") or "forming").lower()
    return "dormant"


def _debate_stance(snapshot: dict) -> str:
    return (
        snapshot.get("ai_debate", {})
               .get("final_verdict", {})
               .get("recommended_stance", "stand_down")
    ).lower()


def _determine_direction(snapshot: dict) -> str:
    """
    Direction priority: active setup > playbook > AI discretionary > debate dominant.
    Returns "bullish", "bearish", or "neutral".
    """
    sl = snapshot.get("setup_lifecycle", {})
    if sl.get("active"):
        d = (sl.get("direction") or "neutral").lower()
        if d in ("bullish", "bearish"):
            return d

    pb_dir = (snapshot.get("playbook", {}).get("direction") or "neutral").lower()
    if pb_dir in ("bullish", "bearish"):
        return pb_dir

    ai_dir = (snapshot.get("ai_discretionary", {}).get("ai_direction") or "neutral").lower()
    if ai_dir in ("bullish", "bearish"):
        return ai_dir

    dom = (
        snapshot.get("ai_debate", {})
               .get("final_verdict", {})
               .get("dominant_thesis", "neutral")
    ).lower()
    if dom in ("bullish", "bearish"):
        return dom

    return "neutral"


def _confidence(snapshot: dict) -> int:
    return snapshot.get("confidence_fusion", {}).get("combined_confidence") or 0


# ── Core decision selection ───────────────────────────────────────────────────

def _select_decision(snapshot: dict, direction: str) -> str:
    qual_status    = (snapshot.get("qualification", {}).get("status") or "no_trade").lower()
    pb_name        = (snapshot.get("playbook", {}).get("selected_playbook") or "no_playbook").lower()
    trade_allowed  = snapshot.get("risk", {}).get("trade_allowed", False)
    st_invalidated = snapshot.get("state_transition", {}).get("invalidated", False)
    lc_phase       = _lifecycle_phase(snapshot)
    debate         = _debate_stance(snapshot)
    raw_tool       = _raw_tool_status(snapshot)
    trig_raw       = _trigger_raw(snapshot)
    exec_rdy       = _execution_ready(snapshot)

    # ── Hard stand_down conditions ─────────────────────────────────────────
    if st_invalidated or lc_phase == "invalidated":
        return "stand_down"
    if qual_status == "no_trade":
        return "stand_down"
    if pb_name == "no_playbook":
        return "stand_down"
    # Debate pushes to stand_down on weak qualification
    if debate == "stand_down" and qual_status in _QUAL_WEAK:
        return "stand_down"

    # ── Risk blocked → monitor (setup exists but gated) ────────────────────
    if not trade_allowed:
        return "monitor"

    # ── Risk allowed: evaluate direction and readiness ─────────────────────
    if direction not in ("bullish", "bearish"):
        return "monitor"

    if qual_status not in _QUAL_ACTIVE:
        return "monitor"

    # All execution conditions aligned — execution gate makes the final call
    if exec_rdy and raw_tool in _TOOL_READY:
        return READY_FOR_EXECUTION

    # Pre-execution preparation: tool ready + trigger approaching
    if raw_tool in _TOOL_READY and trig_raw in (_TRIG_ACTIVE | _TRIG_FULL):
        return "prepare_long" if direction == "bullish" else "prepare_short"

    return "monitor"


# ── Reason ────────────────────────────────────────────────────────────────────

def _build_reason(snapshot: dict, decision: str, direction: str) -> str:
    qual_status   = (snapshot.get("qualification", {}).get("status") or "no_trade").lower()
    pb_name       = (snapshot.get("playbook", {}).get("selected_playbook") or "no_playbook").lower()
    trade_allowed = snapshot.get("risk", {}).get("trade_allowed", False)
    st_inv        = snapshot.get("state_transition", {}).get("invalidated", False)
    lc_phase      = _lifecycle_phase(snapshot)
    fv            = snapshot.get("ai_debate", {}).get("final_verdict", {})
    dom_score     = fv.get("verdict_confidence", 0)

    if decision == "stand_down":
        if st_inv or lc_phase == "invalidated":
            return "Setup lifecycle is invalidated — standing down."
        if qual_status == "no_trade":
            return "Qualification is no_trade — no opportunity identified."
        if pb_name == "no_playbook":
            return "No active playbook — standing down."
        return "Neutral conditions dominant — no directional conviction."

    if decision == "monitor":
        if not trade_allowed:
            return (
                f"{direction.capitalize()} thesis dominant at {dom_score} "
                "but Risk Governor remains blocked."
            )
        return (
            f"Setup {lc_phase} in {direction} direction — "
            "conditions not yet sufficient for entry preparation."
        )

    if decision == "prepare_long":
        return (
            "Bullish setup conditions met — prepared for long trigger confirmation. "
            "Awaiting execution_ready signal."
        )

    if decision == "prepare_short":
        return (
            "Bearish setup conditions met — prepared for short trigger confirmation. "
            "Awaiting execution_ready signal."
        )

    if decision == READY_FOR_EXECUTION:
        return (
            f"All {direction} execution conditions aligned — "
            "ready for execution (final authorization at execution gate)."
        )

    return "Decision indeterminate from current conditions."


# ── Blocking and supporting factors ──────────────────────────────────────────

def _collect_blocking(snapshot: dict) -> list[str]:
    factors = []
    risk   = snapshot.get("risk", {})
    qual   = snapshot.get("qualification", {})
    tb     = snapshot.get("toolbox", {})
    pref_c = _preferred_candidate(snapshot)
    sl     = snapshot.get("setup_lifecycle", {})

    qs       = (qual.get("status") or "no_trade").lower()
    pb_name  = (snapshot.get("playbook", {}).get("selected_playbook") or "no_playbook").lower()
    raw_tool = _raw_tool_status(snapshot)
    trig_raw = _trigger_raw(snapshot)
    lc_phase = _lifecycle_phase(snapshot)

    if not risk.get("trade_allowed", False):
        factors.append(f"risk blocked ({risk.get('risk_tier', 'blocked')})")
    if qs in ("no_trade", "watchlist"):
        factors.append(f"qualification {qs}")
    if pb_name == "no_playbook":
        factors.append("no active playbook")
    if raw_tool not in _TOOL_READY:
        factors.append(f"tool readiness {raw_tool}")
    if trig_raw not in (_TRIG_ACTIVE | _TRIG_FULL) and trig_raw != "n/a":
        factors.append(f"trigger {trig_raw.replace('_', ' ')}")
    elif trig_raw == "n/a":
        factors.append("no active trigger")
    if lc_phase in ("decaying", "invalidated"):
        factors.append(f"setup lifecycle {lc_phase}")

    return factors[:5]


def _collect_supporting(snapshot: dict) -> list[str]:
    factors  = []
    qual     = snapshot.get("qualification", {})
    pb       = snapshot.get("playbook", {})
    tb       = snapshot.get("toolbox", {})
    sl       = snapshot.get("setup_lifecycle", {})
    fv       = snapshot.get("ai_debate", {}).get("final_verdict", {})
    pref_c   = _preferred_candidate(snapshot)

    qs       = (qual.get("status") or "no_trade").lower()
    pb_name  = (pb.get("selected_playbook") or "no_playbook").lower()
    pb_conf  = pb.get("playbook_confidence", 0)
    dom      = (fv.get("dominant_thesis") or "neutral").lower()
    dom_conf = fv.get("verdict_confidence", 0)
    raw_tool = _raw_tool_status(snapshot)
    trig_raw = _trigger_raw(snapshot)

    if dom in ("bullish", "bearish"):
        factors.append(f"{dom} thesis dominant at {dom_conf}")
    if qs in _QUAL_ACTIVE:
        factors.append(f"qualification {qs}")
    if pb_name not in ("no_playbook", ""):
        pb_str = pb_name.replace("_", " ")
        factors.append(f"playbook {pb_str} (confidence {pb_conf})")
    if raw_tool in _TOOL_READY:
        pref = (tb.get("preferred_tool") or "tool").replace("_", " ")
        factors.append(f"preferred tool {pref} raw {raw_tool}")
    if trig_raw in (_TRIG_ACTIVE | _TRIG_FULL):
        factors.append(f"trigger {trig_raw.replace('_', ' ')}")
    if sl.get("active"):
        phase = sl.get("current_phase", "forming")
        if phase not in ("decaying", "invalidated"):
            factors.append(f"setup lifecycle {phase}")

    return factors[:5]


# ── Required before trade ─────────────────────────────────────────────────────

def _required_before_trade(snapshot: dict, decision: str) -> list[str]:
    reqs   = []
    risk   = snapshot.get("risk", {})
    qual   = snapshot.get("qualification", {})
    pref_c = _preferred_candidate(snapshot)

    qs       = (qual.get("status") or "no_trade").lower()
    raw_tool = _raw_tool_status(snapshot)
    trig_raw = _trigger_raw(snapshot)
    exec_rdy = _execution_ready(snapshot)

    if not risk.get("trade_allowed", False):
        reqs.append("Risk Governor must allow trading")
    if qs in ("no_trade", "watchlist"):
        reqs.append(f"Qualification must upgrade from {qs}")
    elif qs == "candidate":
        reqs.append("Qualification should confirm to qualified for stronger conviction")
    if raw_tool not in _TOOL_READY:
        reqs.append(f"Tool readiness must reach ready or actionable (currently {raw_tool})")
    if trig_raw not in (_TRIG_ACTIVE | _TRIG_FULL):
        reqs.append("Trigger must become active (waiting_for_retest or retest_in_progress)")
    if not exec_rdy:
        reqs.append("execution_ready must be true for trade authorization")

    return reqs[:5]


# ── Warnings ──────────────────────────────────────────────────────────────────

def _collect_warnings(snapshot: dict) -> list[str]:
    warns: list[str] = []

    for w in snapshot.get("state_transition", {}).get("warnings", []):
        warns.append(w)

    sl = snapshot.get("setup_lifecycle", {})
    if sl.get("active"):
        for w in sl.get("warnings", []):
            if w not in warns:
                warns.append(w)

    ai_conf = snapshot.get("ai_discretionary", {}).get("ai_confidence", 0)
    if ai_conf < 25:
        msg = f"AI confidence very low ({ai_conf}) — minimal conviction"
        if msg not in warns:
            warns.append(msg)

    return warns[:4]


# ── Public entry point ────────────────────────────────────────────────────────

def make_decision(snapshot: dict) -> dict:
    """
    Phase 1T — Decision Authority Engine.
    Reads all prior layers from the assembled snapshot and returns a single decision.

    trade_authorized is ALWAYS False — this layer is observation and readiness only.
    No execution. No orders. No broker actions.
    """
    direction  = _determine_direction(snapshot)
    confidence = _confidence(snapshot)
    decision   = _select_decision(snapshot, direction)
    reason     = _build_reason(snapshot, decision, direction)
    blocking   = _collect_blocking(snapshot)
    supporting = _collect_supporting(snapshot)
    required   = _required_before_trade(snapshot, decision)
    warnings   = _collect_warnings(snapshot)

    return {
        "decision":              decision,
        "trade_authorized":      False,   # Phase 1T: always false
        "direction":             direction,
        "confidence":            confidence,
        "reason":                reason,
        "required_before_trade": required,
        "blocking_factors":      blocking,
        "supporting_factors":    supporting,
        "warnings":              warnings,
    }

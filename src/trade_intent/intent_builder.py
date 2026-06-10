"""
Phase 1V -- Trade Intent Builder.

Answers: "If execution were eventually allowed, what trade would the bot be preparing?"
This layer does NOT place trades, does NOT route orders, does NOT interact with any broker.
No execution. No orders. No paper trades. No stop losses. No TradingClient.
"""


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def _build_entry_zone(pref_c: dict) -> dict | None:
    pl = pref_c.get("price_level", {})
    if not pl or (pl.get("level_type") or "no_zone") == "no_zone":
        return None
    zone_low  = pl.get("zone_low")
    zone_high = pl.get("zone_high")
    if zone_low is None or zone_high is None:
        return None
    midpoint = round((zone_low + zone_high) / 2, 4)
    return {
        "zone_low":      zone_low,
        "zone_high":     zone_high,
        "midpoint":      midpoint,
        "current_price": pl.get("current_price"),
        "price_relation": pl.get("price_relation", "unknown"),
    }


def _trigger_status(pref_c: dict) -> str:
    tp = pref_c.get("trigger_prep", {})
    return (
        tp.get("effective_trigger_status")
        or tp.get("trigger_status")
        or "n/a"
    ).lower()


def _collect_required(snapshot: dict, pref_c: dict, eg: dict) -> list[str]:
    reqs: list[str] = []
    if not eg.get("allow_execution", False):
        reqs.append("Execution gate must authorize")
    tp = pref_c.get("trigger_prep", {})
    if not tp.get("execution_ready", False):
        reqs.append("Trigger must become execution_ready")
    if not snapshot.get("risk", {}).get("trade_allowed", False):
        reqs.append("Risk must remain approved")
    pl = pref_c.get("price_level", {})
    if not pl or (pl.get("level_type") or "no_zone") == "no_zone":
        reqs.append("Price zone must be identified")
    return reqs[:4]


def _collect_warnings(snapshot: dict, eg: dict) -> list[str]:
    seen: set[str] = set()
    warns: list[str] = []
    for w in eg.get("warnings", []):
        if w not in seen:
            seen.add(w)
            warns.append(w)
    for w in snapshot.get("decision_authority", {}).get("warnings", []):
        if w not in seen:
            seen.add(w)
            warns.append(w)
    return warns[:3]


def _stand_down_reason(decision: str, direction: str, debate_stance: str,
                        qual_status: str, risk: dict) -> str:
    if qual_status == "no_trade":
        return "Qualification no_trade -- standing down."
    if debate_stance == "stand_down":
        return "AI debate recommends stand_down -- no trade intent."
    if not risk.get("trade_allowed", False):
        return (
            f"{direction.capitalize()} setup present but Risk Governor blocked "
            "-- monitoring only."
        )
    return "Conditions insufficient for directional intent -- standing down."


def _active_reason(intent_type: str, direction: str, tool: str,
                   trig: str, eg: dict) -> str:
    gate  = (eg.get("gate_status") or "locked").upper()
    allow = eg.get("allow_execution", False)
    would = eg.get("would_authorize_if_enabled", False)
    if would:
        return (
            f"{direction.capitalize()} {intent_type} setup prepared using {tool}. "
            "All authorization checks pass but execution is globally disabled."
        )
    return (
        f"{direction.capitalize()} {intent_type} setup forming using {tool}. "
        f"Execution gate {gate}. Execution allowed {str(allow).lower()}. "
        f"Trigger: {trig.replace('_', ' ')}."
    )


# ── Output assembler ──────────────────────────────────────────────────────────

def _make_result(
    intent_created:  bool,
    intent_type:     str,
    symbol:          str,
    direction:       str,
    playbook:        str,
    preferred_tool,
    entry_zone,
    trig:            str,
    decision:        str,
    eg:              dict,
    reason:          str,
    required:        list[str],
    warnings:        list[str],
) -> dict:
    return {
        "intent_created":             intent_created,
        "intent_type":                intent_type,
        "symbol":                     symbol,
        "direction":                  direction,
        "playbook":                   playbook,
        "preferred_tool":             preferred_tool,
        "entry_zone":                 entry_zone,
        "trigger_status":             trig,
        "decision":                   decision,
        "execution_allowed":          eg.get("allow_execution", False),
        "would_authorize_if_enabled": eg.get("would_authorize_if_enabled", False),
        "reason":                     reason,
        "required_before_execution":  required,
        "warnings":                   warnings,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def build_intent(snapshot: dict, symbol: str) -> dict:
    """
    Phase 1V -- Trade Intent Builder.
    Returns a structured intent dict. Does not place orders or interact with any broker.
    """
    da    = snapshot.get("decision_authority", {})
    eg    = snapshot.get("execution_gate", {})
    sl    = snapshot.get("setup_lifecycle", {})
    qual  = snapshot.get("qualification", {})
    risk  = snapshot.get("risk", {})
    tb    = snapshot.get("toolbox", {})
    debate = snapshot.get("ai_debate", {})

    # Phase 5F.4: normalize legacy 'trade_authorized_false' to 'ready_for_execution'
    from decision_authority.decision_engine import normalize_decision
    decision       = normalize_decision(da.get("decision"))
    direction      = (da.get("direction") or "neutral").lower()
    playbook       = (snapshot.get("playbook", {}).get("selected_playbook") or "no_playbook").lower()
    preferred_tool = tb.get("preferred_tool") or None
    qual_status    = (qual.get("status") or "no_trade").lower()
    gate_status    = (eg.get("gate_status") or "locked").lower()
    setup_active   = bool(sl.get("active"))
    lc_phase       = (sl.get("current_phase") or "dormant").lower() if setup_active else "dormant"
    setup_inv      = setup_active and lc_phase == "invalidated"
    debate_stance  = (
        debate.get("final_verdict", {}).get("recommended_stance") or "stand_down"
    ).lower()

    pref_c     = _preferred_candidate(snapshot)
    trig       = _trigger_status(pref_c)
    entry_zone = _build_entry_zone(pref_c)
    required   = _collect_required(snapshot, pref_c, eg)
    warnings   = _collect_warnings(snapshot, eg)

    # ── Hard "none" conditions ────────────────────────────────────────────────
    if (
        decision == "stand_down"
        or not setup_active
        or setup_inv
        or playbook == "no_playbook"
        or not preferred_tool
        or gate_status == "invalidated"
    ):
        if decision == "stand_down":
            reason = "Decision authority stands down -- no trade intent."
        elif not setup_active:
            reason = "No active setup -- no trade intent."
        elif setup_inv:
            reason = "Setup is invalidated -- no trade intent."
        elif gate_status == "invalidated":
            reason = "Execution gate invalidated -- no trade intent."
        elif playbook == "no_playbook":
            reason = "No active playbook -- no trade intent."
        else:
            reason = "No preferred tool -- no trade intent."

        return _make_result(
            False, "none", symbol, direction, playbook,
            preferred_tool, None, trig, decision, eg,
            reason, required, warnings,
        )

    # ── Stand-down intent (setup exists but blocked) ──────────────────────────
    is_stand_down = (
        (decision == "monitor" and not risk.get("trade_allowed", False))
        or debate_stance == "stand_down"
        or qual_status == "no_trade"
    )
    if is_stand_down:
        reason = _stand_down_reason(decision, direction, debate_stance, qual_status, risk)
        return _make_result(
            False, "stand_down", symbol, direction, playbook,
            preferred_tool, entry_zone, trig, decision, eg,
            reason, required, warnings,
        )

    # ── Long intent ───────────────────────────────────────────────────────────
    long_intent = (
        decision in ("prepare_long", "ready_for_execution")
        and direction == "bullish"
        and preferred_tool.startswith("bullish_")
        and setup_active
        and entry_zone is not None
    )
    if long_intent:
        reason = _active_reason("long", direction, preferred_tool, trig, eg)
        return _make_result(
            True, "long", symbol, direction, playbook,
            preferred_tool, entry_zone, trig, decision, eg,
            reason, required, warnings,
        )

    # ── Short intent ──────────────────────────────────────────────────────────
    short_intent = (
        decision in ("prepare_short", "ready_for_execution")
        and direction == "bearish"
        and preferred_tool.startswith("bearish_")
        and setup_active
        and entry_zone is not None
    )
    if short_intent:
        reason = _active_reason("short", direction, preferred_tool, trig, eg)
        return _make_result(
            True, "short", symbol, direction, playbook,
            preferred_tool, entry_zone, trig, decision, eg,
            reason, required, warnings,
        )

    # ── Fallback: all conditions partially met but no clean fit ───────────────
    reason = (
        f"{direction.capitalize()} setup forming ({decision}) "
        "but conditions not sufficient for intent creation."
    )
    return _make_result(
        False, "stand_down", symbol, direction, playbook,
        preferred_tool, entry_zone, trig, decision, eg,
        reason, required, warnings,
    )

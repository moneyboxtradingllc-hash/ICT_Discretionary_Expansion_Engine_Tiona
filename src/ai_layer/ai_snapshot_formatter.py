"""
AI Snapshot Formatter — compresses the full snapshot into a compact, AI-readable text summary.
No API calls. Pure text generation from the snapshot dict.
"""


def _structure_line(tf: str, structure: dict) -> str:
    s = structure.get(tf, {})
    state = s.get("state", "unknown")
    bias  = s.get("bias", "neutral")
    flags = []
    if s.get("bos"):
        flags.append("BOS")
    if s.get("mss"):
        flags.append("MSS")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    return f"{tf} structure: {state}, bias {bias}{flag_str}."


def _liquidity_lines(liquidity: dict) -> list:
    lines = []
    for tf in ["15m", "5m", "3m", "1m"]:
        liq = liquidity.get(tf, {})
        if liq.get("sweep_detected"):
            direction = liq.get("sweep_direction", "unknown")
            reclaim   = "reclaim confirmed" if liq.get("reclaim_detected") else "no reclaim"
            lines.append(f"Liquidity sweep {direction} on {tf} — {reclaim}.")
        if liq.get("failed_breakout"):
            lines.append(f"Failed breakout on {tf}.")
    return lines


def _po3_line(po3: dict) -> str:
    tfs    = ["15m", "5m", "3m", "1m"]
    phases = ", ".join(f"{tf} {po3.get(tf, {}).get('phase', 'no_phase')}" for tf in tfs)
    align  = po3.get("alignment", "unknown")
    return f"PO3: {phases}. Alignment: {align}."


def _entry_prep_line(toolbox: dict) -> str:
    """One-line entry prep summary for the preferred tool."""
    preferred = toolbox.get("preferred_tool")
    if not preferred:
        return ""
    candidates = toolbox.get("tool_candidates", [])
    c = next((x for x in candidates if x["tool"] == preferred), {})
    pl = c.get("price_level", {})
    tp = c.get("trigger_prep", {})

    level_type = pl.get("level_type", "no_zone")
    if level_type == "no_zone":
        return f"Entry Prep: {preferred} — no price zone identified."

    zl      = pl.get("zone_low")
    zh      = pl.get("zone_high")
    current = pl.get("current_price")
    dist    = pl.get("distance_to_zone")
    rel     = pl.get("price_relation", "unknown")
    t_stat  = tp.get("effective_trigger_status", tp.get("trigger_status", "no_trigger"))
    ex_rdy  = tp.get("execution_ready", False)

    zone_str = f"zone {zl}-{zh}" if zl is not None else "zone unknown"
    rel_str  = rel.replace("_", " ")

    if dist is not None and dist > 0:
        rel_desc = f"current price {current} is {rel_str} by {dist} pts"
    elif dist == 0:
        rel_desc = f"current price {current} is inside zone"
    else:
        rel_desc = f"current price {current} ({rel_str})"

    exec_str = (
        "Execution ready." if ex_rdy
        else f"Execution not ready — {t_stat.replace('_', ' ')}."
    )

    return f"Entry Prep: {preferred} {zone_str}. {rel_desc}. {exec_str}"


def _toolbox_line(toolbox: dict) -> str:
    if not toolbox:
        return ""
    preferred = toolbox.get("preferred_tool")
    if not preferred:
        status = toolbox.get("toolbox_status", "no_tool")
        return f"Toolbox: {status}."

    candidates   = toolbox.get("tool_candidates", [])
    preferred_c  = next((c for c in candidates if c["tool"] == preferred), {})
    raw_status   = preferred_c.get("raw_status",       "unknown")
    eff_status   = preferred_c.get("effective_status", toolbox.get("toolbox_status", "unknown"))
    confidence   = toolbox.get("tool_confidence", 0)
    alternatives = [c["tool"] for c in candidates if c["tool"] != preferred]

    if eff_status == "blocked_by_risk" and raw_status != "blocked_by_risk":
        line = (
            f"Toolbox: {preferred} earned {raw_status.upper()} ({confidence}). "
            f"Risk Governor reduced effective status to BLOCKED_BY_RISK."
        )
    else:
        line = (
            f"Toolbox: preferred tool {preferred}, "
            f"confidence {confidence}, status {eff_status}."
        )

    if alternatives:
        line += f" Valid alternatives: {', '.join(alternatives)}."
    return line


def _risk_line(risk: dict) -> str:
    if not risk:
        return ""
    allowed    = "ALLOWED" if risk.get("trade_allowed") else "BLOCKED"
    status     = risk.get("governor_status", "unknown").upper()
    tier       = risk.get("risk_tier",       "unknown")
    multiplier = risk.get("risk_multiplier", 0.0)
    authority  = risk.get("authority_reason", "n/a")
    blocks     = risk.get("blocks", [])
    line = (
        f"Risk Governor: {allowed} ({status}, {tier}, {multiplier}x). "
        f"Authority: {authority}."
    )
    if blocks:
        line += f" Blocks: {'; '.join(blocks)}."
    return line


def _playbook_line(pb: dict) -> str:
    if not pb or pb.get("selected_playbook") == "no_playbook":
        return "Playbook: NO_PLAYBOOK."
    name      = pb.get("selected_playbook", "unknown").upper()
    status    = pb.get("status", "unknown").upper()
    direction = pb.get("direction", "unknown")
    conf      = pb.get("playbook_confidence", 0)
    tools     = pb.get("eligible_tools", [])
    tools_str = ", ".join(tools) if tools else "none"
    return (
        f"Playbook: {name}, status {status}, direction {direction}, confidence {conf}. "
        f"Eligible tools: {tools_str}."
    )


def _qualification_line(qual: dict) -> str:
    if not qual:
        return ""
    status  = qual.get("status",            "unknown").upper()
    grade   = qual.get("grade",             "?")
    dir_    = qual.get("direction",          "unknown")
    score   = qual.get("opportunity_score",  0)
    driver  = qual.get("primary_driver",    "n/a")
    return (
        f"Qualification: {status} ({grade}). "
        f"Direction: {dir_}. "
        f"Opportunity Score: {score}. "
        f"Primary driver: {driver}."
    )


def _memory_line(memory: dict) -> str:
    if not memory or not memory.get("available"):
        return "Memory: no prior snapshots available."

    g   = memory.get("global",     {}) or {}
    tfs = memory.get("timeframes", {}) or {}
    parts = []

    # Confidence trend
    trend     = g.get("confidence_trend", "stable")
    delta     = g.get("confidence_delta", 0)
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    p_tier    = g.get("previous_confidence_tier", "")
    c_tier    = g.get("current_confidence_tier", "")

    if trend in ("rising", "falling"):
        parts.append(f"confidence {trend} {delta_str} ({p_tier} → {c_tier})")
    else:
        parts.append(f"confidence stable at {g.get('current_confidence_score', 0)} ({c_tier})")

    # Narrative shift
    if g.get("narrative_changed"):
        parts.append(
            f"narrative: {g.get('previous_market_narrative', '?')} → "
            f"{g.get('current_market_narrative', '?')}"
        )

    # PO3 phase changes and sustained phases
    for tf in ["15m", "5m", "3m", "1m"]:
        tf_m  = tfs.get(tf, {})
        count = tf_m.get("po3_stability_count", 0)
        if tf_m.get("po3_phase_changed"):
            parts.append(
                f"{tf} PO3: {tf_m.get('previous_po3_phase', '?')} → "
                f"{tf_m.get('current_po3_phase', '?')}"
            )
        elif count >= 3:
            parts.append(f"{tf} PO3 held {tf_m.get('stable_po3_phase', '?')} x{count}")

    return "Memory: " + "; ".join(parts) + "."


def _debate_line(ai_debate: dict) -> str:
    """One-line AI debate summary for the snapshot summary string."""
    if not ai_debate or not ai_debate.get("enabled"):
        return ""
    bull    = ai_debate.get("bullish_thesis",  {}).get("case_strength", 0)
    bear    = ai_debate.get("bearish_thesis",  {}).get("case_strength", 0)
    neutral = ai_debate.get("neutral_thesis",  {}).get("case_strength", 0)
    verdict = ai_debate.get("final_verdict",   {})
    stance  = (verdict.get("recommended_stance") or "stand_down").upper()
    dom     = verdict.get("dominant_thesis", "neutral")
    reason  = verdict.get("reason", "")
    return (
        f"AI Debate: {dom} thesis dominant at {max(bull, bear, neutral)}. "
        f"Verdict: {stance.lower()}. Reason: {reason}"
    )


def _discretionary_line(ai_disc: dict, fusion: dict) -> str:
    """Compact single-line AI discretionary summary for the snapshot summary string."""
    if not ai_disc:
        return ""

    direction  = ai_disc.get("ai_direction",  "neutral")
    confidence = ai_disc.get("ai_confidence",  0)
    thesis     = ai_disc.get("primary_thesis", "")
    concerns   = ai_disc.get("concerns",       [])
    missing    = ai_disc.get("missing_evidence", [])
    scenario   = ai_disc.get("preferred_scenario", "")
    agree_pb   = ai_disc.get("agreement_with_playbook", True)
    agree_risk = ai_disc.get("agreement_with_risk",     True)

    mech     = fusion.get("mechanical_score",    0)
    combined = fusion.get("combined_confidence", 0)
    fstatus  = fusion.get("fusion_status",       "unknown")

    parts = [
        f"AI Direction: {direction}.",
        f"AI Confidence: {confidence}.",
    ]

    if not agree_pb:
        parts.append("AI DISAGREES with playbook direction.")
    if not agree_risk:
        parts.append("AI DISAGREES with Risk Governor assessment.")

    if thesis:
        parts.append(f"Primary Thesis: {thesis}")
    if missing:
        parts.append(f"Missing Evidence: {missing[0]}")
    if concerns:
        parts.append(f"Concern: {concerns[0]}")
    if scenario:
        parts.append(f"Preferred Scenario: {scenario}")

    parts.append(
        f"Fusion: {fstatus.replace('_', ' ').title()}. "
        f"Mechanical {mech}, AI {confidence}, Combined {combined}."
    )

    return " ".join(parts)


def format_experience_line(exp: dict) -> str:
    """One-line experience intelligence summary. OBSERVE_ONLY — never influences decisions."""
    if not exp or not exp.get("experience_enabled"):
        return ""
    n     = exp.get("sample_size",  0)
    wr    = exp.get("win_rate")
    avg_r = exp.get("average_r")

    if n == 0 or n < 20:
        return f"Experience: {n} setup(s) | Insufficient Sample | AUTHORITY=OBSERVE_ONLY"

    parts = [f"{n} setups"]
    if wr is not None:
        parts.append(f"WR {wr:.0f}%")
    if avg_r is not None:
        sign = "+" if avg_r >= 0 else ""
        parts.append(f"Avg {sign}{avg_r:.1f}R")

    return "Experience: " + " | ".join(parts) + " | AUTHORITY=OBSERVE_ONLY"


def format_experience_link_line(exp: dict) -> str:
    """One-line linkage stats. OBSERVE_ONLY — never influences decisions."""
    if not exp or not exp.get("experience_enabled"):
        return ""
    linked   = exp.get("linked_trade_count",    0)
    closed   = exp.get("closed_trade_count",    0)
    unlinked = exp.get("unlinked_intent_count", 0)
    quality  = exp.get("linkage_quality",       "none")
    if linked == 0 and unlinked == 0:
        return ""
    return (
        f"Experience Link: {linked} linked | {closed} closed"
        f" | {unlinked} unlinked | quality={quality}"
        f" | AUTHORITY=OBSERVE_ONLY"
    )


def format_correlation_line(corr: dict) -> str:
    """One-line correlation intelligence summary. OBSERVE_ONLY — never influences decisions."""
    if not corr or not corr.get("enabled"):
        return ""
    n   = corr.get("sample_size", 0)
    pos = corr.get("strongest_positive_correlations", [])
    neg = corr.get("strongest_negative_correlations", [])

    if n == 0 or (not pos and not neg):
        return "Experience Corr: insufficient sample | AUTHORITY=OBSERVE_ONLY"

    parts = []
    if pos:
        parts.append(f"+ {pos[0]}")
    if neg:
        parts.append(f"- {neg[0]}")

    return "Experience Corr: " + " | ".join(parts) + " | AUTHORITY=OBSERVE_ONLY"


def format_ai_feedback_line(fb: dict) -> str:
    """One-line AI feedback summary. OBSERVE_ONLY — never influences decisions."""
    if not fb or not fb.get("enabled"):
        return ""
    n   = fb.get("sample_size", 0)
    hr  = fb.get("ai_helpful_rate")
    awr = fb.get("agreement_win_rate")
    dwr = fb.get("disagreement_win_rate")
    if n == 0:
        return "AI Feedback: 0 samples | insufficient | OBSERVE_ONLY"
    if hr is not None:
        parts = [f"{n} samples", f"helpful {hr:.0f}%"]
        if awr is not None:
            parts.append(f"agreement WR {awr:.0f}%")
        if dwr is not None:
            parts.append(f"disagreement WR {dwr:.0f}%")
        return "AI Feedback: " + " | ".join(parts) + " | OBSERVE_ONLY"
    return f"AI Feedback: {n} samples | developing | OBSERVE_ONLY"


def format_regime_line(regime: dict) -> str:
    """One-line market regime summary. OBSERVE_ONLY — never influences decisions."""
    if not regime or not regime.get("enabled"):
        return ""
    label = regime.get("regime_label", "unknown")
    conf  = regime.get("confidence",   0)
    vol   = regime.get("volatility_state", "unknown")
    exp   = regime.get("expansion_state",  "unknown")
    if label == "unknown":
        return "Market Regime: unknown | insufficient evidence | OBSERVE_ONLY"
    return (
        f"Market Regime: {label} | confidence={conf} | "
        f"vol={vol} | expansion={exp} | OBSERVE_ONLY"
    )


def format_paper_execution_line(pe: dict) -> str:
    """One-line paper execution summary -- appended to ai_context summary by the scan loop."""
    if not pe:
        return ""
    status = (pe.get("status") or "disabled").upper()
    reason = pe.get("reason", "")
    order  = pe.get("order_summary", "")
    if status == "SUBMITTED" and order:
        return f"Paper Execution: {status}. {order}."
    if reason:
        return f"Paper Execution: {status}. {reason}."
    return f"Paper Execution: {status}."


def format_paper_activation_line(pa: dict) -> str:
    """One-line paper activation summary for the ai_context summary."""
    if not pa:
        return ""
    status = (pa.get("status") or "disabled").upper()
    reason = pa.get("reason", "")
    if status == "DISABLED":
        return "Paper Activation: DISABLED. Reason: PAPER_ACTIVATION_MODE=false."
    if reason:
        return f"Paper Activation: {status}. {reason}."
    return f"Paper Activation: {status}."


def format_operational_readiness_line(orr: dict) -> str:
    """One-line operational readiness summary for the ai_context summary."""
    if not orr:
        return ""
    score  = orr.get("score", 0)
    ready  = orr.get("ready", False)
    label  = "Ready" if ready else "NOT READY"
    issues = orr.get("blocking_issues", [])
    if issues:
        return f"Operational Readiness: {score}/100. {label}. Blocking: {issues[0]}."
    return f"Operational Readiness: {score}/100. {label}."


def format_activation_line(ac: dict) -> str:
    """One-line activation status summary for the ai_context summary."""
    if not ac:
        return ""
    status = (ac.get("status") or "unknown").upper()
    reason = ac.get("reason", "")
    if reason:
        return f"Activation Status: {status}. {reason}."
    return f"Activation Status: {status}."


def format_position_monitor_line(pm: dict) -> str:
    """One-line position monitor summary for the ai_context summary."""
    if not pm or not pm.get("enabled"):
        return ""
    status = pm.get("status", "disabled")
    if status == "no_position":
        return "Position Monitor: no open position."
    if status == "monitoring":
        side    = pm.get("side", "?")
        qty     = pm.get("qty", 0)
        cp      = pm.get("current_price")
        sr      = pm.get("stop_reference")
        sd      = pm.get("stop_distance")
        pnl     = pm.get("unrealized_pnl")
        dist_str = f" stop_dist={sd}" if sd is not None else ""
        pnl_str  = f" upnl={pnl}"     if pnl is not None else ""
        return (
            f"Position Monitor: {side} {qty} @ {cp} | stop={sr}{dist_str}{pnl_str}."
        )
    if status == "error":
        warns = pm.get("warnings", [])
        return f"Position Monitor: error. {warns[0] if warns else ''}".strip(".")  + "."
    return f"Position Monitor: {status}."


def format_stop_enforcer_line(se: dict) -> str:
    """One-line stop enforcer summary for the ai_context summary."""
    if not se or not se.get("enabled"):
        return ""
    action  = se.get("action_taken", "monitoring")
    breached = se.get("stop_breached", False)
    if action == "exit_submitted":
        oid = se.get("exit_order_id", "?")
        return f"Stop Enforcer: EXIT SUBMITTED. order_id={oid}."
    if action == "stop_breached_no_action":
        return "Stop Enforcer: stop breached — PAPER_EXIT_ON_STOP=false, no order sent."
    if action == "exit_already_submitted":
        return "Stop Enforcer: stop breached — exit already in flight."
    if action == "exit_failed":
        warns = se.get("warnings", [])
        return f"Stop Enforcer: exit FAILED. {warns[0] if warns else ''}".strip(".")  + "."
    if breached:
        return "Stop Enforcer: stop breached — action blocked."
    return ""   # monitoring with no breach — no line needed


def format_broker_stop_line(bs: dict) -> str:
    """One-line broker stop summary for the ai_context summary."""
    if not bs or not bs.get("enabled"):
        return ""
    status    = (bs.get("status") or "disabled").upper()
    stop_price = bs.get("stop_price")
    order_id   = bs.get("stop_order_id")
    if status == "VERIFIED":
        return f"Broker Stop: VERIFIED. stop_price={stop_price}. order_id={order_id}."
    if status == "SUBMITTED":
        return f"Broker Stop: SUBMITTED. stop_price={stop_price}."
    if status == "MISSING":
        return "Broker Stop: MISSING. Software stop backup active."
    return f"Broker Stop: {status}."


def format_archive_line(ia: dict) -> str:
    """One-line intent archive summary -- appended to ai_context summary by the scan loop."""
    if not ia:
        return ""
    active_id = ia.get("active_intent_id")
    if not active_id:
        return ""
    status   = (ia.get("active_status") or "open").upper()
    mfe      = ia.get("mfe", 0.0)
    mae      = ia.get("mae", 0.0)
    touched  = ia.get("zone_touched", False)
    bars     = ia.get("bars_active", 0)
    short_id = active_id[-15:] if len(active_id) > 15 else active_id
    return (
        f"Intent Archive: {status}."
        f" id=...{short_id} mfe={mfe} mae={mae}"
        f" zone_touched={str(touched).lower()} bars={bars}."
    )


def format_score_line(iscr: dict) -> str:
    """One-line intent score summary -- appended to ai_context summary by the scan loop."""
    if not iscr:
        return ""
    if not iscr.get("scored", False):
        reason = iscr.get("score_reason", "no intent")
        return f"Intent Score: 0 (F, no_intent). {reason}"
    raw_s   = iscr.get("raw_score",    0)
    raw_g   = iscr.get("raw_grade",    "F")
    raw_q   = iscr.get("raw_quality",  "no_intent")
    gated_s = iscr.get("gated_score",  raw_s)
    gated_g = iscr.get("gated_grade",  raw_g)
    gated_q = iscr.get("gated_quality", raw_q)
    applied = iscr.get("gating_applied", False)
    reason  = iscr.get("gating_reason", "") if applied else iscr.get("score_reason", "")
    if applied:
        cap = reason.replace("caps quality at", "caps usability to")
        return (
            f"Intent Score: raw {raw_s} ({raw_g}, {raw_q}),"
            f" gated {gated_s} ({gated_g}, {gated_q}). {cap.capitalize()}."
        )
    short_r = iscr.get("score_reason", "")[:100]
    return f"Intent Score: {raw_s} ({raw_g}, {raw_q}). {short_r}"


def format_intent_line(ti: dict) -> str:
    """One-line trade intent summary -- appended to ai_context summary by the scan loop."""
    if not ti:
        return ""
    itype  = (ti.get("intent_type") or "none").upper()
    tool   = ti.get("preferred_tool") or "no_tool"
    trig   = (ti.get("trigger_status") or "n/a").replace("_", " ")
    allow  = ti.get("execution_allowed", False)
    would  = ti.get("would_authorize_if_enabled", False)
    reason = ti.get("reason", "")

    if itype in ("LONG", "SHORT"):
        ez = ti.get("entry_zone") or {}
        zl = ez.get("zone_low")
        zh = ez.get("zone_high")
        zone_str = f"zone {zl}-{zh}. " if zl is not None else ""
        return (
            f"Trade Intent: {itype} prepared using {tool}. {zone_str}"
            f"Trigger: {trig}. "
            f"Execution allowed {str(allow).lower()}."
            + (" All authorization checks pass but execution disabled." if would else "")
        )
    return f"Trade Intent: {itype}. {reason}"


def format_gate_line(eg: dict) -> str:
    """One-line execution gate summary -- appended to ai_context summary by the scan loop."""
    if not eg:
        return ""
    status  = (eg.get("gate_status") or "locked").upper()
    enabled = eg.get("execution_enabled", False)
    allow   = eg.get("allow_execution", False)
    would   = eg.get("would_authorize_if_enabled", False)
    if allow:
        return f"Execution Gate: {status}. Execution authorized."
    if would:
        return (
            f"Execution Gate: {status}. "
            "All checks passed but execution is globally disabled. No orders can be placed."
        )
    return (
        f"Execution Gate: {status}. "
        f"Execution {'enabled' if enabled else 'disabled'}. No orders can be placed."
    )


def format_decision_line(da: dict) -> str:
    """One-line decision authority summary — appended to summary by the scan loop."""
    if not da:
        return ""
    decision  = (da.get("decision")   or "stand_down").upper()
    direction = (da.get("direction")  or "neutral").lower()
    auth      = da.get("trade_authorized", False)
    reason    = da.get("reason", "")
    return (
        f"Decision Authority: {decision}. "
        f"Direction {direction}. "
        f"Trade authorized {str(auth).lower()}. "
        f"Reason: {reason}"
    )


def format_for_ai(snapshot: dict) -> str:
    session       = snapshot.get("session", "unknown")
    structure     = snapshot.get("structure", {})
    volatility    = snapshot.get("volatility", {})
    expansion     = snapshot.get("expansion", {})
    liquidity     = snapshot.get("liquidity", {})
    po3           = snapshot.get("po3", {})
    memory        = snapshot.get("memory", {})
    qualification = snapshot.get("qualification", {})
    playbook      = snapshot.get("playbook", {})
    risk          = snapshot.get("risk",    {})
    toolbox       = snapshot.get("toolbox", {})
    ai_ctx        = snapshot.get("ai_context", {})

    parts = [f"Session: {session}."]

    # Structure — 15m, 5m, 3m
    for tf in ["15m", "5m", "3m"]:
        parts.append(_structure_line(tf, structure))

    # Volatility — 15m headline
    v = volatility.get("15m", {})
    parts.append(
        f"Volatility: {v.get('state', 'unknown')} "
        f"(score {v.get('volatility_score', 0)}, ATR {v.get('atr_trend', 'unknown')})."
    )

    # Expansion — 15m and 5m
    for tf in ["15m", "5m"]:
        e = expansion.get(tf, {})
        disp = "displacement confirmed" if e.get("displacement_detected") else "no displacement"
        parts.append(
            f"{tf} expansion: {e.get('state', 'unknown')} "
            f"(score {e.get('expansion_score', 0)}, {disp}, "
            f"exhaustion: {e.get('exhaustion_risk', 'low')})."
        )

    # Liquidity events
    parts.extend(_liquidity_lines(liquidity))

    # PO3 phase summary
    parts.append(_po3_line(po3))

    # Memory context
    parts.append(_memory_line(memory))

    # AI interpretation
    narrative    = ai_ctx.get("market_narrative",  "unknown")
    bias         = ai_ctx.get("directional_bias",  "unknown")
    personality  = ai_ctx.get("trade_personality", "unknown")
    conf_score   = ai_ctx.get("confidence_score",  0)
    conf_tier    = ai_ctx.get("confidence_tier",   "unknown")
    coherence    = ai_ctx.get("coherence", {})
    warnings     = ai_ctx.get("warnings", [])

    parts.append(f"Narrative: {narrative}. Bias: {bias}. Personality: {personality}.")
    parts.append(
        f"Coherence — structure/expansion: {coherence.get('structure_expansion_alignment', 'n/a')}, "
        f"volatility/expansion: {coherence.get('volatility_expansion_alignment', 'n/a')}, "
        f"liquidity/structure: {coherence.get('liquidity_structure_alignment', 'n/a')}."
    )
    parts.append(f"Confidence: {conf_score} ({conf_tier}).")

    # Qualification verdict
    qual_line = _qualification_line(qualification)
    if qual_line:
        parts.append(qual_line)

    # Playbook selection
    parts.append(_playbook_line(playbook))

    # Risk Governor verdict
    risk_line = _risk_line(risk)
    if risk_line:
        parts.append(risk_line)

    # Toolbox selection
    tb_line = _toolbox_line(toolbox)
    if tb_line:
        parts.append(tb_line)

    # Entry prep summary
    ep_line = _entry_prep_line(toolbox)
    if ep_line:
        parts.append(ep_line)

    # AI Discretionary Engine
    ai_disc = snapshot.get("ai_discretionary", {})
    fusion  = snapshot.get("confidence_fusion", {})
    disc_line = _discretionary_line(ai_disc, fusion)
    if disc_line:
        parts.append(disc_line)

    # AI Debate (Phase 1S)
    debate_line = _debate_line(snapshot.get("ai_debate", {}))
    if debate_line:
        parts.append(debate_line)

    # Execution Gate (Phase 1U)
    gate_line = format_gate_line(snapshot.get("execution_gate", {}))
    if gate_line:
        parts.append(gate_line)

    # Trade Intent (Phase 1V)
    intent_line = format_intent_line(snapshot.get("trade_intent", {}))
    if intent_line:
        parts.append(intent_line)

    # Intent Score (Phase 1W)
    score_line = format_score_line(snapshot.get("intent_score", {}))
    if score_line:
        parts.append(score_line)

    # Intent Archive (Phase 1X)
    archive_line = format_archive_line(snapshot.get("intent_archive", {}))
    if archive_line:
        parts.append(archive_line)

    # Experience Intelligence (Phase 3A — OBSERVE_ONLY)
    exp_line = format_experience_line(snapshot.get("experience_summary", {}))
    if exp_line:
        parts.append(exp_line)

    # Experience Linkage (Phase 3C — OBSERVE_ONLY)
    link_line = format_experience_link_line(snapshot.get("experience_summary", {}))
    if link_line:
        parts.append(link_line)

    # Experience Correlation (Phase 3B — OBSERVE_ONLY)
    corr_line = format_correlation_line(snapshot.get("experience_correlation", {}))
    if corr_line:
        parts.append(corr_line)

    # Market Regime (Phase 5A — OBSERVE_ONLY)
    regime_line = format_regime_line(snapshot.get("market_regime", {}))
    if regime_line:
        parts.append(regime_line)

    # AI Feedback (Phase 5B — OBSERVE_ONLY)
    fb_line = format_ai_feedback_line(snapshot.get("ai_feedback_summary", {}))
    if fb_line:
        parts.append(fb_line)

    # Paper Activation (Phase 2D)
    pa_line = format_paper_activation_line(snapshot.get("paper_activation", {}))
    if pa_line:
        parts.append(pa_line)

    # Paper Execution (Phase 2A)
    pe_line = format_paper_execution_line(snapshot.get("paper_execution", {}))
    if pe_line:
        parts.append(pe_line)

    # Position Monitor (Phase 2B)
    pm_line = format_position_monitor_line(snapshot.get("position_monitor", {}))
    if pm_line:
        parts.append(pm_line)

    # Stop Enforcer (Phase 2B)
    se_line = format_stop_enforcer_line(snapshot.get("stop_enforcer", {}))
    if se_line:
        parts.append(se_line)

    # Operational Readiness (Phase 2C)
    orr_line = format_operational_readiness_line(snapshot.get("operational_readiness", {}))
    if orr_line:
        parts.append(orr_line)

    # Activation Status (Phase 2C)
    ac_line = format_activation_line(snapshot.get("activation_controller", {}))
    if ac_line:
        parts.append(ac_line)

    if warnings:
        parts.append(f"Warnings: {'; '.join(warnings)}.")

    return " ".join(parts)

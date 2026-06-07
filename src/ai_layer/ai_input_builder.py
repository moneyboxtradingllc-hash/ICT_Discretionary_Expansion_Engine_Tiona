"""
AI Input Builder — Phase 1N.
Builds a compact, token-efficient dict from the full snapshot for external AI consumption.
No raw candles. Limits candidates to top 3. Omits low-value intermediate engine internals.
"""

_TFS_SUMMARY = ["15m", "5m", "3m"]


# ── Section builders ──────────────────────────────────────────────────────────

def _structure_summary(structure: dict) -> dict:
    summary = {}
    for tf in _TFS_SUMMARY:
        s = structure.get(tf, {})
        summary[tf] = {
            "bias":            s.get("bias",            "neutral"),
            "state":           s.get("state",           "unknown"),
            "bos":             s.get("bos",             False),
            "mss":             s.get("mss",             False),
            "last_swing_high": s.get("last_swing_high"),
            "last_swing_low":  s.get("last_swing_low"),
        }
    summary["alignment"] = structure.get("alignment", "neutral")
    return summary


def _volatility_summary(volatility: dict) -> dict:
    summary = {}
    for tf in _TFS_SUMMARY:
        v = volatility.get(tf, {})
        summary[tf] = {
            "state":             v.get("state",             "unknown"),
            "atr_trend":         v.get("atr_trend",         "stable"),
            "volatility_score":  v.get("volatility_score",  0),
            "range_acceleration": v.get("range_acceleration", 1.0),
        }
    return summary


def _expansion_summary(expansion: dict) -> dict:
    summary = {}
    for tf in _TFS_SUMMARY:
        e = expansion.get(tf, {})
        summary[tf] = {
            "state":                 e.get("state",                 "unknown"),
            "expansion_score":       e.get("expansion_score",       0),
            "displacement_detected": e.get("displacement_detected", False),
            "exhaustion_risk":       e.get("exhaustion_risk",       "low"),
        }
    return summary


def _liquidity_events(liquidity: dict) -> list:
    """Return compact list of notable liquidity events across all timeframes."""
    events = []
    for tf in ["15m", "5m", "3m", "1m"]:
        liq = liquidity.get(tf, {})
        if liq.get("sweep_detected"):
            events.append({
                "tf":        tf,
                "event":     "sweep",
                "direction": liq.get("sweep_direction"),
                "reclaim":   liq.get("reclaim_detected", False),
            })
        if liq.get("failed_breakout"):
            events.append({"tf": tf, "event": "failed_breakout"})
    return events


def _po3_summary(po3: dict) -> dict:
    return {
        "alignment": po3.get("alignment", ""),
        "15m": {
            "phase":                  po3.get("15m", {}).get("phase"),
            "distribution_direction": po3.get("15m", {}).get("distribution_direction"),
            "manipulation_direction": po3.get("15m", {}).get("manipulation_direction"),
        },
        "5m": {
            "phase":                  po3.get("5m", {}).get("phase"),
            "distribution_direction": po3.get("5m", {}).get("distribution_direction"),
            "manipulation_direction": po3.get("5m", {}).get("manipulation_direction"),
        },
    }


def _candidate_summary(candidate: dict) -> dict:
    """Compact single-candidate dict — price detail included for preferred tool context."""
    pl = candidate.get("price_level", {})
    tp = candidate.get("trigger_prep", {})
    r  = candidate.get("readiness",   {})
    return {
        "tool":               candidate.get("tool"),
        "score":              candidate.get("score"),
        "raw_status":         candidate.get("raw_status"),
        "effective_status":   candidate.get("effective_status"),
        "reasons":            candidate.get("reasons", []),
        "prerequisites_missing": r.get("prerequisites_missing", []),
        "score_gaps":         r.get("score_gaps", [])[:3],
        "price_zone": {
            "level_type":         pl.get("level_type"),
            "zone_low":           pl.get("zone_low"),
            "zone_high":          pl.get("zone_high"),
            "current_price":      pl.get("current_price"),
            "price_relation":     pl.get("price_relation"),
            "distance_to_zone":   pl.get("distance_to_zone"),
            "entered_zone":       pl.get("entered_zone"),
            "invalidated":        pl.get("invalidated"),
            "invalidation_level": pl.get("invalidation_level"),
        },
        "trigger_status":      tp.get("effective_trigger_status"),
        "execution_ready":     tp.get("execution_ready"),
        "confirmation_needed": tp.get("confirmation_needed", [])[:3],
    }


# ── Public entry point ────────────────────────────────────────────────────────

def build_compact_ai_input(snapshot: dict) -> dict:
    """
    Build a compact, token-efficient dict from the full snapshot.
    Designed for external AI API consumption (Phase 1N).
    No raw candles. Top 3 tool candidates only.
    """
    tb     = snapshot.get("toolbox",       {})
    qual   = snapshot.get("qualification", {})
    pb     = snapshot.get("playbook",      {})
    risk   = snapshot.get("risk",          {})
    mem    = snapshot.get("memory",        {})
    po3    = snapshot.get("po3",           {})
    ai_ctx = snapshot.get("ai_context",    {})

    candidates  = tb.get("tool_candidates", [])
    mem_global  = (mem.get("global") or {}) if mem and mem.get("available") else {}

    return {
        "timestamp": snapshot.get("timestamp"),
        "session":   snapshot.get("session"),

        "market_context": {
            "narrative":         ai_ctx.get("market_narrative"),
            "market_state":      ai_ctx.get("market_state"),
            "directional_bias":  ai_ctx.get("directional_bias"),
            "confidence_score":  ai_ctx.get("confidence_score"),
            "confidence_tier":   ai_ctx.get("confidence_tier"),
            "trade_personality": ai_ctx.get("trade_personality"),
            "warnings":          ai_ctx.get("warnings", []),
        },

        "qualification": {
            "status":            qual.get("status"),
            "grade":             qual.get("grade"),
            "direction":         qual.get("direction"),
            "opportunity_score": qual.get("opportunity_score"),
            "primary_driver":    qual.get("primary_driver"),
        },

        "playbook": {
            "selected":   pb.get("selected_playbook"),
            "status":     pb.get("status"),
            "direction":  pb.get("direction"),
            "confidence": pb.get("playbook_confidence"),
        },

        "risk": {
            "trade_allowed":    risk.get("trade_allowed"),
            "risk_tier":        risk.get("risk_tier"),
            "authority_reason": risk.get("authority_reason"),
            "blocks":           risk.get("blocks", []),
            "restrictions":     risk.get("restrictions", [])[:3],
        },

        "toolbox": {
            "preferred_tool":                  tb.get("preferred_tool"),
            "toolbox_status":                  tb.get("toolbox_status"),
            "tool_confidence":                 tb.get("tool_confidence"),
            "best_available_raw_status":       tb.get("best_available_raw_status"),
            "best_available_effective_status": tb.get("best_available_effective_status"),
            "near_tie_tools":                  tb.get("near_tie_tools", []),
            "candidates":                      [_candidate_summary(c) for c in candidates[:3]],
        },

        "memory": {
            "available":        mem.get("available", False),
            "snapshot_count":   mem.get("snapshot_count", 0),
            "confidence_trend": mem_global.get("confidence_trend"),
            "confidence_delta": mem_global.get("confidence_delta"),
        },

        "po3":        _po3_summary(po3),
        "structure":  _structure_summary(snapshot.get("structure",  {})),
        "volatility": _volatility_summary(snapshot.get("volatility", {})),
        "expansion":  _expansion_summary(snapshot.get("expansion",  {})),
        "liquidity":  _liquidity_events(snapshot.get("liquidity",  {})),
    }

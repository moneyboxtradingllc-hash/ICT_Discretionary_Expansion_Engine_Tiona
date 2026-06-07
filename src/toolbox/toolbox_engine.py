"""
Toolbox Engine — Phase 1J.
Selects entry tools from existing snapshot evidence.
No execution, no order placement, no indicator recalculation.
"""

from toolbox.tool_library import eligible_tools, normalize_tool, VALID_TOOLS
from toolbox.tool_readiness import analyze_readiness
from toolbox.price_levels import build_price_level
from toolbox.entry_trigger_prep import build_trigger_prep

_TFS = ["15m", "5m", "3m", "1m"]

_NO_TOOLBOX = {
    "preferred_tool":                  None,
    "toolbox_status":                  "no_tool",
    "tool_confidence":                 0,
    "near_tie_tools":                  [],
    "tool_candidates":                 [],
    "warnings":                        [],
    "best_available_raw_status":       "no_tool",
    "best_available_effective_status": "no_tool",
}

# Rank: lower number = better status
_RAW_RANK = {"actionable": 0, "ready": 1, "forming": 2, "no_tool": 3}
_EFF_RANK = {"actionable": 0, "ready": 1, "forming": 2, "blocked_by_risk": 3, "no_tool": 4}


# ── Direction / family helpers ────────────────────────────────────────────────

def _tool_direction(tool: str) -> str:
    if tool.startswith("bullish_"): return "bullish"
    if tool.startswith("bearish_"): return "bearish"
    return "neutral"


def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


# ── Shared context score (0–20) ───────────────────────────────────────────────

def _context_score(snapshot: dict) -> int:
    struct = snapshot.get("structure", {})
    exp    = snapshot.get("expansion",  {})
    vol    = snapshot.get("volatility", {})
    mem    = snapshot.get("memory",     {})
    pts    = 0

    align = struct.get("alignment", "neutral")
    pts += {"full": 8, "strong": 6, "partial": 3}.get(align, 0)

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in _TFS):
        pts += 5

    if vol.get("15m", {}).get("state") not in ("toxic", "explosive"):
        pts += 4

    g = (mem.get("global") or {}) if mem and mem.get("available") else {}
    if g.get("confidence_trend") == "rising":
        pts += 3

    return min(20, pts)


# ── Family evidence scorers (0–80) ────────────────────────────────────────────

def _score_ifvg(snap: dict, direction: str) -> int:
    liq = snap.get("liquidity", {})
    exp = snap.get("expansion", {})
    po3 = snap.get("po3",       {})
    pts = 20  # eligibility base

    if any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS): pts += 20
    if any(liq.get(tf, {}).get("reclaim_detected")  for tf in _TFS): pts += 15
    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["3m", "1m"]):                                  pts += 10
    if any(po3.get(tf, {}).get("phase") in ("manipulation", "transition")
           for tf in ["3m", "1m"]):                                  pts += 5
    if po3.get("alignment") == "full_distribution_alignment":        pts -= 10

    return pts


def _score_breaker(snap: dict, direction: str) -> int:
    liq    = snap.get("liquidity",  {})
    struct = snap.get("structure",  {})
    pts    = 20

    if any(liq.get(tf, {}).get("failed_breakout")  for tf in _TFS): pts += 20
    if any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS): pts += 15
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): pts += 10
    if any(struct.get(tf, {}).get("mss")           for tf in _TFS): pts += 10
    if any(struct.get(tf, {}).get("bos")           for tf in _TFS): pts += 5

    return pts


def _score_rejection_block(snap: dict, direction: str) -> int:
    liq = snap.get("liquidity", {})
    exp = snap.get("expansion", {})
    pts = 20

    if any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS): pts += 20
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): pts += 15
    for tf in ["15m", "5m"]:
        ex = exp.get(tf, {})
        if ex.get("exhaustion_risk") == "high":
            pts += 10
            break
        if ex.get("exhaustion_risk") == "medium" and \
                ex.get("state") in ("mature_expansion", "exhaustion_risk"):
            pts += 5
            break

    return pts


def _score_fvg(snap: dict, direction: str) -> int:
    exp = snap.get("expansion", {})
    liq = snap.get("liquidity", {})
    pts = 20

    if any(exp.get(tf, {}).get("displacement_detected")
           for tf in ["15m", "5m"]):                                 pts += 25
    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["15m", "5m"]):                                 pts += 15
    if not any(liq.get(tf, {}).get("sweep_detected") for tf in _TFS): pts += 5

    return pts


def _score_order_block(snap: dict, direction: str) -> int:
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})
    po3    = snap.get("po3",       {})
    pts    = 20

    align = struct.get("alignment", "neutral")
    pts += {"full": 20, "strong": 15, "partial": 8}.get(align, 0)

    if any(exp.get(tf, {}).get("state") in ("healthy_expansion", "mature_expansion")
           for tf in ["15m", "5m"]):                                 pts += 10
    if any(po3.get(tf, {}).get("phase") == "distribution"
           for tf in ["15m", "5m"]):                                 pts += 5
    if any(exp.get(tf, {}).get("exhaustion_risk") == "high"
           for tf in ["15m", "5m"]):                                 pts -= 10

    return pts


def _score_ote_retracement(snap: dict, direction: str) -> int:
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})
    po3    = snap.get("po3",       {})
    pts    = 20

    align = struct.get("alignment", "neutral")
    pts += {"full": 15, "strong": 10, "partial": 5}.get(align, 0)

    if any(exp.get(tf, {}).get("state") in ("mature_expansion", "healthy_expansion")
           for tf in ["15m", "5m"]):                                 pts += 15
    if any(po3.get(tf, {}).get("phase") == "distribution"
           for tf in ["15m", "5m"]):                                 pts += 10

    return pts


def _score_mss_retest(snap: dict, direction: str) -> int:
    struct = snap.get("structure", {})
    liq    = snap.get("liquidity", {})
    pts    = 20

    if any(struct.get(tf, {}).get("mss") for tf in _TFS): pts += 25
    if any(struct.get(tf, {}).get("bos") for tf in _TFS): pts += 10
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): pts += 10

    return pts


def _score_ote_after_reclaim(snap: dict, direction: str) -> int:
    liq    = snap.get("liquidity",  {})
    exp    = snap.get("expansion",  {})
    struct = snap.get("structure",  {})
    pts    = 20

    if any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS): pts += 20
    if any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS): pts += 15
    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["3m", "1m"]):                                  pts += 10
    if struct.get("alignment") in ("neutral", "partial"):            pts += 5

    return pts


def _score_opening_fvg(snap: dict, direction: str) -> int:
    if snap.get("session") != "ny_open":
        return 0
    exp = snap.get("expansion",  {})
    vol = snap.get("volatility", {})
    pts = 30  # session gate

    if any(exp.get(tf, {}).get("displacement_detected")
           for tf in ["1m", "3m", "5m"]):                           pts += 20
    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["1m", "3m", "5m"]):                           pts += 15
    vol_state = vol.get("15m", {}).get("state", "")
    if vol_state == "expanding":                                     pts += 10
    if vol_state in ("toxic", "explosive"):                          pts -= 20

    return pts


def _score_opening_order_block(snap: dict, direction: str) -> int:
    if snap.get("session") != "ny_open":
        return 0
    struct = snap.get("structure", {})
    vol    = snap.get("volatility",{})
    exp    = snap.get("expansion", {})
    pts    = 25  # session gate

    align = struct.get("alignment", "neutral")
    pts += {"full": 15, "strong": 12, "partial": 7}.get(align, 0)

    vol_state = vol.get("15m", {}).get("state", "")
    if vol_state in ("expanding", "stable"):                         pts += 10
    if vol_state in ("toxic", "explosive"):                          pts -= 20

    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["1m", "3m", "5m"]):                           pts += 10

    return pts


def _score_range_break_retest(snap: dict, direction: str) -> int:
    struct = snap.get("structure", {})
    exp    = snap.get("expansion", {})
    pts    = 20

    if struct.get("15m", {}).get("state") in ("range_bound", "neutral"): pts += 20
    if any(struct.get(tf, {}).get("bos") for tf in _TFS):           pts += 15
    if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
           for tf in ["1m", "3m", "5m"]):                           pts += 10
    if any(struct.get(tf, {}).get("mss") for tf in _TFS):           pts += 5

    return pts


_FAMILY_SCORERS = {
    "fvg":                 _score_fvg,
    "ifvg":                _score_ifvg,
    "order_block":         _score_order_block,
    "breaker":             _score_breaker,
    "rejection_block":     _score_rejection_block,
    "ote_retracement":     _score_ote_retracement,
    "mss_retest":          _score_mss_retest,
    "ote_after_reclaim":   _score_ote_after_reclaim,
    "opening_fvg":         _score_opening_fvg,
    "opening_order_block": _score_opening_order_block,
    "range_break_retest":  _score_range_break_retest,
}


# ── Status resolution ─────────────────────────────────────────────────────────

def _raw_status(score: int) -> str:
    """Score-only verdict. Risk Governor has no input here."""
    if score < 40:  return "no_tool"
    if score >= 75: return "actionable"
    if score >= 60: return "ready"
    return "forming"


def _effective_status(raw: str, risk_blocked: bool) -> str:
    """Apply Risk Governor override on top of the raw score verdict."""
    if raw == "no_tool":
        return "no_tool"
    return "blocked_by_risk" if risk_blocked else raw


# ── Score a single tool ───────────────────────────────────────────────────────

def _score_tool(tool: str, snapshot: dict) -> int:
    fam    = _family(tool)
    dir_   = _tool_direction(tool)
    scorer = _FAMILY_SCORERS.get(fam)
    if scorer is None:
        return 0
    return max(0, min(100, scorer(snapshot, dir_) + _context_score(snapshot)))


# ── Reasons ───────────────────────────────────────────────────────────────────

def _tool_reasons(tool: str, snapshot: dict) -> list:
    fam    = _family(tool)
    liq    = snapshot.get("liquidity",  {})
    struct = snapshot.get("structure",  {})
    exp    = snapshot.get("expansion",  {})
    po3    = snapshot.get("po3",        {})
    pb     = snapshot.get("playbook",   {})

    pb_name = pb.get("selected_playbook", "unknown")
    r = [f"Tool eligible for {pb_name}"]

    sweep   = any(liq.get(tf, {}).get("sweep_detected")   for tf in _TFS)
    reclaim = any(liq.get(tf, {}).get("reclaim_detected") for tf in _TFS)
    failed  = any(liq.get(tf, {}).get("failed_breakout")  for tf in _TFS)
    mss     = any(struct.get(tf, {}).get("mss")           for tf in _TFS)
    bos     = any(struct.get(tf, {}).get("bos")           for tf in _TFS)
    disp    = any(exp.get(tf, {}).get("displacement_detected") for tf in ["15m", "5m"])
    align   = struct.get("alignment", "neutral")

    if fam in ("ifvg", "breaker", "rejection_block", "ote_after_reclaim"):
        if sweep and reclaim: r.append("Sweep and reclaim confirmed")
        elif sweep:           r.append("Sweep detected — reclaim pending")

    if fam == "ifvg":
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            r.append("Expansion beginning after reclaim")
        if any(po3.get(tf, {}).get("phase") in ("manipulation", "transition")
               for tf in ["3m", "1m"]):
            r.append("Lower timeframe PO3 in manipulation/transition phase")

    if fam == "breaker":
        if failed: r.append("Failed breakout creates breaker context")
        if mss:    r.append("Market structure shift present")
        if bos:    r.append("Break of structure confirmed")

    if fam == "rejection_block":
        for tf in ["15m", "5m"]:
            if exp.get(tf, {}).get("exhaustion_risk") in ("high", "medium"):
                r.append(f"{tf} expansion exhaustion supports wick rejection zone")
                break

    if fam in ("fvg", "order_block"):
        if disp: r.append("Displacement candle confirmed")
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["15m", "5m"]):
            r.append("Expansion in progress")

    if fam == "fvg" and not sweep:
        r.append("Clean directional move — no sweep interference")

    if fam == "order_block":
        if any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"]):
            r.append("PO3 distribution phase active on higher timeframe")

    if fam == "ote_retracement":
        if any(exp.get(tf, {}).get("state") in ("mature_expansion", "healthy_expansion")
               for tf in ["15m", "5m"]):
            r.append("Mature expansion suggests pullback into OTE zone")
        if any(po3.get(tf, {}).get("phase") == "distribution" for tf in ["15m", "5m"]):
            r.append("PO3 distribution supports continuation after pullback")

    if fam == "mss_retest":
        if mss:    r.append("MSS confirmed — retest opportunity forming")
        if bos:    r.append("BOS present — structural momentum")
        if reclaim: r.append("Reclaim adds structural confluence")

    if fam == "ote_after_reclaim":
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["3m", "1m"]):
            r.append("Lower timeframe expansion beginning — OTE zone active")
        if align in ("neutral", "partial"):
            r.append("Neutral/partial alignment — pullback completing")

    if fam in ("opening_fvg", "opening_order_block"):
        r.append("NY Open session — early window active")
        if disp: r.append("Displacement at open confirmed")

    if fam == "range_break_retest":
        if struct.get("15m", {}).get("state") in ("range_bound", "neutral"):
            r.append("15m was range-bound — breakout in progress")
        if bos: r.append("Break of structure confirms range exit")
        if any(exp.get(tf, {}).get("state") in ("early_expansion", "healthy_expansion")
               for tf in ["1m", "3m", "5m"]):
            r.append("Expansion beginning after range break")

    if align in ("full", "strong"):
        r.append(f"MTF structure alignment: {align}")

    return r


# ── Warnings ──────────────────────────────────────────────────────────────────

def _tool_warnings(tool: str, snapshot: dict, risk_blocked: bool) -> list:
    w   = []
    vol = snapshot.get("volatility", {})
    exp = snapshot.get("expansion",  {})
    pb  = snapshot.get("playbook",   {})

    if risk_blocked:
        w.append("Risk Governor blocked — analysis only, no execution")

    if vol.get("15m", {}).get("state") in ("toxic", "explosive"):
        w.append("15m volatility elevated — entry timing critical")

    for tf in ["15m", "5m"]:
        if exp.get(tf, {}).get("exhaustion_risk") == "high":
            w.append(f"{tf} expansion exhaustion risk high — late entry risk")
            break

    if pb.get("direction") in ("neutral", "conflicted"):
        w.append("Playbook direction unconfirmed — tool directional bias not validated")

    return w


# ── Public entry point ────────────────────────────────────────────────────────

def run_toolbox(snapshot: dict) -> dict:
    """
    Phase 1J — Toolbox Engine.
    Reads the fully assembled snapshot (including playbook + risk) and returns
    tool selection results.  Only canonical tools are scored.
    """
    pb   = snapshot.get("playbook", {})
    risk = snapshot.get("risk",     {})

    pb_name      = pb.get("selected_playbook", "no_playbook")
    pb_dir       = pb.get("direction", "neutral")
    risk_blocked = not risk.get("trade_allowed", True)

    if pb_name == "no_playbook":
        result = _NO_TOOLBOX.copy()
        result["warnings"] = ["no playbook selected — toolbox cannot activate"]
        return result

    if pb_dir not in ("bullish", "bearish"):
        result = _NO_TOOLBOX.copy()
        result["warnings"] = [f"playbook direction is {pb_dir} — tool selection deferred"]
        return result

    # Eligible list is already canonical (defined in tool_library)
    raw_eligible = eligible_tools(pb_name, pb_dir)

    # Normalise any stale names that slipped through; drop unknowns
    eligible = []
    for t in raw_eligible:
        if t in VALID_TOOLS:
            eligible.append(t)
        else:
            mapped = normalize_tool(t)
            if mapped and mapped not in eligible:
                eligible.append(mapped)

    # Score
    candidates = []
    for tool in eligible:
        score = _score_tool(tool, snapshot)
        raw   = _raw_status(score)
        if raw == "no_tool":
            continue
        eff      = _effective_status(raw, risk_blocked)
        readiness = analyze_readiness(tool, snapshot, score, raw)
        pl        = build_price_level(tool, snapshot)
        tp        = build_trigger_prep(tool, snapshot, pl, readiness, raw, eff)
        candidates.append({
            "tool":             tool,
            "score":            score,
            "raw_status":       raw,
            "effective_status": eff,
            "reasons":          _tool_reasons(tool, snapshot),
            "warnings":         _tool_warnings(tool, snapshot, risk_blocked),
            "readiness":        readiness,
            "price_level":      pl,
            "trigger_prep":     tp,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        result = _NO_TOOLBOX.copy()
        result["warnings"] = ["no eligible tool scored above threshold (score < 40)"]
        return result

    preferred = candidates[0]

    near_tie = [
        c["tool"] for c in candidates[1:]
        if preferred["score"] - c["score"] <= 5
    ]

    global_warnings = []
    if risk_blocked:
        global_warnings.append("Toolbox found valid tools but Risk Governor is blocked")
    if near_tie:
        global_warnings.append("multiple tools competing — market context may be ambiguous")

    best_raw = min(candidates, key=lambda c: _RAW_RANK.get(c["raw_status"], 99))["raw_status"]
    best_eff = min(candidates, key=lambda c: _EFF_RANK.get(c["effective_status"], 99))["effective_status"]

    return {
        "preferred_tool":                  preferred["tool"],
        "toolbox_status":                  preferred["effective_status"],
        "tool_confidence":                 preferred["score"],
        "near_tie_tools":                  near_tie,
        "tool_candidates":                 candidates,
        "warnings":                        global_warnings,
        "best_available_raw_status":       best_raw,
        "best_available_effective_status": best_eff,
    }

"""
Phase 1W -- Intent Scoring Engine.

Answers: "How good is this prepared trade intent?"
Does not place trades. No execution. No orders. No broker actions.
No TradingClient. No paper trades.
"""

# ── Score tables ──────────────────────────────────────────────────────────────

_QUAL_SCORES = {
    "no_trade": 0, "watchlist": 4, "candidate": 8, "qualified": 12, "elite": 15,
}

_PB_SCORES = {
    "no_playbook": 0, "forming": 5, "active": 8, "strong": 12, "elite": 15,
}

_RISK_SCORES = {
    "blocked":    0,
    "minimal":    5,
    "reduced":    9,
    "normal":    12,
    "clean":     12,   # equivalent to normal
    "aggressive": 15,
}

_TOOL_SCORES = {
    "no_tool": 0, "forming": 5, "ready": 10, "actionable": 15,
}

_TRIG_SCORES = {
    "n/a":                   0,
    "no_trigger":            0,
    "waiting_for_retest":    4,
    "retest_in_progress":    6,
    "confirmation_needed":   8,
    "confirmed":            10,
    "execution_ready":      10,
    "invalidated":           0,
}

_LC_SCORES = {
    "dormant": 0, "none": 0, "born": 3, "forming": 5,
    "maturing": 8, "actionable": 10, "blocked": 5,
    "decaying": 2, "invalidated": 0,
}

_ST_SCORES = {
    "new_setup":   4,
    "upgrade":     8,
    "stable":      5,
    "downgrade":   2,
    "decay":       1,
    "invalidation": 0,
    "reset":       0,
}

_COMPONENT_MAX = {
    "qualification":   15,
    "playbook":        15,
    "risk":            15,
    "tool_quality":    15,
    "trigger_quality": 10,
    "ai_alignment":    10,
    "lifecycle":       10,
    "state_transition": 10,
}


# ── Grade / quality lookups ───────────────────────────────────────────────────

def _grade(score: int) -> str:
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 40: return "D"
    return "F"


def _quality(score: int) -> str:
    if score >= 85: return "elite_intent"
    if score >= 70: return "strong_watch"
    if score >= 55: return "moderate_watch"
    if score >= 40: return "weak_watch"
    return "poor"


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


# ── Component scorers ─────────────────────────────────────────────────────────

def _score_qualification(snapshot: dict) -> int:
    qs = (snapshot.get("qualification", {}).get("status") or "no_trade").lower()
    return _QUAL_SCORES.get(qs, 0)


def _score_playbook(snapshot: dict) -> int:
    pb   = snapshot.get("playbook", {})
    name = (pb.get("selected_playbook") or "no_playbook").lower()
    if name == "no_playbook":
        return 0
    status = (pb.get("status") or "active").lower()
    return _PB_SCORES.get(status, 8)   # default: active = 8


def _score_risk(snapshot: dict) -> int:
    risk = snapshot.get("risk", {})
    if not risk.get("trade_allowed", False):
        return 0
    tier = (risk.get("risk_tier") or "normal").lower()
    return _RISK_SCORES.get(tier, 9)   # default: reduced = 9


def _score_tool(snapshot: dict) -> int:
    pref_c = _preferred_candidate(snapshot)
    raw    = (pref_c.get("raw_status") or "no_tool").lower()
    return _TOOL_SCORES.get(raw, 0)


def _score_trigger(snapshot: dict) -> int:
    pref_c = _preferred_candidate(snapshot)
    tp     = pref_c.get("trigger_prep", {})
    raw    = (tp.get("raw_trigger_status") or "n/a").lower()
    if tp.get("execution_ready") and raw == "confirmed":
        return 10
    return _TRIG_SCORES.get(raw, 0)


def _score_ai_alignment(snapshot: dict, direction: str) -> int:
    """AI-AUTH-1 — sovereign source only. The AI-alignment component is scored
    from the ECU Brain thesis (the ONE live AI): direction agreement (7 pts) +
    thesis conviction >= 55 (3 pts). The legacy wrapper (ai_discretionary /
    ai_debate / confidence_fusion) contributes ZERO points to the gated
    execution threshold — it observes, it does not score. With no Brain thesis
    (ECU off or non-directional scan) the component is 0."""
    bt = snapshot.get("brain_thesis") or {}
    if bt.get("owner") != "ai_brain":
        return 0

    pts = 0
    bt_dir = (bt.get("direction") or "neutral").lower()
    if bt_dir == direction and bt_dir in ("bullish", "bearish"):
        pts += 7
        try:
            if float(bt.get("confidence") or 0) >= 55:
                pts += 3
        except (TypeError, ValueError):
            pass

    return min(pts, 10)


def _score_lifecycle(snapshot: dict) -> int:
    sl = snapshot.get("setup_lifecycle", {})
    if not sl.get("active"):
        return 0
    phase = (sl.get("current_phase") or "dormant").lower()
    return _LC_SCORES.get(phase, 0)


def _score_state_transition(snapshot: dict) -> int:
    label = (snapshot.get("state_transition", {}).get("transition") or "stable").lower()
    return _ST_SCORES.get(label, 0)


# ── Narrative builders ────────────────────────────────────────────────────────

def _build_strengths(breakdown: dict, direction: str) -> list[str]:
    s = []
    if breakdown["qualification"] >= 12:
        s.append("Qualification is strong")
    if breakdown["playbook"] >= 12:
        s.append("Playbook is high-confidence")
    if breakdown["risk"] >= 12:
        s.append("Risk Governor permits trading")
    if breakdown["tool_quality"] >= 10:
        s.append("Preferred tool is ready or actionable")
    if breakdown["trigger_quality"] >= 8:
        s.append("Trigger approaching execution readiness")
    if breakdown["ai_alignment"] >= 7:
        s.append(f"AI systems aligned with {direction} thesis")
    if breakdown["lifecycle"] >= 8:
        s.append("Setup lifecycle is maturing or actionable")
    if breakdown["state_transition"] >= 8:
        s.append("State transition shows upgrade momentum")
    return s[:4]


def _build_weaknesses(breakdown: dict, snapshot: dict, is_invalidated: bool) -> list[str]:
    w = []
    if is_invalidated:
        w.append("setup invalidated")
    if breakdown["risk"] == 0:
        w.append("risk blocked")
    if breakdown["qualification"] <= 4:
        w.append("qualification weak or missing")
    if breakdown["tool_quality"] <= 5:
        w.append("tool not yet ready")
    if breakdown["trigger_quality"] <= 4:
        w.append("trigger not yet active")
    if breakdown["ai_alignment"] <= 3:
        w.append("AI systems not aligned")
    if breakdown["lifecycle"] <= 3:
        w.append("lifecycle in early or decaying phase")
    return w[:4]


def _build_required(breakdown: dict) -> list[str]:
    r = []
    if breakdown["risk"] == 0:
        r.append("Risk Governor must allow trading")
    if breakdown["tool_quality"] < 10:
        r.append("Preferred tool must reach ready or actionable")
    if breakdown["trigger_quality"] < 8:
        r.append("Trigger must advance to confirmation_needed or execution_ready")
    if breakdown["qualification"] < 12:
        r.append("Qualification should reach qualified or elite")
    if breakdown["ai_alignment"] < 7:
        r.append("AI systems need better directional alignment")
    return r[:4]


def _build_reason(score: int, quality: str, intent_type: str,
                   direction: str, weaknesses: list[str]) -> str:
    cap = (direction.capitalize() + " " + intent_type) if intent_type not in ("none", "stand_down") else direction.capitalize()
    if quality == "elite_intent":
        return f"Elite {cap} intent — all systems aligned."
    weak_str = (f"; weakness: {weaknesses[0]}") if weaknesses else ""
    if quality == "strong_watch":
        return f"Strong {cap} intent{weak_str}."
    if quality == "moderate_watch":
        return f"Moderate {cap} intent forming{weak_str}."
    if quality == "weak_watch":
        extras = "; ".join(weaknesses[:2]) if weaknesses else "multiple factors missing"
        return f"Weak {direction} intent — {extras}."
    return f"Poor conditions for {direction} intent — most factors missing."


# ── Public entry point ────────────────────────────────────────────────────────

def score_intent(snapshot: dict, symbol: str) -> dict:
    """
    Phase 1W -- Intent Scoring Engine.
    Scores the trade_intent on a 0-100 scale. Never places orders.
    """
    ti     = snapshot.get("trade_intent", {})
    sl     = snapshot.get("setup_lifecycle", {})
    st     = snapshot.get("state_transition", {})
    pref_c = _preferred_candidate(snapshot)

    intent_type = (ti.get("intent_type") or "none").lower()
    direction   = (ti.get("direction")   or "neutral").lower()

    # ── No intent → unscored ──────────────────────────────────────────────────
    if not ti.get("intent_created", False):
        reason = ti.get("reason", "No trade intent available.")
        return {
            "scored":                False,
            "score":                 0,
            "grade":                 "F",
            "quality":               "no_intent",
            "raw_score":             0,
            "raw_grade":             "F",
            "raw_quality":           "no_intent",
            "gated_score":           0,
            "gated_grade":           "F",
            "gated_quality":         "no_intent",
            "gating_applied":        False,
            "gating_reason":         "",
            "intent_type":           intent_type,
            "direction":             direction,
            "symbol":                symbol,
            "score_breakdown":       {k: 0 for k in _COMPONENT_MAX},
            "strengths":             [],
            "weaknesses":            [],
            "required_improvements": [],
            "score_reason":          reason,
        }

    # ── Invalidation check ────────────────────────────────────────────────────
    sl_inv   = bool(sl.get("active") and (sl.get("current_phase") or "").lower() == "invalidated")
    st_inv   = bool(st.get("invalidated", False))
    trig_inv = (
        pref_c.get("trigger_prep", {}).get("raw_trigger_status", "").lower() == "invalidated"
    )
    is_invalidated = sl_inv or st_inv or trig_inv

    # ── Component scores ──────────────────────────────────────────────────────
    breakdown = {
        "qualification":    _score_qualification(snapshot),
        "playbook":         _score_playbook(snapshot),
        "risk":             _score_risk(snapshot),
        "tool_quality":     _score_tool(snapshot),
        "trigger_quality":  _score_trigger(snapshot),
        "ai_alignment":     _score_ai_alignment(snapshot, direction),
        "lifecycle":        _score_lifecycle(snapshot),
        "state_transition": _score_state_transition(snapshot),
    }

    # ── Raw score (no caps, no gating) ───────────────────────────────────────
    raw_score   = sum(breakdown.values())
    raw_grade   = _grade(raw_score)
    raw_quality = _quality(raw_score)

    # ── Gating rules ─────────────────────────────────────────────────────────
    # Invalidation takes precedence over risk blocking
    if is_invalidated:
        gated_score    = min(raw_score, 39)
        gated_quality  = "poor"
        gating_applied = True
        gating_reason  = "setup invalidated caps quality at poor"
    elif breakdown["risk"] == 0:
        gated_score    = min(raw_score, 69)
        gated_quality  = (
            "moderate_watch"
            if raw_quality in ("strong_watch", "elite_intent")
            else raw_quality
        )
        gating_applied = True
        gating_reason  = "risk blocked caps quality at moderate_watch"
    else:
        gated_score    = raw_score
        gated_quality  = raw_quality
        gating_applied = False
        gating_reason  = ""

    gated_grade = _grade(gated_score)

    # score/grade/quality = gated values (backward compat — always reflect usable state)
    score   = gated_score
    grade   = gated_grade
    quality = gated_quality

    strengths  = _build_strengths(breakdown, direction)
    weaknesses = _build_weaknesses(breakdown, snapshot, is_invalidated)
    required   = _build_required(breakdown)
    reason     = _build_reason(score, quality, intent_type, direction, weaknesses)

    return {
        "scored":                True,
        "score":                 score,
        "grade":                 grade,
        "quality":               quality,
        "raw_score":             raw_score,
        "raw_grade":             raw_grade,
        "raw_quality":           raw_quality,
        "gated_score":           gated_score,
        "gated_grade":           gated_grade,
        "gated_quality":         gated_quality,
        "gating_applied":        gating_applied,
        "gating_reason":         gating_reason,
        "intent_type":           intent_type,
        "direction":             direction,
        "symbol":                symbol,
        "score_breakdown":       breakdown,
        "strengths":             strengths,
        "weaknesses":            weaknesses,
        "required_improvements": required,
        "score_reason":          reason,
    }

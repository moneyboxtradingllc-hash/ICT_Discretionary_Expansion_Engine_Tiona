"""
Execution Gate / Authorization Firewall.

Hard firewall between the decision layer and the paper execution layer.
EXECUTION_ENABLED must be explicitly "true" for allow_execution to ever be True.
Default: False. Missing config: False.

When EXECUTION_ENABLED=true and all internal checks pass:
  allow_execution=True, gate_status="authorized"
  Actual paper orders still require ALLOW_PAPER_ORDERS=true (checked separately).

This module ONLY evaluates authorization -- it never submits orders.
"""
import os


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def evaluate_gate(snapshot: dict) -> dict:
    """
    Phase 1U -- Execution Gate.
    Evaluates whether all authorization conditions are met.
    allow_execution is always False while EXECUTION_ENABLED != "true".
    """
    # Only the literal string "true" enables execution -- everything else locks the gate
    raw               = os.getenv("EXECUTION_ENABLED", "false").lower().strip()
    execution_enabled = raw == "true"

    da     = snapshot.get("decision_authority", {})
    risk   = snapshot.get("risk", {})
    sl     = snapshot.get("setup_lifecycle", {})
    st     = snapshot.get("state_transition", {})
    debate = snapshot.get("ai_debate", {})
    fus    = snapshot.get("confidence_fusion", {})

    pref_c = _preferred_candidate(snapshot)

    # ── Authorization checks ──────────────────────────────────────────────────
    decision       = (da.get("decision") or "stand_down").lower()
    da_trade_auth  = da.get("trade_authorized", False)          # Phase 1T invariant: always False
    risk_allows    = risk.get("trade_allowed", False)
    exec_ready     = bool(pref_c.get("trigger_prep", {}).get("execution_ready", False))
    st_inv         = st.get("invalidated", False)
    lc_phase       = (
        (sl.get("current_phase") or "dormant").lower()
        if sl.get("active") else "dormant"
    )
    lifecycle_inv  = bool(sl.get("active") and lc_phase == "invalidated")
    setup_not_inv  = not (st_inv or lifecycle_inv)
    debate_stance  = (
        debate.get("final_verdict", {}).get("recommended_stance") or "stand_down"
    ).lower()
    ai_supports    = debate_stance in ("prepare_long", "prepare_short")
    lifecycle_ok   = bool(sl.get("active") and lc_phase not in ("invalidated", "decaying"))
    fusion_status  = (fus.get("fusion_status") or "").lower()

    auth_checks = {
        "decision_trade_authorized": da_trade_auth,
        "risk_allows_trade":         risk_allows,
        "trigger_execution_ready":   exec_ready,
        "setup_not_invalidated":     setup_not_inv,
        "ai_verdict_supports_trade": ai_supports,
        "lifecycle_allows_trade":    lifecycle_ok,
    }

    # ── would_authorize_if_enabled ────────────────────────────────────────────
    # True only when every check passes simultaneously and decision reached max readiness.
    # Even when True: allow_execution remains False because EXECUTION_ENABLED=false.
    would_authorize = (
        decision == "trade_authorized_false"
        and da_trade_auth is False
        and risk_allows
        and exec_ready
        and setup_not_inv
        and ai_supports
        and fusion_status != "strong_disagreement"
    )

    # ── Blocking factors ──────────────────────────────────────────────────────
    blocking: list[str] = []
    if not execution_enabled:
        blocking.append("execution globally disabled")
    if decision != "trade_authorized_false":
        blocking.append(f"decision_authority decision={decision}")
    if not risk_allows:
        blocking.append("risk blocked")
    if not exec_ready:
        blocking.append("trigger execution_ready=false")
    if not setup_not_inv:
        blocking.append("setup or trigger invalidated")
    if not ai_supports:
        blocking.append(f"ai debate stance is {debate_stance}")
    if fusion_status == "strong_disagreement":
        blocking.append("confidence fusion: strong disagreement")

    # ── Warnings (propagated from decision layer) ─────────────────────────────
    warnings: list[str] = []
    for w in da.get("warnings", []):
        if w not in warnings:
            warnings.append(w)

    # ── Gate status ───────────────────────────────────────────────────────────
    if st_inv or lifecycle_inv:
        gate_status = "invalidated"
        reason      = "Setup or trigger is invalidated -- execution gate locked."
    elif not execution_enabled:
        if would_authorize:
            gate_status = "would_authorize"
            reason      = "All authorization checks pass but execution is globally disabled."
        else:
            gate_status = "locked"
            reason      = "Execution layer disabled. Phase 1U firewall only."
    else:
        # execution_enabled=True
        if would_authorize:
            gate_status = "authorized"
            reason      = "All checks pass — execution authorized."
        else:
            gate_status = "blocked"
            reason      = "Execution enabled but one or more authorization checks failed."

    # allow_execution: True when execution_enabled=True AND would_authorize=True.
    # Actual paper orders still require ALLOW_PAPER_ORDERS=true (enforcement in execution_engine.py).
    allow_execution = execution_enabled and would_authorize

    return {
        "execution_enabled":          execution_enabled,
        "allow_execution":            allow_execution,
        "gate_status":                gate_status,
        "reason":                     reason,
        "would_authorize_if_enabled": would_authorize,
        "authorization_checks":       auth_checks,
        "blocking_factors":           blocking[:5],
        "warnings":                   warnings[:3],
    }

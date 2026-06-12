"""
Execution Gate / Authorization Firewall.

Hard firewall between the decision layer and the paper execution layer.
EXECUTION_ENABLED must be explicitly "true" for allow_execution to ever be True.
Default: False. Missing config: False.

When EXECUTION_ENABLED=true and all internal checks pass:
  allow_execution=True, gate_status="authorized"
  Actual paper orders still require ALLOW_PAPER_ORDERS=true (checked separately).

Phase 5F additions:
  5F.3 — trigger confirmation enforcement (required_trigger_status from
         regime_permission_matrix; missing matrix defaults to 'confirmed')
  5F.4 — decision state normalization (legacy 'trade_authorized_false'
         accepted and mapped to 'ready_for_execution')
  5F.5 — minimum setup age enforcement (min_setup_age_scans from matrix)
  plus regime permission blocking (regime_permissions.allowed)

Phase FC-1 additions (June 11 promotions):
  - council_permits_trade: council veto blocks when COUNCIL_AUTHORITY=enforce
    (June 11: REGIME NO@95 + DELIVERY NO@75 had no wire into this gate)
  - no_promoted_rule_block: promoted governance rules (PROMOTED_RULES, e.g.
    R-001) block when RULE_GOVERNANCE_MODE=enforce
  Both checks fail-open on internal errors and are inert at default env.

Phase NA-1 addition (narrative authority):
  - narrative_permits_trade: the Narrative Authority Layer's story-coherence
    verdict blocks when NARRATIVE_AUTHORITY=enforce — a trade may not run
    against the synthesized market narrative (AI+Delivery agreement,
    protected swings, conflicts). Structure bias no longer owns direction.
    Fail-open; inert at default env.

This module ONLY evaluates authorization -- it never submits orders.
"""
import os

from decision_authority.decision_engine import normalize_decision
from narrative_authority.narrative_engine import narrative_permits
from rule_governance.promoted_rules import evaluate_promoted_rules


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def _regime_constraints(snapshot: dict) -> tuple[bool, "str | None", int, str, list]:
    """
    Phase 5F — Extract regime constraint inputs for the gate.

    Returns (regime_allowed, required_trigger_status, min_setup_age, source, blocking_reasons).
      - Matrix present and enabled  -> its values
      - Matrix explicitly disabled  -> legacy behavior (no regime gating)
      - Matrix missing/malformed    -> SAFE DEFAULT: require confirmed, min age 2
    """
    rp = snapshot.get("regime_permissions")
    if not isinstance(rp, dict) or not rp:
        return True, "confirmed", 2, "missing_matrix_safe_default", []

    if not rp.get("enabled", False):
        return True, None, 0, "regime_authority_disabled", []

    return (
        bool(rp.get("allowed", True)),
        (rp.get("required_trigger_status") or "confirmed").lower(),
        int(rp.get("min_setup_age_scans", 2) or 0),
        "regime_permission_matrix",
        list(rp.get("blocking_reasons", [])),
    )


def _trigger_requirement_met(required: "str | None", actual: str) -> bool:
    """
    Phase 5F.3 — confirmation_needed and confirmed are distinct states.
      required None                  -> no requirement (authority disabled)
      required 'confirmed'           -> only 'confirmed' passes
      required 'confirmation_needed' -> 'confirmation_needed' or 'confirmed' passes
      unknown requirement            -> safe: only 'confirmed' passes
    """
    if required is None:
        return True
    if required == "confirmation_needed":
        return actual in ("confirmation_needed", "confirmed")
    return actual == "confirmed"


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
    # Phase 5F.4: legacy 'trade_authorized_false' normalizes to 'ready_for_execution'
    decision       = normalize_decision(da.get("decision"))
    da_trade_auth  = da.get("trade_authorized", False)          # invariant: always False pre-gate
    risk_allows    = risk.get("trade_allowed", False)
    trigger_prep   = pref_c.get("trigger_prep") or {}
    exec_ready     = bool(trigger_prep.get("execution_ready", False))
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

    # ── Phase 5F: regime constraint checks ───────────────────────────────────
    (
        regime_allowed,
        required_trigger,
        min_setup_age,
        regime_source,
        regime_blocking,
    ) = _regime_constraints(snapshot)

    # 5F.3 — trigger confirmation requirement
    actual_trigger = (trigger_prep.get("raw_trigger_status") or "unknown").lower()
    trig_req_met   = _trigger_requirement_met(required_trigger, actual_trigger)

    # 5F.5 — minimum setup age requirement
    setup_age_actual = int(sl.get("age_scans", 0) or 0) if sl.get("active") else 0
    setup_age_met    = setup_age_actual >= min_setup_age

    # ── Phase FC-1: promoted authority (June 11) ─────────────────────────────
    council          = snapshot.get("council", {}) or {}
    council_veto     = council.get("veto") or {}
    council_enforced = (council.get("authority_level") == "enforce")
    council_permits  = not (council_enforced and council_veto.get("veto_triggered", False))

    promoted_rules   = evaluate_promoted_rules(snapshot.get("shared_context", {}) or {})
    rules_permit     = not promoted_rules.get("blocked", False)

    # ── Phase NA-1: narrative authority (story coherence) ────────────────────
    proposed_dir = (snapshot.get("playbook", {}) or {}).get("direction", "")
    narrative_ok, narrative_reason = narrative_permits(
        snapshot.get("narrative_authority", {}) or {}, proposed_dir,
    )

    auth_checks = {
        "decision_trade_authorized": da_trade_auth,
        "risk_allows_trade":         risk_allows,
        "trigger_execution_ready":   exec_ready,
        "setup_not_invalidated":     setup_not_inv,
        "ai_verdict_supports_trade": ai_supports,
        "lifecycle_allows_trade":    lifecycle_ok,
        # Phase 5F regime constraint checks
        "regime_permission_allowed": regime_allowed,
        "trigger_requirement_met":   trig_req_met,
        "setup_age_requirement_met": setup_age_met,
        # Phase FC-1 promoted authority checks
        "council_permits_trade":     council_permits,
        "no_promoted_rule_block":    rules_permit,
        # Phase NA-1 narrative authority check
        "narrative_permits_trade":   narrative_ok,
    }

    # ── would_authorize_if_enabled ────────────────────────────────────────────
    # True only when every check passes simultaneously and decision reached max readiness.
    # Even when True: allow_execution remains False because EXECUTION_ENABLED=false.
    would_authorize = (
        decision == "ready_for_execution"
        and da_trade_auth is False
        and risk_allows
        and exec_ready
        and setup_not_inv
        and ai_supports
        and fusion_status != "strong_disagreement"
        # Phase 5F — regime constraint authority
        and regime_allowed
        and trig_req_met
        and setup_age_met
        # Phase FC-1 — promoted authority (June 11)
        and council_permits
        and rules_permit
        # Phase NA-1 — narrative authority
        and narrative_ok
    )

    # ── Blocking factors ──────────────────────────────────────────────────────
    blocking: list[str] = []
    if not execution_enabled:
        blocking.append("execution globally disabled")
    if decision != "ready_for_execution":
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
    # Phase 5F blocking factors
    if not regime_allowed:
        detail = f": {regime_blocking[0]}" if regime_blocking else ""
        blocking.append(f"regime permission blocked{detail}")
    if not trig_req_met:
        blocking.append(
            f"trigger requirement not met "
            f"(required={required_trigger}, actual={actual_trigger})"
        )
    if not setup_age_met:
        blocking.append(
            f"setup age requirement not met "
            f"(required={min_setup_age}, actual={setup_age_actual})"
        )
    # Phase FC-1 blocking factors
    if not council_permits:
        blocking.append(council_veto.get("veto_reason") or "council veto")
    if not rules_permit:
        fired_desc = "; ".join(
            f"{f.get('rule_id')}: {f.get('reason')}"
            for f in promoted_rules.get("fired", [])
        )
        blocking.append(f"promoted rule fired — {fired_desc}")
    # Phase NA-1 blocking factor
    if not narrative_ok:
        blocking.append(f"narrative authority: {narrative_reason}")

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
        "blocking_factors":           blocking[:8],
        "warnings":                   warnings[:3],
        # Phase 5F.3 — trigger confirmation enforcement
        "trigger_requirement_met":    trig_req_met,
        "required_trigger_status":    required_trigger,
        "actual_trigger_status":      actual_trigger,
        # Phase 5F.5 — minimum setup age enforcement
        "setup_age_requirement":      min_setup_age,
        "setup_age_actual":           setup_age_actual,
        "setup_age_requirement_met":  setup_age_met,
        # Phase 5F — regime permission source
        "regime_permission_allowed":  regime_allowed,
        "regime_constraint_source":   regime_source,
        # Phase FC-1 — promoted authority audit trail
        "council_permits_trade":      council_permits,
        "council_authority":          council.get("authority_level", "observe_only"),
        "no_promoted_rule_block":     rules_permit,
        "promoted_rules_fired":       promoted_rules.get("fired", []),
        "promoted_rules_enforced":    promoted_rules.get("enforced", False),
        # Phase NA-1 — narrative authority audit trail
        "narrative_permits_trade":    narrative_ok,
        "narrative_reason":           narrative_reason,
    }

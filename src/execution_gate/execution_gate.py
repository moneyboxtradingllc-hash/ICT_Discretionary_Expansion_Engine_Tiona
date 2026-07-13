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
from market_commander.commander_authority import (
    build_commander_authority, commander_enforces, review_council_authority,
)
from narrative_authority.narrative_engine import narrative_permits
from regime_authority.regime_authority_mode import regime_authority_mode, regime_enforces
from rule_governance.promoted_rules import evaluate_promoted_rules


def _thesis_feeds_readiness() -> bool:
    """Phase AB-7.3b — when true, a mature persistent thesis lends its age to the
    setup-age requirement so a flickering mechanical setup no longer makes a mature
    thesis look immature. Default false: legacy behavior, bit-for-bit unchanged."""
    return os.getenv("THESIS_FEEDS_READINESS", "false").lower().strip() == "true"


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
    # TIER-2A (2026-07-10) — legacy wrapper (ai_debate/confidence_fusion)
    # RETIRED entirely; even its shadow observability is gone. The ECU Brain is
    # the sole AI; it exercises authority upstream (thesis -> qualification/
    # playbook/toolbox direction), never as a second gate vote.

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
    lifecycle_ok   = bool(sl.get("active") and lc_phase not in ("invalidated", "decaying"))

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
    # ── Phase AB-7.3b — readiness inherits the persistent thesis age ──────────
    # A mature ACTIVE/EXECUTABLE thesis keeps age continuity even when the
    # mechanical setup lifecycle resets on one-scan flicker. THREATENED/
    # INVALIDATED theses do NOT lend age — they reset normally. This is age
    # continuity only; it changes no other authorization check.
    ts_state           = snapshot.get("thesis_state") or {}
    effective_setup_age = setup_age_actual
    thesis_age_applied  = False
    if (_thesis_feeds_readiness()
            and ts_state.get("present")
            and ts_state.get("is_trade_thesis")
            and ts_state.get("thesis_status") in ("ACTIVE", "EXECUTABLE")):
        thesis_age = int(ts_state.get("thesis_age_scans") or 0)
        if thesis_age > setup_age_actual:
            effective_setup_age = thesis_age
            thesis_age_applied  = True
    setup_age_met    = effective_setup_age >= min_setup_age

    # ── REGIME-DEMOTE (2026-07-09): mechanical-regime execution authority ──────
    # The three checks above (regime permission, regime-required trigger, regime
    # min-age) are the mechanical regime's ONLY execution-block channels. When
    # REGIME_AUTHORITY_MODE=observe_only the regime is demoted to telemetry: it
    # still computes would_have_blocked / veto_reason (below) and feeds Market
    # Commander, but it may NOT hard-block. The gate then falls through to the
    # next non-regime authority (decision, real trigger execution_ready, risk,
    # council, rules, narrative) — none of which this touches. In enforce mode
    # the effective values equal the raw values, so behavior is bit-for-bit legacy.
    regime_mode      = regime_authority_mode()
    regime_enforced  = regime_enforces()
    eff_regime_allowed = regime_allowed if regime_enforced else True
    eff_trig_req_met   = trig_req_met   if regime_enforced else True
    eff_setup_age_met  = setup_age_met  if regime_enforced else True

    # Raw would-have-blocked telemetry (independent of mode)
    regime_veto_parts: list[str] = []
    if not regime_allowed:
        regime_veto_parts.append(
            (regime_blocking[0] if regime_blocking else "regime permission blocked")
        )
    if not trig_req_met:
        regime_veto_parts.append(
            f"regime-required trigger (required={required_trigger}, actual={actual_trigger})"
        )
    if not setup_age_met:
        regime_veto_parts.append(
            f"regime min setup age (required={min_setup_age}, actual={effective_setup_age})"
        )
    regime_would_have_blocked = bool(regime_veto_parts)
    regime_veto_reason = "; ".join(regime_veto_parts) if regime_veto_parts else None

    # ── Phase FC-1: promoted authority (June 11) ─────────────────────────────
    council          = snapshot.get("council", {}) or {}
    council_veto     = council.get("veto") or {}
    council_enforced = (council.get("authority_level") == "enforce")

    # ── MC-ENFORCE (2026-07-09): Market Commander owns final environment authority.
    # When MARKET_COMMANDER_AUTHORITY_MODE=enforce, the council is split into
    # safety-class (RISK — may still veto) and advisory-class (mechanical REGIME/
    # OPPORTUNITY/DELIVERY/QUALIFICATION/TOOLBOX — demoted to would_have_vetoed).
    # This closes the indirect channel by which demoted mechanical subsystems could
    # still veto the Commander through the council. In observe_only (default) the
    # full council veto stands — bit-for-bit legacy. Safety gates below are untouched.
    commander_auth    = build_commander_authority(snapshot)
    commander_enforce = commander_enforces()
    council_review    = review_council_authority(council, commander_enforce)
    effective_council_veto = council_review["council_veto_effective"]
    council_permits   = not (council_enforced and effective_council_veto)

    # Commander itself may hard-block ONLY a STAND_DOWN (HOSTILE/INERT guardian)
    # environment, and only while it enforces. Directional/rotational reads never
    # hard-block — they let the pipeline reach the real trigger/risk authorities.
    commander_permits = not (commander_enforce and commander_auth["commander_blocks_trade"])

    promoted_rules   = evaluate_promoted_rules(snapshot.get("shared_context", {}) or {})
    rules_permit     = not promoted_rules.get("blocked", False)

    # ── Phase NA-1: narrative authority (story coherence) ────────────────────
    proposed_dir = (snapshot.get("playbook", {}) or {}).get("direction", "")
    narrative_ok, narrative_reason = narrative_permits(
        snapshot.get("narrative_authority", {}) or {}, proposed_dir,
    )

    # ── ENTRY-INVARIANT (2026-07-13): thesis entry eligibility ───────────────
    # A directional Brain-owned thesis must carry a PROVABLY valid correct-
    # side invalidation before it may author FRESH exposure. Neutral/degraded
    # theses are exempt (mechanical era untouched); position management never
    # consults the gate. Inert unless BRAIN_INVALIDATION_ENTRY_INVARIANT=on.
    # HARDENED (2026-07-13): fail-CLOSED for fresh exposure — even an import/
    # evaluation failure of the check itself denies NEW entry while the flag
    # is on (flag off keeps byte-identical legacy pass-through).
    try:
        from ai_brain.ecu import thesis_entry_eligible
        entry_invariant = thesis_entry_eligible(snapshot)
    except Exception as exc:  # noqa: BLE001
        _inv_on = (os.getenv("BRAIN_INVALIDATION_ENTRY_INVARIANT", "off")
                   .lower().strip() == "on")
        entry_invariant = {
            "eligible": not _inv_on,
            "code": "invariant_evaluation_error" if _inv_on else "off",
            "reason": (f"entry invariant unavailable — fresh exposure denied "
                       f"(fail-closed): {exc}") if _inv_on
                      else "entry invariant off",
            "direction": None, "source": None,
            "invalidation_level": None, "current_price": None,
        }
    thesis_eligible = entry_invariant.get("eligible") is True
    thesis_eligibility_reason = entry_invariant.get("reason") or ""

    # ── BRAIN-AUTHORSHIP-CLOSURE (2026-07-13): sole authorship of fresh
    # exposure. The Brain (direct healthy LLM, or valid AB-7 inheritance with
    # a healthy current cycle) must have AUTHORED the directional thesis, and
    # every downstream direction must agree — mechanics may decline, never
    # substitute. Neutral/conflicted/degraded/unavailable/fallback/unknown
    # author nothing new. Gate-only; position management never consults the
    # gate. Inert unless BRAIN_AUTHORSHIP_REQUIRED=on; fail-CLOSED while on.
    try:
        from ai_brain.ecu import brain_authorship
        authorship = brain_authorship(snapshot)
    except Exception as exc:  # noqa: BLE001
        _auth_on = (os.getenv("BRAIN_AUTHORSHIP_REQUIRED", "off")
                    .lower().strip() == "on")
        authorship = {
            "eligible": not _auth_on,
            "code": "authorship_evaluation_error" if _auth_on else "off",
            "reason": (f"authorship guard unavailable — fresh exposure denied "
                       f"(fail-closed): {exc}") if _auth_on
                      else "brain authorship requirement off",
        }
    authorship_ok = authorship.get("eligible") is True

    auth_checks = {
        "decision_trade_authorized": da_trade_auth,
        "risk_allows_trade":         risk_allows,
        "trigger_execution_ready":   exec_ready,
        "setup_not_invalidated":     setup_not_inv,
        "lifecycle_allows_trade":    lifecycle_ok,
        # Phase 5F regime constraint checks (effective = regime-authority-gated)
        "regime_permission_allowed": eff_regime_allowed,
        "trigger_requirement_met":   eff_trig_req_met,
        "setup_age_requirement_met": eff_setup_age_met,
        # Phase FC-1 promoted authority checks
        "council_permits_trade":     council_permits,
        "no_promoted_rule_block":    rules_permit,
        # Phase NA-1 narrative authority check
        "narrative_permits_trade":   narrative_ok,
        # MC-ENFORCE — Market Commander final environment authority
        "commander_permits_trade":   commander_permits,
        # ENTRY-INVARIANT — thesis must name where it is wrong before new risk
        "thesis_invalidation_ok":    thesis_eligible,
        # BRAIN-AUTHORSHIP — the sovereign must have authored the fresh trade
        "brain_authorship_ok":       authorship_ok,
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
        # AI-AUTH-1: the legacy wrapper's debate stance and fusion-disagreement
        # vetoes are REMOVED — the wrapper observes, it does not authorize.
        # Phase 5F — regime constraint authority (REGIME-DEMOTE: effective values;
        # observe_only pass-through so the mechanical regime cannot hard-block)
        and eff_regime_allowed
        and eff_trig_req_met
        and eff_setup_age_met
        # Phase FC-1 — promoted authority (June 11)
        and council_permits
        and rules_permit
        # Phase NA-1 — narrative authority
        and narrative_ok
        # MC-ENFORCE — Commander STAND_DOWN (hostile/inert) may block; else pass-through
        and commander_permits
        # ENTRY-INVARIANT — incomplete directional thesis may not author new risk
        and thesis_eligible
        # BRAIN-AUTHORSHIP — no fresh exposure without sovereign authorship
        and authorship_ok
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
    # Phase 5F blocking factors (REGIME-DEMOTE: effective values — in observe_only
    # these are pass-through True, so the regime never enters hard blocking)
    if not eff_regime_allowed:
        detail = f": {regime_blocking[0]}" if regime_blocking else ""
        blocking.append(f"regime permission blocked{detail}")
    if not eff_trig_req_met:
        blocking.append(
            f"trigger requirement not met "
            f"(required={required_trigger}, actual={actual_trigger})"
        )
    if not eff_setup_age_met:
        blocking.append(
            f"setup age requirement not met "
            f"(required={min_setup_age}, actual={effective_setup_age})"
        )
    # Phase FC-1 blocking factors
    if not council_permits:
        blocking.append(council_veto.get("veto_reason") or "council veto")
    # MC-ENFORCE blocking factor — Commander STAND_DOWN (hostile/inert only)
    if not commander_permits:
        blocking.append(
            f"market commander STAND_DOWN: {commander_auth.get('commander_override_reason') or commander_auth['commander_final_environment']}"
        )
    if not rules_permit:
        fired_desc = "; ".join(
            f"{f.get('rule_id')}: {f.get('reason')}"
            for f in promoted_rules.get("fired", [])
        )
        blocking.append(f"promoted rule fired — {fired_desc}")
    # Phase NA-1 blocking factor
    if not narrative_ok:
        blocking.append(f"narrative authority: {narrative_reason}")
    # ENTRY-INVARIANT blocking factor (code is machine-readable)
    if not thesis_eligible:
        blocking.append(f"entry invariant [{entry_invariant.get('code')}]: "
                        f"{thesis_eligibility_reason}")
    # BRAIN-AUTHORSHIP blocking factor (code is machine-readable)
    if not authorship_ok:
        blocking.append(f"brain authorship [{authorship.get('code')}]: "
                        f"{authorship.get('reason')}")

    # ── Warnings (propagated from decision layer) ─────────────────────────────
    warnings: list[str] = []
    for w in da.get("warnings", []):
        if w not in warnings:
            warnings.append(w)
    # REGIME-DEMOTE: in observe_only the regime's would-have-block survives as a
    # non-blocking warning so the caution signal is never lost.
    if not regime_enforced and regime_would_have_blocked:
        warnings.append(f"regime would_have_blocked (advisory): {regime_veto_reason}")
    # MC-ENFORCE: a demoted advisory council veto survives as a non-blocking warning.
    if council_review.get("advisory_veto_demoted"):
        _adv = ", ".join(f"{m.get('member')}@{m.get('confidence')}"
                         for m in council_review.get("advisory_dissent", []))
        warnings.append(f"council advisory would_have_vetoed (demoted by commander): {_adv}")

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
        # Phase AB-7.3b — thesis age inheritance audit trail
        "setup_age_effective":        effective_setup_age,
        "thesis_age_applied":         thesis_age_applied,
        # Phase 5F — regime permission source
        "regime_permission_allowed":  eff_regime_allowed,
        "regime_constraint_source":   regime_source,
        # REGIME-DEMOTE (2026-07-09) — mechanical-regime authority telemetry.
        # In observe_only the regime is telemetry_only: it records what it WOULD
        # have blocked but does not gate execution. Market Commander owns final
        # environment authority; while Commander is observe-only the enforcement
        # source is none.
        "regime_authority": {
            "regime_authority":                regime_mode,
            "mode":                            regime_mode,
            "regime_would_have_blocked":       regime_would_have_blocked,
            "regime_veto_reason":              regime_veto_reason,
            "final_regime_enforcement_source": (
                "mechanical_regime" if (regime_enforced and regime_would_have_blocked)
                else "market_commander_or_none"
            ),
            "mechanical_regime_role":          "enforce" if regime_enforced else "telemetry_only",
            "regime_effect_on_execution":      "enforced" if regime_enforced else "advisory_only",
            "regime_raw_permission_allowed":   regime_allowed,
            "regime_raw_trigger_requirement_met": trig_req_met,
            "regime_raw_setup_age_met":        setup_age_met,
        },
        # Phase FC-1 — promoted authority audit trail
        "council_permits_trade":      council_permits,
        "council_authority":          council.get("authority_level", "observe_only"),
        "no_promoted_rule_block":     rules_permit,
        "promoted_rules_fired":       promoted_rules.get("fired", []),
        "promoted_rules_enforced":    promoted_rules.get("enforced", False),
        # Phase NA-1 — narrative authority audit trail
        "narrative_permits_trade":    narrative_ok,
        "narrative_reason":           narrative_reason,
        # ENTRY-INVARIANT — structured eligibility record (forensics: was the
        # entry blocked, why, which failure class, which direction/source)
        "entry_invariant":            entry_invariant,
        # BRAIN-AUTHORSHIP — structured authorship record (forensics: was
        # authorship required/satisfied, direct or inherited, cycle health,
        # every stage's direction, provenance, failure code)
        "brain_authorship":           authorship,
        # ── MC-ENFORCE — Market Commander final environment authority ─────────
        "commander_permits_trade":    commander_permits,
        "commander_authority":        commander_auth,
        "council_authority_review":   council_review,
        # Mechanical regime demoted to telemetry (mission-required field names)
        "mechanical_regime": {
            "mechanical_regime":                   regime_source,
            "mechanical_regime_confidence":        int(
                (snapshot.get("market_regime", {}) or {}).get("confidence", 0) or 0
            ),
            "mechanical_regime_would_have_blocked": regime_would_have_blocked,
            "mechanical_regime_veto_reason":       regime_veto_reason,
            "mechanical_regime_role": (
                "enforce" if regime_enforced else "telemetry_only"
            ),
        },
    }

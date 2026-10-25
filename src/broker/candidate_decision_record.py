"""Death certificates for entry proposals: one record, one terminal cause.

COMPLETE-PRODUCTION-CANDIDATE-DECISION-TELEMETRY (2026-08-07).

PROD-20260807 produced 23 propose-entry decisions and 0 candidates, and nothing
persisted said WHY. Establishing that the objective binding was the killer took
offline archaeology across 171 Brain artifacts. The live qualification object
was never written at all, so for that session it is gone for good.

The law here is accounting, not storytelling:

    every propose_entry terminates in exactly one terminal disposition
    terra_proposals == sum(terminal dispositions)

A proposal that vanishes without a certificate is a defect in the evidence
system, and `reconcile()` reports it as CANDIDATE_DECISION_ACCOUNTING_FAILURE
rather than quietly balancing the books.

EVIDENCE IS NOT AUTHORITY. Nothing in this module is read by CandidateProducer,
and a failed write can never manufacture permission to trade -- writes are
best-effort and every caller swallows their errors.
"""
from __future__ import annotations

SCHEMA_VERSION = "candidate_decision.v1"
#: PARTICIPATION-REFUSAL-TELEMETRY (2026-10-25). A v1 record plus the typed
#: same-scan participation evidence `attach_participation_evidence` adds. Only
#: the live loop writes it; v1 journals stay readable exactly as written.
SCHEMA_VERSION_V2 = "candidate_decision.v2"
SCHEMA_VERSIONS = (SCHEMA_VERSION, SCHEMA_VERSION_V2)

# ── terminal dispositions ────────────────────────────────────────────────────
CANDIDATE_CREATED = "CANDIDATE_CREATED"
CONDITIONAL_PLAN_PUBLISHED = "CONDITIONAL_PLAN_PUBLISHED"
QUALIFICATION_REJECTED = "QUALIFICATION_REJECTED"
OBJECTIVE_ID_MISSING = "OBJECTIVE_ID_MISSING"
OBJECTIVE_ID_UNKNOWN = "OBJECTIVE_ID_UNKNOWN"
OBJECTIVE_INVALID = "OBJECTIVE_INVALID"
INVALIDATION_ID_MISSING = "INVALIDATION_ID_MISSING"
INVALIDATION_ID_UNKNOWN = "INVALIDATION_ID_UNKNOWN"
INVALIDATION_INVALID = "INVALIDATION_INVALID"
GEOMETRY_REJECTED = "GEOMETRY_REJECTED"
REWARD_BELOW_QUALIFICATION = "REWARD_BELOW_QUALIFICATION"
RISK_REJECTED = "RISK_REJECTED"
BRAIN_UNUSABLE = "BRAIN_UNUSABLE"
WINDOW_CLOSED = "WINDOW_CLOSED"
STOOD_DOWN = "STOOD_DOWN"

#: DECISION-ACCOUNTING-HELD-1 (2026-09-23). The scan on which the Brain was
#: never asked. `STOOD_DOWN` means the organism looked at the market and
#: declined; `HELD` means it did not look, because the wake controller proved
#: no material semantic change and ENFORCE suppressed the call. Those are
#: different facts about the session and the ledger must not merge them: a
#: reader counting stand-downs is counting judgements, and a suppressed scan
#: contains no judgement to count.
HELD = "HELD"

#: The deterministic daily-loss governor refused entry on PROVEN truth -- the
#: budget is spent. This is a decision, not an absence of one.
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

#: The governor could not ESTABLISH truth, so it refused rather than guess:
#: order discovery came back incomplete, the venue could not be read, or an
#: in-session trade could not be attributed. Kept distinct from
#: `BUDGET_EXHAUSTED` for the reason this codebase keeps every such pair
#: distinct -- "no" and "cannot tell" are not the same answer, and a ledger
#: that renders them identically loses the only signal that says go look.
GOVERNOR_UNPROVEN = "GOVERNOR_UNPROVEN"

#: PARTICIPATION-REFUSAL-TELEMETRY (2026-10-25). A known MECHANICAL refusal of
#: participation: the current campaign Lifecycle assessment (or the loop's
#: binding of it to the current Draw authority) refused before any candidate.
#: NEUTRAL by construction: it is not a Brain judgement (`STOOD_DOWN`), not a
#: candidate and not readiness. `reconcile` counts it as accounted only when
#: the record carries complete, consistent v2 refusal evidence.
PARTICIPATION_REFUSED = "PARTICIPATION_REFUSED"

UNCLASSIFIED = "UNCLASSIFIED"

TERMINAL_DISPOSITIONS = (
    CANDIDATE_CREATED, CONDITIONAL_PLAN_PUBLISHED, QUALIFICATION_REJECTED,
    OBJECTIVE_ID_MISSING, OBJECTIVE_ID_UNKNOWN, OBJECTIVE_INVALID,
    INVALIDATION_ID_MISSING, INVALIDATION_ID_UNKNOWN, INVALIDATION_INVALID,
    GEOMETRY_REJECTED, REWARD_BELOW_QUALIFICATION, RISK_REJECTED,
    BRAIN_UNUSABLE, WINDOW_CLOSED, STOOD_DOWN,
    HELD, BUDGET_EXHAUSTED, GOVERNOR_UNPROVEN, PARTICIPATION_REFUSED,
    UNCLASSIFIED,
)

#: Producer/loop codes that are mechanical participation refusals. Each one
#: needs its typed `participation_refusal` evidence before it is accounted.
MECHANICAL_REFUSAL_CODES = frozenset({"campaign_lifecycle_refused"})

#: producer reason -> terminal disposition. Producer vocabulary is authoritative;
#: this maps it rather than renaming it, so replaying old evidence still works.
_REASON_TO_DISPOSITION = {
    "qualification_rejected": QUALIFICATION_REJECTED,
    "direction_disagreement": QUALIFICATION_REJECTED,
    "direction_invalid": QUALIFICATION_REJECTED,
    "playbook_unauthorized": QUALIFICATION_REJECTED,
    "tool_family_unauthorized": QUALIFICATION_REJECTED,
    "objective_id_missing": OBJECTIVE_ID_MISSING,
    "objective_missing": OBJECTIVE_ID_MISSING,
    "objective_id_unknown": OBJECTIVE_ID_UNKNOWN,
    "objective_unresolved": OBJECTIVE_ID_UNKNOWN,
    "objective_wrong_side": OBJECTIVE_INVALID,
    "objective_off_tick": OBJECTIVE_INVALID,
    "objective_stale": OBJECTIVE_INVALID,
    "invalidation_id_missing": INVALIDATION_ID_MISSING,
    "invalidation_missing": INVALIDATION_ID_MISSING,
    "invalidation_id_unknown": INVALIDATION_ID_UNKNOWN,
    "invalidation_id_ambiguous": INVALIDATION_INVALID,
    "invalidation_invalid": INVALIDATION_INVALID,
    "invalidation_level_mismatch": INVALIDATION_INVALID,
    "invalidation_wrong_side": INVALIDATION_INVALID,
    "invalidation_off_tick": INVALIDATION_INVALID,
    "zero_risk": GEOMETRY_REJECTED,
    "no_reference_price": GEOMETRY_REJECTED,
    "contract_mismatch": GEOMETRY_REJECTED,
    "reward_below_qualification": REWARD_BELOW_QUALIFICATION,
    "risk_rejected": RISK_REJECTED,
    "size_rejected": RISK_REJECTED,
    # FINAL-QUOTE-ECONOMICS-1: an existing proposal failed an existing
    # deterministic pre-submit check at the executable quote.
    "RISK_DRIFTED": RISK_REJECTED,
    "REWARD_COLLAPSED": REWARD_BELOW_QUALIFICATION,
    "INVALIDATION_TOUCHED": GEOMETRY_REJECTED,
    "OBJECTIVE_SWEPT": OBJECTIVE_INVALID,
    "OBJECTIVE_MATERIALLY_DELIVERED": OBJECTIVE_INVALID,
    "STREAM_STALE": QUALIFICATION_REJECTED,
    "brain_invalid": BRAIN_UNUSABLE,
    "brain_timeout": BRAIN_UNUSABLE,
    "brain_superseded": BRAIN_UNUSABLE,
    "wrong_model": BRAIN_UNUSABLE,
    "fallback_not_authoritative": BRAIN_UNUSABLE,
    "window_closed": WINDOW_CLOSED,
    "stand_down": STOOD_DOWN,
    # ACCOUNTING ONLY. The Brain has already emitted the deterministic action
    # token; this maps that exact producer reason to its terminal ledger class.
    "action_declines_entry": STOOD_DOWN,
    # PROD-20260908. `luna_candidate_producer` raises this as a STAND-DOWN
    # (`NoCandidate(..., stand_down=True)`), and it was the session's ONLY
    # rejection reason: 279 of 279 decisions. Absent from this map it fell to
    # UNCLASSIFIED, so `reconcile` returned
    # CANDIDATE_DECISION_ACCOUNTING_FAILURE for a session that had in fact
    # accounted for every scan. The reasons were durable and complete; only the
    # classifier could not count them.
    #
    # ACCOUNTING ONLY. `terminal_disposition` is read by `reconcile` and by the
    # decision ledger; no eligibility, sizing or execution path consults it.
    #
    # STILL UNMAPPED, DELIBERATELY (12, all raised by the producer):
    # action_declines_entry, candle_gap_unrecovered, derived_state_stale,
    # execution_price_unavailable, hybrid_envelope_unauthorized,
    # objective_ambiguous, tool_direction_mismatch, tool_not_detected,
    # tool_not_execution_eligible, tool_occurrence_ambiguous,
    # tool_occurrence_unknown, tool_selection_ambiguous.
    # Each needs its own ruling about which terminal disposition it IS; a bulk
    # sweep into STOOD_DOWN would trade one accounting error for a larger one.
    "session_phase_blocks_entry": STOOD_DOWN,

    # PARTICIPATION-REFUSAL-TELEMETRY (2026-10-25). PROD-20261023-C1 journaled
    # 380 of these as UNCLASSIFIED while the same scan held the exact Lifecycle
    # state and reason. Raised by CandidateProducer's Lifecycle gate and by the
    # loop's binding of a permissive assessment to its Draw authority.
    # ACCOUNTING ONLY, and deliberately NOT STOOD_DOWN: mechanics refused, the
    # Brain did not decline. `reconcile` still requires the typed evidence.
    "campaign_lifecycle_refused": PARTICIPATION_REFUSED,

    # DECISION-ACCOUNTING-HELD-1 (2026-09-23). PROD-20260922 was the first
    # session in which ENFORCE ever suppressed a call: 38 scans held, and all
    # 38 fell to UNCLASSIFIED because this reason did not exist here. With 4
    # governor refusals that made 42, and `reconcile` correctly reported
    # CANDIDATE_DECISION_ACCOUNTING_FAILURE for a session that had in fact
    # accounted for every scan. Left unrepaired, every future session that
    # holds would raise the same false alarm and bury a real one.
    #
    # DELIBERATELY NOT STOOD_DOWN. The Brain did not evaluate that scan.
    "brain_sleep_hold": HELD,

    # The daily-loss governor's own vocabulary. `_record_decision` is handed
    # `budget["state"]`, never the granular reason -- the granular reason
    # (`order_discovery_incomplete`, `venue_truth_unavailable`, ...) travels in
    # the record's `detail`, which is where it stays readable. Only refusal
    # states reach this map: `resolve` records nothing when entry is permitted,
    # so OK never appears.
    "EXHAUSTED": BUDGET_EXHAUSTED,
    "UNKNOWN": GOVERNOR_UNPROVEN,
    "CONTAMINATED": GOVERNOR_UNPROVEN,

    # The governor's GRANULAR reasons are mapped too, so the classification
    # holds whichever of the two vocabularies a caller hands over. The live
    # path passes the state; these are the same refusals named precisely.
    # `daily_loss_budget_spent` is proven exhaustion; the rest are all forms of
    # "the truth could not be established", which is never exhaustion.
    "daily_loss_budget_spent": BUDGET_EXHAUSTED,
    "order_discovery_incomplete": GOVERNOR_UNPROVEN,
    "venue_truth_unavailable": GOVERNOR_UNPROVEN,
    "unattributable_in_session_trade": GOVERNOR_UNPROVEN,
    "authorization_carries_no_daily_loss_budget": GOVERNOR_UNPROVEN,
    "daily_loss_budget_is_not_a_positive_number": GOVERNOR_UNPROVEN,
}


def terminal_disposition(reason, *, created: bool = False) -> str:
    """Exactly one machine-countable cause of death (or birth)."""
    if created:
        return CANDIDATE_CREATED
    return _REASON_TO_DISPOSITION.get(str(reason or ""), UNCLASSIFIED)


def blank_trace() -> dict:
    """Every stage field exists on every record, so absence is readable.

    A field that is simply missing cannot be distinguished from a stage that
    was never reached; `None` states plainly that the proposal died earlier.
    """
    return {
        "requested_objective_id": None, "objective_lookup_found": None,
        "resolved_objective_id": None, "resolved_objective_type": None,
        "resolved_objective_price": None, "objective_side_valid": None,
        "objective_fresh": None, "objective_resolution_status": None,
        "objective_rejection_reason": None,
        "requested_invalidation_id": None, "requested_invalidation_level": None,
        "invalidation_lookup_found": None,
        "resolved_invalidation_id": None, "resolved_invalidation_type": None,
        "resolved_invalidation_price": None, "invalidation_side_valid": None,
        "invalidation_fresh": None, "invalidation_resolution_status": None,
        "invalidation_rejection_reason": None,
        # Contextual mechanical opinion beside the sovereign action. Historical
        # records with session_phase_authorized remain readable as old records.
        "session_phase": None, "session_phase_authority_class": None,
        "session_phase_mechanical_posture": None,
        "session_phase_mechanical_reason": None,
        "session_phase_brain_disagreed": None,
        "session_phase_authorized": None,
        "qualification_result": None, "qualification_reason": None,
        "direction_agreement": None, "playbook_authorized": None,
        # ROADMAP STEP 7 (2026-08-12) — did Terra's selected execution
        # expression physically exist, on the right side, and settled?
        "tool_authorized": None, "tool_selected": None, "tool_catalog": None,
        "tool_detected": None, "tool_execution_eligible": None,
        "tool_matched": None, "tool_matched_source_tf": None,
        "tool_rejection_reason": None,
        "geometry_valid": None, "geometry_reason": None,
        "reward_risk": None, "reward_risk_floor": None, "reward_risk_valid": None,
        # RR-FLOOR-1.0 counterfactual (2026-08-08). Observational.
        "legacy_reward_risk_floor": None, "legacy_floor_verdict": None,
        "eligible_only_because_floor_moved": None,
        "risk_dollars": None, "contract_count": None, "risk_valid": None,
    }


def build_record(*, session_id: str, scan_id: str, timestamp_et: str,
                 instrument: str, contract: str, parsed: dict, trace: dict,
                 disposition: str, rejection_reason=None,
                 detail: str = "", execution_economics: dict = None) -> dict:
    """One complete decision record. Carries no secrets and no account ids."""
    parsed = parsed or {}
    record = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id or "UNSCOPED",
        "scan_id": scan_id, "timestamp_et": timestamp_et,
        "instrument": instrument, "contract": contract,
        "direction": parsed.get("narrative_direction"),
        "action": str(parsed.get("current_action") or "")[:120],
        "playbook": parsed.get("recommended_playbook_family"),
    }
    record.update(blank_trace())
    record.update({k: v for k, v in (trace or {}).items() if k in blank_trace()})
    record["final_disposition"] = disposition
    record["final_rejection_reason"] = rejection_reason
    record["detail"] = str(detail)[:300]
    if execution_economics is not None:
        record["execution_economics"] = dict(execution_economics)
    return record


# ── participation-refusal evidence (v2) ─────────────────────────────────────
#
# PARTICIPATION-REFUSAL-TELEMETRY (2026-10-25). Copied, bounded and typed from
# the SAME scan's own objects; nothing here re-evaluates Lifecycle, re-derives
# a reason from a state label, reads private runtime state or reconstructs
# authority. What the scan does not carry is written UNKNOWN/ABSENT with the
# reason it is missing. EVIDENCE IS NOT AUTHORITY: no participation, risk or
# execution path reads any of these fields.

LIFECYCLE_ASSESSMENT_SCHEMA = "campaign_lifecycle_assessment.v1"
PARTICIPATION_REFUSAL_SCHEMA = "participation_refusal.v1"
#: The two real gates that raise `campaign_lifecycle_refused`.
PRODUCER_LIFECYCLE_GATE = "PRODUCER_LIFECYCLE_GATE"
LOOP_PARTICIPATION_BINDING = "LOOP_PARTICIPATION_BINDING"
KNOWN_GATES = (PRODUCER_LIFECYCLE_GATE, LOOP_PARTICIPATION_BINDING)
_GATE_FUNCTION = {
    PRODUCER_LIFECYCLE_GATE: "broker.luna_candidate_producer.CandidateProducer.produce "
                             "-> market_data.campaign_lifecycle.participation_permission",
    LOOP_PARTICIPATION_BINDING: "broker.topstepx_production_loop.ProductionLoop "
                                "-> market_data.campaign_lifecycle.participation_authority_bound",
}
_REFUSING_STATES = ("UNESTABLISHED", "ESTABLISHING", "RETRACING", "DESTINATION_SUBSTANTIALLY_DELIVERED",
                    "TRANSFER_UNRESOLVED", "AUTHORITY_UNKNOWN")
_PERMITTED_STATES = ("ACTIVE_DELIVERY",)
_ASSESSMENT_UNAVAILABLE = "current_campaign_lifecycle_assessment_unavailable"
_LIFECYCLE_FIELDS = ("schema_version", "state", "reason", "participation_permitted",
                     "authorized_direction", "campaign_episode_id", "objective_identity",
                     "campaign_draw_status", "narrative_control_state", "narrative_phase")
_BINDING_FIELDS = ("record_id", "session_id", "contract_id", "campaign_direction", "campaign_episode_id",
                   "objective_identity", "anchor_bar_time", "history_revision", "settled_cutoff",
                   "authority_status", "superseded", "history_complete", "coverage_status",
                   "progress_authoritative")
_DRAW_FIELDS = ("record_id", "authority_status", "authority_reason", "participation_withheld_reason",
                "withheld_record_id", "withheld_authority_status", "coverage_status", "history_complete",
                "history_revision", "settled_cutoff", "superseded", "session_id", "contract_id",
                "campaign_direction", "campaign_episode_id", "objective_identity", "anchor_bar_time")
_TEXT_LIMIT = 200
_LIST_LIMIT = 8


def _safe(value, depth: int = 0):
    """JSON-safe and bounded: scalars, short strings, small lists/dicts only."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return value[:_TEXT_LIMIT]
    if depth >= 2:
        return str(value)[:_TEXT_LIMIT]
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth + 1) for v in list(value)[:_LIST_LIMIT]]
    if isinstance(value, dict):
        return {str(k)[:64]: _safe(v, depth + 1) for k, v in list(value.items())[:24]}
    return str(value)[:_TEXT_LIMIT]


def _pick(source: dict, fields) -> dict:
    return {k: _safe(source.get(k)) for k in fields}


def _unknown(reason: str, **extra) -> dict:
    return {"status": "UNKNOWN", "unknown_reason": reason, **extra}


def _lifecycle_assessment(scan: dict, *, contract_id: str, session_id: str) -> dict:
    """The assessment the gate consumed: `scan.snapshot.campaign_lifecycle`."""
    snapshot = scan.get("snapshot") if isinstance(scan.get("snapshot"), dict) else {}
    out = {"schema": LIFECYCLE_ASSESSMENT_SCHEMA, "source": "scan.snapshot.campaign_lifecycle"}
    assessment = snapshot.get("campaign_lifecycle")
    if not isinstance(assessment, dict):
        out.update(_unknown("scan_lifecycle_assessment_absent"))
        return out
    snap_contract = snapshot.get("contract_id")
    if snap_contract and contract_id and str(snap_contract) != str(contract_id):
        out.update(_unknown("foreign_contract_snapshot", snapshot_contract=_safe(snap_contract)))
        return out
    out["status"] = "AVAILABLE"
    out.update(_pick(assessment, _LIFECYCLE_FIELDS))
    binding = assessment.get("campaign_draw_binding")
    out["campaign_draw_binding"] = (_pick(binding, _BINDING_FIELDS) if isinstance(binding, dict) else None)
    if isinstance(binding, dict):
        same = ((not session_id or binding.get("session_id") in (None, session_id))
                and (not contract_id or binding.get("contract_id") in (None, contract_id)))
        out["binding_scope_matches_loop"] = bool(same)
    else:
        out["binding_scope_matches_loop"] = None
    # The scan-level copy is the pre-gate projection; a conditional trigger
    # re-evaluates the snapshot's. Say so rather than silently pick one.
    scan_level = scan.get("campaign_lifecycle")
    out["scan_level_copy_differs"] = bool(isinstance(scan_level, dict) and scan_level != assessment)
    return out


def _draw_evidence(scan: dict) -> dict:
    authority = scan.get("campaign_draw_authority")
    if not isinstance(authority, dict):
        snap = scan.get("snapshot") if isinstance(scan.get("snapshot"), dict) else {}
        authority = snap.get("campaign_draw_authority")
    if not isinstance(authority, dict):
        return _unknown("scan_participation_draw_absent", source="scan.campaign_draw_authority")
    return {"status": "AVAILABLE", "source": "scan.campaign_draw_authority", **_pick(authority, _DRAW_FIELDS)}


def _acceptance_evidence(scan: dict) -> dict:
    acceptance = scan.get("campaign_draw_acceptance")
    if acceptance is None:
        # The scan cycle publishes None when no acceptance occurred this scan.
        return {"status": "ABSENT", "reason": "no_acceptance_published_this_scan",
                "source": "scan.campaign_draw_acceptance"}
    if not isinstance(acceptance, dict):
        return _unknown("acceptance_not_an_object", source="scan.campaign_draw_acceptance")
    return {"status": "AVAILABLE", "source": "scan.campaign_draw_acceptance",
            **{k: _safe(v) for k, v in list(acceptance.items())[:24]}}


def _scope_evidence(scan: dict) -> dict:
    snap = scan.get("snapshot") if isinstance(scan.get("snapshot"), dict) else {}
    outcome = snap.get("campaign_scope_proposal_outcome")
    if outcome is None:
        return {"status": "ABSENT", "reason": "no_scope_proposal_outcome_this_scan",
                "source": "scan.snapshot.campaign_scope_proposal_outcome"}
    if not isinstance(outcome, dict):
        return _unknown("scope_outcome_not_an_object")
    keep = ("status", "reasons", "proposal_id", "cutoff", "premise_candidate_id", "direction", "kind")
    return {"source": "scan.snapshot.campaign_scope_proposal_outcome",
            **{k: _safe(outcome.get(k)) for k in keep if k in outcome},
            "outcome_status": _safe(outcome.get("status"))}


def _intent(scan: dict, parsed: dict, *, contract_id: str) -> dict:
    """Authored (pre-hold) beside consumed (post-guard) intent, from the existing envelope."""
    block = scan.get("brain_block") if isinstance(scan.get("brain_block"), dict) else {}
    consumed = {"source": "scan.brain_block.output (post-guard, consumed)",
                "action": _safe(parsed.get("current_action")),
                "direction": _safe(parsed.get("narrative_direction"))}
    read = block.get("authored_market_read")
    if not isinstance(read, dict) or read.get("status") != "AVAILABLE":
        reason = (read or {}).get("reason") if isinstance(read, dict) else None
        authored = _unknown(f"authored_read_unavailable:{reason or 'absent'}"[:_TEXT_LIMIT])
    else:
        prov = read.get("provenance") if isinstance(read.get("provenance"), dict) else {}
        snap = scan.get("snapshot") if isinstance(scan.get("snapshot"), dict) else {}
        if prov.get("contract_id") and contract_id and prov.get("contract_id") != contract_id:
            authored = _unknown("authored_read_foreign_contract")
        elif prov.get("settled_cutoff") and snap.get("timestamp") and \
                str(prov.get("settled_cutoff")) != str(snap.get("timestamp")):
            authored = _unknown("authored_read_other_cutoff")
        else:
            authored = {"status": "AVAILABLE",
                        "source": "scan.brain_block.authored_market_read (validated primary, pre-hold)",
                        "action": _safe(read.get("authored_action")),
                        "direction": _safe(read.get("narrative_direction")),
                        "pre_hold_output_digest": _safe(prov.get("pre_hold_output_digest"))}
    return {"authored": authored, "consumed": consumed,
            "note": "observational intent only; never participation authority"}


def _gate(reason, refusal, producer_current: bool, producer_trace) -> tuple:
    """(gate, basis, observed_gate_reason, problems) from the actual raiser."""
    problems = []
    detail = getattr(refusal, "detail", None) if refusal is not None else None
    raised_by_producer = refusal is not None and getattr(refusal, "decision_trace", None) is not None
    if refusal is None:
        return None, "refusal_object_unavailable", None, ["refusal_object_unavailable"]
    if getattr(refusal, "reason", reason) != reason:
        problems.append("refusal_object_reason_mismatch")
    if raised_by_producer and producer_current:
        gate, basis = PRODUCER_LIFECYCLE_GATE, ("NoCandidate.decision_trace attached by CandidateProducer"
                                                ".produce; loop marked this scan as the producer owner")
        trace = producer_trace if isinstance(producer_trace, dict) else {}
        if trace.get("campaign_lifecycle_refusal") not in (None, detail):
            problems.append("producer_trace_reason_disagrees_with_refusal")
    elif raised_by_producer:
        gate, basis = None, "producer_refusal_without_current_scan_marker"
        problems.append(basis)
    elif not producer_current:
        gate, basis = LOOP_PARTICIPATION_BINDING, ("raised by ProductionLoop before produce(); "
                                                   "producer not invoked for this scan")
    else:
        gate, basis = None, "producer_marked_but_refusal_not_from_producer"
        problems.append(basis)
    observed = detail if isinstance(detail, str) and detail.strip() else None
    if observed is None:
        problems.append("observed_gate_reason_missing")
    return gate, basis, observed, problems


def participation_evidence(*, scan: dict, parsed: dict, reason, refusal=None, producer_current: bool = False,
                           producer_trace=None, session_id: str = "", contract_id: str = "") -> dict:
    """The v2 fields for one decision record. Never raises."""
    try:
        scan = scan if isinstance(scan, dict) else {}
        parsed = parsed if isinstance(parsed, dict) else {}
        assessment = _lifecycle_assessment(scan, contract_id=contract_id, session_id=session_id)
        trace = producer_trace if (producer_current and isinstance(producer_trace, dict)) else None
        out = {"schema_version": SCHEMA_VERSION_V2, "campaign_lifecycle_assessment": assessment,
               "producer_execution": {
                   "executed_this_scan": bool(producer_current),
                   "trace_lifecycle_state": _safe((trace or {}).get("campaign_lifecycle_state")),
                   "trace_lifecycle_refusal": _safe((trace or {}).get("campaign_lifecycle_refusal")),
                   "note": "a scan-level assessment never implies the producer ran"},
               "participation_refusal": None}
        if str(reason or "") not in MECHANICAL_REFUSAL_CODES:
            return out
        gate, basis, observed, problems = _gate(reason, refusal, producer_current, trace)
        snapshot = scan.get("snapshot") if isinstance(scan.get("snapshot"), dict) else {}
        state = assessment.get("state")
        if assessment.get("status") == "AVAILABLE":
            if gate == PRODUCER_LIFECYCLE_GATE and trace is not None and \
                    trace.get("campaign_lifecycle_state") not in (None, state):
                problems.append("producer_trace_state_disagrees_with_assessment")
            if gate == LOOP_PARTICIPATION_BINDING and assessment.get("participation_permitted") is not True:
                problems.append("binding_refusal_on_non_permissive_assessment")
            if gate == PRODUCER_LIFECYCLE_GATE and isinstance(observed, str) and \
                    observed.startswith("campaign_lifecycle_refused:") and \
                    observed.split(":", 1)[1] != str(state):
                problems.append("gate_state_label_disagrees_with_assessment")
        out["participation_refusal"] = {
            "schema": PARTICIPATION_REFUSAL_SCHEMA, "code": str(reason),
            "gate": gate, "gate_basis": basis,
            "observed_gate_reason": _safe(observed), "observed_gate_reason_source": "NoCandidate.detail",
            # A pointer for a reader, NOT an observed reason.
            "diagnostic_reference": {"function": _GATE_FUNCTION.get(gate),
                                     "kind": "DIAGNOSTIC_POINTER_NOT_OBSERVATION"},
            "lifecycle_state": _safe(state) if assessment.get("status") == "AVAILABLE" else None,
            "lifecycle_reason": _safe(assessment.get("reason")) if assessment.get("status") == "AVAILABLE" else None,
            "lifecycle_status": assessment.get("status"),
            "participation_permitted": assessment.get("participation_permitted"),
            "authorized_direction": assessment.get("authorized_direction"),
            "narrative_control_state": assessment.get("narrative_control_state"),
            "narrative_phase": assessment.get("narrative_phase"),
            "campaign_episode_id": assessment.get("campaign_episode_id"),
            "objective_identity": assessment.get("objective_identity"),
            "identity": {"scan_id": _safe(scan.get("snapshot_id")), "scan_count": _safe(scan.get("scan_count")),
                         "contract": _safe(contract_id), "session_id": _safe(session_id),
                         "settled_cutoff": _safe(snapshot.get("timestamp"))},
            "draw": _draw_evidence(scan), "current_acceptance": _acceptance_evidence(scan),
            "scope_proposal": _scope_evidence(scan),
            "intent": _intent(scan, parsed, contract_id=contract_id),
            "downstream": {"stages_after_gate": "NOT_REACHED",
                           "producer": ("EXECUTED_REFUSED_AT_LIFECYCLE" if gate == PRODUCER_LIFECYCLE_GATE
                                        else "NOT_REACHED" if gate == LOOP_PARTICIPATION_BINDING
                                        else "UNKNOWN")},
            "consistency_problems": problems,
        }
        return out
    except Exception as exc:  # noqa: BLE001 -- evidence must never gate a scan
        return {"schema_version": SCHEMA_VERSION_V2,
                "campaign_lifecycle_assessment": _unknown(f"capture_error:{type(exc).__name__}"),
                "participation_refusal": (_unknown(f"capture_error:{type(exc).__name__}")
                                          if str(reason or "") in MECHANICAL_REFUSAL_CODES else None)}


def attach_participation_evidence(record: dict, **kwargs) -> dict:
    """Upgrade one live record to v2 in place. Never raises."""
    try:
        record.update(participation_evidence(parsed=kwargs.pop("parsed", None) or {
            "current_action": record.get("action"), "narrative_direction": record.get("direction")}, **kwargs))
    except Exception:  # noqa: BLE001
        pass
    return record


def refusal_problems(record: dict) -> list:
    """Why a PARTICIPATION_REFUSED record is not (yet) accounted; [] when complete."""
    if record.get("schema_version") != SCHEMA_VERSION_V2:
        return ["legacy_record_lacks_participation_refusal_evidence"]
    reason = record.get("final_rejection_reason")
    if reason not in MECHANICAL_REFUSAL_CODES:
        return ["refusal_code_not_a_known_mechanical_refusal"]
    block = record.get("participation_refusal")
    if not isinstance(block, dict) or block.get("schema") != PARTICIPATION_REFUSAL_SCHEMA:
        return ["participation_refusal_evidence_missing_or_malformed"]
    problems = []
    if block.get("code") != reason:
        problems.append("evidence_code_disagrees_with_record")
    if block.get("gate") not in KNOWN_GATES:
        problems.append("gate_unknown")
    observed = block.get("observed_gate_reason")
    if not isinstance(observed, str) or not observed.strip():
        problems.append("observed_gate_reason_missing")
    identity = block.get("identity") if isinstance(block.get("identity"), dict) else {}
    for key in ("scan_id", "contract"):
        if not isinstance(identity.get(key), str) or not identity.get(key).strip():
            problems.append(f"identity_{key}_missing")
    if identity.get("scan_id") != record.get("scan_id") or identity.get("contract") != record.get("contract"):
        problems.append("identity_disagrees_with_record")
    if block.get("lifecycle_status") == "AVAILABLE":
        if block.get("gate") == PRODUCER_LIFECYCLE_GATE and block.get("lifecycle_state") not in \
                _REFUSING_STATES + _PERMITTED_STATES:
            problems.append("lifecycle_state_unrecognized")
        if block.get("gate") == LOOP_PARTICIPATION_BINDING and block.get("lifecycle_state") not in _PERMITTED_STATES:
            problems.append("lifecycle_state_unrecognized")
        if not isinstance(block.get("lifecycle_reason"), str) or not block.get("lifecycle_reason").strip():
            problems.append("lifecycle_reason_missing")
    elif observed != _ASSESSMENT_UNAVAILABLE:
        problems.append("lifecycle_assessment_unknown")
    if block.get("consistency_problems"):
        problems.extend(f"inconsistent:{p}" for p in block["consistency_problems"])
    return problems


def _contradiction(record: dict):
    """v2 only: the stored disposition must be the classifier's own verdict."""
    d = record.get("final_disposition")
    reason = record.get("final_rejection_reason")
    if d in (CANDIDATE_CREATED, CONDITIONAL_PLAN_PUBLISHED):
        return None if reason in (None, "") else "terminal_success_with_rejection_reason"
    expected = terminal_disposition(reason)
    if expected != d:
        return f"disposition_{d}_contradicts_reason_{reason}"
    return None


def reconcile(records: list) -> dict:
    """terra_proposals == sum(terminal dispositions), or say so.

    v1 records keep their original semantics exactly. A PARTICIPATION_REFUSED
    record is accounted only with complete v2 evidence (`refusal_problems`);
    a v2 record whose disposition contradicts its own reason is never green.
    """
    counts: dict = {}
    unclassified = incomplete = contradictory = 0
    problems: list = []
    schemas: dict = {}
    for r in records or []:
        r = r if isinstance(r, dict) else {}
        version = r.get("schema_version") if r.get("schema_version") in SCHEMA_VERSIONS else "UNKNOWN_SCHEMA"
        schemas[version] = schemas.get(version, 0) + 1
        d = r.get("final_disposition") or UNCLASSIFIED
        if d not in TERMINAL_DISPOSITIONS:
            d = UNCLASSIFIED
        counts[d] = counts.get(d, 0) + 1
        if d == UNCLASSIFIED:
            unclassified += 1
        if d == PARTICIPATION_REFUSED:
            found = refusal_problems(r)
            if found:
                incomplete += 1
                problems.append({"scan_id": r.get("scan_id"), "problems": found[:6]})
        if version == SCHEMA_VERSION_V2:
            clash = _contradiction(r)
            if clash:
                contradictory += 1
                problems.append({"scan_id": r.get("scan_id"), "problems": [clash]})
    total = sum(counts.values())
    balanced = (total == len(records or []) and unclassified == 0
                and incomplete == 0 and contradictory == 0)
    return {
        "terra_proposals": len(records or []),
        "dispositions": dict(sorted(counts.items())),
        "disposition_total": total,
        "unclassified": unclassified,
        "participation_refusal_incomplete": incomplete,
        "contradictory": contradictory,
        "schema_versions": dict(sorted(schemas.items())),
        "problems": problems[:50],
        "status": "RECONCILED" if balanced
                  else "CANDIDATE_DECISION_ACCOUNTING_FAILURE",
    }

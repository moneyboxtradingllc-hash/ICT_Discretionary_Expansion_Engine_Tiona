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

# ── terminal dispositions ────────────────────────────────────────────────────
CANDIDATE_CREATED = "CANDIDATE_CREATED"
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
UNCLASSIFIED = "UNCLASSIFIED"

TERMINAL_DISPOSITIONS = (
    CANDIDATE_CREATED, QUALIFICATION_REJECTED,
    OBJECTIVE_ID_MISSING, OBJECTIVE_ID_UNKNOWN, OBJECTIVE_INVALID,
    INVALIDATION_ID_MISSING, INVALIDATION_ID_UNKNOWN, INVALIDATION_INVALID,
    GEOMETRY_REJECTED, REWARD_BELOW_QUALIFICATION, RISK_REJECTED,
    BRAIN_UNUSABLE, WINDOW_CLOSED, STOOD_DOWN, UNCLASSIFIED,
)

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
    "invalidation_wrong_side": INVALIDATION_INVALID,
    "invalidation_off_tick": INVALIDATION_INVALID,
    "zero_risk": GEOMETRY_REJECTED,
    "no_reference_price": GEOMETRY_REJECTED,
    "contract_mismatch": GEOMETRY_REJECTED,
    "reward_below_qualification": REWARD_BELOW_QUALIFICATION,
    "risk_rejected": RISK_REJECTED,
    "size_rejected": RISK_REJECTED,
    "brain_invalid": BRAIN_UNUSABLE,
    "brain_timeout": BRAIN_UNUSABLE,
    "brain_superseded": BRAIN_UNUSABLE,
    "wrong_model": BRAIN_UNUSABLE,
    "fallback_not_authoritative": BRAIN_UNUSABLE,
    "window_closed": WINDOW_CLOSED,
    "stand_down": STOOD_DOWN,
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
        "requested_invalidation_id": None, "invalidation_lookup_found": None,
        "resolved_invalidation_id": None, "resolved_invalidation_type": None,
        "resolved_invalidation_price": None, "invalidation_side_valid": None,
        "invalidation_fresh": None, "invalidation_resolution_status": None,
        "invalidation_rejection_reason": None,
        # LUNA-SESSION-PO3-AUTHORITY-1 — the canonical session phase, and whether
        # it authorized a NEW entry. First stage of the funnel, so a record whose
        # every other stage is None still says why.
        "session_phase": None, "session_phase_authorized": None,
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
                 detail: str = "") -> dict:
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
    return record


def reconcile(records: list) -> dict:
    """terra_proposals == sum(terminal dispositions), or say so."""
    counts: dict = {}
    unclassified = 0
    for r in records or []:
        d = r.get("final_disposition") or UNCLASSIFIED
        if d not in TERMINAL_DISPOSITIONS:
            d = UNCLASSIFIED
        counts[d] = counts.get(d, 0) + 1
        if d == UNCLASSIFIED:
            unclassified += 1
    total = sum(counts.values())
    balanced = total == len(records or []) and unclassified == 0
    return {
        "terra_proposals": len(records or []),
        "dispositions": dict(sorted(counts.items())),
        "disposition_total": total,
        "unclassified": unclassified,
        "status": "RECONCILED" if balanced
                  else "CANDIDATE_DECISION_ACCOUNTING_FAILURE",
    }

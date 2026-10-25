"""Dual-standard report for the current-Brain evaluation (schema + mechanical first pass).

PREPARED. Codex contract 2026-10-25/1. Two standards are reported separately
and never merged into one score:

  COGNITIVE      what the Brain itself read and intended at each sealed primary
                 decision: the PRE-guard reply (raw provider content) is the
                 Brain's own intent; the post-guard output is what production
                 consumed. Recognition truth is UNPROVEN wherever no owner
                 reference exists, so only the sealed constructed expectations
                 (the two negative cases' expected restraint) are scored.
  PARTICIPATION  what the whole system did with that cognition: candidate,
                 plan, or the first real gate that refused, each refusal given
                 exactly one of the six contract classes.

An all-refusal participation result cannot pass. A run with any
BUDGET_PROVIDER_OR_RUN_FAILURE is INCOMPLETE, never a pass or a fail.

The first pass assigns only what the recorded facts decide without trading
judgment (run failures; Brain no-entry intent; restraint matching a sealed
negative basis). Every other refusal is left UNCLASSIFIED for the audit, with
the three remaining classes as its candidates: the harness never chooses
doctrine.
"""
from __future__ import annotations

import json

REPORT_SCHEMA = "current_brain_eval_report/v1"
REFUSAL_CLASSES = ("CORRECT_RESTRAINT", "BRAIN_NO_ENTRY_INTENT", "MISSING_OR_UNPROVEN_EVIDENCE",
                   "PRODUCER_CONSUMER_DEFECT", "AUTHORITY_CONTRACT_MISMATCH_OR_GAP",
                   "BUDGET_PROVIDER_OR_RUN_FAILURE")
AUDIT_CANDIDATES = ("MISSING_OR_UNPROVEN_EVIDENCE", "PRODUCER_CONSUMER_DEFECT", "AUTHORITY_CONTRACT_MISMATCH_OR_GAP")
ENTRY_ACTIONS = frozenset({"propose_entry", "watching"})
PARTICIPATION = frozenset({"QUALIFIED_CANDIDATE_OBSERVED", "CONDITIONAL_PLAN_PUBLISHED", "CONDITIONAL_TRIGGER"})
NEGATIVE_CASES = frozenset({"NEGATIVE_INTACT_RETRACEMENT", "NEGATIVE_UNSUPPORTED_TRANSFER"})

#: The row every sealed primary decision produces (fields marked * come from the recorded run, never the model).
DECISION_ROW = {
    "trajectory_id": "*", "lane": "ecu | non_ecu", "case": "plan trajectory case", "decision_time_utc": "*",
    "settled_cutoff": "*", "wallclock_started_at": "* real UTC when the request was sent",
    "call": {"record_status": "COMPLETE | REFUSED | INCOMPLETE", "evaluation_origin": "CURRENT_EXTERNAL only",
             "served_model": "*", "provider_request_id": "*", "usage": "*", "budget_reservation_id": "*",
             "repairs": "* count", "fallback_reason": "*"},
    "cognitive": {"pre_guard_action": "raw reply current_action", "pre_guard_direction": "raw narrative_direction",
                  "post_guard_action": "consumed", "post_guard_direction": "consumed",
                  "guard_changed_intent": "bool", "descriptive_market_read": "observational only",
                  "expected": "sealed constructed expectation or UNPROVEN", "cognitive_result": "see COGNITIVE_RESULTS"},
    "participation": {"outcome": "* loop outcome", "first_refusal_code": "*", "lifecycle_state": "*",
                      "lifecycle_reason": "*", "candidate_present": "*", "plan_present": "*",
                      "refusal_class": "one of REFUSAL_CLASSES | UNCLASSIFIED | null (participated)",
                      "classification_basis": "recorded fact that decided it", "assigned_by":
                      "MECHANICAL_FIRST_PASS | AUDIT", "audit_candidates": "for UNCLASSIFIED only"},
}
COGNITIVE_RESULTS = ("RESTRAINED_AS_EXPECTED", "ENTRY_INTENT_ON_NEGATIVE", "UNSCORED_NO_REFERENCE", "NO_COGNITION")


def report_schema() -> dict:
    return {"schema": REPORT_SCHEMA, "standards": ["COGNITIVE", "PARTICIPATION"],
            "refusal_classes": list(REFUSAL_CLASSES), "audit_candidates": list(AUDIT_CANDIDATES),
            "cognitive_results": list(COGNITIVE_RESULTS), "decision_row": DECISION_ROW,
            "verdict_rules": [
                "any BUDGET_PROVIDER_OR_RUN_FAILURE, missing primary, or non-CURRENT_EXTERNAL origin -> INCOMPLETE",
                "participation: zero participating decisions across the 34 primaries -> NOT_PASSED_ALL_REFUSAL "
                "(an all-refusal result cannot pass, whatever its classes)",
                "participation: any UNCLASSIFIED or PRODUCER_CONSUMER_DEFECT / AUTHORITY_CONTRACT_MISMATCH_OR_GAP "
                "-> AUDIT_REQUIRED before any pass",
                "cognitive: any ENTRY_INTENT_ON_NEGATIVE is reported as a cognitive failure on that case",
                "lanes are reported separately and never pooled"],
            "pass_authority": "Codex audit and owner; this schema never certifies a pass by itself"}


def _intent(output):
    if not isinstance(output, dict):
        return None, None
    return output.get("current_action"), output.get("narrative_direction")


def parse_raw(content):
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def classify(*, case: str, call: dict | None, raw: dict | None, post: dict | None, scan: dict,
             negative_basis: dict | None = None) -> dict:
    """One sealed primary decision -> its cognitive result and participation class (first pass)."""
    pre_action, pre_direction = _intent(raw)
    post_action, post_direction = _intent(post)
    status = (call or {}).get("record_status")
    run_failure = (call is None or status != "COMPLETE" or (call or {}).get("evaluation_origin") != "CURRENT_EXTERNAL"
                   or scan.get("infrastructure_error"))
    cognitive = {"pre_guard_action": pre_action, "pre_guard_direction": pre_direction,
                 "post_guard_action": post_action, "post_guard_direction": post_direction,
                 "guard_changed_intent": (pre_action, pre_direction) != (post_action, post_direction)
                 if raw is not None and post is not None else None,
                 "descriptive_market_read": (raw or {}).get("descriptive_market_read")}
    negative = case in NEGATIVE_CASES
    if raw is None:
        cognitive["cognitive_result"] = "NO_COGNITION"
    elif negative:
        cognitive["cognitive_result"] = ("ENTRY_INTENT_ON_NEGATIVE" if pre_action in ENTRY_ACTIONS
                                         else "RESTRAINED_AS_EXPECTED")
    else:
        cognitive["cognitive_result"] = "UNSCORED_NO_REFERENCE"
    participated = scan.get("outcome") in PARTICIPATION or bool(scan.get("candidate_present"))
    participation = {k: scan.get(k) for k in ("outcome", "first_refusal_code", "lifecycle_state", "lifecycle_reason",
                                              "candidate_present")}
    participation.update(refusal_class=None, classification_basis=None, assigned_by="MECHANICAL_FIRST_PASS",
                         audit_candidates=None)
    if run_failure:
        participation.update(refusal_class="BUDGET_PROVIDER_OR_RUN_FAILURE",
                             classification_basis=f"call {status or 'ABSENT'} / origin "
                                                  f"{(call or {}).get('evaluation_origin')} / "
                                                  f"{(call or {}).get('fallback_reason')}")
    elif participated:
        participation["classification_basis"] = f"participated: {scan.get('outcome')}"
    elif pre_action not in ENTRY_ACTIONS:
        participation.update(refusal_class="BRAIN_NO_ENTRY_INTENT",
                             classification_basis=f"pre-guard current_action={pre_action!r}")
    elif negative and negative_basis and scan.get("lifecycle_state") in negative_basis.get("lifecycle_states", ()):
        participation.update(refusal_class="CORRECT_RESTRAINT",
                             classification_basis=f"sealed negative basis: lifecycle {scan.get('lifecycle_state')} "
                                                  f"/ {scan.get('first_refusal_code')}")
    else:
        participation.update(refusal_class="UNCLASSIFIED", audit_candidates=list(AUDIT_CANDIDATES),
                             classification_basis=f"entry intent refused at {scan.get('first_refusal_code')} "
                                                  f"(lifecycle {scan.get('lifecycle_state')}); needs audit")
    return {"cognitive": cognitive, "participation": participation}


def verdict(rows: list, *, expected_primaries: int) -> dict:
    """Per-lane and overall verdicts over classified rows (never a certification)."""
    out = {}
    for lane in sorted({r["lane"] for r in rows}) + ["ALL"]:
        subset = [r for r in rows if lane == "ALL" or r["lane"] == lane]
        want = expected_primaries if lane == "ALL" else expected_primaries // 2
        classes = [r["participation"]["refusal_class"] for r in subset]
        participated = sum(1 for c in classes if c is None)
        if len(subset) != want or "BUDGET_PROVIDER_OR_RUN_FAILURE" in classes:
            participation = "INCOMPLETE"
        elif participated == 0:
            participation = "NOT_PASSED_ALL_REFUSAL"
        elif any(c in ("UNCLASSIFIED", "PRODUCER_CONSUMER_DEFECT", "AUTHORITY_CONTRACT_MISMATCH_OR_GAP")
                 for c in classes):
            participation = "AUDIT_REQUIRED"
        else:
            participation = "ELIGIBLE_FOR_AUDIT_PASS"
        cognitive = [r["cognitive"]["cognitive_result"] for r in subset]
        out[lane] = {"decisions": len(subset), "participated": participated,
                     "refusal_classes": {c: classes.count(c) for c in REFUSAL_CLASSES + ("UNCLASSIFIED",)
                                         if classes.count(c)},
                     "participation_verdict": participation,
                     "cognitive_results": {c: cognitive.count(c) for c in COGNITIVE_RESULTS if cognitive.count(c)},
                     "cognitive_failures_on_negatives": cognitive.count("ENTRY_INTENT_ON_NEGATIVE")}
    return out

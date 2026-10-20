"""result/v1 assembly and the human-readable per-session/trajectory report.

The artifact status is authoritative; rendering it never upgrades a claim.
Current discretionary recognition stays UNPROVEN unless a Mode C trajectory
was scored on sealed owner truth under a ratified plan with every threshold
PASS AND both the recognition ratification and Stage 4 owner acceptance refs
exist -- and even then it is only ELIGIBLE_FOR_OWNER_REVIEW, never accepted.
"""
from __future__ import annotations

import json
from pathlib import Path

from recognition_validation import contracts as C

MANIFEST = "RUN_MANIFEST.json"


def read_manifest(root) -> dict | None:
    path = Path(root) / MANIFEST
    if not path.exists():
        return None
    manifest = C.loads_strict(path.read_text(encoding="utf-8"), pointer="/" + MANIFEST)
    if manifest.get("seal"):
        C.require(manifest["seal"]["sha256"] == C.seal_digest(manifest), "ARTIFACT_MANIFEST_SEAL_MISMATCH", "/seal")
        for ref in manifest.get("trace_refs", []):
            C.verify_artifact(ref, root, "/trace_refs")
        for name in ("run_config_ref", "schedule_ref"):
            if manifest.get(name):
                C.verify_artifact(manifest[name], root, "/" + name)
    return manifest


def required_units(corpus: dict, scored: list) -> list:
    """Every EVALUATION session the corpus names, with each scored trajectory for it.

    A session whose trajectory was never scored still owes every rule (its
    trajectory_id is null). Only an OWNER_RATIFIED corpus's own EXCLUDED
    session with recorded reasons leaves the set; nothing else is excluded here.
    """
    ratified = corpus["selection_state"] == "OWNER_RATIFIED"
    units = []
    for session in corpus["sessions"]:
        if session["partition"] != "EVALUATION":
            continue
        if ratified and session["eligibility"] == "EXCLUDED" and session["exclusion_reasons"]:
            continue
        trajectories = sorted({s["summary"]["trajectory_id"] for s in scored
                               if s["summary"]["session_id"] == session["session_id"]})
        units += [{"session_id": session["session_id"], "trajectory_id": t} for t in trajectories or [None]]
    return units


def _obligation(unit: dict, rule: dict, item: dict | None) -> dict:
    from recognition_validation.scoring import rule_holds
    base = {"session_id": unit["session_id"], "trajectory_id": unit["trajectory_id"], "metric": rule["metric"],
            "operator": rule["operator"], "threshold_value": rule["value"], "decision_ref": rule["decision_ref"],
            "numerator": None, "denominator": None, "value": None}
    if item is None:
        return {**base, "status": "UNPROVEN", "reason": "REQUIRED_TRAJECTORY_NOT_SCORED"}
    metric = next((m for m in item["summary"]["metrics"] if m["name"] == rule["metric"]), None)
    if metric is None:
        return {**base, "status": "UNPROVEN", "reason": "RULE_METRIC_ABSENT"}
    base.update(numerator=metric["numerator"], denominator=metric["denominator"], value=metric["value"])
    if not item["inclusion"]["current_recognition_eligible"]:
        return {**base, "status": "UNPROVEN", "reason": "NOT_CURRENT_RECOGNITION_ELIGIBLE"}
    if metric["denominator"] == 0:
        return {**base, "status": "UNPROVEN", "reason": "ZERO_DENOMINATOR"}
    status = "PASS" if rule_holds(metric["value"], rule) else "FAIL"
    if metric["threshold_ref"] == rule["decision_ref"]:
        C.require(metric["assessment"] == status, "RULE_ASSESSMENT_MISMATCH",
                  f"/session_summaries/{unit['session_id']}/metrics/{rule['metric']}")
    return {**base, "status": status, "reason": None}


def rule_coverage(scored: list, *, scoring: dict | None = None, units: list | None = None) -> dict:
    """One explicit obligation per ratified rule per required session/trajectory.

    Without a ratified plan AND a declared required set the coverage is
    UNDECLARED and can never support eligibility; legacy callers keep only the
    thresholds the scorer itself bound, so a demonstrated FAIL is still visible.
    """
    from recognition_validation.scoring import check_rules
    keys = [(s["summary"]["session_id"], s["summary"]["trajectory_id"]) for s in scored]
    C.require(len(keys) == len(set(keys)), "DUPLICATE_TRAJECTORY_SUMMARY", "/session_summaries")
    by_unit = dict(zip(keys, scored))
    ratified = bool(scoring) and scoring["state"] == "OWNER_RATIFIED" and bool(scoring["thresholds"])
    rules = []
    if ratified:
        check_rules(scoring)
        rules = [{k: r[k] for k in ("metric", "operator", "value", "decision_ref")} for r in scoring["thresholds"]]
    declared = ratified and units is not None
    if declared:
        unit_keys = [(u["session_id"], u["trajectory_id"]) for u in units]
        C.require(len(unit_keys) == len(set(unit_keys)), "DUPLICATE_REQUIRED_UNIT", "/rule_coverage/required_units")
        obligations = [_obligation(u, rule, by_unit.get((u["session_id"], u["trajectory_id"])))
                       for u in units for rule in rules]
    else:
        units = [{"session_id": s, "trajectory_id": t} for s, t in keys]
        obligations = [{"session_id": s["summary"]["session_id"], "trajectory_id": s["summary"]["trajectory_id"],
                        "metric": m["name"], "operator": None, "threshold_value": None,
                        "decision_ref": m["threshold_ref"], "numerator": m["numerator"],
                        "denominator": m["denominator"], "value": m["value"],
                        "status": m["assessment"] if m["assessment"] in ("PASS", "FAIL") else "UNPROVEN",
                        "reason": None if m["assessment"] in ("PASS", "FAIL") else "RULE_NOT_SCORED"}
                       for s in scored for m in s["summary"]["metrics"] if m["threshold_ref"]]
    return {"declared": declared, "status": coverage_status(declared, obligations),
            "required_units": list(units), "rules": rules, "obligations": obligations}


def coverage_status(declared: bool, obligations: list) -> str:
    if any(o["status"] == "FAIL" for o in obligations):
        return "FAIL"
    if not declared:
        return "UNDECLARED"
    return "COMPLETE" if obligations and all(o["status"] == "PASS" for o in obligations) else "INCOMPLETE"


def build_result(*, document_id: str, run_digest: str, mode: str, scored: list, manifest: dict | None,
                 artifact_refs: list, missing_prerequisites: list, stage4_internal_status: str = "UNPROVEN",
                 recognition_ratification_ref: str | None = None,
                 stage4_owner_acceptance_ref: str | None = None, scoring: dict | None = None,
                 required_units: list | None = None, process_problems: list | None = None) -> dict:
    invariant_failures = sorted({v for s in scored for v in s["violations"]})
    missing = list(missing_prerequisites)
    incomplete = []
    if manifest is None:
        incomplete.append("RUN_MANIFEST_MISSING")
    elif manifest.get("infrastructure_error"):
        incomplete.append("RECORDING_OR_INFRASTRUCTURE_ERROR: " + manifest["infrastructure_error"])
    if manifest and manifest.get("network_attempts"):
        invariant_failures.append("NETWORK_ATTEMPTED_OFFLINE")
    if manifest and manifest.get("venue_writes") and manifest.get("venue_lane", "DISARMED") == "DISARMED":
        invariant_failures.append("VENUE_WRITE_OFFLINE")  # a disarmed trajectory never reaches the venue seam
    if manifest and manifest.get("events") != sum(s["event_count"] for s in scored):
        incomplete.append("EVENT_COUNT_MISMATCH")
    if manifest and (manifest.get("tick_count") != manifest.get("ticks")
                     or manifest.get("ticks") != manifest.get("events")):
        incomplete.append("TICK_COVERAGE_INCOMPLETE")
    if manifest and (manifest.get("primary_calls", 0) + manifest.get("repair_calls", 0)
                     != sum(s["call_count"] for s in scored)):
        incomplete.append("BRAIN_CALL_COUNT_MISMATCH")
    # A trajectory child that crashed, timed out or never bound its request is INCOMPLETE.
    incomplete += list(process_problems or [])
    isolated = (manifest or {}).get("process_isolation", {}).get("kind") == "FRESH_CHILD" and not process_problems
    if manifest is not None and not isolated:
        missing.append("PROCESS_ISOLATION_UNPROVEN: trajectory not recorded by a completed fresh child process")
    engineering = "FAIL" if invariant_failures else ("INCOMPLETE" if incomplete else "COMPLETE")
    coverage = rule_coverage(scored, scoring=scoring, units=required_units)
    eligible = (mode == "C" and isolated and coverage["status"] == "COMPLETE"
                and all(s["inclusion"]["current_recognition_eligible"] for s in scored)
                and bool(recognition_ratification_ref) and bool(stage4_owner_acceptance_ref)
                and engineering == "COMPLETE")
    recognition = "ELIGIBLE_FOR_OWNER_REVIEW" if eligible else "UNPROVEN"
    if coverage["status"] == "FAIL" and mode == "C":
        recognition = "FAIL"
    if coverage["status"] in ("UNDECLARED", "INCOMPLETE"):
        missing.append(f"RULE_COVERAGE_{coverage['status']}: "
                       + ("no ratified rule set and required session/trajectory set were declared"
                          if coverage["status"] == "UNDECLARED" else
                          f"{sum(o['status'] != 'PASS' for o in coverage['obligations'])} of "
                          f"{len(coverage['obligations'])} required rule obligations unscored"))
    if recognition == "UNPROVEN" and "CURRENT_RECOGNITION_PREREQUISITES" not in missing:
        missing.append("CURRENT_RECOGNITION_PREREQUISITES: authorized Mode C, sealed owner annotations,"
                       " ratified scoring plan and owner acceptance refs")
    final = ("FAIL" if engineering == "FAIL" else "ENGINEERING_INCOMPLETE" if engineering == "INCOMPLETE"
             else "READY_FOR_OWNER_REVIEW")
    result = {
        "schema_version": "result/v2", "document_id": document_id,
        "provenance": {"classification": "CONSTRUCTED" if mode in ("A", "B") else "UNKNOWN",
                       "author_role": "STAGE5_REPORT", "source_refs": [r["path"] for r in artifact_refs],
                       "notes": "Generated after execution from chain-verified traces; descriptive unless ratified."
                                + (" " + "; ".join(incomplete) if incomplete else "")},
        "run_digest": run_digest, "mode": mode, "engineering_status": engineering,
        "stage4_internal_status": stage4_internal_status,
        "stage4_owner_acceptance_ref": stage4_owner_acceptance_ref,
        "current_brain_recognition": recognition,
        "recognition_ratification_ref": recognition_ratification_ref if eligible else None,
        "historical_archive_certification": "UNPROVEN",
        "controlled_observation_authorized": False, "production_authorized": False,
        "external_request_count": sum(s["external_request_count"] for s in scored),
        "session_summaries": [s["summary"] for s in scored],
        "invariant_failures": invariant_failures, "missing_prerequisites": missing,
        "artifact_refs": artifact_refs, "final_status": final, "rule_coverage": coverage,
    }
    C.validate(result)
    return result


def _table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return "\n".join(out)


def render_markdown(result: dict, scored: list) -> str:
    lines = [f"# Stage 5 report: {result['document_id']}", "",
             f"- mode: {result['mode']}; engineering: {result['engineering_status']}; "
             f"final: {result['final_status']}",
             f"- current Brain recognition: **{result['current_brain_recognition']}**; "
             f"historical archive certification: {result['historical_archive_certification']}",
             f"- external requests: {result['external_request_count']}; production authorized: "
             f"{result['production_authorized']}", ""]
    if result["invariant_failures"]:
        lines += ["## Invariant failures", ""] + [f"- {x}" for x in result["invariant_failures"]] + [""]
    if result["missing_prerequisites"]:
        lines += ["## Missing prerequisites", ""] + [f"- {x}" for x in result["missing_prerequisites"]] + [""]
    coverage = result.get("rule_coverage")
    if coverage:
        lines += [f"## Required rule coverage: {coverage['status']}", "",
                  _table([(o["session_id"], o["trajectory_id"], o["metric"], o["decision_ref"], o["numerator"],
                           o["denominator"], o["status"], o["reason"]) for o in coverage["obligations"]],
                         ["session", "trajectory", "rule metric", "decision", "num", "den", "status", "reason"]), ""]
    for s, detail in zip(result["session_summaries"], scored):
        lines += [f"## {s['session_id']} / {s['trajectory_id']}", "",
                  f"inclusion mask: `{json.dumps(detail['inclusion'], sort_keys=True)}`", "",
                  _table([(m["name"], m["numerator"], m["denominator"], m["excluded_count"], m["unproven_count"],
                           None if m["value"] is None else round(m["value"], 4), m["assessment"])
                          for m in s["metrics"]],
                         ["metric", "num", "den", "excluded", "unproven", "value", "assessment"]), "",
                  _table([(c["layer"], c["expected"], c["observed"], c["count"], c["eligible_count"],
                           c["excluded_count"], c["unproven_count"], c["assessment"]) for c in s["confusion_cells"]],
                         ["layer", "expected", "observed", "count", "eligible", "excluded", "unproven",
                          "assessment"]), "",
                  _table([(e["label_id"], e["observed_action"], e["first_recognition_utc"], e["first_candidate_utc"],
                           e["latency_seconds"], ", ".join(e["selected_occurrences"]) or None)
                          for e in detail["episodes"]],
                         ["label", "observed", "first recognition", "first candidate", "latency s", "occurrences"]),
                  "", "Limitations:", ""] + [f"- {x}" for x in s["limitations"]] + [""]
    return "\n".join(lines)

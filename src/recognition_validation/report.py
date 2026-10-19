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


def build_result(*, document_id: str, run_digest: str, mode: str, scored: list, manifest: dict | None,
                 artifact_refs: list, missing_prerequisites: list, stage4_internal_status: str = "UNPROVEN",
                 recognition_ratification_ref: str | None = None,
                 stage4_owner_acceptance_ref: str | None = None) -> dict:
    invariant_failures = sorted({v for s in scored for v in s["violations"]})
    missing = list(missing_prerequisites)
    incomplete = []
    if manifest is None:
        incomplete.append("RUN_MANIFEST_MISSING")
    elif manifest.get("infrastructure_error"):
        incomplete.append("RECORDING_OR_INFRASTRUCTURE_ERROR: " + manifest["infrastructure_error"])
    if manifest and manifest.get("network_attempts"):
        invariant_failures.append("NETWORK_ATTEMPTED_OFFLINE")
    if manifest and manifest.get("venue_writes"):
        invariant_failures.append("VENUE_WRITE_OFFLINE")
    if manifest and manifest.get("events") != sum(s["event_count"] for s in scored):
        incomplete.append("EVENT_COUNT_MISMATCH")
    if manifest and (manifest.get("tick_count") != manifest.get("ticks")
                     or manifest.get("ticks") != manifest.get("events")):
        incomplete.append("TICK_COVERAGE_INCOMPLETE")
    if manifest and (manifest.get("primary_calls", 0) + manifest.get("repair_calls", 0)
                     != sum(s["call_count"] for s in scored)):
        incomplete.append("BRAIN_CALL_COUNT_MISMATCH")
    engineering = "FAIL" if invariant_failures else ("INCOMPLETE" if incomplete else "COMPLETE")
    metrics = [m for s in scored for m in s["summary"]["metrics"] if m["threshold_ref"]]
    all_pass = bool(metrics) and all(m["assessment"] == "PASS" for m in metrics)
    eligible = (mode == "C" and all_pass and all(s["inclusion"]["current_recognition_eligible"] for s in scored)
                and bool(recognition_ratification_ref) and bool(stage4_owner_acceptance_ref)
                and engineering == "COMPLETE")
    recognition = "ELIGIBLE_FOR_OWNER_REVIEW" if eligible else "UNPROVEN"
    if any(m["assessment"] == "FAIL" for m in metrics) and mode == "C":
        recognition = "FAIL"
    if recognition == "UNPROVEN" and "CURRENT_RECOGNITION_PREREQUISITES" not in missing:
        missing.append("CURRENT_RECOGNITION_PREREQUISITES: authorized Mode C, sealed owner annotations,"
                       " ratified scoring plan and owner acceptance refs")
    final = ("FAIL" if engineering == "FAIL" else "ENGINEERING_INCOMPLETE" if engineering == "INCOMPLETE"
             else "READY_FOR_OWNER_REVIEW")
    result = {
        "schema_version": "result/v1", "document_id": document_id,
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
        "artifact_refs": artifact_refs, "final_status": final,
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

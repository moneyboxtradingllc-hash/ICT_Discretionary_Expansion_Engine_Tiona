"""Replay the production semantic Brain wake controller over pre-call evidence.

The historical filename is retained for operator continuity. This is no longer
the v1 whole-block hash experiment: replay imports the same deterministic
controller production uses. It never calls a model, writes telemetry, places
orders, or treats synthetic evidence as historical acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_brain import wake_controller as WAKE  # noqa: E402


VERSION = "brain_wake_replay.v2"
REPORT_SCHEMA = "brain_wake_replay_report.v2"
BUNDLE_SCHEMA = "pre_brain_wake_bundle.v2"

RECORDED = "recorded_pre_provider"
SYNTHETIC = "synthetic"
NON_ECU_STAGE = "pre_provider_after_catalogs"
ECU_STAGE = "ecu_pre_provider"

PRIMARY = "primary"
REPAIR_ROLES = ("json_repair", "family_repair", "invalidation_repair",
                "other_repair")
CALL_ROLES = (PRIMARY,) + REPAIR_ROLES

# A bundle cannot omit one known live trade and claim 100% recall on the other.
KNOWN_TRADE_SPECS = {
    "PROD-20260909": {
        "T1": {"direction": "bullish", "quantity": 7,
               "planned_entry": 29407.5, "stop": 29386.5,
               "target": 29451.75},
        "T2": {"direction": "bearish", "quantity": 15,
               "planned_entry": 29471.25, "stop": 29480.75,
               "target": 29386.5},
    },
}


def _timestamp(value) -> "datetime | None":
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _identity(row) -> "tuple[str, str, str] | None":
    if not isinstance(row, dict):
        return None
    values = tuple(row.get(key) for key in
                   ("session_id", "contract_id", "scan_id"))
    if any(not isinstance(value, str) or not value.strip() for value in values):
        return None
    return values


def _ratio(numerator: int, denominator: int):
    return round(numerator / denominator, 6) if denominator else None


def unknown_report(session_id, status, max_silence_seconds) -> dict:
    return {
        "version": VERSION,
        "controller_schema": WAKE.SCHEMA_VERSION,
        "projection_version": WAKE.PROJECTION_VERSION,
        "session_id": session_id,
        "max_silence_seconds": max_silence_seconds,
        "status": status,
        "historical_acceptance": "NOT_PROVEN",
        "historical_acceptance_proven": False,
        "production_authorized": False,
        "evidence_kind": None,
        "provenance_independently_verified": False,
        "evidence_complete_as_declared": False,
        "problems": [],
        "total_scans": None,
        "historical_calls": None,
        "hypothetical_wake_scans": None,
        "hypothetical_hold_scans": None,
        "maximum_consecutive_hold_scans": None,
        "maximum_consecutive_hold_duration_seconds": None,
        "reasons_distribution": None,
        "candidate_origin_recall": None,
        "trade_origin_recall": None,
        "candidate_origin_results": None,
        "trade_origin_results": None,
        "lead_in_wake_timing": None,
        "hypothetical_provider_call_reduction": None,
        "actual_call_ledger_reduction_estimate": None,
        "decisions": [],
    }


def _provider_index(bundle, observation_keys, problems):
    calls = bundle.get("provider_calls")
    if bundle.get("provider_call_coverage") != "complete":
        problems.append("provider_call_coverage_unproven")
    if not isinstance(calls, list):
        problems.append("provider_calls_missing")
        calls = []

    by_key = defaultdict(list)
    seen_ids = set()
    repair_counts = Counter()
    for index, call in enumerate(calls, 1):
        if not isinstance(call, dict):
            problems.append(f"provider_call:{index}:malformed")
            continue
        key = _identity(call)
        if key is None:
            problems.append(f"provider_call:{index}:identity_missing")
            continue
        if key not in observation_keys:
            problems.append(f"provider_call:{index}:scan_unmatched")
        call_id = call.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            problems.append(f"provider_call:{index}:call_id_missing")
        elif call_id in seen_ids:
            problems.append(f"provider_call:{index}:duplicate_call_id")
        else:
            seen_ids.add(call_id)
        role = call.get("role")
        if role not in CALL_ROLES:
            problems.append(f"provider_call:{index}:role_unknown")
            continue
        if role == PRIMARY and type(call.get("sovereign_result")) is not bool:
            problems.append(f"provider_call:{index}:sovereign_result_missing")
        if role in REPAIR_ROLES:
            repair_counts[role] += 1
        by_key[key].append(call)

    if bundle.get("provider_call_coverage") == "complete":
        for key in observation_keys:
            primary = [row for row in by_key.get(key, [])
                       if row.get("role") == PRIMARY]
            if len(primary) != 1:
                problems.append(
                    "primary_call_coverage_mismatch:" + "|".join(key))
    return by_key, calls, repair_counts


def _origin_results(bundle, decision_by_key, row_by_key, problems):
    candidate_rows = bundle.get("candidate_origins")
    trade_rows = bundle.get("trade_origins")
    if bundle.get("candidate_label_coverage") != "complete":
        problems.append("candidate_label_coverage_unproven")
    if bundle.get("trade_label_coverage") != "complete":
        problems.append("trade_label_coverage_unproven")
    if not isinstance(candidate_rows, list):
        problems.append("candidate_origins_missing")
        candidate_rows = []
    if not isinstance(trade_rows, list):
        problems.append("trade_origins_missing")
        trade_rows = []

    candidate_results = []
    candidate_by_id = {}
    candidate_keys = set()
    for index, label in enumerate(candidate_rows, 1):
        key = _identity(label)
        candidate_id = label.get("candidate_id") if isinstance(label, dict) else None
        if key is None:
            problems.append(f"candidate_origin:{index}:identity_missing")
            continue
        if key in candidate_keys:
            problems.append(f"candidate_origin:{index}:duplicate_scan")
        candidate_keys.add(key)
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            problems.append(f"candidate_origin:{index}:candidate_id_missing")
        elif candidate_id in candidate_by_id:
            problems.append(f"candidate_origin:{index}:duplicate_candidate_id")
        observed = decision_by_key.get(key)
        if observed is None:
            problems.append(f"candidate_origin:{index}:scan_unmatched")
        result = {
            "candidate_id": candidate_id,
            "scan_id": key[2],
            "decision": observed.get("decision") if observed else None,
            "recalled": bool(observed and observed.get("decision") == WAKE.WAKE),
        }
        candidate_results.append(result)
        if isinstance(candidate_id, str) and candidate_id:
            candidate_by_id[candidate_id] = (key, result)

    trade_results = []
    lead_in = []
    seen_trade_ids = set()
    for index, label in enumerate(trade_rows, 1):
        key = _identity(label)
        if key is None:
            problems.append(f"trade_origin:{index}:identity_missing")
            continue
        trade_id = label.get("trade_id")
        candidate_id = label.get("candidate_id")
        if not isinstance(trade_id, str) or not trade_id.strip():
            problems.append(f"trade_origin:{index}:trade_id_missing")
        elif trade_id in seen_trade_ids:
            problems.append(f"trade_origin:{index}:duplicate_trade_id")
        else:
            seen_trade_ids.add(trade_id)
        linked = candidate_by_id.get(candidate_id)
        if linked is None or linked[0] != key:
            problems.append(f"trade_origin:{index}:candidate_lineage_unproven")
        observed = decision_by_key.get(key)
        if observed is None:
            problems.append(f"trade_origin:{index}:scan_unmatched")

        opportunity_ids = label.get("opportunity_scan_ids")
        if not isinstance(opportunity_ids, list) or not opportunity_ids:
            problems.append(f"trade_origin:{index}:opportunity_window_missing")
            opportunity_ids = []
        elif (any(not isinstance(scan_id, str) or not scan_id
                  for scan_id in opportunity_ids)
              or len(set(opportunity_ids)) != len(opportunity_ids)):
            problems.append(f"trade_origin:{index}:opportunity_window_malformed")
        elif opportunity_ids[-1] != key[2]:
            problems.append(f"trade_origin:{index}:origin_not_window_terminal")

        window = []
        for scan_id in opportunity_ids:
            window_key = (key[0], key[1], scan_id)
            decision = decision_by_key.get(window_key)
            row = row_by_key.get(window_key)
            if decision is None or row is None:
                problems.append(
                    f"trade_origin:{index}:opportunity_scan_unmatched:{scan_id}")
                continue
            window.append((row["sequence"], scan_id, decision, row))
        if window and [item[0] for item in window] != sorted(
                item[0] for item in window):
            problems.append(f"trade_origin:{index}:opportunity_window_reordered")

        wake_rows = [item for item in window
                     if item[2].get("decision") == WAKE.WAKE]
        origin_when = _timestamp((row_by_key.get(key) or {}).get("observed_at"))

        def timing(item):
            when = _timestamp(item[3].get("observed_at"))
            return ((origin_when - when).total_seconds()
                    if origin_when is not None and when is not None else None)

        lead_in.append({
            "trade_id": trade_id,
            "origin_scan_id": key[2],
            "opportunity_scan_ids": opportunity_ids,
            "wake_scan_ids": [item[1] for item in wake_rows],
            "first_wake_scan_id": wake_rows[0][1] if wake_rows else None,
            "first_wake_lead_seconds": timing(wake_rows[0]) if wake_rows else None,
            "last_wake_scan_id": wake_rows[-1][1] if wake_rows else None,
            "last_wake_lead_seconds": timing(wake_rows[-1]) if wake_rows else None,
        })
        trade_results.append({
            "trade_id": trade_id,
            "candidate_id": candidate_id,
            "scan_id": key[2],
            "decision": observed.get("decision") if observed else None,
            # An unrelated earlier wake gets no speculative recall credit.
            "recalled": bool(observed and observed.get("decision") == WAKE.WAKE),
        })

    expected = KNOWN_TRADE_SPECS.get(bundle.get("session_id"), {})
    if expected:
        if seen_trade_ids != set(expected):
            problems.append("known_trade_manifest_mismatch")
        rows_by_trade = {row.get("trade_id"): row for row in trade_rows
                         if isinstance(row, dict)}
        for trade_id, spec in expected.items():
            row = rows_by_trade.get(trade_id) or {}
            for field, wanted in spec.items():
                if row.get(field) != wanted:
                    problems.append(f"known_trade_spec_mismatch:{trade_id}:{field}")

    return candidate_results, trade_results, lead_in


def _hold_metrics(decisions):
    max_scans = current_scans = 0
    max_duration = 0.0
    last_wake_at = None
    last_observed_at = None
    for decision in decisions:
        when = _timestamp(decision.get("timestamp"))
        if when is not None:
            last_observed_at = when
        if decision.get("decision") == WAKE.HOLD:
            current_scans += 1
            max_scans = max(max_scans, current_scans)
            continue
        if current_scans and last_wake_at is not None and when is not None:
            max_duration = max(max_duration,
                               (when - last_wake_at).total_seconds())
        current_scans = 0
        if when is not None:
            last_wake_at = when
    if current_scans and last_wake_at is not None and last_observed_at is not None:
        max_duration = max(max_duration,
                           (last_observed_at - last_wake_at).total_seconds())
    return max_scans, max(0.0, max_duration)


def evaluate(bundle: dict, *, max_silence_seconds=300.0) -> dict:
    """Evaluate one session without feeding labels into wake decisions."""
    session = bundle.get("session_id") if isinstance(bundle, dict) else None
    report = unknown_report(session, "MISSING_OR_INVALID_EVIDENCE",
                            max_silence_seconds)
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        report["problems"] = ["bundle_schema_invalid"]
        return report
    rows = bundle.get("observations")
    if (not isinstance(session, str) or not session or not isinstance(rows, list)
            or not rows):
        report["problems"] = ["session_or_observations_missing"]
        return report
    max_silence = WAKE.configured_max_silence(max_silence_seconds)
    if max_silence is None:
        report["problems"] = ["max_silence_invalid"]
        return report

    problems = []
    evidence_kind = bundle.get("evidence_kind")
    if evidence_kind not in (SYNTHETIC, RECORDED):
        problems.append("evidence_kind_unproven")
    expected_count = bundle.get("expected_scan_count")
    if type(expected_count) is not int or expected_count != len(rows):
        problems.append("scan_coverage_unproven")

    row_by_key = {}
    sequence_seen = set()
    previous_time = None
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            problems.append(f"observation:{index}:malformed")
            continue
        key = _identity(row)
        if key is None:
            problems.append(f"observation:{index}:identity_missing")
        else:
            if key in row_by_key:
                problems.append(f"observation:{index}:duplicate_scan_identity")
            row_by_key[key] = row
            if key[0] != session:
                problems.append(f"observation:{index}:cross_session")
            snapshot = row.get("snapshot")
            if (isinstance(snapshot, dict)
                    and str(snapshot.get("contract_id")) != key[1]):
                problems.append(f"observation:{index}:snapshot_contract_mismatch")
        sequence = row.get("sequence")
        if type(sequence) is not int or sequence < 1:
            problems.append(f"observation:{index}:sequence_invalid")
        else:
            if sequence in sequence_seen:
                problems.append(f"observation:{index}:sequence_duplicate")
            sequence_seen.add(sequence)
            if sequence != index:
                problems.append(f"observation:{index}:sequence_gap_or_reordering")
        when = _timestamp(row.get("observed_at"))
        if when is None:
            problems.append(f"observation:{index}:time_invalid")
        elif previous_time is not None and when <= previous_time:
            problems.append(f"observation:{index}:time_reordering")
        if when is not None:
            previous_time = when
        pipeline = row.get("pipeline_mode")
        expected_stage = (NON_ECU_STAGE if pipeline == "non_ecu" else
                          ECU_STAGE if pipeline == "ecu_pre_provider" else None)
        if expected_stage is None:
            problems.append(f"observation:{index}:pipeline_mode_unknown")
        elif row.get("capture_stage") != expected_stage:
            problems.append(f"observation:{index}:capture_stage_unproven")
        if type(row.get("catalogs_ok")) is not bool:
            problems.append(f"observation:{index}:catalog_status_missing")

    call_by_key, calls, repair_counts = _provider_index(
        bundle, set(row_by_key), problems)

    controller = WAKE.BrainWakeController(
        mode=WAKE.ENFORCE, max_silence_seconds=max_silence)
    decisions = []
    decision_by_key = {}
    for row in rows:
        row = row if isinstance(row, dict) else {}
        key = _identity(row)
        result = controller.observe(
            snapshot=row.get("snapshot"), brain_input=row.get("brain_input"),
            session_id=row.get("session_id"),
            contract_id=row.get("contract_id"), scan=row.get("sequence"),
            now=row.get("observed_at"),
            pipeline_mode=row.get("pipeline_mode") or "unknown",
            catalogs_ok=row.get("catalogs_ok") is True)
        result = dict(result)
        result["scan_id"] = row.get("scan_id")
        result["capture_stage"] = row.get("capture_stage")
        result["pipeline_mode"] = row.get("pipeline_mode")
        decisions.append(result)
        if key is not None:
            decision_by_key[key] = result
        if result.get("decision") == WAKE.WAKE:
            primary = [call for call in call_by_key.get(key, [])
                       if call.get("role") == PRIMARY]
            controller.note_provider_result(
                result, request_attempted=len(primary) == 1,
                sovereign=(len(primary) == 1
                           and primary[0].get("sovereign_result") is True))

    candidate_results, trade_results, lead_in = _origin_results(
        bundle, decision_by_key, row_by_key, problems)
    problems = sorted(set(problems))
    complete = not problems
    wake_count = sum(row.get("decision") == WAKE.WAKE for row in decisions)
    hold_count = sum(row.get("decision") == WAKE.HOLD for row in decisions)
    max_hold_scans, max_hold_seconds = _hold_metrics(decisions)
    reasons = Counter(reason for row in decisions for reason in row.get("reasons", []))

    candidate_recalled = sum(row["recalled"] for row in candidate_results)
    trade_recalled = sum(row["recalled"] for row in trade_results)
    candidate_recall = (_ratio(candidate_recalled, len(candidate_results))
                        if complete and candidate_results else None)
    trade_recall = (_ratio(trade_recalled, len(trade_results))
                    if complete and trade_results else None)

    provenance = bundle.get("provenance_independently_verified") is True
    measured = complete and evidence_kind == RECORDED and provenance
    primary_calls = [call for call in calls
                     if isinstance(call, dict) and call.get("role") == PRIMARY]
    repair_calls = [call for call in calls
                    if isinstance(call, dict) and call.get("role") in REPAIR_ROLES]
    retained_primary = sum(
        decision_by_key.get(_identity(call), {}).get("decision") == WAKE.WAKE
        for call in primary_calls)
    retained_repairs = sum(
        decision_by_key.get(_identity(call), {}).get("decision") == WAKE.WAKE
        for call in repair_calls)

    if not complete:
        acceptance = "NOT_PROVEN_INCOMPLETE_EVIDENCE"
        status = "INCOMPLETE_EVIDENCE"
    elif evidence_kind == SYNTHETIC:
        acceptance = "NOT_PROVEN_SYNTHETIC"
        status = "SYNTHETIC_ONLY"
    elif not provenance:
        acceptance = "NOT_PROVEN_PROVENANCE"
        status = "RECORDED_REPLAY_UNVERIFIED"
    elif any(not row["recalled"] for row in trade_results):
        acceptance = "REJECTED_TRADE_ORIGIN_MISS"
        status = "RECORDED_REPLAY_REJECTED"
    elif any(not row["recalled"] for row in candidate_results):
        acceptance = "REJECTED_CANDIDATE_ORIGIN_MISS"
        status = "RECORDED_REPLAY_REJECTED"
    elif session == "PROD-20260909":
        acceptance = "PASSED_RECALL_DAY"
        status = "RECORDED_REPLAY_ACCEPTED"
    elif trade_results:
        acceptance = "PASSED_RECORDED_RECALL"
        status = "RECORDED_REPLAY_ACCEPTED"
    else:
        acceptance = "WASTE_MEASUREMENT_ONLY"
        status = "RECORDED_REPLAY_MEASURED"

    report.update({
        "status": status,
        "historical_acceptance": acceptance,
        "historical_acceptance_proven": acceptance.startswith("PASSED_"),
        "evidence_kind": evidence_kind,
        "provenance_independently_verified": provenance,
        "evidence_complete_as_declared": complete,
        "problems": problems,
        "total_scans": len(rows),
        "historical_calls": {
            "primary": len(primary_calls),
            "repairs": len(repair_calls),
            "repair_by_role": {role: repair_counts.get(role, 0)
                               for role in REPAIR_ROLES},
            "total": len(primary_calls) + len(repair_calls),
        },
        "hypothetical_wake_scans": wake_count,
        "hypothetical_hold_scans": hold_count,
        "maximum_consecutive_hold_scans": max_hold_scans,
        "maximum_consecutive_hold_duration_seconds": max_hold_seconds,
        "reasons_distribution": dict(sorted(reasons.items())),
        "candidate_origin_recall": candidate_recall,
        "trade_origin_recall": trade_recall,
        "candidate_origin_results": candidate_results,
        "trade_origin_results": trade_results,
        "lead_in_wake_timing": lead_in,
        "decisions": decisions,
    })
    if measured:
        suppressed_primary = len(primary_calls) - retained_primary
        suppressed_repairs = len(repair_calls) - retained_repairs
        historical_total = len(primary_calls) + len(repair_calls)
        retained_total = retained_primary + retained_repairs
        report["hypothetical_provider_call_reduction"] = {
            "historical_primary_calls": len(primary_calls),
            "retained_primary_calls": retained_primary,
            "suppressed_primary_calls": suppressed_primary,
            "reduction_fraction": _ratio(suppressed_primary,
                                         len(primary_calls)),
        }
        report["actual_call_ledger_reduction_estimate"] = {
            "historical_total_calls": historical_total,
            "retained_total_calls": retained_total,
            "suppressed_total_calls": historical_total - retained_total,
            "suppressed_repair_calls": suppressed_repairs,
            "reduction_fraction": _ratio(historical_total - retained_total,
                                         historical_total),
            "assumption": (
                "recorded same-scan repairs disappear only when their primary "
                "call is held; WAKE-scan repair behavior is retained"),
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--max-silence-seconds", nargs="+", type=float,
                        default=[60.0, 180.0, 300.0, 600.0])
    args = parser.parse_args(argv)
    try:
        raw = args.bundle.read_bytes()
        bundle = json.loads(raw)
        runs = [evaluate(bundle, max_silence_seconds=value)
                for value in args.max_silence_seconds]
        if any(run.get("session_id") != args.session for run in runs):
            runs = [unknown_report(args.session, "SESSION_MISMATCH", value)
                    for value in args.max_silence_seconds]
        input_hash = hashlib.sha256(raw).hexdigest()
    except FileNotFoundError:
        runs = [unknown_report(args.session, "MISSING_EVIDENCE", value)
                for value in args.max_silence_seconds]
        input_hash = None
    except (OSError, ValueError, TypeError):
        runs = [unknown_report(args.session,
                               "UNREADABLE_OR_INVALID_EVIDENCE", value)
                for value in args.max_silence_seconds]
        input_hash = None

    output = {
        "schema": REPORT_SCHEMA,
        "session_id": args.session,
        "input_path": str(args.bundle),
        "input_sha256": input_hash,
        "runs": runs,
        "production_authorized": False,
    }
    print(json.dumps(output, sort_keys=True, indent=2, allow_nan=False))
    if any(not run.get("evidence_complete_as_declared") for run in runs):
        return 2
    accepted = {
        "PASSED_RECALL_DAY", "PASSED_RECORDED_RECALL",
        "WASTE_MEASUREMENT_ONLY",
    }
    return 0 if all(run.get("historical_acceptance") in accepted
                    for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())

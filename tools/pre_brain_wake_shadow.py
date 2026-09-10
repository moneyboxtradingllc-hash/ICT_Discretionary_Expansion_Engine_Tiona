"""Offline pre-provider evidence-change experiment. NEVER a production gate.

No provider, broker, detector reimplementation or production-loop imports.
Input must be an explicit pre-call capture, not a relabelled post-call snapshot.
The stage/provenance declarations are assertions by the exporter, not proof of
authenticity. Real-session provenance still requires an independent audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

VERSION = "pre_brain_wake_shadow.v1"
BUNDLE_SCHEMA = "pre_brain_wake_bundle.v1"

# Whole canonical blocks are retained, including embedded event timestamps,
# numeric changes and ordering. No quantization, per-phase veto, dwell threshold
# or aggressive volatile-field stripping is certified without a replay corpus.
# This intentionally over-wakes; efficiency is unproven, not tuned on labels.
SNAPSHOT_GROUPS = {
    "session": ("session", "session_po3", "session_context"),
    "liquidity": ("liquidity",),
    "structure": ("structure", "protected_swings", "structure_flips", "mtf_market_state"),
    "ownership": ("active_path_state",),
    "delivery": ("expansion", "volatility", "po3"),
    "market_context": ("market_regime", "market_context"),
    "setup": ("setup_lifecycle",),
    "executable_quote": ("execution_price",),
    "integrity": ("candle_continuity", "derived_state"),
}
CATALOGS = ("authorized_tool_catalog", "authorized_objectives", "authorized_invalidations")
POST_CALL_KEYS = ("ai_brain", "candidate_thesis", "brain_thesis", "brain_result")


def digest(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def project(record: dict) -> tuple[dict, list[str]]:
    """Read audited owners only; never infer missing evidence as an empty set."""
    problems = []
    if record.get("capture_stage") != "pre_provider_after_catalogs":
        problems.append("pre_call_stage_unproven")
    # ECU can have paid before the late scan snapshot exists. v1 cannot use that
    # late snapshot as evidence that a prior call could have been avoided.
    if record.get("pipeline_mode") != "non_ecu":
        problems.append("pipeline_not_supported_for_suppression")
    snapshot = record.get("snapshot")
    brain_input = record.get("brain_input")
    if not isinstance(snapshot, dict) or not isinstance(brain_input, dict):
        return {}, problems + ["snapshot_or_pre_call_input_missing"]
    if any(key in snapshot for key in POST_CALL_KEYS):
        problems.append("post_call_snapshot_not_accepted")
    if snapshot.get("contract_id") != record.get("contract_id"):
        problems.append("snapshot_contract_mismatch")
    groups = {}
    for group, keys in SNAPSHOT_GROUPS.items():
        groups[group] = {}
        for key in keys:
            if key not in snapshot or snapshot[key] is None:
                problems.append(f"missing_evidence:{key}")
            else:
                groups[group][key] = snapshot[key]
    groups["catalogs"] = {}
    for key in CATALOGS:
        if not isinstance(brain_input.get(key), list):
            problems.append(f"missing_catalog:{key}")
        else:
            groups["catalogs"][key] = brain_input[key]
    continuity = snapshot.get("candle_continuity")
    derived = snapshot.get("derived_state")
    quote = snapshot.get("execution_price")
    if not isinstance(continuity, dict) or continuity.get("continuous") is not True:
        problems.append("continuity_unproven")
    if not isinstance(derived, dict) or derived.get("current") is not True:
        problems.append("derived_state_unproven")
    if (not isinstance(quote, dict) or quote.get("fresh") is not True
            or quote.get("available") is not True
            or any(not isinstance(quote.get(key), (int, float))
                   or isinstance(quote.get(key), bool) for key in ("best_bid", "best_ask"))):
        problems.append("executable_quote_unproven")
    try:
        return {key: digest(value) for key, value in groups.items()}, problems
    except (TypeError, ValueError):
        return {}, problems + ["noncanonical_evidence"]


class ShadowDetector:
    """Session/contract-scoped sequential observer; all state is process-local."""

    def __init__(self):
        self.previous = None
        self.seen = set()

    def observe(self, record: dict) -> dict:
        if not isinstance(record, dict):
            record = {}
        issues = []
        identity = tuple(record.get(key) for key in ("session_id", "contract_id"))
        scan_id = record.get("scan_id")
        seq = record.get("sequence")
        if any(not isinstance(value, str) or not value for value in (*identity, scan_id)):
            issues.append("missing_identity")
        if type(seq) is not int or seq < 1:
            issues.append("invalid_sequence")
        try:
            when = timestamp(record.get("observed_at"))
        except (TypeError, ValueError):
            when = None
            issues.append("invalid_observation_time")
        if all(isinstance(value, str) and value for value in (*identity, scan_id)):
            seen_key = (*identity, scan_id)
            if seen_key in self.seen:
                issues.append("duplicate_scan_identity")
            self.seen.add(seen_key)
        groups, evidence_issues = project(record)
        issues.extend(evidence_issues)
        before = self.previous
        reasons = []
        if before is None:
            reasons.append("bootstrap_or_uncertainty_reset")
        elif identity != before["identity"]:
            reasons.append("session_or_contract_changed")
        else:
            if type(seq) is int and seq != before["sequence"] + 1:
                issues.append("sequence_gap_or_reordering")
            if when is not None and when <= before["when"]:
                issues.append("nonincreasing_observation_time")
            reasons.extend(f"changed:{key}" for key in sorted(groups)
                           if groups[key] != before["groups"].get(key))
        if issues:
            # Corrupt/incomplete input must not become the comparison baseline.
            self.previous = None
            decision = "PRESERVE_BASELINE"
        else:
            self.previous = {"identity": identity, "sequence": seq,
                             "when": when, "groups": groups}
            decision = "WAKE_SHADOW" if reasons else "HOLD_SHADOW"
        return {"version": VERSION, "session_id": record.get("session_id"),
                "contract_id": record.get("contract_id"), "scan_id": scan_id,
                "decision": decision, "reasons": reasons, "issues": sorted(set(issues)),
                "group_fingerprints": groups,
                "production_action": "NONE", "production_authorized": False}


def unknown_report(session_id, reason):
    return {"version": VERSION, "session_id": session_id, "status": reason,
            "observations": None, "hold_fraction": None,
            "candidate_scan_recall_proxy": None, "trade_recall_proxy": None,
            "model_calls_saved": None, "cost_saved": None,
            "production_authorized": False}


def evaluate(bundle: dict) -> dict:
    """Historical labels are joined AFTER decisions, never fed to the observer.

    Same-scan candidate capture is a recall proxy, not a counterfactual trading
    simulation: suppressing prior calls could change stance and future actions.
    An earlier wake gets no speculative credit for a later held candidate.
    """
    if not isinstance(bundle, dict):
        return unknown_report(None, "INVALID_BUNDLE")
    session = bundle.get("session_id")
    rows = bundle.get("observations")
    if (bundle.get("schema") != BUNDLE_SCHEMA or not isinstance(session, str)
            or not session or not isinstance(rows, list) or not rows):
        return unknown_report(session, "MISSING_OR_INVALID_EVIDENCE")
    detector = ShadowDetector()
    decisions = [detector.observe(row) for row in rows]
    problems = [f"scan:{i}:{issue}" for i, result in enumerate(decisions, 1)
                for issue in result["issues"]]
    for result in decisions:
        if result["session_id"] != session:
            problems.append("cross_session_observation")
    expected = bundle.get("expected_scan_count")
    if type(expected) is not int or expected != len(rows):
        problems.append("scan_coverage_unproven")
    if not isinstance(rows[0], dict) or rows[0].get("sequence") != 1:
        problems.append("session_start_missing")
    if bundle.get("evidence_kind") not in ("synthetic", "recorded_pre_call"):
        problems.append("evidence_provenance_unproven")
    labels = bundle.get("candidate_labels")
    if not isinstance(labels, list) or bundle.get("label_coverage") != "complete":
        problems.append("candidate_label_coverage_unproven")
        labels = []
    by_key = {(result["session_id"], result["contract_id"], result["scan_id"]): result
              for result in decisions
              if all(isinstance(result[key], str) for key in
                     ("session_id", "contract_id", "scan_id"))}
    candidates = set()
    trade_ids = set()
    candidate_results = []
    for label in labels:
        if not isinstance(label, dict):
            problems.append("invalid_candidate_label")
            continue
        key = tuple(label.get(key) for key in ("session_id", "contract_id", "scan_id"))
        if any(not isinstance(value, str) or not value for value in key):
            problems.append("label_identity_missing")
            continue
        if key in candidates:
            problems.append("duplicate_candidate_scan_label")
        candidates.add(key)
        observed = by_key.get(key)
        if observed is None:
            problems.append("candidate_scan_unmatched")
        trade = label.get("trade_id")
        if trade is not None:
            if not isinstance(trade, str) or not trade or trade in trade_ids:
                problems.append("invalid_or_duplicate_trade_identity")
            else:
                trade_ids.add(trade)
        candidate_results.append({"scan_id": key[2], "trade_id": trade,
                                  "decision": observed["decision"] if observed else None})
    complete = not problems
    captured = lambda row: row["decision"] == "WAKE_SHADOW"
    trades = [row for row in candidate_results if row["trade_id"] is not None]
    misses = [row for row in candidate_results if not captured(row)]
    return {**unknown_report(session, "SYNTHETIC_ONLY" if bundle.get("evidence_kind") == "synthetic"
                             else "OBSERVED_LABEL_PROXY_ONLY"),
            "observations": len(rows), "evidence_complete_as_declared": complete,
            "provenance_independently_verified": False,
            "problems": sorted(set(problems)), "decisions": decisions,
            "hypothetical_holds": sum(row["decision"] == "HOLD_SHADOW" for row in decisions),
            "hold_fraction": (sum(row["decision"] == "HOLD_SHADOW" for row in decisions)
                              / len(rows)) if complete else None,
            "candidate_scan_recall_proxy": (sum(map(captured, candidate_results))
                                            / len(candidate_results))
                if complete and candidate_results else None,
            "trade_recall_proxy": sum(map(captured, trades)) / len(trades)
                if complete and bundle.get("trade_label_coverage") == "complete" and trades else None,
            "candidate_results": candidate_results, "missed_candidate_scans": misses,
            "observed_candidate_gate": ("REJECTED_OBSERVED_MISS" if misses else
                                         "NO_OBSERVED_MISS" if candidate_results else
                                         "NOT_TESTED_NO_POSITIVE_LABELS") if complete else "UNPROVEN"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = args.bundle.read_bytes()
        bundle = json.loads(raw)
        result = evaluate(bundle)
        if result["session_id"] != args.session:
            result = unknown_report(args.session, "SESSION_MISMATCH")
        result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    except FileNotFoundError:
        result = unknown_report(args.session, "MISSING_EVIDENCE")
    except (OSError, ValueError):
        result = unknown_report(args.session, "UNREADABLE_OR_INVALID_EVIDENCE")
    result["input_path"] = str(args.bundle)
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    if not result.get("evidence_complete_as_declared"):
        return 2
    # A complete packet with no positive labels is not a recall test, and a
    # complete packet with a held candidate is an explicit false negative.
    # Neither may look like a successful acceptance gate to a caller that only
    # checks the process exit code.
    if result.get("observed_candidate_gate") != "NO_OBSERVED_MISS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Post-execution scoring join (contract 07). The scorer never drives the organism.

It consumes one completed, chain-verified trace (raw identities, never a
semantic projection) and at most one annotation set, and reports descriptive
cells and metrics with explicit numerators, denominators, exclusions and
UNPROVEN counts. Nothing here selects a threshold: PASS/FAIL appears only
when an OWNER_RATIFIED scoring plan names one, on a sealed owner/delegate
annotation, in Mode C. Mode A/B never enter current-recognition denominators.

Three clocks stay separate: market/fact time (settled cutoffs), annotation
time (label windows, earliest availability) and real time (seals, run start).
A tolerance can only extend a recognition target forward; nothing observed
before `earliest_available_utc` is ever a hit -- it is a chronology violation.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from recognition_validation import contracts as C
from recognition_validation import recorder as REC

ENTRY_OUTCOMES = frozenset({"QUALIFIED_CANDIDATE_OBSERVED", "CONDITIONAL_PLAN_PUBLISHED"})
#: Lawful pre-cognition / post-cognition refusals that are not cognition misses.
NON_COGNITION_BLOCKERS = frozenset({"RISK_REJECTED", "WINDOW_CLOSED", "TRADING_COGNITION_OFF"})
DEGRADED_OUTCOMES = frozenset({"BRAIN_DEGRADED", "BRAIN_SLEEP_HOLD", "NO_CANDLES"})
DIRECTIONS = ("bullish", "bearish", "conflicted", "neutral", "UNKNOWN")
#: Engineering/author roles that may never stand in for the owner.
ENGINEERING_AUTHOR_PREFIXES = ("STAGE5", "CLAUDE", "CONTRACT_EXAMPLE", "ENGINEERING", "CODEX")


class Inclusion:
    """The frozen per-metric inclusion mask for one scoring pass."""

    def __init__(self, *, mode: str, annotation: dict | None, scoring: dict | None):
        self.mode = mode
        self.annotation_state = (annotation or {}).get("state")
        classification = ((annotation or {}).get("provenance") or {}).get("classification")
        self.owner_truth = (annotation is not None and self.annotation_state == "SEALED"
                            and classification != "FICTIONAL")
        self.ratified = bool(scoring) and scoring["state"] == "OWNER_RATIFIED" and bool(scoring["thresholds"])
        self.current_recognition = mode == "C" and self.owner_truth

    def document(self) -> dict:
        return {"mode": self.mode, "annotation_state": self.annotation_state, "owner_truth": self.owner_truth,
                "scoring_ratified": self.ratified, "current_recognition_eligible": self.current_recognition}


def admit_annotation(annotation: dict, *, corpus: dict | None, run_started_at: str | None,
                     certification: bool = False) -> list:
    """Validate and bind an annotation set; returns limitations, raises on violations."""
    C.validate(annotation, certification=certification)
    author = str(annotation["provenance"]["author_role"]).upper()
    if annotation["annotator_role"] in ("OWNER", "AUTHORIZED_DELEGATE"):
        C.require(not author.startswith(ENGINEERING_AUTHOR_PREFIXES), "SELF_AUTHORED_OWNER_ANNOTATION",
                  "/provenance/author_role", annotation["provenance"]["author_role"])
    if corpus is not None:
        C.cross(corpus, annotations=annotation)
    limitations = []
    if annotation["state"] != "SEALED" or annotation["provenance"]["classification"] == "FICTIONAL":
        limitations.append(f"ANNOTATION_{annotation['state']}: descriptive only, never benchmark truth")
    if annotation["state"] == "SEALED":
        C.require(run_started_at is not None, "RUN_START_UNKNOWN", "/run_started_at")
        C.require(C.instant(annotation["seal"]["sealed_at"]) <= C.instant(run_started_at),
                  "ANNOTATION_SEALED_AFTER_OUTPUTS", "/seal/sealed_at",
                  f"{annotation['seal']['sealed_at']} > {run_started_at}")
    return limitations


def admit_corpus(corpus: dict, *, run_started_at: str | None) -> None:
    """A corpus curated after outputs were visible is not an evaluation corpus."""
    seal = corpus.get("seal")
    C.require(bool(seal), "CORPUS_UNSEALED", "/seal")
    if run_started_at is not None:
        C.require(C.instant(seal["sealed_at"]) <= C.instant(run_started_at), "CORPUS_SEALED_AFTER_OUTPUTS",
                  "/seal/sealed_at")


def _primary_directions(root: Path, calls: list) -> list:
    """(settled cutoff, narrative direction) for each complete primary call."""
    out = []
    for call in calls:
        if call["purpose"] != "PRIMARY" or call["record_status"] != "COMPLETE" or not call["post_guard_output_ref"]:
            continue
        data = C.verify_artifact(call["post_guard_output_ref"], root, "/post_guard_output_ref")
        parsed = json.loads(data.decode("utf-8"))
        direction = parsed.get("narrative_direction") if isinstance(parsed, dict) else None
        out.append((C.instant(call["decision_time"]), direction if direction in DIRECTIONS else "UNKNOWN",
                    call["evaluation_origin"]))
    return out


def _cell(layer, expected, observed, *, count=1, eligible=True, unproven=False, ref=None, assessment="DIAGNOSTIC"):
    return {"layer": layer, "expected": expected, "observed": observed, "unit": "EPISODE", "count": count,
            "eligible_count": count if eligible and not unproven else 0,
            "excluded_count": 0 if eligible else count, "unproven_count": count if unproven else 0,
            "truth_source_ref": ref, "assessment": "UNPROVEN" if unproven else assessment}


def _metric(name, numerator, denominator, *, excluded=0, unproven=0, assessment="DIAGNOSTIC", threshold=None):
    C.require(0 <= numerator <= denominator, "METRIC_NUMERATOR_OUT_OF_RANGE", "/" + name)
    return {"name": name, "value": (numerator / denominator) if denominator else None, "numerator": numerator,
            "denominator": denominator, "excluded_count": excluded, "unproven_count": unproven,
            "threshold_ref": threshold, "assessment": assessment if denominator else "UNSCORED"}


def classify_episode(label: dict, events: list, directions: list, *, tolerance_seconds: int = 0) -> dict:
    """Every layer for one labelled episode; pure function of trace + label."""
    window = (C.instant(label["window"]["start_utc"]), C.instant(label["window"]["end_utc"]))
    earliest = C.instant(label["earliest_available_utc"])
    target_start = C.instant(label["recognition_target"]["start_utc"])
    target_end = C.instant(label["recognition_target"]["end_utc"])
    # Tolerance extends the target forward only; it never moves availability earlier.
    tolerant_end = target_end + timedelta(seconds=max(0, tolerance_seconds))
    def observation_time(event):
        return C.instant(event.get("observed_at", event["settled_cutoff"]))
    inside = [e for e in events if window[0] <= observation_time(e) < window[1]]
    scored = [e for e in inside if not e["event_kind"].startswith("PREWARM")]
    expected_direction = label["dominant_campaign_direction"]
    violations, cells = [], []
    early = [d for d in directions if d[0] < earliest and d[1] == expected_direction
             and target_start <= d[0] < tolerant_end]
    early_entries = [e for e in scored if e["outcome"] in ENTRY_OUTCOMES and observation_time(e) < earliest]
    if early_entries:
        violations.append(f"EARLY_POSITIVE_AUTHORITY:{label['label_id']}:{observation_time(early_entries[0]).isoformat()}")
    lawful = [d for d in directions if earliest <= d[0] and target_start <= d[0] < tolerant_end]
    first_match = next((d for d in lawful if d[1] == expected_direction), None)
    observed_direction = lawful[0][1] if lawful else "unavailable"
    ambiguous = label["ambiguous"] or label["confidence"] == "UNKNOWN"
    # RECOGNITION
    if not lawful:
        cells.append(_cell("RECOGNITION", expected_direction, "unavailable", unproven=True))
    elif expected_direction != "UNKNOWN" and all(d[1] == "UNKNOWN" for d in lawful):
        cells.append(_cell("RECOGNITION", expected_direction, "UNKNOWN_JUDGMENT", unproven=True))
    elif expected_direction == "UNKNOWN" or ambiguous:
        name = "UNKNOWN_TRUTH_DIRECTIONAL_OBSERVATION" if observed_direction in ("bullish", "bearish") else \
            "AMBIGUOUS_UNSCORED"
        cells.append(_cell("RECOGNITION", expected_direction, name, eligible=False, assessment="UNSCORED"))
    else:
        cells.append(_cell("RECOGNITION", expected_direction,
                           "HIT" if first_match else f"OBSERVED_{observed_direction}"))
    # TIMING
    latency = None
    if first_match:
        latency = max(0.0, (first_match[0] - target_end).total_seconds())
        cells.append(_cell("TIMING", "within_target", "LATE" if latency > 0 else "ON_TIME"))
    if early:
        # A matching judgment before the fact was knowable is never a hit; positive
        # authority (a candidate) that early is a chronology violation, below.
        cells.append(_cell("TIMING", "after_availability", "EARLY_BEFORE_AVAILABILITY", eligible=False))
    # REFUSAL / opportunity
    expected_action = label["expected_action"]
    entries = [e for e in scored if e["outcome"] in ENTRY_OUTCOMES and observation_time(e) >= earliest]
    blockers = [e for e in scored if e["outcome"] in NON_COGNITION_BLOCKERS]
    degraded = scored and all(e["outcome"] in DEGRADED_OUTCOMES for e in scored)
    if not scored:
        observed = "missing"
    elif degraded:
        observed = "degraded"
    elif entries:
        observed = "ENTRY"
    else:
        observed = "STAND_DOWN"
    if observed in ("missing", "degraded") or (not lawful and not entries and not blockers) or (
            expected_action == "ENTRY" and lawful and all(d[1] == "UNKNOWN" for d in lawful) and not entries):
        name, unproven, eligible = "UNPROVEN", True, True
    elif expected_action == "UNKNOWN" or ambiguous or label["opportunity"] in ("ambiguous", "UNKNOWN"):
        name, unproven, eligible = ("HONEST_UNKNOWN" if observed == "STAND_DOWN" else "AMBIGUOUS_UNSCORED"), False, False
    elif expected_action == "ENTRY" and observed == "ENTRY":
        name, unproven, eligible = "HIT", False, True
    elif expected_action == "ENTRY" and first_match and blockers:
        # Right cognition, lawfully blocked downstream: not a cognition miss.
        name, unproven, eligible = "RECOGNIZED_BLOCKED_BY_" + blockers[0]["outcome"], False, True
    elif expected_action == "ENTRY":
        name, unproven, eligible = ("MISS" if label["confidence"] == "CLEAR" else "AMBIGUOUS_UNSCORED"), False, \
            label["confidence"] == "CLEAR"
    elif observed == "ENTRY":
        name, unproven, eligible = "FALSE_POSITIVE", False, True
    else:
        name, unproven, eligible = "CORRECT_REFUSAL", False, True
    cells.append(_cell("REFUSAL", expected_action, name, unproven=unproven, eligible=eligible))
    # FACT: exact occurrence identity, raw (never alpha-renamed)
    occurrence = label.get("occurrence_id")
    selected = sorted({e["tool_occurrence_id"] for e in entries if e["tool_occurrence_id"]})
    if occurrence:
        cells.append(_cell("FACT", occurrence, "EXACT_OCCURRENCE" if occurrence in selected else
                           ("OTHER_OCCURRENCE" if selected else "NOT_SELECTED"), ref=label["label_id"]))
    first_candidate = observation_time(entries[0]).isoformat() if entries else None
    return {"label_id": label["label_id"], "cells": cells, "violations": violations,
            "first_recognition_utc": first_match[0].isoformat() if first_match else None,
            "first_candidate_utc": first_candidate, "latency_seconds": latency,
            "selected_occurrences": selected, "scan_count": len(scored),
            "first_refusal_code": next((e["first_refusal_code"] for e in scored if e["first_refusal_code"]), None),
            "observed_action": observed, "evidence": "missing" if not scored else "present"}


#: Every metric `score_trace` emits; a ratified rule naming anything else is refused.
METRIC_NAMES = ("episodes_with_evidence", "recognition_hits", "recognition_hits_diagnostic", "false_positive_entries",
                "correct_refusals", "exact_occurrence_selected", "authority_invariant_violations",
                "missing_cognition_calls", "degraded_scans", "unique_candidates")


def rule_holds(value, rule: dict) -> bool:
    """The one comparison a ratified threshold rule means; the report reuses it."""
    return {"<=": value <= rule["value"], ">=": value >= rule["value"], "==": value == rule["value"]}[rule["operator"]]


def _threshold(metric: dict, scoring: dict | None, inclusion: Inclusion) -> dict:
    if not (inclusion.ratified and inclusion.current_recognition):
        return metric
    for rule in scoring["thresholds"]:
        if rule["metric"] == metric["name"]:
            # A required rule with no scored evidence stays bound to its rule as UNPROVEN;
            # it must never drop out of the obligation set (contract 07, owner audit residual).
            assessment = ("UNPROVEN" if metric["denominator"] == 0
                          else "PASS" if rule_holds(metric["value"], rule) else "FAIL")
            metric.update(assessment=assessment, threshold_ref=rule["decision_ref"])
    return metric


def check_rules(scoring: dict) -> None:
    """Unknown or duplicated threshold rules are hard refusals, never silently skipped."""
    rules = [r["metric"] for r in scoring["thresholds"]]
    C.require(all(name in METRIC_NAMES for name in rules), "UNKNOWN_SCORING_METRIC", "/thresholds")
    C.require(len(rules) == len(set(rules)), "DUPLICATE_SCORING_METRIC", "/thresholds")


def score_trace(root, *, mode: str, session_id: str, trajectory_id: str, annotation: dict | None,
                scoring: dict | None = None) -> dict:
    """One session/trajectory summary (result/v1 `session_summaries[]` item) + its mask."""
    root = Path(root)
    from recognition_validation.report import read_manifest
    manifest = read_manifest(root)
    events = REC.read_events(root)      # chain-verified, raw identities
    calls = REC.read_calls(root)
    if annotation is not None:
        admit_annotation(annotation, corpus=None, run_started_at=(manifest or {}).get("real_started_at"))
        C.require(annotation["session_id"] == session_id, "ANNOTATION_SESSION_MISMATCH", "/session_id")
    expected_calls = sum(e["primary_call_count"] + e["repair_call_count"] for e in events)
    C.require(expected_calls == len(calls), "BRAIN_CALL_COUNT_MISMATCH", "/brain_calls",
              f"{len(calls)} records for {expected_calls} declared calls")
    allowed = {"A": {"HISTORICAL", "MISSING"}, "B": {"MOCK", "MISSING"},
               "C": {"CURRENT_EXTERNAL", "MISSING"}}
    C.require(mode in allowed, "MODE_UNKNOWN", "/mode")
    C.require(all(c["evaluation_origin"] in allowed[mode] for c in calls),
              "MODE_EVIDENCE_MISMATCH", "/brain_calls/evaluation_origin")
    for record in events + calls:
        C.require(record["trajectory_id"] == trajectory_id, "ARTIFACT_FOREIGN_TRAJECTORY", "/trajectory_id")
        if manifest:
            C.require(record["run_digest"] == manifest.get("run_digest", manifest["corpus_digest"]),
                      "ARTIFACT_FOREIGN_RUN", "/run_digest")
    if manifest and annotation:
        C.require(annotation["corpus_digest"] == manifest["corpus_digest"], "ANNOTATION_CORPUS_MISMATCH", "/corpus_digest")
    for event in events:
        for ref in event["evidence_refs"]:
            C.verify_artifact(ref, root, "/events/evidence_refs")
    for call in calls:
        for name in ("input_ref", "prompt_ref", "raw_response_ref", "parsed_output_ref", "post_guard_output_ref",
                     "request_ref"):
            if call.get(name):
                C.verify_artifact(call[name], root, f"/calls/{call['document_id']}/{name}")
    # An outcome is never truth: labels may not cite this run's own evidence.
    produced = {C.sha256_hex(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for index, label in enumerate((annotation or {}).get("labels") or []):
        for ref in label["source_evidence"]:
            C.require(ref["sha256"] not in produced, "OUTCOME_AS_TRUTH", f"/labels/{index}/source_evidence",
                      ref["path"])
    inclusion = Inclusion(mode=mode, annotation=annotation, scoring=scoring)
    directions = _primary_directions(root, calls)
    tolerance = int((scoring or {}).get("tolerance_seconds") or 0) if inclusion.ratified else 0
    labels = (annotation or {}).get("labels") or []
    episodes = [classify_episode(label, events, directions, tolerance_seconds=tolerance) for label in labels]
    cells = [cell for e in episodes for cell in e["cells"]]
    if not inclusion.current_recognition:
        for cell in cells:
            if cell["layer"] in ("RECOGNITION", "TIMING") and cell["assessment"] != "FAIL":
                # Mode A/B (or unsealed truth) are diagnostics outside current-recognition denominators.
                cell["excluded_count"], cell["eligible_count"] = cell["count"], 0
    violations = [v for e in episodes for v in e["violations"]]
    rec = [c for c in cells if c["layer"] == "RECOGNITION"]
    ref = [c for c in cells if c["layer"] == "REFUSAL"]
    missing_cognition = sum(1 for c in calls if c["evaluation_origin"] == "MISSING")
    degraded = sum(1 for e in events if e["outcome"] in DEGRADED_OUTCOMES)
    unique_candidates = len({e["candidate_id"] for e in events if e["candidate_id"]})
    current = "DIAGNOSTIC" if inclusion.current_recognition else "UNPROVEN"
    metrics = [
        _metric("episodes_with_evidence", sum(1 for e in episodes if e["evidence"] == "present"), len(episodes)),
        _threshold(_metric("recognition_hits", sum(1 for c in rec if c["observed"] == "HIT" and c["eligible_count"]),
                           sum(c["eligible_count"] for c in rec), excluded=sum(c["excluded_count"] for c in rec),
                           unproven=sum(c["unproven_count"] for c in rec), assessment=current), scoring, inclusion),
        _metric("recognition_hits_diagnostic", sum(1 for c in rec if c["observed"] == "HIT"),
                sum(1 for c in rec if c["assessment"] != "UNSCORED" and not c["unproven_count"]),
                unproven=sum(c["unproven_count"] for c in rec)),
        _threshold(_metric("false_positive_entries", sum(1 for c in ref if c["observed"] == "FALSE_POSITIVE"),
                           sum(c["eligible_count"] for c in ref), excluded=sum(c["excluded_count"] for c in ref),
                           unproven=sum(c["unproven_count"] for c in ref)), scoring, inclusion),
        _metric("correct_refusals", sum(1 for c in ref if c["observed"] == "CORRECT_REFUSAL"),
                sum(c["eligible_count"] for c in ref), excluded=sum(c["excluded_count"] for c in ref),
                unproven=sum(c["unproven_count"] for c in ref)),
        _metric("exact_occurrence_selected",
                sum(1 for c in cells if c["layer"] == "FACT" and c["observed"] == "EXACT_OCCURRENCE"),
                sum(1 for c in cells if c["layer"] == "FACT")),
        _metric("authority_invariant_violations", len(violations), max(len(violations), len(episodes))),
        _metric("missing_cognition_calls", missing_cognition, len(calls)),
        _metric("degraded_scans", degraded, len(events)),
        _metric("unique_candidates", unique_candidates, max(unique_candidates, 1) if events else 0),
    ]
    C.require(tuple(m["name"] for m in metrics) == METRIC_NAMES, "METRIC_SET_DRIFT", "/metrics")
    if scoring is not None:
        check_rules(scoring)
        metrics = [_threshold(metric, scoring, inclusion) for metric in metrics]
    limitations = []
    if annotation is None:
        limitations.append("NO_ANNOTATION: every label metric UNSCORED")
    elif not inclusion.owner_truth:
        limitations.append(f"ANNOTATION_{inclusion.annotation_state}: descriptive only, never benchmark truth")
    if mode in ("A", "B"):
        limitations.append(f"MODE_{mode}: mechanics only; current discretionary recognition UNPROVEN")
    if not inclusion.ratified:
        limitations.append("SCORING_NOT_RATIFIED: no thresholds; assessments DIAGNOSTIC")
    first_rec = sorted(e["first_recognition_utc"] for e in episodes if e["first_recognition_utc"])
    first_cand = sorted(e["first_candidate_utc"] for e in episodes if e["first_candidate_utc"])
    return {
        "summary": {"session_id": session_id, "trajectory_id": trajectory_id,
                    "scored_episode_count": sum(1 for e in episodes if e["evidence"] == "present"),
                    "missing_episode_count": sum(1 for e in episodes if e["evidence"] == "missing"),
                    "metrics": metrics, "confusion_cells": cells,
                    "first_recognition_utc": first_rec[0] if first_rec else None,
                    "first_candidate_utc": first_cand[0] if first_cand else None,
                    "first_refusal_code": next((e["first_refusal_code"] for e in events if e["first_refusal_code"]),
                                               None),
                    "limitations": limitations},
        "episodes": episodes, "violations": violations, "inclusion": inclusion.document(),
        "external_request_count": sum(1 for c in calls if c["request_attempted"]),
        "event_count": len(events), "call_count": len(calls),
    }

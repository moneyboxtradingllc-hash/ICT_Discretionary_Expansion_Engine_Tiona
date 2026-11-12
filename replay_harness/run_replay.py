"""Offline replay harness -- Layer A and Layer B.

    python replay_harness/run_replay.py --evidence-root <dir> --out <dir>

``--evidence-root`` holds the five approved packet zips under their original
names. ``--out`` must be a new or empty directory outside the repository.

The run is offline and read-only with respect to everything except ``--out``:
the network is refused, credential-looking environment variables are dropped,
the frozen source is verified against the pinned manifest before it is
imported, and every packet is hash-checked before it is read.

Order of work, which is also the order of the no-lookahead guarantee:

  1. isolation, frozen-source check, packet and per-file hash check
  2. planted failures
  3. DECISION PASS  -- replay every Brain record; outcomes cannot be opened
  4. the replay output is written and hashed (sealed)
  5. COMPARISON PASS -- populations, Layer A bins, Layer B crosswalk
  6. coverage report and output hashes

Exit status is 0 only when integrity, populations, planted failures and both
layers are all clean.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import guard                                           # noqa: E402
import frozen as frozen_mod                            # noqa: E402
import layer_a                                         # noqa: E402
import layer_b                                         # noqa: E402
import planted                                         # noqa: E402
import populations                                     # noqa: E402
from evidence import SESSIONS, Evidence, sha256_file   # noqa: E402


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, ensure_ascii=False, default=str)
        fh.write("\n")


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(layer_a.dumps(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    root = os.path.abspath(args.evidence_root)
    repo = frozen_mod.REPO
    if os.path.commonpath([out, repo]) == repo:
        print("REFUSED: --out must be outside the repository")
        return 2
    os.makedirs(out, exist_ok=True)
    if os.listdir(out):
        print("REFUSED: --out must be empty")
        return 2

    # 1. isolation and integrity ------------------------------------------
    guard.block_network()
    removed = guard.scrub_environment()
    os.chdir(out)                      # any stray relative write lands in --out
    source = frozen_mod.verify_source()
    phase = guard.Phase()
    evidence = Evidence(root, phase)
    packets = evidence.verify()
    _write_json(os.path.join(out, "01_integrity.json"), {
        "frozen_source": source, "evidence": packets,
        "environment_variables_dropped": len(removed),
        "python": "%d.%d" % sys.version_info[:2]})
    if not (source["ok"] and packets["ok"]):
        print("STOP: integrity check failed; see 01_integrity.json")
        return 1
    frozen = frozen_mod.Frozen()

    # 2. planted failures ---------------------------------------------------
    plant = planted.run(evidence, SESSIONS[0])
    _write_json(os.path.join(out, "02_planted_failures.json"), plant)

    # 3. decision pass ------------------------------------------------------
    replays = collections.OrderedDict()
    for s in SESSIONS:
        replays[s] = layer_a.replay_session(frozen, evidence, s)
    assert evidence.outcome_reads == 0, "an outcome was read during the decision pass"
    flat = [r for s in SESSIONS for r in replays[s]]
    replay_path = os.path.join(out, "03_layer_a_decision_pass.jsonl")
    _write_jsonl(replay_path, flat)
    sealed = sha256_file(replay_path)

    # 4./5. comparison pass -------------------------------------------------
    phase.enter_comparison()
    per_session, comparisons, crosswalks, labelled_all = collections.OrderedDict(), [], [], {}
    for s in SESSIONS:
        base = f"data/replay_sessions/{s}/memory_retrieval/"
        rows = evidence.read_jsonl(s, base + "candidate_decisions.jsonl")
        labelled = layer_a.classify_rows(rows)
        labelled_all[s] = labelled
        retrieval = evidence.read_jsonl(s, base + "retrieval_scans.jsonl")
        cw = layer_b.crosswalk_session(frozen, evidence, s, labelled)
        crosswalks.append(cw)
        per_session[s] = populations.count_session(
            replays[s], labelled, retrieval, cw["totals"]["missions"])
        comparisons.extend(layer_a.compare(replays[s], labelled))
    controls = planted.comparison_controls(frozen, evidence, labelled_all[SESSIONS[0]],
                                           SESSIONS[0])
    plant["comparison_controls"] = controls
    plant["all_pass"] = plant["all_pass"] and controls["all_pass"]
    _write_json(os.path.join(out, "02_planted_failures.json"), plant)
    totals = populations.total(per_session)
    pop_check = populations.check_against_reported(totals)
    _write_json(os.path.join(out, "04_populations.json"), {
        "per_session": per_session, "total": totals, "check": pop_check,
        "reported_figures_used_only_for_this_check": populations.REPORTED})
    _write_jsonl(os.path.join(out, "05_layer_a_comparison.jsonl"), comparisons)

    answers = [c for c in comparisons if c["record_class"] == layer_a.CLASS_ANSWER]
    others = [c for c in comparisons if c["record_class"] != layer_a.CLASS_ANSWER]
    bins = collections.Counter(c["bin"] for c in answers)
    by_session = collections.OrderedDict()
    for s in SESSIONS:
        a = [c for c in answers if c["session_id"] == s]
        o = [c for c in others if c["session_id"] == s]
        b = collections.Counter(c["bin"] for c in a)
        k = per_session[s]["rows_by_kind"]
        by_session[s] = {
            "compared": len(a), "MATCH": b[layer_a.MATCH], "DEFECT": b[layer_a.DEFECT],
            "LIMITATION": b[layer_a.LIMITATION],
            "consistency_checked": len(o),
            "CONSISTENT": sum(1 for c in o if c["consistency"] == "CONSISTENT"),
            "INCONSISTENT": sum(1 for c in o if c["consistency"] != "CONSISTENT"),
            "NOT_ATTEMPTED_plan_trigger_rows": k["PLAN_TRIGGER"],
            "NOT_ATTEMPTED_held_rows": k["HELD"]}
    audit_findings = [{"scan_id": r["scan_id"], "session_id": r["session_id"], **f}
                      for r in flat for f in r["lookahead_audit"]]
    layer_a_summary = {
        "decision_pass_sha256_sealed_before_any_outcome_was_opened": sealed,
        "compared_denominator": len(answers),
        "MATCH": bins[layer_a.MATCH], "DEFECT": bins[layer_a.DEFECT],
        "LIMITATION": bins[layer_a.LIMITATION],
        "consistency_denominator": len(others),
        "CONSISTENT": sum(1 for c in others if c["consistency"] == "CONSISTENT"),
        "INCONSISTENT": sum(1 for c in others if c["consistency"] != "CONSISTENT"),
        "NOT_ATTEMPTED": {
            "plan_trigger_rows": totals["rows_by_kind"]["PLAN_TRIGGER"],
            "held_rows": totals["rows_by_kind"]["HELD"]},
        "by_session": by_session,
        "fields_not_compared": layer_a.NOT_COMPARED,
        "recorded_inputs_audited_for_lookahead": len(flat),
        "lookahead_findings_in_recorded_inputs": audit_findings,
        "non_matching_scans": [c for c in comparisons
                               if c.get("bin") in (layer_a.DEFECT, layer_a.LIMITATION)
                               or c.get("consistency") == "INCONSISTENT"]}
    _write_json(os.path.join(out, "06_layer_a_summary.json"), layer_a_summary)

    mission_bins = collections.Counter(m["bin"] for cw in crosswalks for m in cw["missions"])
    later_bins = collections.Counter(r["bin"] for cw in crosswalks for r in cw["later_stage_rows"])
    b_totals = collections.Counter()
    for cw in crosswalks:
        b_totals.update(cw["totals"])
    layer_b_summary = {
        "missions": {"denominator": sum(mission_bins.values()),
                     "MATCH": mission_bins[layer_a.MATCH], "DEFECT": mission_bins[layer_a.DEFECT],
                     "LIMITATION": mission_bins[layer_a.LIMITATION]},
        "later_stage_rows": {"denominator": sum(later_bins.values()),
                             "MATCH": later_bins[layer_a.MATCH],
                             "DEFECT": later_bins[layer_a.DEFECT],
                             "LIMITATION": later_bins[layer_a.LIMITATION]},
        "totals": dict(sorted(b_totals.items())),
        "not_in_the_packets": [
            "per-trade and per-session profit, loss and fees (venue account reads)",
            "the venue account read behind each loss-budget governor refusal",
            "a shared identifier between a decision row and its mission"]}
    _write_json(os.path.join(out, "07_layer_b_crosswalk.json"),
                {"summary": layer_b_summary, "sessions": crosswalks})

    # 6. coverage -----------------------------------------------------------
    coverage = {"populations_not_replayed": [
        {"population": "conditional-plan trigger rows",
         "count": totals["rows_by_kind"]["PLAN_TRIGGER"],
         "by_result": totals["plan_trigger_rows_by_result"],
         "why": "no snapshot or Brain input is recorded at a trigger; the catalogs, "
                "protected swings and path state the decision step re-validated "
                "against cannot be rebuilt from the packets"},
        {"population": "held rows (model intentionally not called)",
         "count": totals["rows_by_kind"]["HELD"],
         "why": "no model call and no snapshot; only the hold and its reason are recorded"},
        {"population": "timeout fallbacks and the degraded record",
         "count": totals["timeout_fallbacks"] + totals["degraded"],
         "why": "no model answer exists and no decision row was written; checked for "
                "consistency only (the frozen code must refuse them), never as MATCH"},
        {"population": "scans with retrieval telemetry but no Brain record and no decision row",
         "count": totals["retrieval_scan_ids_with_neither_brain_record_nor_row"],
         "why": "these scans made no entry decision; retrieval telemetry is not a decision"},
        {"population": "later-stage rows not tied to a mission",
         "count": later_bins[layer_a.LIMITATION],
         "why": "governor and post-trigger refusals: the reason is recorded, the live "
                "venue read or trigger-time quote behind it is not"},
        {"population": "Layer C (rebuilding snapshots from candles)", "count": None,
         "why": "out of scope for this authorisation"}],
        "layer_a": {k: layer_a_summary[k] for k in (
            "compared_denominator", "MATCH", "DEFECT", "LIMITATION",
            "consistency_denominator", "CONSISTENT", "INCONSISTENT", "NOT_ATTEMPTED")},
        "layer_b": layer_b_summary}
    _write_json(os.path.join(out, "08_coverage.json"), coverage)

    hashes = {f: sha256_file(os.path.join(out, f)) for f in sorted(os.listdir(out))}
    _write_json(os.path.join(out, "OUTPUT_HASHES.json"), hashes)

    ok = (plant["all_pass"] and pop_check["ok"] and bins[layer_a.DEFECT] == 0
          and layer_a_summary["INCONSISTENT"] == 0 and not audit_findings
          and mission_bins[layer_a.DEFECT] == 0 and later_bins[layer_a.DEFECT] == 0)
    print(f"integrity            : source ok={source['ok']}  packets ok={packets['ok']}")
    print(f"planted failures     : all pass={plant['all_pass']}")
    print(f"populations          : ok={pop_check['ok']}  diffs={pop_check['differences_from_reported']}")
    print(f"layer A (of {len(answers)})     : MATCH {bins[layer_a.MATCH]}  DEFECT {bins[layer_a.DEFECT]}"
          f"  LIMITATION {bins[layer_a.LIMITATION]}")
    print(f"consistency (of {len(others)}) : CONSISTENT {layer_a_summary['CONSISTENT']}"
          f"  INCONSISTENT {layer_a_summary['INCONSISTENT']}")
    print(f"not attempted        : {layer_a_summary['NOT_ATTEMPTED']}")
    print(f"lookahead findings   : {len(audit_findings)}")
    print(f"layer B missions     : {dict(mission_bins)}   later-stage rows: {dict(later_bins)}")
    print(f"RESULT               : {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

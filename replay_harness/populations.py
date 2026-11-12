"""Scan populations and denominators, counted from the packets alone.

Nothing here uses a number from an earlier report as an input. The figures
previously reported to the owner are held in ``REPORTED`` only to be compared
against after counting; a difference is recorded and fails the run.
"""
from __future__ import annotations

import collections

from layer_a import (CLASS_ANSWER, CLASS_DEGRADED, CLASS_FALLBACK, ROW_BRAIN,
                     ROW_HELD, ROW_LATER, ROW_TRIGGER)

REPORTED = {"brain_records": 1039, "provider_answers": 815, "timeout_fallbacks": 223,
            "degraded": 1, "decision_rows": 919, "scan_ids_with_a_row": 865,
            "rows_beyond_first_per_scan_id": 54, "retrieval_scan_ids": 4283,
            "missions": 14}


def count_session(replays: list, labelled: list, retrieval_rows: list,
                  mission_count: int) -> dict:
    classes = collections.Counter(r["record_class"] for r in replays)
    kinds = collections.Counter(item["kind"] for item in labelled)
    by_scan = collections.defaultdict(list)
    for item in labelled:
        by_scan[item["row"].get("scan_id")].append(item["kind"])
    brain_scan_ids = {r["scan_id"] for r in replays}
    answer_ids = {r["scan_id"] for r in replays if r["record_class"] == CLASS_ANSWER}
    no_answer_ids = brain_scan_ids - answer_ids
    row_ids = set(by_scan)
    shared = {sid: kinds_ for sid, kinds_ in by_scan.items()
              if len({k for k in kinds_ if k != ROW_LATER}) > 1
              or kinds_.count(ROW_HELD) > 1 or kinds_.count(ROW_TRIGGER) > 1}
    trigger = [i["row"] for i in labelled if i["kind"] == ROW_TRIGGER]
    retrieval_ids = {r.get("scan_id") for r in retrieval_rows if r.get("scan_id")}
    return {
        "brain_records": len(replays),
        "brain_record_scan_ids_unique": len(brain_scan_ids) == len(replays),
        "provider_answers": classes[CLASS_ANSWER],
        "timeout_fallbacks": classes[CLASS_FALLBACK],
        "degraded": classes[CLASS_DEGRADED],
        "other_brain_records": len(replays) - classes[CLASS_ANSWER]
        - classes[CLASS_FALLBACK] - classes[CLASS_DEGRADED],
        "decision_rows": len(labelled),
        "rows_by_kind": {k: kinds[k] for k in (ROW_BRAIN, ROW_HELD, ROW_TRIGGER, ROW_LATER)},
        "plan_trigger_rows_by_result": dict(sorted(collections.Counter(
            ("candidate_created" if r.get("final_disposition") == "CANDIDATE_CREATED"
             else str(r.get("final_rejection_reason"))) for r in trigger).items())),
        "later_stage_rows_by_reason": dict(sorted(collections.Counter(
            str(i["row"].get("final_rejection_reason")) for i in labelled
            if i["kind"] == ROW_LATER).items())),
        "scan_ids_with_a_row": len(row_ids),
        "rows_beyond_first_per_scan_id": len(labelled) - len(row_ids),
        "scan_ids_shared_by_two_separate_events": len(shared),
        "shared_scan_ids": {k: v for k, v in sorted(shared.items())},
        "answers_with_a_first_stage_row": len(
            answer_ids & {i["row"].get("scan_id") for i in labelled if i["kind"] == ROW_BRAIN}),
        "fallback_or_degraded_with_any_row": len(no_answer_ids & row_ids),
        "scan_ids_with_a_row_but_no_brain_record": len(row_ids - brain_scan_ids),
        "retrieval_scan_ids": len(retrieval_ids),
        "retrieval_scan_ids_with_neither_brain_record_nor_row": len(
            retrieval_ids - brain_scan_ids - row_ids),
        "brain_or_row_scan_ids_missing_from_retrieval": len(
            (brain_scan_ids | row_ids) - retrieval_ids),
        "missions": mission_count,
    }


def total(per_session: dict) -> dict:
    out = collections.OrderedDict()
    keys = [k for k, v in next(iter(per_session.values())).items() if isinstance(v, int)
            and not isinstance(v, bool)]
    for k in keys:
        out[k] = sum(s[k] for s in per_session.values())
    for nested in ("rows_by_kind", "plan_trigger_rows_by_result", "later_stage_rows_by_reason"):
        acc = collections.Counter()
        for s in per_session.values():
            acc.update(s[nested])
        out[nested] = dict(sorted(acc.items()))
    out["brain_record_scan_ids_unique"] = all(
        s["brain_record_scan_ids_unique"] for s in per_session.values())
    return dict(out)


def check_against_reported(totals: dict) -> dict:
    diffs = {k: {"reported": v, "counted": totals.get(k)}
             for k, v in REPORTED.items() if totals.get(k) != v}
    arithmetic = {
        "answers+fallbacks+degraded==brain_records":
            totals["provider_answers"] + totals["timeout_fallbacks"] + totals["degraded"]
            + totals["other_brain_records"] == totals["brain_records"],
        "row_kinds_sum==decision_rows":
            sum(totals["rows_by_kind"].values()) == totals["decision_rows"],
        "every_answer_has_exactly_one_first_stage_row":
            totals["answers_with_a_first_stage_row"] == totals["provider_answers"]
            == totals["rows_by_kind"]["BRAIN_FIRST_STAGE"],
        "no_fallback_or_degraded_record_has_a_row":
            totals["fallback_or_degraded_with_any_row"] == 0,
    }
    return {"differences_from_reported": diffs, "arithmetic": arithmetic,
            "ok": not diffs and all(arithmetic.values())}

"""Layer B -- mission / submission / fill crosswalk and terminal-state check.

Nothing is simulated. Fills, exits and venue answers are recorded facts. What
is checked is whether the independent records of one mission agree with each
other and with the frozen mission state machine:

* the mission's recorded state equals the last transition in its own history;
* the history only ever moves forward on the frozen lifecycle ladder and ends
  in a frozen terminal state;
* the attempt count, the submission journal and the venue order id agree;
* the decision row that follows the candidate (if any) says the same thing the
  mission says.

A mission whose exit the venue could not attribute to the trade plan is kept
as UNATTRIBUTED. It is never scored as a strategy win or loss here.
"""
from __future__ import annotations

import collections
import re
from datetime import datetime, timezone

from layer_a import DEFECT, LIMITATION, MATCH, ROW_LATER

_SCAN = re.compile(r"^scan-(\d{8})T(\d{6})$")


def scan_time(scan_id: str):
    m = _SCAN.match(str(scan_id or ""))
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
        tzinfo=timezone.utc)


def _ts(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def crosswalk_session(frozen, evidence, session_id: str, labelled: list) -> dict:
    ms = frozen.mission_state
    prefix = "data/integration/topstepx/"
    mission_files = sorted(
        (f for f in evidence.list(session_id, prefix + f"trade_mission_{session_id}_")),
        key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))
    sub_file = prefix + f"submissions_{session_id}.jsonl"
    journal = evidence.read_jsonl(session_id, sub_file) \
        if sub_file in evidence.list(session_id, prefix) else []
    subs = collections.OrderedDict()
    for entry in journal:
        subs.setdefault(entry.get("submission_id"), []).append(entry)
    auth = evidence.read_json(session_id, prefix + f"session_auth_{session_id}.json")

    creators = [i for i in labelled if i["row"].get("final_disposition") == "CANDIDATE_CREATED"]
    later_by_scan = collections.defaultdict(list)
    for i in labelled:
        if i["kind"] == ROW_LATER:
            later_by_scan[i["row"].get("scan_id")].append(i)

    missions, linked_later = [], set()
    for rel in mission_files:
        m = evidence.read_json(session_id, rel)
        hist = m.get("history") or []
        tos = [h.get("to") for h in hist]
        ranks = [ms.lifecycle_rank(s) for s in tos if ms.lifecycle_rank(s) is not None]
        armed_at = next((_ts(h.get("at")) for h in hist if h.get("to") == ms.ARMED), None)
        mine = {sid: e for sid, e in subs.items()
                if e and e[-1].get("mission_id") == m.get("mission_id")}
        # An entry order and an emergency close are different submissions.
        my_subs = {sid: e for sid, e in mine.items()
                   if e[-1].get("operation") == "ORDER_PLACE"}
        closes = {sid: e for sid, e in mine.items()
                  if e[-1].get("operation") == "POSITION_CLOSE"}
        other_ops = sorted({e[-1].get("operation") for e in mine.values()}
                           - {"ORDER_PLACE", "POSITION_CLOSE"})
        final = (list(my_subs.values())[-1][-1] if my_subs else None)
        state = m.get("state")
        filled = m.get("filled_quantity")
        unattributed = (m.get("completion_state") == "unattributed")

        # The candidate row this mission was armed from: the latest candidate
        # created at or before the arming time. The records share no key.
        prior = [c for c in creators if scan_time(c["row"].get("scan_id")) is not None
                 and armed_at is not None and scan_time(c["row"]["scan_id"]) <= armed_at]
        cand = prior[-1] if prior else None
        follow = later_by_scan.get(cand["row"].get("scan_id")) if cand else None
        follow_row = follow[0]["row"] if follow else None
        follow_reason = follow_row.get("final_rejection_reason") if follow_row else None
        if follow:
            linked_later.add(follow[0]["index"])

        if state == ms.TERMINAL_REFUSAL:
            kind = "REFUSED_BEFORE_SUBMISSION"
            note = str(m.get("last_transition") or "")
            expected_follow = note.split(":")[-1].strip() if ":" in note else None
        elif state == ms.VENUE_REJECTED_ZERO_FILL:
            kind, expected_follow = "VENUE_REJECTED_NO_FILL", "SUBMIT_REJECTED"
        elif state == ms.COMPLETE and unattributed:
            kind, expected_follow = "FILLED_EXIT_UNATTRIBUTED", "PROTECTION_MISSING"
        elif state == ms.COMPLETE:
            kind, expected_follow = "FILLED_EXIT_ATTRIBUTED", None
        else:
            kind, expected_follow = "NOT_TERMINAL", None

        geometry = (final or {}).get("geometry") if isinstance((final or {}).get("geometry"), dict) else {}
        crow = cand["row"] if cand else {}
        checks = collections.OrderedDict()
        checks["recorded_state_equals_last_history_transition"] = bool(tos) and tos[-1] == state
        checks["history_starts_unarmed"] = bool(hist) and hist[0].get("from") == ms.UNARMED
        checks["history_never_moves_backward_on_frozen_ladder"] = ranks == sorted(ranks)
        checks["recorded_state_is_a_frozen_terminal_state"] = state in ms.TERMINAL_STATES
        checks["attempt_count_agrees_with_history"] = \
            int(m.get("attempt_count") or 0) == (1 if ms.ATTEMPT_CONSUMED in tos else 0)
        checks["entry_submission_count_equals_attempt_count"] = \
            len(my_subs) == int(m.get("attempt_count") or 0)
        checks["emergency_close_submitted_only_for_unattributed_exit"] = \
            len(closes) == (1 if unattributed else 0) and not other_ops
        checks["venue_order_id_agrees_with_submission"] = (
            True if final is None or not final.get("success")
            else final.get("venue_order_id") == m.get("order_id"))
        checks["fill_agrees_with_history"] = (
            (filled is not None and int(filled) > 0) == (ms.POSITION_OPEN in tos))
        checks["candidate_row_found_before_arming"] = cand is not None
        checks["following_decision_row_agrees_with_mission"] = (follow_reason == expected_follow)
        problems = [k for k, v in checks.items() if not v]
        limitations = ["candidate row linked to the mission by time order; "
                       "the two records share no identifier"]
        if unattributed:
            limitations.append("exit unattributed by the venue records: closed by the "
                               "emergency flatten, not by the trade plan; not a strategy outcome")
        missions.append({
            "mission_id": m.get("mission_id"), "kind": kind, "recorded_state": state,
            "history": tos, "attempt_count": m.get("attempt_count"),
            "entry_submissions": len(my_subs),
            "emergency_close_submissions": len(closes),
            "submission_success": (final or {}).get("success"),
            "requested_quantity": (final or {}).get("quantity"),
            "filled_quantity": filled, "fill_price": m.get("fill_price"),
            "exit_type": m.get("exit_type") or None, "exit_price": m.get("exit_price"),
            "completion_state": m.get("completion_state") or None,
            "strategy_outcome": ("UNATTRIBUTED" if unattributed else
                                 "ATTRIBUTED" if kind == "FILLED_EXIT_ATTRIBUTED" else "NONE"),
            "candidate_scan_id": crow.get("scan_id"),
            "candidate_row_kind": cand["kind"] if cand else None,
            "candidate_from_conditional_plan":
                crow.get("decision_authority") == "PREAUTHORIZED_CONDITIONAL_PLAN",
            "following_row_reason": follow_reason, "expected_following_reason": expected_follow,
            "submitted_target_equals_row_objective": (
                None if not geometry or crow.get("resolved_objective_price") is None
                else geometry.get("target_price") == crow.get("resolved_objective_price")),
            "checks": dict(checks), "bin": MATCH if not problems else DEFECT,
            "failed_checks": problems, "limitations": limitations})

    ceiling = auth.get("absolute_stop_ceiling")
    armed_times = sorted(t for t in (
        next((_ts(h.get("at")) for h in (evidence.read_json(session_id, rel).get("history") or [])
              if h.get("to") == ms.ARMED), None) for rel in mission_files) if t)
    later_rows = []
    for i in labelled:
        if i["kind"] != ROW_LATER:
            continue
        row = i["row"]
        reason = row.get("final_rejection_reason")
        entry = {"scan_id": row.get("scan_id"), "row_index": i["index"], "reason": reason,
                 "linked_to_mission": i["index"] in linked_later}
        if i["index"] in linked_later:
            entry.update(bin=MATCH, basis="agrees with the linked mission's terminal state")
        elif reason == "CONTAMINATED":
            entry.update(bin=LIMITATION,
                         basis="loss-budget governor refusal; the refusal reason is "
                               "recorded, the venue read behind it is not",
                         missing_input="venue account read at the refusal")
        elif reason == "stop_distance_above_cap":
            m = re.search(r"stop distance ([\d.]+) points", str(row.get("detail") or ""))
            over = (m is not None and ceiling is not None and float(m.group(1)) > float(ceiling))
            entry.update(bin=LIMITATION, stated_distance=float(m.group(1)) if m else None,
                         ceiling=ceiling, stated_distance_exceeds_ceiling=over,
                         basis="refusal after a plan trigger; the stated distance exceeds the "
                               "authorised ceiling, but the trigger-time quote is not recorded",
                         missing_input="entry reference at the trigger")
        else:
            entry.update(bin=DEFECT, basis="later-stage row not explained by any mission")
        later_rows.append(entry)

    return {"session_id": session_id,
            "authorization": {k: auth.get(k) for k in (
                "decision_window", "maximum_trades", "maximum_risk_per_trade",
                "maximum_contracts", "absolute_stop_ceiling", "daily_loss_budget_usd")},
            "missions": missions, "later_stage_rows": later_rows,
            "totals": {
                "missions": len(missions),
                "entry_submissions": sum(m["entry_submissions"] for m in missions),
                "emergency_close_submissions": sum(
                    m["emergency_close_submissions"] for m in missions),
                "fills": sum(1 for m in missions if (m["filled_quantity"] or 0) > 0),
                "contracts_filled": sum(int(m["filled_quantity"] or 0) for m in missions),
                "refused_before_submission": sum(
                    1 for m in missions if m["kind"] == "REFUSED_BEFORE_SUBMISSION"),
                "venue_rejections": sum(
                    1 for m in missions if m["kind"] == "VENUE_REJECTED_NO_FILL"),
                "unattributed_exits": sum(
                    1 for m in missions if m["strategy_outcome"] == "UNATTRIBUTED"),
                "arming_times_recorded": len(armed_times)}}

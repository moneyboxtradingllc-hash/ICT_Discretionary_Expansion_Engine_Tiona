"""Layer A -- scan-level decision replay.

DECISION PASS (``replay_session``): for every Brain call record, the recorded
snapshot, recorded Brain input and recorded model answer are handed to the
frozen ``CandidateProducer.produce`` and the resulting decision record is built
with the frozen ``build_record``. No outcome file is opened in this pass.

COMPARISON PASS (``compare``): the sealed replay records are paired with the
recorded decision rows and each scan lands in exactly one bin.

Inputs that are reconstructed rather than recorded, each named so a reviewer
can challenge it:

* A-NOW      ``now`` is the recorded completion time of the model call. The
             live value was the process clock read a moment later.
* A-WINDOW   ``in_window`` is computed from ``now`` with the frozen
             ``window_for`` and the comparison used by
             tools/topstepx_production_session.py:749-759 (start <= HH:MM < end).
* A-INPUT    ``brain_input`` is the recorded ``input_payload`` (what the model
             saw). Live code rebuilt it from the same snapshot after the call.
* A-LASTBAR  ``latest_closed_bar_timestamp`` is the snapshot's
             ``candle_continuity.last``. It is not part of any compared field.
* A-CONTRACT tick size 0.25 and tick value 0.50 for MNQ. Not recorded as such;
             every recorded risk and contract figure depends on them.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from guard import ScanClock

CONTRACT_ID = "CON.F.US.MNQ.Z26"

CLASS_ANSWER = "PROVIDER_ANSWER"
CLASS_FALLBACK = "TIMEOUT_FALLBACK"
CLASS_DEGRADED = "DEGRADED"
CLASS_OTHER = "UNCLASSIFIED_RECORD"

MATCH, DEFECT, LIMITATION, NOT_ATTEMPTED = "MATCH", "DEFECT", "LIMITATION", "NOT_ATTEMPTED"

#: Row fields written by the recorder that the decision step does not determine.
NOT_COMPARED = {
    "volume_profile": "post-decision observation attached by the recorder",
    "conditional_plan_id": "derived from the process clock at publication",
    "execution_economics": "set only on later-stage rows",
    "decision_authority": "set only on plan-trigger rows",
    "plan_authored_scan_id": "set only on plan-trigger rows",
}


def classify_record(rec: dict) -> str:
    source = rec.get("source")
    fallback = str(rec.get("fallback_reason") or "")
    if source == "llm" and not fallback and rec.get("llm_raw_response"):
        return CLASS_ANSWER
    if source == "llm_failed_fallback" and "APITimeoutError" in fallback:
        return CLASS_FALLBACK
    if source == "degraded":
        return CLASS_DEGRADED
    return CLASS_OTHER


def _in_window(frozen, now: datetime) -> bool:
    sa = frozen.session_authorization
    now_et = now.astimezone(ZoneInfo(sa.PRODUCTION_WINDOW_TZ))
    w = sa.window_for(now_et.strftime("%Y%m%d"))
    return w["start"] <= now_et.strftime("%H:%M") < w["end"]


def replay_record(frozen, session_id: str, rel: str, rec: dict) -> dict:
    snapshot = rec.get("raw_snapshot") or {}
    brain_input = rec.get("input_payload") or {}
    parsed = rec.get("parsed_output") or {}
    scan_id = snapshot.get("memory_retrieval_telemetry_id")
    quote = ((brain_input.get("market") or {}).get("execution_price") or {})
    clock = ScanClock(t_market=snapshot.get("timestamp"),
                      t_quote=quote.get("captured_at"),
                      t_call_started=rec.get("provider_call_started_at"),
                      t_answer=rec.get("provider_call_completed_at"))
    out = {"session_id": session_id, "scan_id": scan_id, "brain_record": rel,
           "record_class": classify_record(rec),
           "t_market": clock.t_market.isoformat(),
           "t_quote": clock.t_quote.isoformat() if clock.t_quote else None,
           "t_answer": clock.t_answer.isoformat(),
           "lookahead_audit": clock.audit(snapshot, brain_input)}

    block = {"source": rec.get("source"), "output": parsed,
             "fallback_reason": rec.get("fallback_reason"),
             "llm_model": rec.get("llm_model"),
             "warnings": parsed.get("warnings") or []}
    out["sovereign"] = bool(frozen.is_sovereign(block))
    brain_result = frozen.to_brain_result(block)
    now = clock.release_answer(clock.t_answer, "producer invocation")
    in_window = _in_window(frozen, now)
    contract = frozen.TopstepXContract(id=CONTRACT_ID, name="MNQZ6", description="MNQ",
                                       tick_size=0.25, tick_value=0.5, active=True)
    producer = frozen.CandidateProducer(account_fingerprint="acct:replay",
                                        contract=contract)
    action = str(parsed.get("current_action") or "").lower()
    disposition, reason, detail, extras = None, None, "", {}
    try:
        candidate = producer.produce(
            brain_result=brain_result, brain_input=brain_input, snapshot=snapshot,
            qualification=snapshot.get("qualification") or {},
            engine_inventory=frozen.engine_inventory(snapshot),
            snapshot_id=scan_id,
            market_data_timestamp=str(snapshot.get("timestamp") or ""),
            latest_closed_bar_timestamp=str(
                (snapshot.get("candle_continuity") or {}).get("last") or ""),
            in_window=in_window, now=now, conditional_plan=(action == "watching"))
        if candidate.extras.get("conditional_plan"):
            disposition = "CONDITIONAL_PLAN"
            extras = {"conditional_plan": True,
                      "plan_expires_at": parsed.get("plan_expires_at"),
                      "activation_zone": candidate.extras.get("activation_zone")}
        else:
            disposition = "CANDIDATE"
    except frozen.NoCandidate as exc:
        disposition, reason, detail = "REJECTED", exc.reason, str(exc)
    except Exception as exc:  # noqa: BLE001 -- reported, never hidden
        out.update(replay_error=f"{type(exc).__name__}: {exc}"[:300], in_window=in_window)
        return out

    trace = dict(producer.last_decision_trace or {})
    qual = snapshot.get("qualification")
    if isinstance(qual, dict) and trace.get("qualification_result") is None:
        # topstepx_production_loop.py:175-179, applied by the recorder.
        trace["qualification_result"] = "PASS" if qual.get("qualified") else "REJECTED"
        trace["qualification_reason"] = qual.get("reason")
    record = frozen.build_record(
        session_id=session_id, scan_id=scan_id,
        timestamp_et=str(snapshot.get("timestamp") or ""), instrument="MNQ",
        contract=CONTRACT_ID, parsed=parsed, trace=trace,
        disposition=frozen.terminal_disposition(reason, created=(disposition == "CANDIDATE")),
        rejection_reason=reason, detail=detail)
    if disposition == "CONDITIONAL_PLAN":
        record["final_disposition"] = frozen.CONDITIONAL_PLAN_PUBLISHED
        record.update(extras)
    record["active_draw"] = str(parsed.get("active_draw") or "")[:200]
    record["invalidation_level"] = parsed.get("invalidation_level")
    out.update(in_window=in_window, replay_outcome=disposition, replay_record=record)
    return out


def replay_session(frozen, evidence, session_id: str) -> list:
    results = []
    for rel in evidence.brain_files(session_id):
        rec = evidence.read_json(session_id, rel)
        results.append(replay_record(frozen, session_id, rel, rec))
    return results


# ---------------------------------------------------------------- comparison
ROW_HELD, ROW_TRIGGER, ROW_BRAIN, ROW_LATER = "HELD", "PLAN_TRIGGER", "BRAIN_FIRST_STAGE", "LATER_STAGE"


def classify_rows(rows: list) -> list:
    """Label every decision row by what wrote it, from the row's own content.

    * HELD          reason is brain_sleep_hold (no model call was made).
    * LATER_STAGE   the previous row with the same scan id created a candidate;
                    this row is what then happened to that candidate.
    * PLAN_TRIGGER  written by the conditional-plan trigger path: it carries the
                    pre-authorised-plan marker, or it has no action text.
    * BRAIN_FIRST_STAGE  everything else: the decision step's verdict on a
                    model answer.
    """
    labelled, last_by_scan = [], {}
    for i, row in enumerate(rows):
        sid = row.get("scan_id")
        prev = last_by_scan.get(sid)
        if row.get("final_rejection_reason") == "brain_sleep_hold":
            kind = ROW_HELD
        elif prev is not None and prev.get("final_disposition") == "CANDIDATE_CREATED":
            kind = ROW_LATER
        elif row.get("decision_authority") == "PREAUTHORIZED_CONDITIONAL_PLAN" \
                or not str(row.get("action") or ""):
            kind = ROW_TRIGGER
        else:
            kind = ROW_BRAIN
        labelled.append({"index": i, "kind": kind, "row": row})
        last_by_scan[sid] = row
    return labelled


def compare(replays: list, labelled_rows: list) -> list:
    brain_rows = {}
    for item in labelled_rows:
        if item["kind"] == ROW_BRAIN:
            brain_rows.setdefault(item["row"].get("scan_id"), []).append(item)
    used = set()
    results = []
    for rp in replays:
        base = {"session_id": rp["session_id"], "scan_id": rp["scan_id"],
                "brain_record": rp["brain_record"], "record_class": rp["record_class"]}
        candidates = brain_rows.get(rp["scan_id"]) or []
        if rp["record_class"] != "PROVIDER_ANSWER":
            # Consistency check, never a MATCH.
            refused = rp.get("replay_outcome") == "REJECTED"
            ok = (not rp["sovereign"]) and refused and not candidates
            base.update(bin=None,
                        consistency="CONSISTENT" if ok else "INCONSISTENT",
                        sovereign=rp["sovereign"],
                        producer_refusal=(rp.get("replay_record") or {}).get(
                            "final_rejection_reason"),
                        first_stage_rows_found=len(candidates),
                        replay_error=rp.get("replay_error"))
            results.append(base)
            continue
        if len(candidates) != 1:
            base.update(bin=LIMITATION,
                        reason=f"pairing: {len(candidates)} first-stage rows carry this scan id",
                        missing_input="a unique scan identifier on the decision row")
            results.append(base)
            continue
        row = candidates[0]["row"]
        used.add(candidates[0]["index"])
        base["row_index"] = candidates[0]["index"]
        if rp.get("replay_error"):
            base.update(bin=DEFECT, reason="replay raised: " + rp["replay_error"],
                        recorded_disposition=row.get("final_disposition"),
                        recorded_reason=row.get("final_rejection_reason"))
            results.append(base)
            continue
        new = rp["replay_record"]
        keys = sorted((set(new) | set(row)) - set(NOT_COMPARED))
        diffs = [{"field": k, "recorded": row.get(k), "replayed": new.get(k)}
                 for k in keys if row.get(k) != new.get(k)]
        base.update(recorded_disposition=row.get("final_disposition"),
                    recorded_reason=row.get("final_rejection_reason"),
                    replayed_disposition=new.get("final_disposition"),
                    replayed_reason=new.get("final_rejection_reason"),
                    fields_compared=len(keys))
        if not diffs:
            base["bin"] = MATCH
        elif row.get("final_rejection_reason") == "conditional_plan_watch_unavailable" \
                and rp.get("replay_outcome") == "CONDITIONAL_PLAN":
            base.update(bin=LIMITATION, differences=diffs,
                        reason="the plan was refused because the live level watcher "
                               "could not arm; the watcher's state is not recorded",
                        missing_input="live quote-watcher state at publication")
        else:
            base.update(bin=DEFECT, differences=diffs,
                        reason="replayed record differs and every input was present")
        results.append(base)
    return results


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)

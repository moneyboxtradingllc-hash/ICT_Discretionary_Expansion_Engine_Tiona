"""Planted no-lookahead failures.

Each test asks for something the rules forbid and passes only if the harness
refuses with the intended rule. A control beside each test makes the same kind
of request legally, so a test cannot pass merely because everything is refused.
"""
from __future__ import annotations

import copy
import socket
from datetime import timedelta

from guard import (RULE_NETWORK, RULE_T_ANSWER, RULE_T_MARKET, RULE_T_OUTCOME,
                   RULE_T_QUOTE, IsolationViolation, LookaheadViolation, ScanClock)
from layer_a import CLASS_ANSWER, classify_record


def _attempt(fn):
    try:
        fn()
    except (LookaheadViolation, IsolationViolation) as exc:
        return {"refused": True, "rule_fired": exc.rule, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"refused": True, "rule_fired": f"OTHER:{type(exc).__name__}",
                "message": str(exc)[:200]}
    return {"refused": False, "rule_fired": None, "message": "request was allowed"}


def run(evidence, session_id: str) -> dict:
    rel = rec = None
    for f in evidence.brain_files(session_id):
        candidate = evidence.read_json(session_id, f)
        if classify_record(candidate) == CLASS_ANSWER:
            rel, rec = f, candidate
            break
    snapshot, brain_input = rec["raw_snapshot"], rec["input_payload"]
    quote = brain_input["market"]["execution_price"]

    def clock():
        return ScanClock(t_market=snapshot["timestamp"], t_quote=quote["captured_at"],
                         t_call_started=rec["provider_call_started_at"],
                         t_answer=rec["provider_call_completed_at"])

    c = clock()
    late_bar = (c.t_market + timedelta(minutes=1)).isoformat()
    late_quote = (c.t_quote + timedelta(seconds=1)).isoformat()
    early = c.t_answer - timedelta(seconds=1)
    decisions = (f"data/replay_sessions/{session_id}/memory_retrieval/"
                 "candidate_decisions.jsonl")

    tampered_snapshot = copy.deepcopy(snapshot)
    tampered_snapshot["timeframes"]["1m"]["last_candle"]["timestamp"] = late_bar
    tampered_input = copy.deepcopy(brain_input)
    tampered_input["market"]["execution_price"]["captured_at"] = late_quote

    tests = [
        {"id": "P1", "rule": RULE_T_MARKET,
         "what": f"a scan asks for a candle stamped {late_bar}, one minute after its "
                 f"snapshot time {c.t_market.isoformat()}",
         "attempt": lambda: clock().request_market_data(late_bar, "planted candle"),
         "control": lambda: clock().request_market_data(c.t_market.isoformat(), "control")},
        {"id": "P2", "rule": RULE_T_QUOTE,
         "what": f"a scan asks for a quote captured {late_quote}, one second after its "
                 f"recorded quote {c.t_quote.isoformat()}",
         "attempt": lambda: clock().request_quote(late_quote, "planted quote"),
         "control": lambda: clock().request_quote(c.t_quote.isoformat(), "control")},
        {"id": "P3", "rule": RULE_T_ANSWER,
         "what": f"the decision step is invoked at {early.isoformat()}, one second before "
                 f"the model answer existed at {c.t_answer.isoformat()}",
         "attempt": lambda: clock().release_answer(early, "planted early use"),
         "control": lambda: clock().release_answer(c.t_answer, "control")},
        {"id": "P4", "rule": RULE_T_OUTCOME,
         "what": "the decision pass asks for a recorded decision row",
         "attempt": lambda: evidence.read(session_id, decisions),
         "control": lambda: evidence.read(session_id, rel)},
        {"id": "P5", "rule": RULE_NETWORK,
         "what": "the process tries to open a network connection",
         "attempt": lambda: socket.create_connection(("192.0.2.1", 443), timeout=1),
         "control": lambda: None},
    ]
    results = []
    for t in tests:
        attempt, control = _attempt(t["attempt"]), _attempt(t["control"])
        results.append({"id": t["id"], "intended_rule": t["rule"], "request": t["what"],
                        "refused": attempt["refused"], "rule_fired": attempt["rule_fired"],
                        "refusal_message": attempt["message"],
                        "control_allowed": not control["refused"],
                        "pass": attempt["rule_fired"] == t["rule"] and not control["refused"]})

    # The same two tampered stamps, found by the per-scan audit that every
    # replayed scan goes through, rather than by calling a gate directly.
    clean = clock().audit(snapshot, brain_input)
    found_bar = clock().audit(tampered_snapshot, brain_input)
    found_quote = clock().audit(snapshot, tampered_input)
    audit = {"clean_record_findings": len(clean),
             "tampered_candle_detected": any(f["rule"] == RULE_T_MARKET for f in found_bar),
             "tampered_quote_detected": any(f["rule"] == RULE_T_QUOTE for f in found_quote)}
    audit["pass"] = (audit["clean_record_findings"] == 0 and audit["tampered_candle_detected"]
                     and audit["tampered_quote_detected"])
    return {"record_used": rel, "session_id": session_id, "tests": results,
            "audit_of_tampered_record": audit,
            "all_pass": all(r["pass"] for r in results) and audit["pass"]}


def comparison_controls(frozen, evidence, labelled_rows: list, session_id: str) -> dict:
    """Prove the comparison can fail.

    A replay that always reports MATCH proves nothing. Here the recorded model
    answer of a real scan is altered, the scan is replayed, and the comparison
    against the untouched recorded row must report DEFECT. Run in the
    comparison pass; the altered records are never written anywhere.
    """
    import layer_a

    target = None
    created = {i["row"].get("scan_id") for i in labelled_rows
               if i["kind"] == layer_a.ROW_BRAIN
               and i["row"].get("final_disposition") == "CANDIDATE_CREATED"}
    for rel in evidence.brain_files(session_id):
        rec = evidence.read_json(session_id, rel)
        if (rec.get("raw_snapshot") or {}).get("memory_retrieval_telemetry_id") in created \
                and classify_record(rec) == CLASS_ANSWER:
            target = (rel, rec)
            break
    rel, rec = target
    results = []

    def run(label, mutate, expect):
        altered = copy.deepcopy(rec)
        mutate(altered)
        outcome = layer_a.compare([layer_a.replay_record(frozen, session_id, rel, altered)],
                                  labelled_rows)[0]
        results.append({"control": label, "expected_bin": expect, "bin": outcome.get("bin"),
                        "recorded": outcome.get("recorded_disposition"),
                        "replayed": outcome.get("replayed_disposition"),
                        "replayed_reason": outcome.get("replayed_reason"),
                        "fields_differing": len(outcome.get("differences") or []),
                        "pass": outcome.get("bin") == expect})

    run("unaltered record", lambda r: None, layer_a.MATCH)
    run("model answer changed from an entry proposal to stand_down",
        lambda r: r["parsed_output"].__setitem__("current_action", "stand_down"),
        layer_a.DEFECT)
    run("model answer names an invalidation that is not in the catalog",
        lambda r: r["parsed_output"].__setitem__("invalidation_id", "INV_DOES_NOT_EXIST"),
        layer_a.DEFECT)
    run("model answer names an objective that is not in the catalog",
        lambda r: r["parsed_output"].__setitem__("objective_id", "OBJ_DOES_NOT_EXIST"),
        layer_a.DEFECT)
    return {"record_used": rel, "session_id": session_id, "controls": results,
            "all_pass": all(r["pass"] for r in results)}

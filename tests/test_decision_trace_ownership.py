"""PHASE 3 -- the candidate decision record carries THIS scan's real producer trace.

`ProductionLoop._scan_once` calls its own `self.producer.produce(...)`. The
decision recorder used to read `getattr(self.cycle, "producer", None)`; the
scan cycle owns no producer, so every record's stage trace was blank, and an
unrelated object placed there would have been journaled as the decision.
The record now takes the trace the loop's own producer left while producing
THIS scan, and says UNKNOWN when no produce() ran for the scan.

Real ProductionLoop over the existing W5 natural tape (disarmed), real
ProductionScanCycle and CandidateProducer; Brain replies are the existing
MOCKED W5 replies. Test-only instrumentation observes produce() calls; it
changes nothing they do. Observability only: outcomes must be identical.
"""
import copy
import json

import pytest

import test_po3_anchor_replacement_revocation as C
import test_po3_full_graph_production_loop as G

KEYS = ("requested_objective_id", "resolved_objective_id", "resolved_invalidation_id",
        "tool_selected", "tool_matched", "geometry_valid", "reward_risk")


class _Decoy:
    last_decision_trace = {"requested_objective_id": "DECOY-OBJECTIVE",
                           "resolved_objective_id": "DECOY-OBJECTIVE",
                           "geometry_valid": True}


def _run(root, monkeypatch, ecu, *, decoy=False, refuse_bound_at=None, break_record=False):
    from broker.luna_candidate_producer import CandidateProducer
    import market_data.campaign_lifecycle as CL
    calls = []
    real = CandidateProducer.produce

    def observed(self, **kw):
        try:
            return real(self, **kw)
        finally:
            calls.append({"snapshot_id": kw.get("snapshot_id"),
                          "trace": {k: copy.deepcopy(self.last_decision_trace.get(k))
                                    for k in KEYS}})
    monkeypatch.setattr(CandidateProducer, "produce", observed)
    if decoy:
        from live_scan.production_scan_cycle import ProductionScanCycle
        monkeypatch.setattr(ProductionScanCycle, "producer", _Decoy(), raising=False)
    if refuse_bound_at is not None:
        # DEFENSE-ONLY: one scan refused at the loop's binding gate BEFORE any
        # produce(), immediately after a scan that did produce.
        bound = CL.participation_authority_bound

        def gate(lifecycle, draw, *, snapshot, **kw):
            if str((snapshot or {}).get("timestamp", ""))[11:16] == refuse_bound_at:
                return False, "defense_only_injected_refusal"
            return bound(lifecycle, draw, snapshot=snapshot, **kw)
        monkeypatch.setattr(CL, "participation_authority_bound", gate)
    if break_record:
        import broker.candidate_decision_record as R

        def boom(**kw):
            raise OSError("decision journal unavailable")
        monkeypatch.setattr(R, "build_record", boom)
    out, loop, *_ = G._loop(root, monkeypatch, C._HEALTHY, ecu=ecu, arm_at=None)
    files = list((root / "replay").rglob("candidate_decisions.jsonl"))
    records = [json.loads(line) for f in files for line in f.read_text().splitlines()
               if line.strip()]
    return out, records, calls


def _outcomes(out):
    return {hm: (o.get("outcome"), o.get("reason")) for hm, o in out.items()}


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_records_carry_this_scans_real_producer_trace(tmp_path, monkeypatch, ecu):
    out, records, calls = _run(tmp_path / "plain", monkeypatch, ecu)
    produced = {c["snapshot_id"]: c["trace"] for c in calls}
    created = [r for r in records if r["final_disposition"] == "CANDIDATE_CREATED"]
    assert len(created) >= 2
    for record in records:
        trace = produced.get(record["scan_id"])
        assert trace is not None
        assert record["decision_trace_source"] == "loop_producer_current_scan"
        assert {k: record[k] for k in KEYS} == trace, record["scan_id"]
    # Healthy twin of the parent defect: a created candidate's objective and
    # invalidation are on its record, not blank.
    assert all(r["resolved_objective_id"] and r["resolved_invalidation_id"] for r in created)


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_a_decoy_cycle_producer_never_supplies_the_trace(tmp_path, monkeypatch, ecu):
    plain_out, plain, _ = _run(tmp_path / "plain", monkeypatch, ecu)
    monkeypatch.undo()
    decoy_out, decoyed, _ = _run(tmp_path / "decoy", monkeypatch, ecu, decoy=True)
    assert _outcomes(decoy_out) == _outcomes(plain_out)
    assert [{k: r[k] for k in KEYS} for r in decoyed] == [{k: r[k] for k in KEYS} for r in plain]
    assert all(r["requested_objective_id"] != "DECOY-OBJECTIVE" for r in decoyed)


def test_a_scan_without_produce_records_unknown_not_the_previous_trace(tmp_path,
                                                                       monkeypatch):
    # Bar 14:38 produced a candidate (scan id 14:39 by the scan clock); the
    # very next bar, 14:39 (scan id 14:40), is refused before produce().
    out, records, calls = _run(tmp_path / "gap", monkeypatch, False, refuse_bound_at="14:39")
    refused = next(r for r in records if r["scan_id"].endswith("144000"))
    assert refused["final_rejection_reason"] == "campaign_lifecycle_refused"
    assert refused["decision_trace_source"] == "UNKNOWN:no_producer_call_this_scan"
    assert all(refused[k] is None for k in KEYS)
    # The preceding scan did produce, so a stale trace existed to be misreported.
    previous = next(r for r in records if r["scan_id"].endswith("143900"))
    assert previous["decision_trace_source"] == "loop_producer_current_scan"
    assert previous["resolved_objective_id"]


def test_a_failing_decision_journal_cannot_change_any_outcome(tmp_path, monkeypatch):
    plain_out, _plain, _ = _run(tmp_path / "plain", monkeypatch, False)
    monkeypatch.undo()
    broken_out, broken, _ = _run(tmp_path / "broken", monkeypatch, False, break_record=True)
    assert broken == []
    assert _outcomes(broken_out) == _outcomes(plain_out)

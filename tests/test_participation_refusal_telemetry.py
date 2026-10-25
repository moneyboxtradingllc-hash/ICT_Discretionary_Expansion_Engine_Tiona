"""PARTICIPATION-REFUSAL-TELEMETRY (2026-10-25): exact mechanical refusals in the journal.

Parent defect (7b5218a): `ProductionLoop._record_decision` received a scan whose
`snapshot.campaign_lifecycle` named the exact refusing state and reason, but the
journal kept only the generic detail text and mapped `campaign_lifecycle_refused`
to UNCLASSIFIED, so real refusal rows failed `reconcile()`.

Final contract, proven here through the actual loop / producer / recorder /
reconciler in BOTH ECU modes, with CONTROLLED Brain replies only:

  * every mechanical refusal is PARTICIPATION_REFUSED (never STOOD_DOWN,
    never a candidate) and carries the same-scan assessment's exact state and
    reason, its real gate, identity, Draw, acceptance, scope and intent;
  * it reconciles only with that complete, consistent evidence; unknown
    reasons, legacy rows, malformed identity and contradictions never go green;
  * no previous-scan, decoy, foreign or superseded cause leaks into a record;
  * telemetry is observational: failures change no outcome and no
    participation module reads it.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_campaign_scope_binding as B
import test_decision_trace_ownership as TO
import test_po3_anchor_replacement_revocation as C
import test_po3_full_graph_production_loop as G
import test_protected_structure_continuity as PS
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
import ai_brain.ecu as ECUMOD
import broker.candidate_decision_record as R
from broker.luna_candidate_producer import CandidateProducer, NoCandidate
from broker.topstepx_production_loop import ProductionLoop

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
ECU = pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])


def _journal(root):
    return [json.loads(line) for f in Path(root).rglob("candidate_decisions.jsonl")
            for line in f.read_text().splitlines() if line.strip()]


def _observe_recorder(monkeypatch):
    seen = {}
    original = ProductionLoop._record_decision

    def observe(self, scan, *args, **kwargs):
        seen[scan.get("snapshot_id")] = copy.deepcopy((scan.get("snapshot") or {}).get("campaign_lifecycle"))
        return original(self, scan, *args, **kwargs)
    monkeypatch.setattr(ProductionLoop, "_record_decision", observe)
    return seen


def _assert_matches_assessment(record, assessment):
    block = record["participation_refusal"]
    assert record["schema_version"] == R.SCHEMA_VERSION_V2
    assert record["final_disposition"] == R.PARTICIPATION_REFUSED
    assert block["lifecycle_status"] == "AVAILABLE"
    for key in ("state", "reason"):
        assert block[f"lifecycle_{key}"] == assessment[key], (record["scan_id"], key)
    for key in ("participation_permitted", "authorized_direction", "narrative_control_state",
                "narrative_phase", "campaign_episode_id", "objective_identity"):
        assert block[key] == assessment[key], key
    assert block["identity"]["scan_id"] == record["scan_id"] and block["identity"]["contract"] == record["contract"]
    assert block["consistency_problems"] == []
    assert R.refusal_problems(record) == []


# -- 1. the actual production loop: healthy candidate unchanged, refusals exact --------

@ECU
def test_actual_loop_refusals_persist_the_same_scan_cause_and_reconcile(tmp_path, monkeypatch, ecu):
    seen = _observe_recorder(monkeypatch)
    out, loop, venue, mission, chosen, payloads = G._loop(tmp_path / "healthy", monkeypatch, C._HEALTHY,
                                                          ecu=ecu, arm_at=None)
    assert out["15:06"]["outcome"] == G.PL.QUALIFIED_CANDIDATE_OBSERVED
    assert out["15:06"]["execution"] == G.PL.EXECUTION_DISARMED
    assert not loop.armed and venue.place_calls == 0 and payloads == []
    assert mission.token_count == mission.entry_attempt_count == 0
    records = _journal(tmp_path / "healthy")
    refused = [r for r in records if r["final_rejection_reason"] == "campaign_lifecycle_refused"]
    assert refused
    for record in refused:
        _assert_matches_assessment(record, seen[record["scan_id"]])
        assert record["participation_refusal"]["gate"] == R.PRODUCER_LIFECYCLE_GATE
        assert record["producer_execution"]["executed_this_scan"] is True
        assert record["participation_refusal"]["downstream"]["stages_after_gate"] == "NOT_REACHED"
    reasons = {r["participation_refusal"]["lifecycle_reason"] for r in refused}
    # Real unknown Draw, retired-by-current-acceptance and delivered destination.
    assert "campaign_draw_authority_unknown" in reasons
    assert any("retired_by_current_acceptance" in x for x in reasons)
    assert "settled_campaign_objective_touch_proven" in reasons
    assert R.reconcile(refused)["status"] == "RECONCILED"
    # A deliberately unmapped producer refusal is untouched by this repair.
    tools = [r for r in records if r["final_rejection_reason"] == "tool_not_detected"]
    assert tools and all(r["final_disposition"] == R.UNCLASSIFIED for r in tools)
    assert all(r["participation_refusal"] is None for r in tools)
    created = [r for r in records if r["final_disposition"] == R.CANDIDATE_CREATED]
    assert created and all(r["participation_refusal"] is None for r in created)
    assert all(r["campaign_lifecycle_assessment"]["status"] == "AVAILABLE" for r in created)


@ECU
def test_retired_formation_refusal_is_unchanged(tmp_path, monkeypatch, ecu):
    bad, loop, venue, mission, chosen, payloads = G._loop(tmp_path / "retired", monkeypatch, C._REPLACED,
                                                          ecu=ecu, arm_at=None)
    assert chosen[max(chosen)] == G.FORMATION_ID
    assert bad["15:06"]["outcome"] == G.PL.NO_CANDIDATE and bad["15:06"]["reason"] == "tool_not_detected"
    assert venue.place_calls == 0 and mission.token_count == 0
    last = [r for r in _journal(tmp_path / "retired") if r["final_rejection_reason"] == "tool_not_detected"][-1]
    assert last["final_disposition"] == R.UNCLASSIFIED and last["participation_refusal"] is None


@ECU
def test_loop_binding_refusal_is_attributed_to_the_binding_with_no_stale_producer_trace(tmp_path, monkeypatch,
                                                                                         ecu):
    out, records, calls = TO._run(tmp_path / "gap", monkeypatch, ecu, refuse_bound_at="14:39")
    refused = next(r for r in records if r["scan_id"].endswith("144000"))
    block = refused["participation_refusal"]
    assert block["gate"] == R.LOOP_PARTICIPATION_BINDING
    assert block["observed_gate_reason"] == "defense_only_injected_refusal"
    assert block["downstream"]["producer"] == "NOT_REACHED"
    assert refused["producer_execution"] == {"executed_this_scan": False, "trace_lifecycle_state": None,
                                             "trace_lifecycle_refusal": None,
                                             "note": "a scan-level assessment never implies the producer ran"}
    assert block["participation_permitted"] is True and block["lifecycle_state"] == "ACTIVE_DELIVERY"
    assert refused["decision_trace_source"] == "UNKNOWN:no_producer_call_this_scan"
    previous = next(r for r in records if r["scan_id"].endswith("143900"))
    assert previous["final_disposition"] == R.CANDIDATE_CREATED   # a stale trace existed to leak
    assert R.refusal_problems(refused) == []


@ECU
def test_a_decoy_cycle_producer_never_supplies_a_refusal_cause(tmp_path, monkeypatch, ecu):
    plain_out, plain, _ = TO._run(tmp_path / "plain", monkeypatch, ecu)
    monkeypatch.undo()
    decoy_out, decoyed, _ = TO._run(tmp_path / "decoy", monkeypatch, ecu, decoy=True)
    assert TO._outcomes(decoy_out) == TO._outcomes(plain_out)
    def causes(rows):
        # Semantic cause fields only: episode/record/proposal ids are per-run.
        out = []
        for r in rows:
            block = r["participation_refusal"] or {}
            out.append((r["scan_id"], r["final_disposition"], block.get("gate"), block.get("observed_gate_reason"),
                        block.get("lifecycle_state"), block.get("lifecycle_reason"),
                        json.dumps(r["producer_execution"], sort_keys=True),
                        r["campaign_lifecycle_assessment"].get("state")))
        return out
    assert causes(decoyed) == causes(plain)
    assert "DECOY" not in json.dumps(decoyed)


# -- 2. scan-level states through the real recorder: ESTABLISHING, TRANSFER, newborn ----

def _record(cycle, scan, *, producer=None, mark=True, refusal=None, record_root=None):
    """The actual `ProductionLoop._record_decision` on a real scan and a real refusal."""
    producer = producer or CandidateProducer(account_fingerprint="acct:telemetry", contract=RF.MNQ)
    host = SimpleNamespace(cycle=cycle, producer=producer, _decision_trace_owner=("previous", "previous"),
                           active_conditional_plan=None, _decision_refusal=None)
    candidate = None
    if refusal is None:
        if mark:
            host._decision_trace_owner = (scan.get("scan_count"), scan.get("snapshot_id"))
        try:
            candidate = B._candidate(scan, cycle, producer=producer)
        except NoCandidate as exc:
            refusal = exc
    if refusal is not None:   # exactly as the loop's NoCandidate handlers hand it over
        host._decision_refusal = (scan.get("scan_count"), scan.get("snapshot_id"), refusal)
    ProductionLoop._record_decision(host, scan, "CANDIDATE" if candidate else "REJECTED",
                                    None if candidate else refusal.reason, "" if candidate else str(refusal))
    return candidate, refusal


@ECU
def test_friday_establishing_refusals_carry_the_exact_assessment(tmp_path, monkeypatch, ecu):
    for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key))
    monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    monkeypatch.setattr(ECUMOD, "_STANCE", None)
    cycle = PS._friday_cycle("TELEMETRY-FRIDAY")
    for hhmm in PS._minutes("12:55", "13:15"):
        PS._scan(cycle, hhmm, False)
    RF._mock_current_brain(monkeypatch, [], output_mutator=PS._controlled)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    scans = [PS._scan(cycle, hhmm, True) for hhmm in ("13:16", "13:17", "13:18")]
    for scan in scans:
        assert scan["snapshot"]["campaign_lifecycle"]["state"] == "ESTABLISHING"
        _record(cycle, scan)
    records = _journal(tmp_path / "REPLAY_SESSIONS_DIR")
    assert len(records) == 3
    for record, scan in zip(records, scans):
        _assert_matches_assessment(record, scan["snapshot"]["campaign_lifecycle"])
        assert record["participation_refusal"]["lifecycle_reason"] == "active_path_causal_hypothesis_only"
        assert record["participation_refusal"]["intent"]["authored"]["action"] == "stand_down"
    assert R.reconcile(records)["status"] == "RECONCILED"


@ECU
def test_c2_unresolved_transfer_refusals_carry_the_exact_assessment(tmp_path, monkeypatch, ecu):
    for key in ("AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key))
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows, scans = list(TA.LATER), []
    for bar in L.SCENARIOS["C2"]:
        rows.append(bar)
        scan, _ = H._brain_scan(cycle, calls, rows)
        if bar["timestamp"][11:16] >= "03:07":
            _record(cycle, scan)
            scans.append(scan)
    records = [r for r in _journal(tmp_path) if r["final_rejection_reason"] == "campaign_lifecycle_refused"]
    assert len(records) == len(scans) and scans
    for record, scan in zip(records, scans):
        _assert_matches_assessment(record, scan["snapshot"]["campaign_lifecycle"])
        assert record["participation_refusal"]["lifecycle_state"] == "TRANSFER_UNRESOLVED"
        assert record["participation_refusal"]["lifecycle_reason"] == "narrative_control_transfer_not_yet_confirmed"
        assert record["participation_refusal"]["narrative_control_state"] == "developing_transfer"
    assert R.reconcile(records)["status"] == "RECONCILED"


@ECU
def test_w5_newborn_draw_refusal_then_candidate_and_a_real_binding_mismatch(tmp_path, monkeypatch, ecu):
    from market_data.campaign_draw_truth import scan_participation_authority
    from market_data.campaign_lifecycle import participation_authority_bound
    cycle, scan, calls = B._w5_producer(tmp_path, monkeypatch, ecu)
    t2, t3 = scan(97), scan(98)
    producer = CandidateProducer(account_fingerprint="acct:telemetry", contract=RF.MNQ)
    _record(cycle, t2, producer=producer)
    _, refusal = _record(cycle, t3, producer=producer)
    assert refusal is not None and refusal.reason == "campaign_lifecycle_refused"
    t4 = scan(99)
    candidate, _ = _record(cycle, t4, producer=producer)
    assert candidate is not None and candidate.direction == "bearish"
    # The loop's own binding function, asked for a foreign session: a real refusal
    # raised exactly as the loop raises it, on a scan where the producer never ran.
    bound, why = participation_authority_bound(
        t4["snapshot"]["campaign_lifecycle"], scan_participation_authority(t4), snapshot=t4["snapshot"],
        session_id="FOREIGN-SESSION", contract_id=str(cycle.contract_id))
    assert bound is False and why
    _record(cycle, t4, producer=producer, refusal=NoCandidate("campaign_lifecycle_refused", why))
    records = _journal(tmp_path)
    t3_record = next(r for r in records if r["scan_id"] == t3["snapshot_id"])
    _assert_matches_assessment(t3_record, t3["snapshot"]["campaign_lifecycle"])
    created = next(r for r in records if r["final_disposition"] == R.CANDIDATE_CREATED)
    assert created["participation_refusal"] is None
    binding = [r for r in records if r["scan_id"] == t4["snapshot_id"]][-1]
    block = binding["participation_refusal"]
    assert block["gate"] == R.LOOP_PARTICIPATION_BINDING and block["observed_gate_reason"] == why
    assert block["lifecycle_state"] == "ACTIVE_DELIVERY" and block["participation_permitted"] is True
    assert binding["producer_execution"]["executed_this_scan"] is False
    assert binding["producer_execution"]["trace_lifecycle_state"] is None   # T4's real trace never leaks
    assert block["draw"]["status"] == "AVAILABLE"
    assert R.reconcile([r for r in records if r["final_disposition"] == R.PARTICIPATION_REFUSED])["status"] \
        == "RECONCILED"


# -- 3. custody: foreign, superseded, missing evidence stays typed UNKNOWN ---------------

def _scan_fixture(**over):
    lifecycle = {"schema_version": 1, "state": "TRANSFER_UNRESOLVED",
                 "reason": "narrative_control_transfer_not_yet_confirmed", "participation_permitted": False,
                 "authorized_direction": None, "campaign_episode_id": None, "objective_identity": None,
                 "campaign_draw_status": "UNKNOWN", "campaign_draw_binding": None,
                 "narrative_control_state": "developing_transfer", "narrative_phase": "transition"}
    scan = {"snapshot_id": "scan-1", "scan_count": 7,
            "snapshot": {"timestamp": "2026-08-19T03:10:00+00:00", "contract_id": "CON.F.US.MNQ.Z26",
                         "campaign_lifecycle": lifecycle},
            "campaign_lifecycle": copy.deepcopy(lifecycle), "campaign_draw_acceptance": None}
    scan.update(over)
    return scan


def _producer_refusal(detail="campaign_lifecycle_refused:TRANSFER_UNRESOLVED"):
    exc = NoCandidate("campaign_lifecycle_refused", detail)
    exc.decision_trace = {"campaign_lifecycle_state": "TRANSFER_UNRESOLVED", "campaign_lifecycle_refusal": detail}
    return exc


def _evidence(scan, refusal, *, current=True, contract="CON.F.US.MNQ.Z26"):
    trace = getattr(refusal, "decision_trace", None)
    record = R.build_record(session_id="S", scan_id=scan.get("snapshot_id"), timestamp_et="t", instrument="MNQ",
                            contract=contract, parsed={"current_action": "stand_down"}, trace={},
                            disposition=R.terminal_disposition("campaign_lifecycle_refused"),
                            rejection_reason="campaign_lifecycle_refused", detail=str(refusal))
    return R.attach_participation_evidence(record, scan=scan, reason="campaign_lifecycle_refused",
                                           refusal=refusal, producer_current=current, producer_trace=trace,
                                           session_id="S", contract_id=contract)


def test_foreign_contract_assessment_is_unknown_and_never_accounted():
    record = _evidence(_scan_fixture(snapshot={**_scan_fixture()["snapshot"], "contract_id": "CON.F.US.ES.Z26"}),
                       _producer_refusal())
    assert record["campaign_lifecycle_assessment"]["unknown_reason"] == "foreign_contract_snapshot"
    assert record["participation_refusal"]["lifecycle_state"] is None
    assert "lifecycle_assessment_unknown" in R.refusal_problems(record)


def test_producer_refusal_without_this_scans_marker_is_not_attributed():
    record = _evidence(_scan_fixture(), _producer_refusal(), current=False)
    block = record["participation_refusal"]
    assert block["gate"] is None and "producer_refusal_without_current_scan_marker" in block["consistency_problems"]
    assert record["producer_execution"]["trace_lifecycle_state"] is None
    assert R.refusal_problems(record)


def test_superseded_scan_level_copy_is_flagged_and_the_consumed_snapshot_is_recorded():
    scan = _scan_fixture()
    scan["campaign_lifecycle"]["reason"] = "stale_pre_trigger_reason"
    record = _evidence(scan, _producer_refusal())
    assert record["campaign_lifecycle_assessment"]["scan_level_copy_differs"] is True
    assert record["participation_refusal"]["lifecycle_reason"] == "narrative_control_transfer_not_yet_confirmed"


def test_missing_acceptance_scope_draw_and_intent_stay_typed_absent_or_unknown():
    block = _evidence(_scan_fixture(), _producer_refusal())["participation_refusal"]
    assert block["current_acceptance"] == {"status": "ABSENT", "reason": "no_acceptance_published_this_scan",
                                           "source": "scan.campaign_draw_acceptance"}
    assert block["scope_proposal"]["status"] == "ABSENT"
    assert block["draw"]["status"] == "UNKNOWN"
    assert block["intent"]["authored"]["status"] == "UNKNOWN"
    assert R.refusal_problems(_evidence(_scan_fixture(), _producer_refusal())) == []


def test_a_contradicting_producer_trace_or_state_label_is_never_green():
    refusal = _producer_refusal("campaign_lifecycle_refused:ESTABLISHING")
    record = _evidence(_scan_fixture(), refusal)
    assert "gate_state_label_disagrees_with_assessment" in record["participation_refusal"]["consistency_problems"]
    assert R.reconcile([record])["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"


# -- 4. readers: legacy, mixed, unknown, malformed, contradictory -----------------------

def _v1(reason, disposition=None, scan_id="old"):
    return R.build_record(session_id="S", scan_id=scan_id, timestamp_et="t", instrument="MNQ", contract="C",
                          parsed={}, trace={}, disposition=disposition or R.UNCLASSIFIED, rejection_reason=reason,
                          detail=f"{reason}: x")


def test_mixed_legacy_and_v2_journal_keeps_each_schemas_status():
    valid = _evidence(_scan_fixture(), _producer_refusal())
    legacy = _v1("campaign_lifecycle_refused")                   # as the parent wrote it
    assert legacy["schema_version"] == R.SCHEMA_VERSION and legacy["final_disposition"] == R.UNCLASSIFIED
    out = R.reconcile([valid, legacy])
    assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE" and out["unclassified"] == 1
    assert out["schema_versions"] == {R.SCHEMA_VERSION: 1, R.SCHEMA_VERSION_V2: 1}
    assert R.reconcile([valid])["status"] == "RECONCILED"
    # A derived COPY reclassified by today's classifier is still not complete evidence.
    AUDIT = _tool("topstepx_reclassify_decision_audit")
    copy_row = AUDIT.reclassify([legacy])[0]
    assert copy_row["final_disposition"] == R.PARTICIPATION_REFUSED
    assert copy_row["original_final_disposition"] == R.UNCLASSIFIED
    out = R.reconcile([copy_row])
    assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE" and out["participation_refusal_incomplete"] == 1
    assert out["problems"][0]["problems"] == ["legacy_record_lacks_participation_refusal_evidence"]


def test_legacy_v1_semantics_are_unchanged_for_other_reasons():
    rows = [_v1("action_declines_entry", R.STOOD_DOWN, f"s{i}") for i in range(3)]
    assert R.reconcile(rows)["status"] == "RECONCILED"
    assert R.reconcile(rows + [_v1("tool_not_detected")])["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: r["participation_refusal"]["identity"].update(scan_id=None), "identity_scan_id_missing"),
    (lambda r: r["participation_refusal"]["identity"].update(contract=""), "identity_contract_missing"),
    (lambda r: r["participation_refusal"].update(gate="SOMEWHERE"), "gate_unknown"),
    (lambda r: r["participation_refusal"].update(observed_gate_reason=None), "observed_gate_reason_missing"),
    (lambda r: r["participation_refusal"].update(lifecycle_reason=""), "lifecycle_reason_missing"),
    (lambda r: r["participation_refusal"].update(lifecycle_state="MADE_UP"), "lifecycle_state_unrecognized"),
    (lambda r: r.update(participation_refusal=None), "participation_refusal_evidence_missing_or_malformed"),
    (lambda r: r.update(final_rejection_reason="tool_not_detected"), "refusal_code_not_a_known_mechanical_refusal"),
])
def test_malformed_refusal_evidence_never_reconciles(mutate, problem):
    record = _evidence(_scan_fixture(), _producer_refusal())
    mutate(record)
    assert problem in R.refusal_problems(record)
    assert R.reconcile([record])["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"


@pytest.mark.parametrize("disposition", [R.STOOD_DOWN, R.CANDIDATE_CREATED, R.QUALIFICATION_REJECTED])
def test_contradictory_v2_disposition_never_reconciles(disposition):
    record = _evidence(_scan_fixture(), _producer_refusal())
    record["final_disposition"] = disposition
    out = R.reconcile([record])
    assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE" and out["contradictory"] == 1


def test_unknown_reasons_are_not_blanket_mapped():
    assert R.terminal_disposition("campaign_lifecycle_refused") == R.PARTICIPATION_REFUSED
    for reason in ("tool_not_detected", "derived_state_stale", "campaign_lifecycle_unknown_new_code", "", None):
        assert R.terminal_disposition(reason) == R.UNCLASSIFIED
    assert R.PARTICIPATION_REFUSED != R.STOOD_DOWN and R.PARTICIPATION_REFUSED in R.TERMINAL_DISPOSITIONS


def test_session_report_reads_a_mixed_journal_and_the_audit_never_touches_it(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_SESSIONS_DIR", str(tmp_path))
    from ai_retrieval.retrieval_telemetry import session_root
    root = Path(session_root("MIXED"))
    root.mkdir(parents=True, exist_ok=True)
    rows = [_evidence(_scan_fixture(), _producer_refusal()), _v1("campaign_lifecycle_refused")]
    journal = root / "candidate_decisions.jsonl"
    journal.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    before = journal.read_bytes()
    REPORT = _tool("topstepx_session_outcome_report")
    out = REPORT.decisions("MIXED")
    assert out["count"] == 2 and out["reconciliation"]["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"
    assert out["reconciliation"]["dispositions"] == {R.PARTICIPATION_REFUSED: 1, R.UNCLASSIFIED: 1}
    assert journal.read_bytes() == before


# -- 5. isolation: bounded, observational, never authority ------------------------------

def test_evidence_is_bounded_json_safe_and_free_of_account_fields():
    scan = _scan_fixture(campaign_draw_acceptance={"accepted": False, "reason": "x" * 5000,
                                                   "nested": {"deep": {"deeper": {"deepest": 1}}}})
    record = _evidence(scan, _producer_refusal())
    text = json.dumps(record)
    assert len(record["participation_refusal"]["current_acceptance"]["reason"]) == 200
    assert "account" not in text.lower() and len(text) < 20000


def test_a_capture_error_is_typed_and_never_raises(monkeypatch):
    monkeypatch.setattr(R, "_lifecycle_assessment", lambda *a, **k: 1 / 0)
    record = _evidence(_scan_fixture(), _producer_refusal())
    assert record["participation_refusal"]["unknown_reason"] == "capture_error:ZeroDivisionError"
    assert R.reconcile([record])["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"


@ECU
def test_failing_evidence_or_journal_cannot_change_any_outcome(tmp_path, monkeypatch, ecu):
    plain_out, plain, _ = TO._run(tmp_path / "plain", monkeypatch, ecu)
    monkeypatch.undo()

    def boom(*a, **k):
        raise RuntimeError("telemetry exploded")
    monkeypatch.setattr(R, "participation_evidence", boom)
    broken_out, broken, _ = TO._run(tmp_path / "broken", monkeypatch, ecu)
    assert TO._outcomes(broken_out) == TO._outcomes(plain_out)
    assert len(broken) == len(plain)   # the record is still written, without v2 evidence
    assert all(r["schema_version"] == R.SCHEMA_VERSION for r in broken)
    monkeypatch.undo()
    jammed_out, jammed, _ = TO._run(tmp_path / "jammed", monkeypatch, ecu, break_record=True)
    assert jammed == [] and TO._outcomes(jammed_out) == TO._outcomes(plain_out)


def test_no_participation_module_reads_the_telemetry():
    for path in ("src/broker/luna_candidate_producer.py", "src/market_data/campaign_lifecycle.py",
                 "src/market_data/campaign_draw_truth.py", "src/market_data/campaign_scope.py",
                 "src/broker/conditional_plan_authority.py", "src/live_scan/production_scan_cycle.py",
                 "src/ai_brain/narrative_continuity.py", "src/ai_brain/narrative_brain.py"):
        text = (ROOT / path).read_text()
        # The producer's PRE-EXISTING trace template import is the one allowed use.
        text = text.replace("from broker.candidate_decision_record import blank_trace", "")
        # Names introduced by this telemetry (the producer's own trace already
        # uses `campaign_lifecycle_assessment` for triggers, at the parent).
        for name in ("participation_refusal", "candidate_decision_record", "PARTICIPATION_REFUSED",
                     "producer_execution", "refusal_problems", "attach_participation_evidence"):
            assert name not in text, (path, name)
    loop = (ROOT / "src/broker/topstepx_production_loop.py").read_text()
    assert loop.count("candidate_decision_record") == 3   # all inside _record_decision
    assert "participation_refusal" not in loop and "refusal_problems" not in loop


def test_a_refusal_handed_over_for_another_scan_is_never_read_and_is_consumed(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_SESSIONS_DIR", str(tmp_path))
    cycle = SimpleNamespace(retrieval_telemetry=SimpleNamespace(session_id="HANDOFF"), contract_id="CON.F.US.MNQ.Z26",
                            session_id="HANDOFF")
    scan = _scan_fixture()
    host = SimpleNamespace(cycle=cycle, producer=None, _decision_trace_owner=None, active_conditional_plan=None,
                           _decision_refusal=("other-scan-count", "other-scan", _producer_refusal()))
    ProductionLoop._record_decision(host, scan, "REJECTED", "campaign_lifecycle_refused", "x")
    assert host._decision_refusal is None
    record = _journal(tmp_path)[-1]
    assert record["participation_refusal"]["gate"] is None
    assert "refusal_object_unavailable" in record["participation_refusal"]["consistency_problems"]
    assert R.reconcile([record])["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"
    # The same refusal handed over for THIS scan is read once, then consumed.
    host._decision_refusal = (scan["scan_count"], scan["snapshot_id"], _producer_refusal())
    host._decision_trace_owner = (scan["scan_count"], scan["snapshot_id"])
    host.producer = SimpleNamespace(last_decision_trace=_producer_refusal().decision_trace)
    ProductionLoop._record_decision(host, scan, "REJECTED", "campaign_lifecycle_refused", "x")
    assert host._decision_refusal is None
    record = _journal(tmp_path)[-1]
    assert record["participation_refusal"]["gate"] == R.PRODUCER_LIFECYCLE_GATE
    assert R.refusal_problems(record) == []

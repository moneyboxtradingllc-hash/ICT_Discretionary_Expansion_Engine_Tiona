"""STAGE 3B-1A — COGNITIVE HISTORY HYGIENE / PER-CYCLE ECU CUSTODY.

Persisted Brain stance is cognition, not market fact. A row may supply the
incumbent prior to the next canonical cognition only when its schema, scope,
chronology and current history lineage are PROVED. Everything else stays
visible as labelled audit context and supplies no prior_thesis, prior falsifier
status, campaign_established or incumbent_failed.

Every assertion reads the EXACT transported model payload (the mocked
transport's deep copy taken at call time) and the real ProductionScanCycle,
ECU and non-ECU. The shared reversal-foundation harness replaces
`ecu._stance` with an in-memory StanceMemory; these tests restore the
PRODUCTION accessor so the custody defect cannot be hidden by the helper.

DEFENSE-ONLY. Rows injected into a live custody or seeded into the persisted
file are adversarial states the normal producer does not write. They are
labelled as such at each use. Runtime roots are isolated per test.
"""
from __future__ import annotations

import copy
import json

import pytest

import ai_brain.ecu as ECU
import test_campaign_draw_temporal_authority as TA
import test_reversal_foundation_proof_closure as RF
from ai_brain.narrative_continuity import (build_narrative_continuity,
                                           recheck_narrative_continuity)
from broker.luna_candidate_producer import CandidateProducer
from market_data.object_identity import canonical_instant

#: The production accessor, captured before any test patches it.
PRODUCTION_ECU_STANCE = ECU._stance

AT_0259 = "2026-08-19T02:59:00+00:00"
AT_0304 = "2026-08-19T03:04:00+00:00"
AT_0309 = "2026-08-19T03:09:00+00:00"
FUTURE = "2026-08-19T03:45:00+00:00"     # same production session (20260818 ET)


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def _lane(tmp_path, monkeypatch, ecu, *, mutator=None):
    cycle, calls = TA._cycle_with_brain(tmp_path, monkeypatch, ecu=ecu,
                                        mutator=mutator)
    monkeypatch.setattr(ECU, "_stance", PRODUCTION_ECU_STANCE)
    ECU._STANCE = None
    return cycle, calls


def _brain_scan(cycle, calls, rows):
    before = len(calls)
    scan = TA._scan(cycle, rows)
    assert len(calls) == before + 1, "exactly one canonical Brain call"
    return scan, calls[-1]


def _rows(cycle):
    return cycle.stance_memory.recent(30)


def _instant(value):
    return canonical_instant(value, strict=True)


def _assert_healthy_bullish_incumbent(payload, scan, recorded_at):
    hist = payload["stance_history"]
    assert hist["available"] is True
    assert hist["last"]["direction"] == "bullish"
    assert _instant(hist["last"]["recorded_at_cutoff"]) == _instant(recorded_at)
    nc = payload["narrative_continuity"]
    assert nc["prior_thesis"]["direction"] == "bullish"
    assert nc["control_state"] == "incumbent_intact"
    assert nc["dominant_direction"] == "bullish"
    assert scan["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    RF._produce_candidate(scan)


# ── 1. Invalid rows in the live custody never become the incumbent ─────────
#
# DEFENSE-ONLY: each case appends one adversarial bearish row to the cycle's
# own custody after two healthy bullish scans.
def _poison(row, case):
    bad = copy.deepcopy(row)
    bad.update(direction="bearish", campaign_direction="bearish",
               campaign_established=True, thesis_falsifier_status="not_occurred",
               control_state="incumbent_intact", phase="continuation")
    if case == "future_dated":
        bad.update(timestamp=FUTURE, recorded_at_cutoff=FUTURE)
    elif case == "wrong_contract":
        bad["contract_id"] = "CON.F.US.MES.Z26"
    elif case == "wrong_market_session":
        bad["market_session"] = "20260101"
    elif case == "superseded_revision":
        bad["superseded_by_history_revision"] = 99
    elif case == "legacy_schema":
        for key in ("stance_schema_version", "contract_id", "market_session",
                    "process_session_id", "recorded_at_cutoff", "history_lineage"):
            bad.pop(key, None)
    elif case == "malformed_chronology":
        bad["recorded_at_cutoff"] = "not-a-settled-instant"
    else:
        raise AssertionError(case)
    return bad


EXPECTED_REASON = {
    "future_dated": "future_dated",
    "wrong_contract": "scope_mismatch",
    "wrong_market_session": "scope_mismatch",
    "superseded_revision": "superseded_history_revision",
    "legacy_schema": "legacy_schema",
    "malformed_chronology": "malformed_scope",
}


@TA.ECU_MODES
@pytest.mark.parametrize("case", list(EXPECTED_REASON))
def test_invalid_custody_row_is_context_never_incumbent(tmp_path, monkeypatch,
                                                         ecu, case):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    _brain_scan(cycle, calls, TA.LATER)
    rows = _rows(cycle)
    assert len(rows) == 2, "the canonical Brain records into the cycle custody"
    # DEFENSE-ONLY injection into the live custody.
    cycle.stance_memory._buf.append(_poison(rows[-1], case))

    scan, payload = _brain_scan(cycle, calls, TA.LATER2)
    _assert_healthy_bullish_incumbent(payload, scan, AT_0304)
    withheld = payload["stance_history"]["withheld_context"]
    assert any(row["authority_withheld_reason"] == EXPECTED_REASON[case]
               and row["direction"] == "bearish" for row in withheld)
    # The garbage stays visible for audit but cannot self-perpetuate.
    newest = _rows(cycle)[-1]
    assert newest["campaign_direction"] == "bullish"
    assert _instant(newest["recorded_at_cutoff"]) == _instant(AT_0309)

    # A retained garbage row does not indefinitely block the healthy chain.
    scan, payload = _brain_scan(cycle, calls, TA.LATER3)
    _assert_healthy_bullish_incumbent(payload, scan, AT_0309)
    assert any(row["authority_withheld_reason"] == EXPECTED_REASON[case]
               for row in payload["stance_history"]["withheld_context"])


# ── 2. Restart with a reused revision number cannot restore cognition ──────
@TA.ECU_MODES
def test_restart_with_reused_revision_number_loads_context_only(
        tmp_path, monkeypatch, ecu):
    first, calls = _lane(tmp_path / "process_a", monkeypatch, ecu)
    _brain_scan(first, calls, RF.TAPE_1M)
    _brain_scan(first, calls, TA.LATER)
    assert first._history.revision == 0
    persisted = json.loads((tmp_path / "brain_runtime" / "stance_memory.json")
                           .read_text())["buf"]
    assert len(persisted) == 2

    # A new process: same session, same contract, revision 0 again.
    second, calls = _lane(tmp_path / "process_b", monkeypatch, ecu)
    assert second._history.revision == 0
    scan, payload = _brain_scan(second, calls, RF.TAPE_1M)
    hist = payload["stance_history"]
    assert hist["available"] is False and hist["last"] is None
    assert payload["narrative_continuity"]["prior_thesis"] is None
    reasons = {row["authority_withheld_reason"] for row in hist["withheld_context"]}
    assert reasons == {"history_lineage_unproved"}
    # Fresh current cognition becomes the next incumbent.
    scan, payload = _brain_scan(second, calls, TA.LATER)
    assert _instant(payload["stance_history"]["last"]["recorded_at_cutoff"]) \
        == _instant(AT_0259)
    assert payload["narrative_continuity"]["prior_thesis"]["direction"] == "bullish"


# DEFENSE-ONLY: a persisted file seeded with adversarial rows before start.
@TA.ECU_MODES
def test_seeded_persisted_rows_supply_no_incumbent(tmp_path, monkeypatch, ecu):
    seeded = [{"timestamp": FUTURE, "direction": "bearish",
               "campaign_direction": "bearish", "campaign_established": True,
               "narrative_state_version": 1, "thesis_falsifier_status": "occurred",
               "phase": "continuation", "action": "propose_entry"},
              {"timestamp": "2026-08-19T02:30:00+00:00", "direction": "bearish",
               "campaign_direction": "bearish", "campaign_established": True,
               "narrative_state_version": 1, "superseded_by_history_revision": 4,
               "contract_id": "CON.F.US.MES.Z26", "phase": "continuation"}]
    runtime = tmp_path / "brain_runtime"
    runtime.mkdir()
    (runtime / "stance_memory.json").write_text(
        json.dumps({"buf": seeded, "thesis_anchor": seeded[0]}))
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    scan, payload = _brain_scan(cycle, calls, RF.TAPE_1M)
    hist = payload["stance_history"]
    assert hist["available"] is False and hist["thesis_anchor"] is None
    assert payload["narrative_continuity"]["prior_thesis"] is None
    assert len(hist["withheld_context"]) == 2
    scan, payload = _brain_scan(cycle, calls, TA.LATER)
    _assert_healthy_bullish_incumbent(payload, scan, AT_0259)
    # STAGE-3B-1B: the seeded rows' "occurred" (a leg status under the old
    # campaign-falsifier name) supplies no leg failure and no campaign status.
    assert payload["narrative_continuity"]["active_leg_failure_status"] != "occurred"
    assert payload["narrative_continuity"]["thesis_falsifier_status"] == "unknown"


# ── 3. A real canonical revision is consumed before cognition ──────────────
def _revised(rows):
    revised = copy.deepcopy(rows)
    revised[0]["close"] += 0.25
    revised[0]["high"] = max(revised[0]["high"], revised[0]["close"])
    revised[0]["low"] = min(revised[0]["low"], revised[0]["close"])
    return revised


@TA.ECU_MODES
def test_real_history_revision_is_consumed_before_cognition(tmp_path, monkeypatch,
                                                            ecu):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    _brain_scan(cycle, calls, TA.LATER)
    scan, payload = _brain_scan(cycle, calls, _revised(TA.LATER))
    assert scan["snapshot"]["derived_state"]["history_revision"] == 1
    hist = payload["stance_history"]
    assert hist["available"] is False
    assert payload["narrative_continuity"]["prior_thesis"] is None
    assert {row["authority_withheld_reason"] for row in hist["withheld_context"]} \
        == {"superseded_history_revision"}
    # The memory the Brain reads is the memory the revision re-anchored.
    rows = _rows(cycle)
    assert len(rows) == 3
    assert [row.get("superseded_by_history_revision") for row in rows] == [1, 1, None]
    scan, payload = _brain_scan(
        cycle, calls, _revised(TA.LATER) + TA.LATER2[len(TA.LATER):])
    assert payload["stance_history"]["last"]["history_lineage"]["history_revision"] == 1
    assert payload["narrative_continuity"]["prior_thesis"]["direction"] == "bullish"


# ── 4. Interleaved cycles keep separate custody and revision effects ───────
@TA.ECU_MODES
def test_interleaved_cycles_keep_separate_custody(tmp_path, monkeypatch, ecu):
    cycle_a = RF._cycle(tmp_path / "a", monkeypatch)
    RF._scan_prefix(cycle_a, len(RF.TAPE_1M) - 5)
    cycle_b = RF._cycle(tmp_path / "b", monkeypatch)
    RF._scan_prefix(cycle_b, len(RF.TAPE_1M) - 5)
    calls = []
    RF._mock_current_brain(monkeypatch, calls)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    monkeypatch.setattr(ECU, "_stance", PRODUCTION_ECU_STANCE)
    ECU._STANCE = None
    assert cycle_a.stance_memory is not cycle_b.stance_memory

    for rows in (RF.TAPE_1M, TA.LATER):
        _brain_scan(cycle_a, calls, rows)
        _brain_scan(cycle_b, calls, rows)
    for cycle in (cycle_a, cycle_b):
        own = _rows(cycle)
        assert len(own) == 2, "each cycle's Brain records into its own custody"
    assert cycle_a.stance_memory.custody_token != cycle_b.stance_memory.custody_token
    for cycle in (cycle_a, cycle_b):
        assert {row["history_lineage"]["custody"] for row in _rows(cycle)} == {
            cycle.stance_memory.custody_token}

    # Revision in A only.
    scan, payload = _brain_scan(cycle_a, calls, _revised(TA.LATER))
    assert payload["stance_history"]["available"] is False
    assert all(row.get("superseded_by_history_revision") is None
               for row in _rows(cycle_b))
    scan, payload = _brain_scan(cycle_b, calls, TA.LATER2)
    last = payload["stance_history"]["last"]
    assert last["history_lineage"]["custody"] == cycle_b.stance_memory.custody_token
    assert _instant(last["recorded_at_cutoff"]) == _instant(AT_0304)
    # No cycle's custody was ever installed as the process-global ECU memory.
    assert ECU._STANCE is None


# ── 5. Transported input is immutable; one recording pass per Brain call ───
def _capture_transport(monkeypatch):
    """Keep a reference to the EXACT object handed to the model transport."""
    import ai_brain.narrative_brain as NB

    mocked = NB._call_llm
    sent = []

    def capture(payload, repair=None):
        sent.append((payload, copy.deepcopy(payload)))
        return mocked(payload, repair)

    monkeypatch.setattr(NB, "_call_llm", capture)
    return sent


@TA.ECU_MODES
def test_transported_input_cannot_be_altered_after_transport(tmp_path, monkeypatch,
                                                             ecu):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    sent = _capture_transport(monkeypatch)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    _brain_scan(cycle, calls, TA.LATER)
    transported, at_transport = sent[-1]
    # Recording the current response cannot alter the input it was given.
    assert transported["stance_history"] == at_transport["stance_history"]
    assert transported["narrative_continuity"] == at_transport["narrative_continuity"]
    # Nor can later recording or a later history re-anchoring.
    _brain_scan(cycle, calls, TA.LATER2)
    cycle._reanchor_cognitive_state(9)
    assert transported["stance_history"] == at_transport["stance_history"]


@TA.ECU_MODES
def test_one_brain_call_one_recording_and_brainless_scans_record_nothing(
        tmp_path, monkeypatch, ecu):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    for count, rows in enumerate((RF.TAPE_1M, TA.LATER), start=1):
        _brain_scan(cycle, calls, rows)
        assert len(calls) == count
        assert len(_rows(cycle)) == count
    TA._scan(cycle, TA.LATER2, brain=False)
    assert len(calls) == 2 and len(_rows(cycle)) == 2
    assert ECU._STANCE is None, "the process-global ECU memory is never used"


# ── 6. Sealed plan recheck keeps truthful authoring lineage ────────────────
@TA.ECU_MODES
def test_sealed_plan_recheck_keeps_truthful_authoring_lineage(tmp_path, monkeypatch,
                                                              ecu):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls = _lane(tmp_path, monkeypatch, ecu, mutator=TA._watching(now))
    producer = CandidateProducer(account_fingerprint="acct:history-hygiene",
                                 contract=RF.MNQ)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    planning, _payload = _brain_scan(cycle, calls, TA.LATER)
    plan_candidate = TA._plan_candidate(producer, planning, now)
    auth = TA._authorization(plan_candidate, now)
    plan = producer.capture_conditional_plan_authority(
        candidate=plan_candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    authored = plan.payload()["brain_result"]["narrative_continuity"]
    prior = authored["prior_thesis"]
    assert prior["stance_schema_version"] == 2
    assert _instant(prior["recorded_at_cutoff"]) == _instant(AT_0259)
    assert prior["history_lineage"]["history_revision"] == 0
    assert prior["contract_id"] == RF.CONTRACT

    trigger = TA._scan(cycle, TA.NEXT_MINUTE, brain=False)
    fresh = TA._trigger(producer, trigger, plan_candidate=plan_candidate,
                        authority=plan, auth=auth, now=now)
    assert fresh.extras["conditional_plan_authority"]["state"] == "VERIFIED"
    rechecked = recheck_narrative_continuity(trigger["snapshot"], authored)
    for key in ("stance_schema_version", "recorded_at_cutoff", "history_lineage",
                "contract_id", "market_session", "process_session_id"):
        assert rechecked["prior_thesis"][key] == prior[key], key


def test_legacy_prior_thesis_is_not_stamped_with_new_schema_or_trigger_scope():
    snapshot = {"timestamp": AT_0304, "contract_id": RF.CONTRACT,
                "active_path_state": {"state_available": False}}
    legacy_last = {"timestamp": AT_0259, "direction": "bullish",
                   "campaign_direction": "bullish", "campaign_established": True,
                   "narrative_state_version": 1, "thesis_falsifier_status": "not_occurred"}
    authored = build_narrative_continuity(
        snapshot, {"available": True, "last": legacy_last})
    for key in ("stance_schema_version", "recorded_at_cutoff", "history_lineage",
                "contract_id", "market_session", "process_session_id"):
        assert authored["prior_thesis"][key] is None, key
    later = dict(snapshot, timestamp=AT_0309)
    rechecked = recheck_narrative_continuity(later, authored)
    for key in ("stance_schema_version", "recorded_at_cutoff", "history_lineage",
                "contract_id", "market_session", "process_session_id"):
        assert rechecked["prior_thesis"][key] is None, key


# ── 7. Selection rule, anchor and compatibility (StanceMemory only) ────────
AUTHORING = ("stance_schema_version", "recorded_at_cutoff", "history_lineage",
             "contract_id", "market_session", "process_session_id")
AT_0314 = "2026-08-19T03:14:00+00:00"


def _scope_snapshot(at, revision=0, contract=None):
    return {"timestamp": at, "contract_id": contract or RF.CONTRACT,
            "derived_state": {"history_revision": revision}}


def _stance(direction, phase="continuation"):
    return {"narrative_direction": direction, "narrative_phase": phase}


def _bound(**kwargs):
    from ai_brain.stance_memory import StanceMemory

    memory = StanceMemory(persist=False, **kwargs)
    memory.bind_production_scope(RF.CONTRACT, RF.SESSION_ID)
    return memory


def _strip(row):
    return {k: v for k, v in (row or {}).items() if k not in AUTHORING}


def test_normal_chronology_selects_what_the_legacy_summary_selected():
    from ai_brain.stance_memory import StanceMemory

    legacy, bound = StanceMemory(persist=False), _bound()
    for at, direction in ((AT_0259, "bullish"), (AT_0304, "bearish"),
                          (AT_0309, "bearish")):
        legacy.record(at, _stance(direction))
        bound.record(at, _stance(direction), snapshot=_scope_snapshot(at))
    old = legacy.history_summary()
    new = bound.history_summary(snapshot=_scope_snapshot(AT_0314))
    assert new["available"] is old["available"] is True
    assert _strip(new["last"]) == _strip(old["last"])
    assert [_strip(r) for r in new["prior_5"]] == [_strip(r) for r in old["prior_5"]]
    assert new["changed_since_last"] == old["changed_since_last"]
    assert _strip(new["thesis_anchor"]) == _strip(old["thesis_anchor"])
    assert new["withheld_context"] == []
    assert new["eligibility"]["eligible_count"] == 3


def test_equal_cutoffs_resolve_by_recording_sequence_not_buffer_position():
    bound = _bound()
    bound.record(AT_0304, _stance("bearish"), snapshot=_scope_snapshot(AT_0304))
    bound.record(AT_0304, _stance("bullish"), snapshot=_scope_snapshot(AT_0304))
    for _ in range(2):
        hist = bound.history_summary(snapshot=_scope_snapshot(AT_0309))
        assert hist["last"]["direction"] == "bullish"
        assert hist["last"]["history_lineage"]["sequence"] == 2
        bound._buf.reverse()   # DEFENSE-ONLY: position never decides recency


def test_garbage_does_not_reset_the_thesis_anchor_or_the_change():
    bound = _bound()
    bound.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    bound.record(AT_0304, _stance("bullish"), snapshot=_scope_snapshot(AT_0304))
    bad = copy.deepcopy(bound._buf[-1])           # DEFENSE-ONLY injection
    bad.update(direction="bearish", timestamp=FUTURE, recorded_at_cutoff=FUTURE)
    bound._buf.append(bad)
    bound.record(AT_0309, _stance("bullish"), snapshot=_scope_snapshot(AT_0309))
    hist = bound.history_summary(snapshot=_scope_snapshot(AT_0314))
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert hist["changed_since_last"]["direction"] is False
    assert [r["authority_withheld_reason"] for r in hist["withheld_context"]] == [
        "future_dated"]


def test_a_run_longer_than_the_buffer_keeps_its_true_start():
    from ai_brain.stance_memory import StanceMemory

    legacy, bound = StanceMemory(max_len=3, persist=False), _bound(max_len=3)
    minutes = ["2026-08-19T02:%02d:00+00:00" % m for m in range(50, 57)]
    for index, at in enumerate(minutes):
        direction = "bearish" if index == 0 else "bullish"
        legacy.record(at, _stance(direction))
        bound.record(at, _stance(direction), snapshot=_scope_snapshot(at))
    hist = bound.history_summary(snapshot=_scope_snapshot(AT_0259))
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(minutes[1])
    assert _strip(hist["thesis_anchor"]) == _strip(legacy.history_summary()["thesis_anchor"])


@pytest.mark.parametrize("snapshot", [
    None,
    {"timestamp": AT_0304, "contract_id": RF.CONTRACT},           # no revision
    _scope_snapshot("not-a-settled-instant"),
    _scope_snapshot(AT_0304, contract="CON.F.US.MES.Z26"),
], ids=["no-snapshot", "no-revision", "bad-cutoff", "foreign-contract"])
def test_a_bound_custody_without_proved_current_scope_supplies_nothing(snapshot):
    bound = _bound()
    bound.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    hist = bound.history_summary(snapshot=snapshot)
    assert hist["available"] is False and hist["last"] is None
    assert hist["thesis_anchor"] is None and hist["prior_5"] == []
    assert [r["authority_withheld_reason"] for r in hist["withheld_context"]] == [
        "current_scope_unproved"]


def test_missing_producer_scope_is_recorded_missing_never_manufactured():
    from ai_brain.stance_memory import StanceMemory

    unscoped = StanceMemory(persist=False)
    unscoped.bind_production_scope("", RF.SESSION_ID)
    unscoped.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    assert unscoped._buf[-1]["contract_id"] is None
    no_revision = _bound()
    no_revision.record(AT_0259, _stance("bullish"),
                       snapshot={"timestamp": AT_0259, "contract_id": RF.CONTRACT})
    assert no_revision._buf[-1]["history_lineage"]["history_revision"] is None
    for memory in (unscoped, no_revision):
        hist = memory.history_summary(snapshot=_scope_snapshot(AT_0304))
        assert hist["available"] is False
        assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 1}


def test_standalone_memory_keeps_the_legacy_contract():
    from ai_brain.stance_memory import StanceMemory

    memory = StanceMemory(persist=False)
    memory.record(AT_0259, _stance("bullish"))
    assert "stance_schema_version" not in memory._buf[-1]
    hist = memory.history_summary()
    assert hist["available"] is True and "withheld_context" not in hist
    hist["last"]["direction"] = "mutated"
    assert memory._buf[-1]["direction"] == "bullish", "summaries are copies"


# ── 8. Malformed retained rows are quarantined ONE BY ONE (3B-1A-R1) ───────
#
# DEFENSE-ONLY throughout: the producer never writes these shapes. Each must
# be withheld individually as malformed_scope. None may suppress, replace or
# reset the healthy incumbent, anchor or change summary, interrupt revision
# marking, or be repaired by manufactured content.
MALFORMED_ITEMS = {"null": None, "string": "not-a-stance-row", "list": ["bullish"]}


def _runtime_file(tmp_path):
    return tmp_path / "brain_runtime" / "stance_memory.json"


# R1 -- real ProductionScanCycle, exact transported payload, both lanes.
@TA.ECU_MODES
@pytest.mark.parametrize("item", list(MALFORMED_ITEMS))
def test_non_object_row_cannot_suppress_the_healthy_incumbent(tmp_path, monkeypatch,
                                                              ecu, item):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    _brain_scan(cycle, calls, TA.LATER)
    # DEFENSE-ONLY: a malformed element retained ahead of healthy cognition.
    cycle.stance_memory._buf.insert(0, copy.deepcopy(MALFORMED_ITEMS[item]))

    scan, payload = _brain_scan(cycle, calls, TA.LATER2)
    _assert_healthy_bullish_incumbent(payload, scan, AT_0304)
    hist = payload["stance_history"]
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 1}
    assert hist["eligibility"]["eligible_count"] == 2
    [withheld] = hist["withheld_context"]
    assert withheld["authority_withheld_reason"] == "malformed_scope"
    assert withheld["item_type"] == type(MALFORMED_ITEMS[item]).__name__
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert hist["changed_since_last"]["direction"] is False
    # Retained for audit (not deleted), and recording continues normally.
    assert cycle.stance_memory._buf[0] == MALFORMED_ITEMS[item]
    assert _instant(_rows(cycle)[-1]["recorded_at_cutoff"]) == _instant(AT_0309)

    scan, payload = _brain_scan(cycle, calls, TA.LATER3)
    _assert_healthy_bullish_incumbent(payload, scan, AT_0309)


# R2 -- a loaded malformed element cannot block fresh in-process cognition.
@pytest.mark.parametrize("persisted", [
    {"buf": [None], "thesis_anchor": None},
    {"buf": ["not-a-stance-row", ["bullish"]], "thesis_anchor": "not-an-anchor"},
    {"buf": "not-a-buffer", "thesis_anchor": None},          # malformed container
], ids=["null-row", "scalar-rows-and-anchor", "non-list-buffer"])
def test_loaded_malformed_row_cannot_block_fresh_cognition(tmp_path, persisted):
    from ai_brain.stance_memory import StanceMemory

    path = _runtime_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(persisted))        # DEFENSE-ONLY seeded file
    memory = StanceMemory()
    memory.bind_production_scope(RF.CONTRACT, RF.SESSION_ID)
    retained = (persisted["buf"] if isinstance(persisted["buf"], list)
                else [persisted["buf"]])
    memory.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    assert len(memory.recent()) == len(retained) + 1

    hist = memory.history_summary(snapshot=_scope_snapshot(AT_0304))
    assert hist["available"] is True
    assert hist["last"]["direction"] == "bullish"
    assert _instant(hist["last"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": len(retained)}
    # The malformed content is still persisted, not deleted or reset.
    on_disk = json.loads(path.read_text())["buf"]
    assert on_disk[:len(retained)] == retained
    assert on_disk[-1]["stance_schema_version"] == 2


# R3 -- a scoped dictionary of the wrong shape is withheld, never repaired.
def _missing(key):
    return lambda row: row.pop(key)


def _set(key, value):
    return lambda row: row.__setitem__(key, value)


MALFORMED_SHAPES = {
    "missing_direction": _missing("direction"),
    "null_direction": _set("direction", None),
    "empty_direction": _set("direction", ""),
    "list_direction": _set("direction", ["bullish"]),
    "missing_phase": _missing("phase"),
    "int_phase": _set("phase", 7),
    "dict_phase": _set("phase", {"name": "continuation"}),
    "missing_state_version": _missing("narrative_state_version"),
    "wrong_state_version": _set("narrative_state_version", 2),
    "missing_timestamp": _missing("timestamp"),
    "timestamp_not_the_cutoff": _set("timestamp", AT_0259),
    "missing_campaign_direction": _missing("campaign_direction"),
    "string_campaign_established": _set("campaign_established", "yes"),
    "int_falsifier_status": _set("thesis_falsifier_status", 5),
    "string_falsifier": _set("thesis_falsifier", "29500"),
    "int_custody": lambda row: row["history_lineage"].__setitem__("custody", 7),
}


@pytest.mark.parametrize("shape", list(MALFORMED_SHAPES))
def test_malformed_dictionary_cannot_suppress_or_replace_the_incumbent(shape):
    bound = _bound()
    bound.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    bad = copy.deepcopy(bound.recent()[0])        # DEFENSE-ONLY
    bad.update(timestamp=AT_0304, recorded_at_cutoff=AT_0304, direction="bearish",
               campaign_direction="bearish")
    bad["history_lineage"]["sequence"] = 2
    MALFORMED_SHAPES[shape](bad)
    bound._buf.append(bad)

    hist = bound.history_summary(snapshot=_scope_snapshot(AT_0309))
    assert hist["available"] is True
    assert hist["last"]["direction"] == "bullish"
    assert _instant(hist["last"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(AT_0259)
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 1}
    assert [r["authority_withheld_reason"] for r in hist["withheld_context"]] == [
        "malformed_scope"]
    # Nothing was manufactured into the stored row.
    assert bound._buf[-1] == bad
    continuity = build_narrative_continuity(
        {"timestamp": AT_0309, "contract_id": RF.CONTRACT,
         "active_path_state": {"state_available": False}}, hist)
    assert continuity["prior_thesis"]["direction"] == "bullish"
    assert _instant(continuity["prior_thesis"]["timestamp"]) == _instant(AT_0259)


def test_withheld_context_is_bounded_and_detached():
    bound = _bound()
    bound.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    huge = {"stance_schema_version": 2, "direction": ["bullish"] * 2000,
            "history_lineage": {"custody": "x" * 5000}, "timestamp": "y" * 5000}
    bound._buf[:0] = ["z" * 20000, huge]            # DEFENSE-ONLY
    hist = bound.history_summary(snapshot=_scope_snapshot(AT_0304))
    assert hist["available"] is True and hist["eligibility"]["withheld_count"] == 2
    assert len(json.dumps(hist["withheld_context"])) < 2000
    hist["withheld_context"][1]["history_lineage"]["truncated_preview"] = "mutated"
    hist["last"]["direction"] = "mutated"
    assert bound._buf[1] == huge and bound._buf[2]["direction"] == "bullish"


# R4 -- malformed elements/anchor cannot interrupt revision marking.
LAYOUTS = {
    "around_rows": lambda good: [None, good[0], "garbage", good[1], ["x"]],
    "anchor_only": lambda good: list(good),
}
ANCHORS = {
    "string_anchor": lambda good: "not-an-anchor",
    "dict_anchor_without_direction": lambda good: {
        k: v for k, v in copy.deepcopy(good[0]).items() if k != "direction"},
}


@pytest.mark.parametrize("anchor", list(ANCHORS))
@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_malformed_items_cannot_interrupt_revision_marking(tmp_path, layout, anchor):
    from ai_brain.stance_memory import StanceMemory

    memory = StanceMemory()
    memory.bind_production_scope(RF.CONTRACT, RF.SESSION_ID)
    memory.record(AT_0259, _stance("bullish"), snapshot=_scope_snapshot(AT_0259))
    memory.record(AT_0304, _stance("bullish"), snapshot=_scope_snapshot(AT_0304))
    good = list(memory._buf)
    memory._buf[:] = LAYOUTS[layout](good)          # DEFENSE-ONLY
    memory._thesis_anchor = ANCHORS[anchor](good)   # DEFENSE-ONLY
    bad_count = len(memory._buf) - 2
    reasons = {"superseded_history_revision": 2}
    if bad_count:
        reasons["malformed_scope"] = bad_count

    # Lineage alone already withholds the stale rows, before any marking.
    hist = memory.history_summary(snapshot=_scope_snapshot(AT_0309, revision=1))
    assert hist["available"] is False and hist["last"] is None
    assert hist["eligibility"]["withheld_reasons"] == reasons

    assert memory.supersede(1, note="repaired") == {
        "marked": 2, "revision": 1, "not_markable": bad_count}
    assert [row["superseded_by_history_revision"] for row in good] == [1, 1]
    on_disk = json.loads(_runtime_file(tmp_path).read_text())["buf"]
    assert on_disk == memory._buf, "marks persisted; malformed items retained"

    hist = memory.history_summary(snapshot=_scope_snapshot(AT_0309, revision=1))
    assert hist["available"] is False
    assert hist["eligibility"]["withheld_reasons"] == reasons
    assert hist["history_revision"]["stances_formed_before_a_repair"] == 2
    assert len(hist["withheld_context"]) == len(memory._buf)

    memory.record(AT_0309, _stance("bullish"),
                  snapshot=_scope_snapshot(AT_0309, revision=1))
    hist = memory.history_summary(snapshot=_scope_snapshot(AT_0314, revision=1))
    assert hist["available"] is True
    assert hist["last"]["history_lineage"]["history_revision"] == 1
    assert _instant(hist["thesis_anchor"]["recorded_at_cutoff"]) == _instant(AT_0309)


@TA.ECU_MODES
def test_malformed_items_do_not_interrupt_a_real_revision(tmp_path, monkeypatch, ecu):
    cycle, calls = _lane(tmp_path, monkeypatch, ecu)
    _brain_scan(cycle, calls, RF.TAPE_1M)
    _brain_scan(cycle, calls, TA.LATER)
    good = _rows(cycle)
    # DEFENSE-ONLY: malformed items before/between/after, and a malformed anchor.
    cycle.stance_memory._buf[:] = [None, good[0], "garbage", good[1], ["x"]]
    cycle.stance_memory._thesis_anchor = "not-an-anchor"

    scan, payload = _brain_scan(cycle, calls, _revised(TA.LATER))
    assert cycle.rebuilds[-1]["cognitive"]["stance"] == {
        "marked": 2, "revision": 1, "not_markable": 3}
    assert [row["superseded_by_history_revision"] for row in good] == [1, 1]
    hist = payload["stance_history"]
    assert hist["available"] is False
    assert payload["narrative_continuity"]["prior_thesis"] is None
    assert hist["eligibility"]["withheld_reasons"] == {
        "superseded_history_revision": 2, "malformed_scope": 3}

    scan, payload = _brain_scan(
        cycle, calls, _revised(TA.LATER) + TA.LATER2[len(TA.LATER):])
    assert payload["stance_history"]["last"]["history_lineage"]["history_revision"] == 1
    assert payload["narrative_continuity"]["prior_thesis"]["direction"] == "bullish"

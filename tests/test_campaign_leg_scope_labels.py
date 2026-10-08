"""STAGE 3B-1B — ACTIVE-LEG LABELS SEPARATED FROM CAMPAIGN FALSIFICATION.

Local ActivePath load-bearing evidence and leg death are published and
persisted ONLY under leg names (`active_leg`, `active_leg_structure`,
`active_leg_failure_status`, `prior_active_leg_failure_status`). No producer
binds a campaign premise, so `campaign_premise` is UNKNOWN and every
campaign-falsifier surface is null/"unknown".

The deterministic outcomes are pinned to the values measured on the parent
(77d5149) with the SAME mocked model response: control state, held
stand-down and invalidation level, Lifecycle state/reason, Draw retirement,
candidate refusal and sealed-plan trigger outcome. Only representation moved.

Real ProductionScanCycle, ECU and non-ECU, production ECU accessor restored,
exact transported payloads, isolated per-test runtime roots. Synthetic settled
bars only; every positive case is natural emitter output. DEFENSE-ONLY inputs
are labelled.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone

import pytest

import ai_brain.ecu as ECU
import test_campaign_draw_temporal_authority as TA
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
from ai_brain.narrative_continuity import (build_narrative_continuity,
                                           output_direction_hold,
                                           recheck_narrative_continuity)
from broker.luna_candidate_producer import CandidateProducer, NoCandidate

C = RF.CONTRACT
UNKNOWN_PREMISE = {"status": "UNKNOWN", "reason": "campaign_premise_unbound",
                   "binding": None}
LEG_STATUS_KEYS = {"active_leg_failure_status", "prior_active_leg_failure_status"}
CAMPAIGN_STATUS_KEYS = ("thesis_falsifier_status", "current_thesis_falsifier_status",
                        "prior_thesis_falsifier_status")


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def bar(hhmm, o, h, l, c):
    return {"timestamp": f"2026-08-19T{hhmm}:00+00:00", "open": o, "high": h,
            "low": l, "close": c, "volume": 10, "contract": C}


_SWEEP = [bar("03:05", 29460, 29462, 29455, 29458), bar("03:06", 29458, 29459, 29450, 29452),
          bar("03:07", 29452, 29453, 29445, 29447), bar("03:08", 29447, 29455, 29446, 29454),
          bar("03:09", 29454, 29458, 29452, 29456), bar("03:10", 29456, 29457, 29449, 29451)]
SCENARIOS = {
    # C1: 1m protected low 29445 registers at 03:11; the 03:13 close 29440
    # breaks it, far above the 3m/5m protected low 29429.75.
    "C1": _SWEEP + [bar("03:11", 29451, 29452, 29443, 29450),
                    bar("03:12", 29450, 29456, 29449, 29455),
                    bar("03:13", 29455, 29455, 29438, 29440),
                    bar("03:14", 29440, 29452, 29439, 29451)],
    # C2: the 3m bucket 03:09-03:11 closes 29422 below 29429.75 while the
    # containing 5m bucket recovers; a later 15m structure appears at 03:14.
    "C2": [bar("03:05", 29460, 29461, 29458, 29460), bar("03:06", 29460, 29461, 29455, 29456),
           bar("03:07", 29456, 29457, 29450, 29451), bar("03:08", 29451, 29452, 29446, 29447),
           bar("03:09", 29447, 29448, 29440, 29445), bar("03:10", 29445, 29446, 29420, 29425),
           bar("03:11", 29425, 29428, 29418, 29422), bar("03:12", 29422, 29440, 29421, 29438),
           bar("03:13", 29438, 29450, 29437, 29448), bar("03:14", 29448, 29452, 29446, 29450)],
    # C4: a single opposing 1m break at 03:11 (close 29441 below 29445)
    # contests the path.
    "C4": _SWEEP + [bar("03:11", 29451, 29452, 29440, 29441),
                    bar("03:12", 29441, 29450, 29440, 29449),
                    bar("03:13", 29449, 29455, 29448, 29454),
                    bar("03:14", 29454, 29458, 29453, 29457)],
}

TRANSFER_UNRESOLVED = ["TRANSFER_UNRESOLVED", "narrative_control_transfer_not_yet_confirmed"]
ACTIVE = ["ACTIVE_DELIVERY", "validated_brain_delivery_with_intact_owner"]

# Outcomes measured on the parent 77d5149 (both lanes) with the same mocked
# response: (control, dominant, lifecycle, candidate, brain action, held
# invalidation level, leg failure status, recorded leg structure (tf, level)).
PINNED = {
    ("C1", "03:11"): ("incumbent_intact", "bullish", ACTIVE, None, "propose_entry",
                      29445.0, "not_occurred", ("1m", 29445.0)),
    ("C1", "03:13"): ("developing_transfer", None, TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29445.0, "occurred",
                      ("1m", 29445.0)),
    ("C1", "03:14"): ("developing_transfer", None, TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29445.0, "occurred",
                      ("1m", 29445.0)),
    ("C2", "03:11"): ("developing_transfer", None, TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29429.75, "occurred",
                      ("3m", 29429.75)),
    ("C2", "03:14"): ("developing_transfer", None, TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29429.0, "occurred",
                      ("15m", 29429.0)),
    ("C4", "03:10"): ("incumbent_intact", "bullish", ACTIVE, None, "propose_entry",
                      29429.75, "not_occurred", ("3m", 29429.75)),
    ("C4", "03:11"): ("developing_transfer", "bullish", TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29429.75,
                      "not_occurred", ("3m", 29429.75)),
    ("C4", "03:14"): ("developing_transfer", "bullish", TRANSFER_UNRESOLVED,
                      "campaign_lifecycle_refused", "stand_down", 29429.75,
                      "not_occurred", ("3m", 29429.75)),
}


def _occurred_paths(value, path=""):
    """Every key path whose value is the string 'occurred'."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found += _occurred_paths(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for item in value:
            found += _occurred_paths(item, path + "[]")
    elif value == "occurred":
        found.append(path)
    return found


def _assert_campaign_unbound(continuity):
    assert continuity["campaign_premise"] == UNKNOWN_PREMISE
    assert continuity["current_thesis_falsifier"] is None
    for key in CAMPAIGN_STATUS_KEYS:
        assert continuity[key] == "unknown", key
    prior = continuity.get("prior_thesis")
    if prior is not None:
        assert prior["thesis_falsifier"] is None
        assert prior["falsifier_status"] == "unknown"
        assert prior["campaign_premise"] == UNKNOWN_PREMISE
    for path in _occurred_paths(continuity):
        assert path.split(".")[-1] in LEG_STATUS_KEYS, path


def _assert_row_unbound(row):
    assert row["campaign_premise"] == UNKNOWN_PREMISE
    assert row["thesis_falsifier"] is None
    assert row["thesis_falsifier_status"] == "unknown"
    assert row["prior_thesis_falsifier_status"] == "unknown"
    for path in _occurred_paths(row):
        assert path.split(".")[-1] in LEG_STATUS_KEYS, path


def _candidate(scan):
    try:
        RF._produce_candidate(scan)
    except NoCandidate as exc:
        return exc.reason
    return None


# ── 1. C1/C2/C4: leg evidence only under leg names; outcomes unchanged ─────
@TA.ECU_MODES
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_local_leg_failure_is_never_published_as_campaign_falsification(
        tmp_path, monkeypatch, ecu, name):
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    sent = H._capture_transport(monkeypatch)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows = list(TA.LATER)
    seen_failure = False
    for b in SCENARIOS[name]:
        rows = rows + [b]
        scan, _payload = H._brain_scan(cycle, calls, rows)
        hhmm = b["timestamp"][11:16]
        transported = sent[-1][1]            # deep copy taken at transport
        nc = transported["narrative_continuity"]
        _assert_campaign_unbound(nc)
        for row in ([transported["stance_history"].get("last")]
                    + list(transported["stance_history"].get("prior_5") or [])):
            if row:
                _assert_row_unbound(row)
        recorded = cycle.stance_memory.recent(1)[-1]
        _assert_row_unbound(recorded)
        assert recorded["active_leg_failure_status"] == \
            scan["brain_block"]["narrative_continuity"]["active_leg_failure_status"] \
            or scan["brain_block"]["narrative_continuity"]["control_state"] \
            == "confirmed_transfer"
        seen_failure |= nc["active_leg_failure_status"] == "occurred"

        expected = PINNED.get((name, hhmm))
        if expected is None:
            continue
        (control, dominant, lifecycle, refusal, action, held_level,
         leg_status, (leg_tf, leg_level)) = expected
        current = scan["brain_block"]["narrative_continuity"]
        assert current["control_state"] == control
        assert current["dominant_direction"] == dominant
        assert [scan["campaign_lifecycle"]["state"],
                scan["campaign_lifecycle"]["reason"]] == lifecycle
        assert _candidate(scan) == refusal
        output = scan["brain_block"]["output"]
        assert output["current_action"] == action
        assert output["invalidation_level"] == held_level
        assert current["active_leg_failure_status"] == leg_status
        assert recorded["active_leg_failure_status"] == leg_status
        assert (recorded["active_leg_structure"]["timeframe"],
                recorded["active_leg_structure"]["level"]) == (leg_tf, leg_level)
    assert seen_failure is (name in ("C1", "C2"))
    # Persisted custody carries no campaign-falsification evidence either.
    on_disk = json.loads(H._runtime_file(tmp_path).read_text())["buf"]
    for row in on_disk:
        _assert_row_unbound(row)


# ── 2. Sticky local failure still refuses on every later scan ──────────────
# After C1, three more 1m closes stay below 29445. Measured on the parent in
# both lanes: every scan 03:13-03:17 is developing_transfer / TRANSFER_UNRESOLVED
# / campaign_lifecycle_refused / held stand_down at 29445, and the Draw retires
# exactly once (campaign_ownership_lost) with no later advance or retirement.
STICKY_TAIL = [bar("03:15", 29451, 29452, 29440, 29442),
               bar("03:16", 29442, 29444, 29439, 29441),
               bar("03:17", 29441, 29443, 29438, 29440)]


@TA.ECU_MODES
def test_sticky_leg_failure_keeps_identical_refusals_across_scans(tmp_path,
                                                                   monkeypatch, ecu):
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows = list(TA.LATER)
    for b in SCENARIOS["C1"] + STICKY_TAIL:
        rows = rows + [b]
        scan, payload = H._brain_scan(cycle, calls, rows)
        hhmm = b["timestamp"][11:16]
        if hhmm < "03:13":
            continue
        nc = payload["narrative_continuity"]
        assert nc["control_state"] == "developing_transfer"
        assert nc["dominant_direction"] is None
        assert nc["active_leg_failure_status"] == "occurred"
        assert nc["prior_active_leg_failure_status"] == (
            "not_occurred" if hhmm == "03:13" else "occurred")
        _assert_campaign_unbound(nc)
        assert [scan["campaign_lifecycle"]["state"],
                scan["campaign_lifecycle"]["reason"]] == TRANSFER_UNRESOLVED
        assert _candidate(scan) == "campaign_lifecycle_refused"
        output = scan["brain_block"]["output"]
        assert (output["current_action"], output["invalidation_level"]) == (
            "stand_down", 29445.0)
        row = cycle.stance_memory.recent(1)[-1]
        assert row["active_leg_failure_status"] == "occurred"
        assert (row["active_leg_structure"]["timeframe"],
                row["active_leg_structure"]["level"]) == ("1m", 29445.0)
        _assert_row_unbound(row)
        records = cycle.campaign_draw_truth.audit_records
        assert len(records) == 1
        assert [r.get("superseded_reason") for r in records if r.get("superseded")] == [
            "campaign_ownership_lost:owner=none:status=none"]


# ── 3. Sealed plan: authoring leg evidence carried; outcomes unchanged ─────
@TA.ECU_MODES
def test_sealed_plan_carries_leg_evidence_and_refuses_identically(tmp_path,
                                                                  monkeypatch, ecu):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu, mutator=TA._watching(now))
    producer = CandidateProducer(account_fingerprint="acct:leg-scope", contract=RF.MNQ)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    planning, _payload = H._brain_scan(cycle, calls, TA.LATER)
    plan_candidate = TA._plan_candidate(producer, planning, now)
    auth = TA._authorization(plan_candidate, now)
    plan = producer.capture_conditional_plan_authority(
        candidate=plan_candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    authored = plan.payload()["brain_result"]["narrative_continuity"]
    _assert_campaign_unbound(authored)
    prior = authored["prior_thesis"]
    assert prior["active_leg_structure"]["level"] == 29429.75
    assert prior["active_leg_failure_status"] == "unknown"
    assert authored["active_leg_failure_status"] == "not_occurred"

    trigger = TA._scan(cycle, TA.NEXT_MINUTE, brain=False)
    fresh = TA._trigger(producer, trigger, plan_candidate=plan_candidate,
                        authority=plan, auth=auth, now=now)
    assert fresh.extras["conditional_plan_authority"]["state"] == "VERIFIED"
    rechecked = recheck_narrative_continuity(trigger["snapshot"], authored)
    _assert_campaign_unbound(rechecked)
    assert rechecked["prior_thesis"]["active_leg_structure"] == prior["active_leg_structure"]
    assert rechecked["prior_thesis"]["active_leg_failure_status"] == "unknown"
    for key in H.AUTHORING:
        assert rechecked["prior_thesis"][key] == prior[key], key

    # Measured on the parent: C1's 03:13 local failure refuses the trigger
    # through the same Lifecycle boundary.
    rows = list(TA.LATER) + SCENARIOS["C1"][:9]
    trigger = TA._scan(cycle, rows, brain=False)
    with pytest.raises(NoCandidate) as refused:
        TA._trigger(producer, trigger, plan_candidate=plan_candidate,
                    authority=plan, auth=auth, now=now)
    assert refused.value.reason == "campaign_lifecycle_refused"
    assert trigger["snapshot"]["campaign_lifecycle"]["state"] == "TRANSFER_UNRESOLVED"
    _assert_campaign_unbound(recheck_narrative_continuity(trigger["snapshot"], authored))


# ── 4. Legacy (pre-3B-1B) inputs: aliases read as LEG evidence only ────────
def _legacy_snapshot(owner, status, *, invalidated=None, bearing=None):
    return {"timestamp": "2026-08-19T03:09:00+00:00", "contract_id": C,
            "active_path_state": {
                "state_available": True, "owner": owner, "status": status,
                "contract_id": C, "session": "20260818",
                "load_bearing_structure": bearing, "last_invalidated": invalidated,
                "transfer_evidence": {"opposing_structure_break": False,
                                      "load_bearing_failure": bool(invalidated),
                                      "load_bearing_replaced_against_path": False,
                                      "ambiguous_load_bearing_invalidation": False}}}


def test_legacy_row_alias_is_read_as_leg_evidence_never_campaign_authority():
    # A row shaped before 3B-1B: the leg status/structure sit under the old
    # campaign-falsifier names.
    legacy_last = {"timestamp": "2026-08-19T03:04:00+00:00", "direction": "bullish",
                   "campaign_direction": "bullish", "campaign_established": True,
                   "narrative_state_version": 1, "thesis_falsifier_status": "occurred",
                   "thesis_falsifier": {"level": 29445.0, "timeframe": "1m"}}
    snapshot = _legacy_snapshot("none", "none", invalidated={
        "owner": "bullish", "at": "2026-08-19T03:08:00+00:00", "level": 29445.0})
    continuity = build_narrative_continuity(snapshot, {"available": True,
                                                       "last": legacy_last})
    assert continuity["control_state"] == "developing_transfer"
    assert continuity["prior_active_leg_failure_status"] == "occurred"
    assert continuity["active_leg_failure_status"] == "occurred"
    assert continuity["prior_thesis"]["active_leg_structure"] == legacy_last["thesis_falsifier"]
    assert continuity["prior_thesis"]["active_leg_failure_status"] == "occurred"
    _assert_campaign_unbound(continuity)


def test_legacy_sealed_prior_thesis_rechecks_as_leg_evidence():
    # A plan sealed before 3B-1B carried leg status as prior_thesis.falsifier_status.
    authored = {"prior_thesis": {"direction": "bullish", "campaign_established": True,
                                 "timestamp": "2026-08-19T03:04:00+00:00",
                                 "falsifier_status": "occurred",
                                 "thesis_falsifier": {"level": 29445.0}}}
    snapshot = _legacy_snapshot("none", "none", invalidated={
        "owner": "bullish", "at": "2026-08-19T03:08:00+00:00", "level": 29445.0})
    rechecked = recheck_narrative_continuity(snapshot, authored)
    assert rechecked["control_state"] == "developing_transfer"
    assert rechecked["prior_active_leg_failure_status"] == "occurred"
    _assert_campaign_unbound(rechecked)


# ── 5. output_direction_hold reads the equivalent leg structure ────────────
def test_held_invalidation_level_comes_from_the_leg_structure():
    continuity = {"control_state": "developing_transfer", "dominant_direction": None,
                  "prior_thesis": {"direction": "bullish", "invalidation_level": 1.0,
                                   "causal_reason": "sell-side raid reclaimed"},
                  "active_leg_structure": {"level": 29445.0, "timeframe": "1m"},
                  "current_thesis_falsifier": None,
                  "campaign_premise": dict(UNKNOWN_PREMISE)}
    held, guard = output_direction_hold(
        {"narrative_direction": "bullish", "current_action": "propose_entry"},
        continuity)
    assert held["invalidation_level"] == 29445.0
    assert held["current_action"] == "stand_down"
    assert guard["status"] == "entry_held_for_control_state"
    assert "not proof that a campaign premise failed" in held["dominant_reasoning"]
    without_leg = dict(continuity, active_leg_structure=None)
    held, _ = output_direction_hold(
        {"narrative_direction": "bullish", "current_action": "propose_entry"},
        without_leg)
    assert held["invalidation_level"] == 1.0, "prior thesis level as before"


# ── 6. Stance rows: leg fields are required, shape-checked, never manufactured
LEG_SHAPES = {
    "missing_leg_status": lambda row: row.pop("active_leg_failure_status"),
    "missing_leg_structure": lambda row: row.pop("active_leg_structure"),
    "int_leg_status": lambda row: row.__setitem__("active_leg_failure_status", 5),
    "string_leg_structure": lambda row: row.__setitem__("active_leg_structure", "29445"),
}


@pytest.mark.parametrize("shape", list(LEG_SHAPES))
def test_malformed_leg_fields_are_withheld_without_hiding_the_incumbent(shape):
    bound = H._bound()
    bound.record(H.AT_0259, H._stance("bullish"), snapshot=H._scope_snapshot(H.AT_0259))
    recorded = bound.recent()[0]
    assert recorded["active_leg_failure_status"] is None
    assert recorded["active_leg_structure"] is None
    _assert_row_unbound(recorded)
    bad = copy.deepcopy(recorded)                 # DEFENSE-ONLY
    bad.update(timestamp=H.AT_0304, recorded_at_cutoff=H.AT_0304, direction="bearish")
    bad["history_lineage"]["sequence"] = 2
    LEG_SHAPES[shape](bad)
    bound._buf.append(bad)
    hist = bound.history_summary(snapshot=H._scope_snapshot(H.AT_0309))
    assert hist["available"] is True
    assert hist["last"]["direction"] == "bullish"
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 1}
    assert bound._buf[-1] == bad, "nothing manufactured"


# ── 7. P3: oversized numeric audit context is bounded ──────────────────────
def _numeric_memory():
    memory = H._bound()
    memory.record(H.AT_0304, H._stance("bullish"), snapshot=H._scope_snapshot(H.AT_0304))
    return memory


VIEW_KEYS = ["timestamp", "recorded_at_cutoff", "direction", "campaign_direction",
             "phase", "action", "contract_id", "market_session", "history_lineage",
             "superseded_by_history_revision"]


@pytest.mark.parametrize("value", [int("9" * 1000), -int("9" * 1000)],
                         ids=["large_positive", "large_negative"])
def test_large_integers_are_bounded_typed_previews(value):
    from ai_brain.stance_memory import CONTEXT_VALUE_LIMIT

    memory = _numeric_memory()
    bad = dict.fromkeys(VIEW_KEYS, value)
    bad["stance_schema_version"] = 2
    memory._buf.append(json.loads(json.dumps(bad)))   # DEFENSE-ONLY
    hist = memory.history_summary(snapshot=H._scope_snapshot(H.AT_0304))
    assert hist["available"] and hist["last"]["direction"] == "bullish"
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 1}
    view = hist["withheld_context"][0]
    for key in VIEW_KEYS:
        assert view[key]["type"] == "int"
        assert len(view[key]["truncated_preview"]) <= CONTEXT_VALUE_LIMIT
    assert len(json.dumps(hist["withheld_context"])) < 4000
    assert memory._buf[-1]["direction"] == value, "stored value untouched"


def test_small_numbers_none_and_bools_stay_compatible():
    memory = _numeric_memory()
    bad = {"stance_schema_version": 2, "timestamp": 7, "recorded_at_cutoff": -3.5,
           "direction": True, "campaign_direction": None, "phase": 0,
           "superseded_by_history_revision": 2}
    memory._buf.append(bad)                           # DEFENSE-ONLY
    view = memory.history_summary(snapshot=H._scope_snapshot(H.AT_0304))[
        "withheld_context"][0]
    assert (view["timestamp"], view["recorded_at_cutoff"], view["direction"],
            view["campaign_direction"], view["phase"],
            view["superseded_by_history_revision"]) == (7, -3.5, True, None, 0, 2)


def test_non_finite_and_unrenderable_values_render_as_strict_json():
    memory = _numeric_memory()
    memory._buf += [                                   # DEFENSE-ONLY
        {"stance_schema_version": 2, "direction": float("nan"),
         "timestamp": float("inf"), "phase": float("-inf"),
         "history_lineage": {"custody": float("nan")}},
        float("nan"), 10 ** 5000, {"stance_schema_version": 2, "action": 10 ** 5000}]
    hist = memory.history_summary(snapshot=H._scope_snapshot(H.AT_0304))
    assert hist["available"] is True and hist["last"]["direction"] == "bullish"
    assert hist["eligibility"]["withheld_reasons"] == {"malformed_scope": 4}
    text = json.dumps(hist["withheld_context"], allow_nan=False)
    assert len(text) < 4000
    first = hist["withheld_context"][0]
    assert first["direction"] == {"truncated_preview": "nan", "type": "float"}
    assert first["timestamp"] == {"truncated_preview": "inf", "type": "float"}
    assert first["history_lineage"]["type"] == "dict"
    assert math.isnan(memory._buf[1]["direction"]), "stored value untouched"


def test_multiple_malformed_rows_stay_bounded_and_detached():
    memory = _numeric_memory()
    for index in range(8):                             # DEFENSE-ONLY
        memory._buf.insert(0, {"stance_schema_version": 2,
                               "direction": int("7" * (500 + index)),
                               "market_session": ["x"] * 5000})
    hist = memory.history_summary(snapshot=H._scope_snapshot(H.AT_0309))
    assert hist["available"] is True
    assert hist["eligibility"]["withheld_count"] == 8
    assert len(hist["withheld_context"]) == 5
    assert len(json.dumps(hist["withheld_context"], allow_nan=False)) < 6000
    hist["withheld_context"][0]["market_session"]["truncated_preview"] = "mutated"
    assert all(row.get("market_session") == ["x"] * 5000
               for row in memory._buf[:8])

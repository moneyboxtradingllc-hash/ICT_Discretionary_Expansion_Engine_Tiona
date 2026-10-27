"""LOCAL-AUTHORITY-20261026 Mission 1 -- source-backed constituent member order.

Tape: the archived PROD-20261023-C1 settled 1m bars (Friday). A bullish local
leg fails on the settled 1m 11:43 ET bar. The next rejected sell-side raid is
published natively on the 5m bucket that OPENED at 11:40, so the accepted
same-direction successor proof refuses at 11:49 (native R <= D). Its complete
settled members show the first strict crossing of 29218.75 happened in the
11:44 minute, after the failure settled. The second episode's 3m bucket first
crosses inside the 12:23 failure minute: still unproved, still refused.

Only a cycle built with the exact offline profile derives the witness; the
default cycle is the accepted source. Brain responses in the loop tests are
CONTROLLED; quotes are CONTROLLED; nothing here is natural model evidence,
historical intent or a fill. Execution is disarmed throughout.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

import local_authority_loop as H
import test_protected_structure_continuity as P
from ai_brain.narrative_continuity import _same_direction_successor_proof
from broker import topstepx_production_loop as PL
from broker.luna_candidate_producer import NoCandidate
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data import local_authority as LA

RUNTIME_DIRS = ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR")
FAILURE_1143 = "2026-10-23T15:43:00+00:00"
PARENT_1140 = "2026-10-23T15:40:00+00:00"
CROSSING_1144 = "2026-10-23T15:44:00+00:00"


def _isolate(monkeypatch, root):
    for key in RUNTIME_DIRS:
        monkeypatch.setenv(key, str(root / key))


def _scan(cycle, tape, hm):
    cut = P._cut(hm)
    bars = [b for b in tape if b["timestamp"] <= cut][-300:]
    return cycle.scan(bars, now=datetime.fromisoformat(cut) + timedelta(minutes=1),
                      invoke_brain=False), bars


def _walk(cycle, tape, start, end, direction, inspect=None):
    rows = {}
    for hm in P._minutes(start, end):
        scan, bars = _scan(cycle, tape, hm)
        snap = scan["snapshot"]
        path = snap["active_path_state"]
        rows[hm] = {"path": copy.deepcopy(path),
                    "successor": copy.deepcopy(
                        _same_direction_successor_proof(path, snap, direction))}
        if inspect:
            inspect(hm, cycle, scan, bars)
    return rows


def _origin(path):
    return (path or {}).get("origin") or {}


@pytest.fixture(scope="module")
def friday(tmp_path_factory):
    captured = {}

    def inspect(hm, cycle, scan, bars):
        if hm != "15:49":
            return
        snap = scan["snapshot"]
        path = snap["active_path_state"]
        captured["inputs"] = {
            "path": copy.deepcopy(path), "bars": copy.deepcopy(bars),
            "rows": copy.deepcopy(cycle._current_chronology_occurrences()),
            "revision": cycle._history.revision,
            "session": path.get("session")}
        captured["live_witness"] = copy.deepcopy(
            LA.authenticated_member_order(path, snap, "bullish"))
        bad = {}
        for name, change in BINDING_ATTACKS.items():
            altered = copy.deepcopy(path)
            change(altered)
            bad[name] = LA.authenticated_member_order(altered, snap, "bullish")
        captured["binding_attacks"] = bad
        captured["copied"] = _same_direction_successor_proof(
            copy.deepcopy(path), copy.deepcopy(snap), "bullish")
        cycle.local_authority.revoke("test_revocation")
        captured["revoked"] = _same_direction_successor_proof(path, snap, "bullish")
        again, _ = _scan(cycle, P.TAPE, hm)        # same cutoff: re-derived once
        captured["duplicate_path"] = copy.deepcopy(again["snapshot"]["active_path_state"])
        captured["stale_after_duplicate"] = _same_direction_successor_proof(
            path, snap, "bullish")
        captured["duplicate_successor"] = _same_direction_successor_proof(
            again["snapshot"]["active_path_state"], again["snapshot"], "bullish")

    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m1_friday"))
        default = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="M1-DEFAULT")
        # Mission 1 in isolation: the witness-only component profile (the full
        # offline profile's 12:24 ET delivery change is Mission 2's subject).
        offline = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="M1-OFFLINE",
                                      local_authority_profile=LA.OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1)
        rows_default = _walk(default, P.TAPE, "15:40", "16:30", "bullish")
        rows_offline = _walk(offline, P.TAPE, "15:40", "16:30", "bullish", inspect)
        yield {"default": rows_default, "offline": rows_offline, "captured": captured,
               "default_cycle": default, "offline_cycle": offline}


BINDING_ATTACKS = {
    "foreign_origin_occurrence": lambda p: p["origin"].update(occurrence_id="FOREIGN"),
    "other_native_bucket": lambda p: p["origin"].update(
        source_bar_time="2026-10-23T15:35:00+00:00"),
    "other_native_timeframe": lambda p: p["origin"].update(source_tf="15m"),
    "other_failure_life": lambda p: p["last_invalidated"].update(occurrence_id="OTHER"),
    "other_failure_bar": lambda p: p["last_invalidated"].update(
        source_bar_time="2026-10-23T15:44:00+00:00"),
    "tampered_witness_crossing": lambda p: p["origin"]["member_order_witness"][
        "first_crossing"].update(timestamp="2026-10-23T15:45:00+00:00"),
    "tampered_witness_status": lambda p: p["origin"]["member_order_witness"].update(
        status=LA.FACT_ORDER_ESTABLISHED, reason="forged"),
    "witness_removed": lambda p: p["origin"].pop("member_order_witness"),
}


# ── profile: default-off, exact object only ───────────────────────────────────
def test_only_the_exact_offline_profile_object_enables_anything(monkeypatch):
    for key in LA._EXECUTION_SWITCHES:
        monkeypatch.delenv(key, raising=False)
    assert LA.resolve_profile(None) == (LA.DISABLED, "default_disabled")
    lookalike = LA.LocalAuthorityProfile(**{
        k: getattr(LA.OFFLINE_TEST_PROFILE_V1, k)
        for k in LA.LocalAuthorityProfile.__dataclass_fields__})
    for value in ("local_authority_offline_test/v1", {"version": "x"}, lookalike,
                  copy.deepcopy(LA.OFFLINE_TEST_PROFILE_V1)):
        if value is LA.OFFLINE_TEST_PROFILE_V1:
            continue
        assert LA.resolve_profile(value) == (LA.DISABLED, "unrecognized_profile_disabled")
    assert LA.resolve_profile(LA.OFFLINE_TEST_PROFILE_V1) == (LA.OFFLINE_TEST_PROFILE_V1, None)
    monkeypatch.setenv("EXECUTION_ENABLED", "true")
    assert LA.resolve_profile(LA.OFFLINE_TEST_PROFILE_V1) == (
        LA.DISABLED, "offline_profile_refused_execution_environment")
    assert ProductionScanCycle(symbol="MNQ").local_authority.enabled is False


def test_default_cycle_is_the_accepted_parent_and_refuses_11_49(friday):
    rows = friday["default"]
    assert friday["default_cycle"].local_authority.enabled is False
    assert all("member_order_witness" not in _origin(r["path"]) for r in rows.values())
    at = rows["15:49"]
    origin, failure = _origin(at["path"]), at["path"]["last_invalidated"]
    assert (origin["source_tf"], origin["source_bar_time"]) == ("5m", PARENT_1140)
    assert (failure["source_tf"], failure["source_bar_time"]) == ("1m", FAILURE_1143)
    assert at["path"]["owner"] == "bullish" and at["successor"] is None


def test_offline_differs_from_default_only_by_the_attached_witness(friday):
    for hm, offline in friday["offline"].items():
        stripped = copy.deepcopy(offline["path"])
        _origin(stripped).pop("member_order_witness", None)
        assert stripped == friday["default"][hm]["path"], hm


def test_member_witness_proves_the_actual_11_44_crossing_after_the_11_43_failure(friday):
    at = friday["offline"]["15:49"]
    origin = _origin(at["path"])
    witness = origin["member_order_witness"]
    assert witness["status"] == LA.FACT_ORDER_ESTABLISHED
    assert witness["first_crossing"]["timestamp"] == CROSSING_1144
    assert witness["swept_level"] == 29218.75
    assert witness["failure_available_at"] == "2026-10-23T15:44:00+00:00"
    assert witness["parent_available_at"] == "2026-10-23T15:45:00+00:00"
    assert witness["canonical_parent_raid_id"].endswith(":5m:" + PARENT_1140)
    # Native identity is untouched: R stays the 11:40 bucket open.
    assert (origin["source_bar_time"], origin["source_tf"]) == (PARENT_1140, "5m")
    proof = at["successor"]
    assert proof["status"] == "verified" and proof["direction"] == "bullish"
    assert proof["order_basis"] == "constituent_member_order_witness"
    assert proof["causal_source_event_time"] == CROSSING_1144
    assert proof["member_order_witness_id"] == witness["witness_id"]
    assert proof["successor_origin"]["source_bar_time"] == PARENT_1140
    assert friday["captured"]["live_witness"]["witness_id"] == witness["witness_id"]


def test_same_minute_12_23_crossing_stays_refused(friday):
    for hm in H.minutes("16:24", "16:30"):
        row = friday["offline"][hm]
        witness = _origin(row["path"])["member_order_witness"]
        assert witness["status"] == LA.NOT_ESTABLISHED
        assert witness["reason"] == "first_crossing_not_after_settled_failure"
        assert witness["first_crossing"]["timestamp"] == "2026-10-23T16:23:00+00:00"
        assert row["successor"] is None


def test_copied_revoked_stale_and_duplicate_cutoffs(friday):
    c = friday["captured"]
    assert c["copied"] is None
    assert c["revoked"] is None
    assert c["stale_after_duplicate"] is None
    assert c["duplicate_path"] == friday["offline"]["15:49"]["path"]
    assert c["duplicate_successor"]["member_order_witness_id"] == \
        friday["offline"]["15:49"]["successor"]["member_order_witness_id"]


@pytest.mark.parametrize("attack", list(BINDING_ATTACKS))
def test_detached_or_altered_witness_relations_refuse_at_the_consumer(friday, attack):
    assert friday["captured"]["binding_attacks"][attack] is None


def _rebuild(inputs, **changes):
    args = dict(path=copy.deepcopy(inputs["path"]), ledger_rows=copy.deepcopy(inputs["rows"]),
                settled_1m=copy.deepcopy(inputs["bars"]), cutoff=P._cut("15:49"),
                contract_id=P.C, market_session=inputs["session"],
                history_revision=inputs["revision"])
    args.update(changes)
    return LA.member_order_witness(**args)


def _member(bars, stamp):
    return next(b for b in bars if b["timestamp"] == stamp)


def _earlier_crossing(i):
    bars = copy.deepcopy(i["bars"])
    _member(bars, "2026-10-23T15:42:00+00:00")["low"] = 29210.0
    return {"settled_1m": bars}


def _without(i, stamp):
    return {"settled_1m": [b for b in copy.deepcopy(i["bars"]) if b["timestamp"] != stamp]}


def _duplicate(i):
    bars = copy.deepcopy(i["bars"])
    return {"settled_1m": bars + [copy.deepcopy(_member(bars, CROSSING_1144))]}


def _foreign(i):
    bars = copy.deepcopy(i["bars"])
    _member(bars, "2026-10-23T15:41:00+00:00")["contract"] = "CON.F.US.MNQ.H27"
    return {"settled_1m": bars}


def _parent_rows(i, change):
    rows = copy.deepcopy(i["rows"])
    for row in rows:
        if (row.get("event_type") == "LIQUIDITY_SWEEP" and row.get("source_tf") == "5m"
                and row.get("event_time") == PARENT_1140):
            change(row)
    return {"ledger_rows": rows}


def _ambiguous(i):
    rows = copy.deepcopy(i["rows"])
    twin = next(copy.deepcopy(r) for r in rows if r.get("event_type") == "LIQUIDITY_SWEEP"
                and r.get("source_tf") == "5m" and r.get("event_time") == PARENT_1140)
    twin["swept_level"] = 29219.0
    return {"ledger_rows": rows + [twin]}


def _failure_later(i):
    path = copy.deepcopy(i["path"])
    path["last_invalidated"]["source_bar_time"] = CROSSING_1144
    return {"path": path}


PRODUCER_ATTACKS = {
    "earlier_member_crossing": (_earlier_crossing, "first_crossing_not_after_settled_failure"),
    "missing_member": (lambda i: _without(i, "2026-10-23T15:42:00+00:00"),
                       "parent_members_incomplete_or_unordered"),
    "duplicate_member": (_duplicate, "member_duplicate"),
    "foreign_contract_member": (_foreign, "member_foreign_contract"),
    "future_parent": (lambda i: {"cutoff": P._cut("15:43")}, "parent_bucket_not_settled"),
    "changed_reference_level": (lambda i: _parent_rows(
        i, lambda r: r.update(swept_level=29200.0)), "no_member_crosses_raid_reference"),
    "parent_not_reclaimed": (lambda i: _parent_rows(
        i, lambda r: r.update(reclaimed=False)), "canonical_parent_raid_missing_or_ambiguous"),
    "ambiguous_parent_payload": (_ambiguous, "canonical_parent_raid_missing_or_ambiguous"),
    "parent_missing": (lambda i: {"ledger_rows": []},
                       "canonical_parent_raid_missing_or_ambiguous"),
    "failure_shares_crossing_minute": (_failure_later,
                                       "first_crossing_not_after_settled_failure"),
    "wrong_session": (lambda i: {"market_session": "20261022"}, "witness_context_incomplete"),
    "revision_not_integer": (lambda i: {"history_revision": None},
                             "witness_context_incomplete"),
}


def test_the_unaltered_inputs_reproduce_the_live_witness(friday):
    rebuilt = _rebuild(friday["captured"]["inputs"])
    assert rebuilt == _origin(friday["offline"]["15:49"]["path"])["member_order_witness"]


@pytest.mark.parametrize("attack", list(PRODUCER_ATTACKS))
def test_each_broken_member_relation_is_not_established(friday, attack):
    change, reason = PRODUCER_ATTACKS[attack]
    inputs = friday["captured"]["inputs"]
    witness = _rebuild(inputs, **change(inputs))
    assert witness["status"] == LA.NOT_ESTABLISHED and witness["reason"] == reason


def test_cold_restart_rederives_the_identical_witness(tmp_path, monkeypatch, friday):
    _isolate(monkeypatch, tmp_path)
    cold = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="M1-COLD",
                               local_authority_profile=LA.OFFLINE_TEST_PROFILE_V1)
    scan, _ = _scan(cold, P.TAPE, "15:49")
    path = scan["snapshot"]["active_path_state"]
    expected = _origin(friday["offline"]["15:49"]["path"])["member_order_witness"]
    assert _origin(path)["member_order_witness"] == expected
    proof = _same_direction_successor_proof(path, scan["snapshot"], "bullish")
    assert proof["member_order_witness_id"] == expected["witness_id"]


def test_history_revision_retires_the_issue_and_rederives_under_the_new_revision(
        tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="M1-REV",
                                local_authority_profile=LA.OFFLINE_TEST_PROFILE_V1)
    first, bars = _scan(cycle, P.TAPE, "15:49")
    old_snap, old_path = first["snapshot"], first["snapshot"]["active_path_state"]
    assert _same_direction_successor_proof(old_path, old_snap, "bullish")
    revised = copy.deepcopy(bars)
    revised[10]["volume"] = revised[10].get("volume", 0) + 1     # a past bar changes
    second = cycle.scan(revised, now=datetime.fromisoformat(P._cut("15:49"))
                        + timedelta(minutes=1), invoke_brain=False)
    assert cycle._history.revision == first["snapshot"]["derived_state"]["history_revision"] + 1
    assert _same_direction_successor_proof(old_path, old_snap, "bullish") is None
    witness = _origin(second["snapshot"]["active_path_state"])["member_order_witness"]
    assert witness["history_revision"] == cycle._history.revision
    assert witness["witness_id"] != _origin(old_path)["member_order_witness"]["witness_id"]


def test_constructed_mirror_proves_the_bearish_order_and_refuses_its_same_minute_case(
        tmp_path, monkeypatch):
    """CONSTRUCTED: the Friday tape reflected in price. Not a historical session."""
    _isolate(monkeypatch, tmp_path)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="M1-MIRROR",
                                local_authority_profile=LA.OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1)
    rows = _walk(cycle, H.mirrored_tape(P.TAPE), "15:40", "16:25", "bearish")
    at = rows["15:49"]
    witness = _origin(at["path"])["member_order_witness"]
    assert witness["direction"] == "bearish" and witness["status"] == LA.FACT_ORDER_ESTABLISHED
    assert witness["first_crossing"]["timestamp"] == CROSSING_1144
    assert at["successor"]["order_basis"] == "constituent_member_order_witness"
    late = _origin(rows["16:24"]["path"])["member_order_witness"]
    assert late["reason"] == "first_crossing_not_after_settled_failure"
    assert rows["16:24"]["successor"] is None


# ── the real disarmed loop, both ECU modes ────────────────────────────────────
@pytest.fixture(scope="module", params=[False, True], ids=["non-ecu", "ecu"])
def loop(request, tmp_path_factory):
    with pytest.MonkeyPatch.context() as m:
        out = {}
        for name, profile in (("default", None), ("offline", LA.OFFLINE_TEST_PROFILE_V1)):
            out[name] = H.run(m, tmp_path_factory.mktemp(f"m1_loop_{name}"),
                              ecu=request.param, profile=profile, warmup="15:36",
                              schedule=H.minutes("15:37", "15:57"), act_from="15:49",
                              direction="bullish", session=f"M1-{name.upper()}")
        last = out["offline"]["scans"][-1]
        attempts = {}
        try:
            attempts["healthy"] = H.produce(out["offline"], last).direction
        except NoCandidate as exc:
            attempts["healthy"] = exc.reason
        for name, alter in (("copied_snapshot", copy.deepcopy),):
            try:
                H.produce(out["offline"], last, snapshot=alter(last["snapshot"]))
                attempts[name] = "CANDIDATE"
            except NoCandidate as exc:
                attempts[name] = exc.reason
        out["offline"]["cycle"].local_authority.revoke("test_revocation")
        try:
            H.produce(out["offline"], last)
            attempts["revoked_issue"] = "CANDIDATE"
        except NoCandidate as exc:
            attempts["revoked_issue"] = exc.reason
        out["attempts"] = attempts
        yield out


def test_default_loop_never_reaches_a_candidate(loop):
    run = loop["default"]
    assert run["candidates"] == [] and run["zero_orders"]
    assert run["tokens"] == run["attempts"] == 0
    assert {o["outcome"] for hm, o in run["outputs"].items() if hm >= "15:49"} == {
        PL.NO_CANDIDATE}


def test_offline_profile_reaches_the_disarmed_candidate_boundary(loop):
    run = loop["offline"]
    assert run["candidates"] == ["15:57"], {k: v.get("reason") for k, v in run["outputs"].items()}
    out = run["outputs"]["15:57"]
    assert out["execution"] == PL.EXECUTION_DISARMED and not run["loop"].armed
    assert run["zero_orders"] and run["tokens"] == run["attempts"] == 0
    # Mechanical gates downstream of authority are unchanged and still refuse.
    reasons = {o.get("reason") for hm, o in run["outputs"].items() if "15:50" <= hm < "15:57"}
    assert {"stop_distance_above_cap", "reward_below_qualification"} <= reasons
    # The generation was first admitted by the witness-backed successor proof
    # the actual Brain input carried; later scans continue it as incumbent.
    bases = [((s["brain_block"] or {}).get("narrative_continuity") or {}).get(
        "same_direction_successor_proof") or {} for s in run["scans"]]
    assert any(b.get("order_basis") == "constituent_member_order_witness" for b in bases)


def test_the_actual_candidate_consumer_refuses_copied_and_revoked_authority(loop):
    attempts = loop["attempts"]
    assert attempts["healthy"] == "bullish"
    assert attempts["copied_snapshot"] != "CANDIDATE"
    assert attempts["revoked_issue"] != "CANDIDATE"

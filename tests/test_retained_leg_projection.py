"""S4E PRIORITY 1 -- RETAINED PRIOR-LEG PROJECTION (narrative continuity).

Since fed9b8d, `build_narrative_continuity` projected the prior row's recorded
leg with `_load_bearing(row_leg)`, which reads a NESTED `load_bearing_structure`
key. Rows record the leg FLAT, so the projection was always None and the
`retained_prior_leg_row` branch was unreachable.

Retained-evidence rule (narrative_continuity._retained_leg_projection): the
prior row's recorded leg is published as the current leg evidence only when
the CURRENT producer state corroborates it -- same-session causal row, row
contract (when declared) equals this contract, the path is available for this
contract/session and publishes no live load-bearing structure, the leg is a
well-formed producer-backed life on the incumbent's supporting side, and the
path's own `last_invalidated` release names that exact life (owner, level,
side, timeframe, swing_id, registered_at). The projection is `intact: False`:
evidence of a failed life, never a live leg, campaign falsifier, transfer or
entry permission. Everything else is withheld.

Positives come from real ProductionScanCycle recording and stance readback in
both ECU lanes on the refounded 703a417 tape. Negatives mutate those exact
production-captured inputs (DEFENSE-ONLY labels mark every mutation).
"""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone

import pytest

import ai_brain.ecu as ECU
import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
from ai_brain.narrative_continuity import (build_narrative_continuity,
                                           candidate_direction_authorized,
                                           output_direction_hold,
                                           recheck_narrative_continuity)
from broker.luna_candidate_producer import CandidateProducer, NoCandidate

C1_DEATH = "2026-08-19T03:15:00+00:00"
C1_LIFE = ("1m", 29470.0, "2026-08-19T03:13:00+00:00")     # registered 03:13
C2_LIFE = ("1m", 29457.0, "2026-08-19T02:56:00+00:00")     # registered 02:56
IDENTITY = ("level", "side", "timeframe", "swing_id", "registered_at")


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def _life(structure):
    return (structure["timeframe"], structure["level"], structure["registered_at"])


def _assert_matches_release(structure, release, owner="bullish"):
    """The projected leg is exactly the life the producer released."""
    assert release["owner"] == owner
    assert structure["level"] == release["level"]
    assert structure["side"] == release["side"]
    assert structure["timeframe"] == release["source_tf"]
    assert structure["swing_id"] == release["swing_id"]
    assert structure["registered_at"] == release["registered_at"]


def _authority(continuity):
    """Every field the retained projection must never change."""
    keys = ("control_state", "dominant_direction", "transfer_confirmed",
            "transfer_proof", "same_direction_successor_proof", "confirmed_from",
            "confirmed_to", "campaign_premise", "current_thesis_falsifier",
            "thesis_falsifier_status", "prior_thesis_falsifier_status",
            "current_thesis_falsifier_status", "active_leg_failure_status",
            "prior_active_leg_failure_status")
    return {k: copy.deepcopy(continuity.get(k)) for k in keys}


def _assert_no_campaign_authority(continuity):
    """Captured snapshots replayed outside their live cycle read campaign scope
    as unavailable (custody is per cycle); either way nothing is bound."""
    assert continuity["campaign_premise"]["status"] == "UNKNOWN"
    assert continuity["campaign_premise"]["binding"] is None
    assert continuity["current_thesis_falsifier"] is None
    for key in L.CAMPAIGN_STATUS_KEYS:
        assert continuity[key] == "unknown", key
    assert continuity["dominant_direction"] is None
    assert continuity["transfer_confirmed"] is False


def _run_c1(tmp_path, monkeypatch, ecu, through):
    """Real cycle through C1 (+ sticky tail); yields (hhmm, scan, payload, row)."""
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows = list(TA.LATER)
    out = []
    for b in L.SCENARIOS["C1"] + L.STICKY_TAIL:
        rows = rows + [b]
        scan, payload = H._brain_scan(cycle, calls, rows)
        hhmm = b["timestamp"][11:16]
        out.append((hhmm, scan, payload, copy.deepcopy(cycle.stance_memory.recent(1)[-1])))
        if hhmm == through:
            break
    return cycle, out


# ── 1. Production positive: record -> readback -> retained failed leg ──────
@TA.ECU_MODES
def test_retained_branch_reached_from_production_record_and_readback(
        tmp_path, monkeypatch, ecu):
    cycle, out = _run_c1(tmp_path, monkeypatch, ecu, through="03:19")
    by_bar = {hhmm: (scan, payload, row) for hhmm, scan, payload, row in out}

    # 03:14: the live 1m 29470@03:13 life is the CURRENT producer structure.
    scan, payload, row_0314 = by_bar["03:14"]
    nc = payload["narrative_continuity"]
    assert nc["active_leg_structure_source"] == "current_active_path"
    assert _life(nc["active_leg_structure"]) == C1_LIFE
    assert nc["active_leg_structure"]["intact"] is True
    assert _life(row_0314["active_leg_structure"]) == C1_LIFE

    # 03:15: the producer released exactly that life; the dead path publishes
    # no structure. The transported continuity reads the 03:14 row back from
    # stance custody and publishes it as RETAINED failed-leg evidence.
    scan, payload, row_0315 = by_bar["03:15"]
    assert payload["stance_history"]["last"]["recorded_at_cutoff"] == \
        row_0314["recorded_at_cutoff"]
    path = scan["snapshot"]["active_path_state"]
    assert path["load_bearing_structure"] is None
    release = path["last_invalidated"]
    nc = payload["narrative_continuity"]
    assert nc["active_leg_structure_source"] == "retained_prior_leg_row"
    retained = nc["active_leg_structure"]
    assert _life(retained) == C1_LIFE
    assert retained["intact"] is False, "a failed life is never a live leg"
    _assert_matches_release(retained, release)
    assert nc["active_leg"]["load_bearing_structure"] is None
    assert nc["active_path"]["load_bearing_structure"] is None
    # Held stand-down pins the failed leg's level (formerly the authored stop).
    output = scan["brain_block"]["output"]
    assert (output["current_action"], output["invalidation_level"]) == (
        "stand_down", 29470.0)
    assert output["invalidation_level"] != nc["prior_thesis"]["invalidation_level"]
    # Authority is unchanged by the evidence.
    assert nc["control_state"] == "developing_transfer"
    assert nc["dominant_direction"] is None
    assert nc["transfer_confirmed"] is False
    assert nc["same_direction_successor_proof"] is None
    L._assert_campaign_unbound(nc)
    assert [scan["campaign_lifecycle"]["state"],
            scan["campaign_lifecycle"]["reason"]] == L.TRANSFER_UNRESOLVED
    assert L._candidate(scan) == "campaign_lifecycle_refused"
    # The 03:15 row records the retained (failed) projection, not a live leg.
    assert _life(row_0315["active_leg_structure"]) == C1_LIFE
    assert row_0315["active_leg_structure"]["intact"] is False
    assert row_0315["active_leg_failure_status"] == "occurred"
    L._assert_row_unbound(row_0315)

    # 03:16: a NEW forming 1m 29470@03:16 life is current producer evidence;
    # it replaces the retained failed life without resurrecting the campaign.
    scan, payload, row_0316 = by_bar["03:16"]
    nc = payload["narrative_continuity"]
    assert nc["active_leg_structure_source"] == "current_active_path"
    assert _life(nc["active_leg_structure"]) == ("1m", 29470.0, "2026-08-19T03:16:00+00:00")
    assert nc["control_state"] == "developing_transfer"
    assert nc["dominant_direction"] is None
    assert nc["same_direction_successor_proof"] is None
    assert nc["transfer_confirmed"] is False
    assert L._candidate(scan) == "campaign_lifecycle_refused"
    # 03:17 kills the 03:16 life: the producer releases it and the retained
    # evidence follows that newer life (never the older 03:13 one). 03:18
    # registers another live life, which is current again.
    expected = {"03:17": ("retained_prior_leg_row",
                          ("1m", 29470.0, "2026-08-19T03:16:00+00:00"), False),
                "03:18": ("current_active_path",
                          ("1m", 29463.0, "2026-08-19T03:18:00+00:00"), True),
                "03:19": ("current_active_path",
                          ("1m", 29463.0, "2026-08-19T03:18:00+00:00"), True)}
    for hhmm, (source, life, intact) in expected.items():
        scan, payload, _row = by_bar[hhmm]
        nc = payload["narrative_continuity"]
        assert nc["active_leg_structure_source"] == source, hhmm
        assert _life(nc["active_leg_structure"]) == life, hhmm
        assert nc["active_leg_structure"]["intact"] is intact, hhmm
        if source == "retained_prior_leg_row":
            _assert_matches_release(nc["active_leg_structure"],
                                    scan["snapshot"]["active_path_state"]["last_invalidated"])
        assert scan["brain_block"]["output"]["invalidation_level"] == life[1], hhmm
        assert nc["control_state"] == "developing_transfer", hhmm
        assert nc["same_direction_successor_proof"] is None, hhmm
        assert L._candidate(scan) == "campaign_lifecycle_refused", hhmm
    # Draw retirement stays exactly once.
    records = cycle.campaign_draw_truth.audit_records
    assert len(records) == 1
    assert [r.get("superseded_reason") for r in records if r.get("superseded")] == [
        "campaign_ownership_lost:owner=none:status=none"]


@TA.ECU_MODES
def test_c2_first_post_death_and_sticky_scans_retain_the_released_life(
        tmp_path, monkeypatch, ecu):
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows = list(TA.LATER)
    retained_bars = []
    for b in L.SCENARIOS["C2"]:
        rows = rows + [b]
        scan, payload = H._brain_scan(cycle, calls, rows)
        hhmm = b["timestamp"][11:16]
        nc = payload["narrative_continuity"]
        if hhmm == "03:05":
            assert nc["active_leg_structure_source"] == "current_active_path"
            continue
        # 03:06 is the first post-death scan; 03:07-03:14 are sticky.
        assert nc["active_leg_structure_source"] == "retained_prior_leg_row", hhmm
        assert _life(nc["active_leg_structure"]) == C2_LIFE, hhmm
        assert nc["active_leg_structure"]["intact"] is False
        path = scan["snapshot"]["active_path_state"]
        _assert_matches_release(nc["active_leg_structure"], path["last_invalidated"])
        # From 03:07 an opposing bearish owner holds the path WITHOUT a
        # structure of its own: nothing live supersedes the incumbent's
        # released life, and the opposing owner gains no authority from it.
        assert path["load_bearing_structure"] is None
        assert (path["owner"], path["status"]) == (
            ("none", "none") if hhmm == "03:06" else ("bearish", "active"))
        assert nc["dominant_direction"] is None
        assert nc["transfer_confirmed"] is False
        assert scan["brain_block"]["output"]["invalidation_level"] == 29457.0
        assert nc["active_leg_failure_status"] == "occurred"
        assert nc["prior_active_leg_failure_status"] == (
            "not_occurred" if hhmm == "03:06" else "occurred")
        assert nc["control_state"] == "developing_transfer"
        L._assert_campaign_unbound(nc)
        assert L._candidate(scan) == "campaign_lifecycle_refused"
        retained_bars.append(hhmm)
    assert retained_bars == [b["timestamp"][11:16] for b in L.SCENARIOS["C2"][1:]]
    assert len(cycle.campaign_draw_truth.audit_records) == 1


# ── 2. Custody negatives on production-captured inputs ─────────────────────
@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    """The real 03:15 snapshot and the 03:14 row it reads back (non-ECU)."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("AI_BRAIN_DIR", str(tmp_path_factory.mktemp("cap") / "brain"))
        ECU._STANCE = None
        _cycle, out = _run_c1(tmp_path_factory.mktemp("lane"), mp, False, through="03:15")
        bars = {hhmm: (scan, row) for hhmm, scan, _payload, row in out}
        snapshot = copy.deepcopy(bars["03:15"][0]["snapshot"])
        row = copy.deepcopy(bars["03:14"][1])
    finally:
        mp.undo()
        ECU._STANCE = None
    return snapshot, row


def _continuity(snapshot, row):
    return build_narrative_continuity(snapshot, {"available": True, "last": row})


def test_captured_inputs_reproduce_the_production_projection(captured):
    snapshot, row = captured
    nc = _continuity(snapshot, row)
    assert nc["active_leg_structure_source"] == "retained_prior_leg_row"
    assert _life(nc["active_leg_structure"]) == C1_LIFE
    assert nc["active_leg_structure"]["intact"] is False


def _leg(row):
    return row["active_leg_structure"]


# DEFENSE-ONLY mutations of the recorded leg.
MALFORMED_LEGS = {
    "missing_swing_id": lambda leg: leg.pop("swing_id"),
    "empty_swing_id": lambda leg: leg.__setitem__("swing_id", ""),
    "non_finite_level": lambda leg: leg.__setitem__("level", math.nan),
    "bool_level": lambda leg: leg.__setitem__("level", True),
    "string_level": lambda leg: leg.__setitem__("level", "29470"),
    "opposing_side": lambda leg: leg.__setitem__("side", "high"),
    "unknown_timeframe": lambda leg: leg.__setitem__("timeframe", "2m"),
    "naive_registered_at": lambda leg: leg.__setitem__("registered_at",
                                                        "2026-08-19T03:13:00"),
    "missing_registered_at": lambda leg: leg.pop("registered_at"),
    "not_producer_backed": lambda leg: leg.__setitem__("producer_backed", False),
    "missing_producer_backed": lambda leg: leg.pop("producer_backed"),
}


@pytest.mark.parametrize("shape", list(MALFORMED_LEGS))
def test_malformed_recorded_leg_is_withheld_without_changing_authority(captured, shape):
    snapshot, row = captured
    positive = _continuity(snapshot, row)
    bad = copy.deepcopy(row)                                    # DEFENSE-ONLY
    MALFORMED_LEGS[shape](bad["active_leg_structure"])
    nc = _continuity(snapshot, bad)
    assert nc["active_leg_structure"] is None
    assert nc["active_leg_structure_source"] is None
    assert _authority(nc) == _authority(positive)
    held, _ = output_direction_hold({"narrative_direction": "bullish",
                                     "current_action": "propose_entry"}, nc)
    assert held["invalidation_level"] == nc["prior_thesis"]["invalidation_level"]


@pytest.mark.parametrize("value", [None, "29470", 29470.0, ["1m"], {}])
def test_non_structure_recorded_leg_is_withheld(captured, value):
    snapshot, row = captured
    bad = dict(copy.deepcopy(row), active_leg_structure=value)   # DEFENSE-ONLY
    nc = _continuity(snapshot, bad)
    assert nc["active_leg_structure"] is None
    assert nc["active_leg_structure_source"] is None


def test_prior_session_row_is_withheld(captured):
    snapshot, row = captured
    old = copy.deepcopy(row)                                     # DEFENSE-ONLY
    old["timestamp"] = "2026-08-18T03:14:00+00:00"   # previous production session
    nc = _continuity(snapshot, old)
    assert nc["same_production_session"] is False
    assert nc["legacy_or_prior_session_stance_ignored"] is True
    assert nc["prior_thesis"] is None
    assert nc["active_leg_structure"] is None
    assert nc["active_leg_structure_source"] is None


def test_legacy_unversioned_row_is_withheld(captured):
    snapshot, row = captured
    legacy = copy.deepcopy(row)                                  # DEFENSE-ONLY
    legacy.pop("narrative_state_version")
    nc = _continuity(snapshot, legacy)
    assert nc["same_production_session"] is False
    assert nc["active_leg_structure"] is None


def test_foreign_contract_row_is_withheld(captured):
    snapshot, row = captured
    positive = _continuity(snapshot, row)
    foreign = copy.deepcopy(row)                                 # DEFENSE-ONLY
    foreign["contract_id"] = "CON.F.US.MES.Z26"
    nc = _continuity(snapshot, foreign)
    assert nc["active_leg_structure"] is None
    assert nc["active_leg_structure_source"] is None
    assert _authority(nc) == _authority(positive)


def test_foreign_or_session_conflicting_path_is_withheld(captured):
    snapshot, row = captured
    for field, value in (("contract_id", "CON.F.US.MES.Z26"), ("session", "20260817")):
        bad = copy.deepcopy(snapshot)                            # DEFENSE-ONLY
        bad["active_path_state"][field] = value
        nc = _continuity(bad, row)
        assert nc["active_path"]["identity_conflict"] is True, field
        assert nc["control_state"] == "unresolved", field
        assert nc["active_leg_structure"] is None, field
        assert nc["active_leg_structure_source"] is None, field


def test_unavailable_path_is_withheld(captured):
    snapshot, row = captured
    bad = copy.deepcopy(snapshot)                                # DEFENSE-ONLY
    bad["active_path_state"]["state_available"] = False
    nc = _continuity(bad, row)
    assert nc["active_leg_structure"] is None


# DEFENSE-ONLY mutations of the producer's release record.
UNCORROBORATED_RELEASES = {
    "absent": lambda path: path.__setitem__("last_invalidated", None),
    "other_registration_life": lambda path: path["last_invalidated"].__setitem__(
        "registered_at", "2026-08-19T03:16:00+00:00"),
    "other_swing": lambda path: path["last_invalidated"].__setitem__(
        "swing_id", path["last_invalidated"]["swing_id"] + ":other"),
    "other_timeframe": lambda path: path["last_invalidated"].__setitem__("source_tf", "3m"),
    "other_level": lambda path: path["last_invalidated"].__setitem__("level", 29469.0),
    "other_side": lambda path: path["last_invalidated"].__setitem__("side", "high"),
    "other_owner": lambda path: path["last_invalidated"].__setitem__("owner", "bearish"),
}


@pytest.mark.parametrize("shape", list(UNCORROBORATED_RELEASES))
def test_uncorroborated_by_producer_release_is_withheld(captured, shape):
    snapshot, row = captured
    bad = copy.deepcopy(snapshot)
    UNCORROBORATED_RELEASES[shape](bad["active_path_state"])
    nc = _continuity(bad, row)
    assert nc["active_leg_structure"] is None
    assert nc["active_leg_structure_source"] is None
    _assert_no_campaign_authority(nc)


def test_live_producer_structure_takes_precedence(captured):
    snapshot, row = captured
    bad = copy.deepcopy(snapshot)                                # DEFENSE-ONLY
    live = dict(copy.deepcopy(_leg(row)), level=29471.0, intact=True,
                registered_at="2026-08-19T03:15:00+00:00")
    bad["active_path_state"]["load_bearing_structure"] = live
    nc = _continuity(bad, row)
    assert nc["active_leg_structure_source"] == "current_active_path"
    assert nc["active_leg_structure"]["level"] == 29471.0


def test_legacy_row_alias_retains_the_same_released_life(captured):
    snapshot, row = captured
    legacy = copy.deepcopy(row)                       # pre-3B-1B field name
    legacy["thesis_falsifier"] = legacy.pop("active_leg_structure")
    nc = _continuity(snapshot, legacy)
    assert nc["active_leg_structure_source"] == "retained_prior_leg_row"
    assert _life(nc["active_leg_structure"]) == C1_LIFE
    assert nc["active_leg_structure"]["intact"] is False
    _assert_no_campaign_authority(nc)


# ── 3. The retained projection can never bypass refusal ────────────────────
def test_retained_projection_cannot_authorize_a_candidate_or_entry(captured):
    snapshot, row = captured
    nc = _continuity(snapshot, row)
    assert nc["active_leg_structure_source"] == "retained_prior_leg_row"
    for direction in ("bullish", "bearish"):
        allowed, reason = candidate_direction_authorized(direction, snapshot, nc, nc)
        assert (allowed, reason) == (False, "narrative_transfer_unresolved"), direction
    for proposed in ("bullish", "bearish"):
        held, guard = output_direction_hold({"narrative_direction": proposed,
                                             "current_action": "propose_entry"}, nc)
        assert held["current_action"] == "stand_down"
        assert held["allowed_direction"] == "none"
        assert held["invalidation_level"] == 29470.0
        assert guard["status"] == "entry_held_for_control_state"
    # Even a forged live flag on the recorded leg changes nothing: the
    # projection is derived as failed evidence and authority is unchanged.
    forged = copy.deepcopy(row)                                  # DEFENSE-ONLY
    forged["active_leg_structure"]["intact"] = True
    again = _continuity(snapshot, forged)
    assert again["active_leg_structure"]["intact"] is False
    assert _authority(again) == _authority(nc)


# ── 4. Sealed plan recheck keeps truthful authoring metadata ───────────────
def _sealed_plan(tmp_path, monkeypatch, ecu):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu, mutator=TA._watching(now))
    producer = CandidateProducer(account_fingerprint="acct:retained-leg",
                                 contract=RF.MNQ)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    planning, _payload = H._brain_scan(cycle, calls, TA.LATER)
    plan_candidate = TA._plan_candidate(producer, planning, now)
    auth = TA._authorization(plan_candidate, now)
    plan = producer.capture_conditional_plan_authority(
        candidate=plan_candidate, scan=planning, authorization=auth,
        process_session_id=RF.SESSION_ID, now=now)
    return cycle, producer, plan_candidate, auth, plan, now


@TA.ECU_MODES
def test_sealed_plan_recheck_retains_only_the_released_authoring_life(
        tmp_path, monkeypatch, ecu):
    cycle, producer, plan_candidate, auth, plan, now = _sealed_plan(
        tmp_path, monkeypatch, ecu)
    authored = plan.payload()["brain_result"]["narrative_continuity"]
    prior = authored["prior_thesis"]
    assert _life(prior["active_leg_structure"]) == C2_LIFE

    # C2 03:06 kills the authoring life itself: the recheck retains it.
    rows = list(TA.LATER) + L.SCENARIOS["C2"][:2]
    assert rows[-1]["timestamp"] == "2026-08-19T03:06:00+00:00"
    trigger = TA._scan(cycle, rows, brain=False)
    rechecked = recheck_narrative_continuity(trigger["snapshot"], authored)
    assert rechecked["active_leg_structure_source"] == "retained_prior_leg_row"
    assert _life(rechecked["active_leg_structure"]) == C2_LIFE
    assert rechecked["active_leg_structure"]["intact"] is False
    _assert_matches_release(rechecked["active_leg_structure"],
                            trigger["snapshot"]["active_path_state"]["last_invalidated"])
    for key in H.AUTHORING:
        assert rechecked["prior_thesis"][key] == prior[key], key
    assert rechecked["prior_thesis"]["active_leg_structure"] == prior["active_leg_structure"]
    L._assert_campaign_unbound(rechecked)
    with pytest.raises(NoCandidate) as refused:
        TA._trigger(producer, trigger, plan_candidate=plan_candidate,
                    authority=plan, auth=auth, now=now)
    assert refused.value.reason == "campaign_lifecycle_refused"


@TA.ECU_MODES
def test_sealed_plan_recheck_withholds_a_replaced_authoring_life(
        tmp_path, monkeypatch, ecu):
    cycle, producer, plan_candidate, auth, plan, now = _sealed_plan(
        tmp_path, monkeypatch, ecu)
    authored = plan.payload()["brain_result"]["narrative_continuity"]
    # C1 replaced the authoring 29457@02:56 life with 29470@03:13 and killed
    # THAT one at 03:15: the authoring leg is not the released life.
    rows = list(TA.LATER) + L.SCENARIOS["C1"][:11]
    assert rows[-1]["timestamp"] == C1_DEATH
    trigger = TA._scan(cycle, rows, brain=False)
    release = trigger["snapshot"]["active_path_state"]["last_invalidated"]
    assert (release["source_tf"], release["level"], release["registered_at"]) == C1_LIFE
    rechecked = recheck_narrative_continuity(trigger["snapshot"], authored)
    assert rechecked["active_leg_structure"] is None
    assert rechecked["active_leg_structure_source"] is None
    for key in H.AUTHORING:
        assert rechecked["prior_thesis"][key] == authored["prior_thesis"][key], key
    with pytest.raises(NoCandidate) as refused:
        TA._trigger(producer, trigger, plan_candidate=plan_candidate,
                    authority=plan, auth=auth, now=now)
    assert refused.value.reason == "campaign_lifecycle_refused"

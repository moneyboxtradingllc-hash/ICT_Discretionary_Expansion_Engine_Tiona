"""S4E PRIORITY 2 -- NATURAL 3m LOAD-BEARING LEG DEATH (both lanes).

The refounded C2 proves the early 1m death and no longer reaches a 3m-scope
death. This minute tape restores that coverage with real producers only; no
path, LifeRef, registration, scope, release or candidate object is injected.

Construction (every bar below, appended after TA.LATER, i.e. after 03:04):

* 03:05-03:11  wickless up bars 29460 -> 29488 (no 1m sweep: each low is the
               prior close, each high the close).
* 03:12-03:18  full-body down bars 29488 -> 29474 (close == low, so nothing is
               pierced and reclaimed), 03:19 a 1m DOUBLE BOTTOM at 29474. The
               equal lows leave 1m without a pivot there, while the 03:18-03:20
               3m bucket is a 3m pivot low 29474 (three higher 3m buckets on
               each side).
* 03:20-03:29  wickless up bars to 29496: three higher 3m buckets confirm it.
* 03:30-03:32  the 03:30-03:32 3m bucket raids 29474 (low 29472) and closes
               back at 29478: ONE settled 3m candle pierced the 3m pivot and
               closed back through it. The tracker REPLACES its 3m protected
               low 29429.75@01:38 with 29474@03:32 and ActivePath makes that
               exact life load-bearing (favourable over 1m 29457@02:56).
* 03:33-03:37  healthy control: the 3m life holds, incumbent_intact.
* 03:36-03:38  the settled 3m close 29473 violates 29474. Every 1m close stays
               above the 1m pivot 29472 and the 1m 29457 life; the 5m 29429.75
               life is untouched (broader structure intact).
* 03:39-03:41  sticky scans; 03:40-03:41 recover above 29474 without any new
               registration, so nothing resurrects the campaign.

Measured on the S4E repair (identical in both lanes).
"""
from __future__ import annotations

import copy

import pytest

import ai_brain.ecu as ECU
import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H

C = RF.CONTRACT


def _up(hhmm, o, c):
    return L.bar(hhmm, o, c, o, c)


def _down(hhmm, o, c):
    return L.bar(hhmm, o, o, c, c)


NATURAL_3M = (
    [_up("03:05", 29460, 29464), _up("03:06", 29464, 29468), _up("03:07", 29468, 29472),
     _up("03:08", 29472, 29476), _up("03:09", 29476, 29480), _up("03:10", 29480, 29484),
     _up("03:11", 29484, 29488)]
    + [_down("03:12", 29488, 29486), _down("03:13", 29486, 29484), _down("03:14", 29484, 29482),
       _down("03:15", 29482, 29480), _down("03:16", 29480, 29478), _down("03:17", 29478, 29476),
       _down("03:18", 29476, 29474), L.bar("03:19", 29474, 29476, 29474, 29476)]
    + [_up("03:20", 29476, 29478), _up("03:21", 29478, 29480), _up("03:22", 29480, 29482),
       _up("03:23", 29482, 29484), _up("03:24", 29484, 29486), _up("03:25", 29486, 29488),
       _up("03:26", 29488, 29490), _up("03:27", 29490, 29492), _up("03:28", 29492, 29494),
       _up("03:29", 29494, 29496)]
    + [_down("03:30", 29496, 29484), _down("03:31", 29484, 29478),
       L.bar("03:32", 29478, 29479, 29472, 29478)]
    + [_up("03:33", 29478, 29480), _up("03:34", 29480, 29482), _up("03:35", 29482, 29484)]
    + [_down("03:36", 29484, 29480), _down("03:37", 29480, 29477), _down("03:38", 29477, 29473)]
    + [_down("03:39", 29473, 29473), _up("03:40", 29473, 29475), _up("03:41", 29475, 29477)])

# CAUSAL NEGATIVE CONTROL: identical tape except the 03:32 bar does not pierce
# 29474 (low 29478). Without that producer history there is no 3m life.
WITHOUT_3M_REGISTRATION = [
    L.bar("03:32", 29478, 29479, 29478, 29478) if b["timestamp"].endswith("03:32:00+00:00")
    else b for b in NATURAL_3M]

REGISTRATION_ID = (
    "PROTECTED_SWING_REPLACED:CON.F.US.MNQ.Z26:3m:2026-08-19T03:32:00+00:00:low:"
    "29429.75->29474.0:3m:swing_low:29429.8@2026-08-19T01:38:00+00:00->"
    "3m:swing_low:29474@2026-08-19T03:32:00+00:00")
VIOLATION_ID = (
    "PROTECTED_SWING_VIOLATED:CON.F.US.MNQ.Z26:3m:2026-08-19T03:38:00+00:00:low@29474.0:"
    "3m:swing_low:29474@2026-08-19T03:32:00+00:00")
LIFE = {"level": 29474.0, "side": "low", "timeframe": "3m",
        "swing_id": "3m:swing_low:29474",
        "registered_at": "2026-08-19T03:32:00+00:00",
        "source_bar_time": "2026-08-19T03:30:00+00:00",
        "settled_edge_time": "2026-08-19T03:32:00+00:00",
        "occurrence_id": REGISTRATION_ID, "producer_backed": True}
RELEASE = {"owner": "bullish", "level": 29474.0, "side": "low", "source_tf": "3m",
           "swing_id": "3m:swing_low:29474",
           "registered_at": "2026-08-19T03:32:00+00:00",
           "at": "2026-08-19T03:38:00+00:00",
           "source_bar_time": "2026-08-19T03:36:00+00:00",
           "settled_edge_time": "2026-08-19T03:38:00+00:00",
           "occurrence_id": VIOLATION_ID}
EARLIER_1M = ("1m", 29457.0, "2026-08-19T02:56:00+00:00")
HEALTHY = ("03:32", "03:33", "03:34", "03:35", "03:36", "03:37")
STICKY = ("03:39", "03:40", "03:41")


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def _life(structure):
    return (structure["timeframe"], structure["level"], structure["registered_at"])


def _protected_lows(scan):
    lows = ((scan["snapshot"].get("protected_swings") or {}).get("by_timeframe") or {}
            ).get("lows") or {}
    return {tf: (v["level"], v.get("registered_at")) for tf, v in lows.items() if v}


def _run(tmp_path, monkeypatch, ecu, tape, *, skip=()):
    # Each run owns its runtime roots (stance custody, occurrence ledger).
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows, out = list(TA.LATER), {}
    for b in tape:
        rows = rows + [b]
        hhmm = b["timestamp"][11:16]
        if hhmm in skip:
            continue
        scan, payload = H._brain_scan(cycle, calls, rows)
        out[hhmm] = (scan, payload, copy.deepcopy(cycle.stance_memory.recent(1)[-1]))
    return cycle, out


def _ledger_3m(cycle):
    keys = ("event_type", "occurrence_id", "event_time", "source_bar_time",
            "settled_edge_time", "level", "side", "swing_id", "registered_at")
    return [{k: r.get(k) for k in keys} for r in cycle.occurrence_ledger.occurrences()
            if str(r.get("event_type", "")).startswith("PROTECTED_SWING")
            and r.get("source_tf") == "3m"
            and str(r.get("event_time")) >= "2026-08-19T03:05"]


def _decision(scan, payload):
    nc = payload["narrative_continuity"]
    return {"control": nc["control_state"], "dominant": nc["dominant_direction"],
            "leg": nc["active_leg_failure_status"],
            "source": nc["active_leg_structure_source"],
            "structure": nc["active_leg_structure"],
            "transfer": nc["transfer_confirmed"],
            "premise": nc["campaign_premise"],
            "held": (scan["brain_block"]["output"]["current_action"],
                     scan["brain_block"]["output"]["invalidation_level"]),
            "lifecycle": [scan["campaign_lifecycle"]["state"],
                          scan["campaign_lifecycle"]["reason"]],
            "candidate": L._candidate(scan),
            "release": scan["snapshot"]["active_path_state"]["last_invalidated"]}


# ── 1. Registration -> load-bearing -> healthy -> settled 3m violation ──────
@TA.ECU_MODES
def test_natural_3m_load_bearing_life_dies_on_its_settled_3m_close(
        tmp_path, monkeypatch, ecu):
    cycle, out = _run(tmp_path, monkeypatch, ecu, NATURAL_3M)

    # Before the raid the path rests on the 1m 29457@02:56 life.
    scan, payload, _row = out["03:31"]
    bearing = scan["snapshot"]["active_path_state"]["load_bearing_structure"]
    assert _life(bearing) == EARLIER_1M
    assert _protected_lows(scan)["3m"] == (29429.75, "2026-08-19T01:38:00+00:00")

    # 03:32: one settled 3m candle pierced the 3m pivot 29474 and closed back.
    scan, payload, _row = out["03:32"]
    sweep = scan["snapshot"]["liquidity"]["3m"]
    assert (sweep["sweep_detected"], sweep["sweep_direction"],
            sweep["sweep_fact"]["swept_level"]) == (True, "below_low", 29474.0)
    assert scan["snapshot"]["structure"]["3m"]["last_swing_low"] == 29474
    assert scan["snapshot"]["liquidity"]["1m"]["sweep_detected"] is False
    assert _protected_lows(scan) == {"3m": (29474.0, "2026-08-19T03:32:00+00:00"),
                                     "5m": (29429.75, "2026-08-19T01:39:00+00:00"),
                                     "1m": (29457.0, "2026-08-19T02:56:00+00:00")}

    for hhmm in HEALTHY:
        scan, payload, row = out[hhmm]
        path = scan["snapshot"]["active_path_state"]
        bearing = path["load_bearing_structure"]
        assert {k: bearing[k] for k in LIFE} == LIFE, hhmm
        assert bearing["intact"] is True and bearing["last_move_favourable"] is True
        assert (path["owner"], path["status"]) == ("bullish", "active"), hhmm
        nc = payload["narrative_continuity"]
        assert nc["control_state"] == "incumbent_intact", hhmm
        assert nc["dominant_direction"] == "bullish", hhmm
        assert nc["active_leg_failure_status"] == "not_occurred", hhmm
        assert nc["active_leg_structure_source"] == "current_active_path", hhmm
        assert _life(nc["active_leg_structure"]) == _life(LIFE), hhmm
        L._assert_campaign_unbound(nc)
        assert [scan["campaign_lifecycle"]["state"],
                scan["campaign_lifecycle"]["reason"]] == L.ACTIVE, hhmm
        assert _life(row["active_leg_structure"]) == _life(LIFE), hhmm
        L._assert_row_unbound(row)

    # 03:38: the settled 03:36-03:38 3m close 29473 kills exactly that life.
    scan, payload, row = out["03:38"]
    path = scan["snapshot"]["active_path_state"]
    assert {k: path["last_invalidated"][k] for k in RELEASE} == RELEASE
    assert path["load_bearing_structure"] is None
    assert (path["owner"], path["status"]) == ("none", "none")
    lows = _protected_lows(scan)
    assert "3m" not in lows
    assert lows["5m"] == (29429.75, "2026-08-19T01:39:00+00:00"), "5m intact"
    assert lows["1m"] == (29457.0, "2026-08-19T02:56:00+00:00"), "1m intact"
    nc = payload["narrative_continuity"]
    assert nc["control_state"] == "developing_transfer"
    assert nc["dominant_direction"] is None
    assert nc["transfer_confirmed"] is False
    assert nc["same_direction_successor_proof"] is None
    assert nc["active_leg_failure_status"] == "occurred"
    assert nc["prior_active_leg_failure_status"] == "not_occurred"
    assert nc["active_leg_structure_source"] == "retained_prior_leg_row"
    assert _life(nc["active_leg_structure"]) == _life(LIFE)
    assert nc["active_leg_structure"]["intact"] is False
    L._assert_campaign_unbound(nc)
    output = scan["brain_block"]["output"]
    assert (output["current_action"], output["invalidation_level"]) == (
        "stand_down", 29474.0)
    assert [scan["campaign_lifecycle"]["state"],
            scan["campaign_lifecycle"]["reason"]] == L.TRANSFER_UNRESOLVED
    assert L._candidate(scan) == "campaign_lifecycle_refused"
    assert row["active_leg_failure_status"] == "occurred"
    assert _life(row["active_leg_structure"]) == _life(LIFE)
    assert row["active_leg_structure"]["intact"] is False
    L._assert_row_unbound(row)

    # Sticky refusal, including the recovery above 29474 at 03:40-03:41.
    for hhmm in STICKY:
        scan, payload, row = out[hhmm]
        nc = payload["narrative_continuity"]
        assert nc["control_state"] == "developing_transfer", hhmm
        assert nc["dominant_direction"] is None, hhmm
        assert nc["active_leg_failure_status"] == "occurred", hhmm
        assert nc["prior_active_leg_failure_status"] == "occurred", hhmm
        assert nc["active_leg_structure_source"] == "retained_prior_leg_row", hhmm
        assert _life(nc["active_leg_structure"]) == _life(LIFE), hhmm
        L._assert_campaign_unbound(nc)
        assert [scan["campaign_lifecycle"]["state"],
                scan["campaign_lifecycle"]["reason"]] == L.TRANSFER_UNRESOLVED, hhmm
        assert L._candidate(scan) == "campaign_lifecycle_refused", hhmm
        assert scan["brain_block"]["output"]["invalidation_level"] == 29474.0, hhmm
        L._assert_row_unbound(row)
    assert NATURAL_3M[-1]["close"] > 29474.0, "recovered above the dead level"
    records = cycle.campaign_draw_truth.audit_records
    assert len(records) == 1
    assert [r.get("superseded_reason") for r in records if r.get("superseded")] == [
        "campaign_ownership_lost:owner=none:status=none"]
    ledger = _ledger_3m(cycle)
    assert [(r["event_type"], r["occurrence_id"]) for r in ledger] == [
        ("PROTECTED_SWING_REPLACED", REGISTRATION_ID),
        ("PROTECTED_SWING_VIOLATED", VIOLATION_ID)]


# ── 2. Minute scans == skipped 3m-close scan handled by catch-up ───────────
@TA.ECU_MODES
def test_skipped_3m_close_scan_catches_up_to_the_identical_death(
        tmp_path, monkeypatch, ecu):
    minute_cycle, minute = _run(tmp_path / "minute", monkeypatch, ecu, NATURAL_3M)
    skipped_cycle, skipped = _run(tmp_path / "skipped", monkeypatch, ecu, NATURAL_3M,
                                  skip=("03:38",))
    assert "03:38" not in skipped
    # Identical producer history: same 3m registration and violation facts.
    assert _ledger_3m(skipped_cycle) == _ledger_3m(minute_cycle)
    assert [r["occurrence_id"] for r in _ledger_3m(skipped_cycle)] == [
        REGISTRATION_ID, VIOLATION_ID]
    # The first post-death decision is identical: minute 03:38 vs caught-up 03:39.
    first_minute = _decision(*minute["03:38"][:2])
    first_skipped = _decision(*skipped["03:39"][:2])
    assert first_skipped == first_minute
    assert {k: first_skipped["release"][k] for k in RELEASE} == RELEASE
    assert minute["03:38"][1]["narrative_continuity"]["prior_active_leg_failure_status"] \
        == skipped["03:39"][1]["narrative_continuity"]["prior_active_leg_failure_status"] \
        == "not_occurred"
    # And every later decision is identical scan for scan.
    for hhmm in STICKY:
        assert _decision(*skipped[hhmm][:2]) == _decision(*minute[hhmm][:2]), hhmm
    for c in (minute_cycle, skipped_cycle):
        records = c.campaign_draw_truth.audit_records
        assert len(records) == 1
        assert [r.get("superseded_reason") for r in records if r.get("superseded")] == [
            "campaign_ownership_lost:owner=none:status=none"]


# ── 3. Causal negative: the death depends on that producer history ─────────
# Measured without the 03:32 raid: no 3m life is registered, the path keeps
# resting on 1m 29457@02:56, and the SAME 03:36-03:38 closes are not a leg
# death. (The non-raiding 03:32 low 29478 becomes a 1m pivot, so the 03:38
# close contests the path through an opposing 1m break -- the C4-style
# contested-without-death state, never a released life.)
@TA.ECU_MODES
def test_without_the_3m_registration_the_same_closes_are_not_a_leg_death(
        tmp_path, monkeypatch, ecu):
    cycle, out = _run(tmp_path, monkeypatch, ecu, WITHOUT_3M_REGISTRATION)
    scan, payload, _row = out["03:32"]
    assert scan["snapshot"]["liquidity"]["3m"]["sweep_detected"] is False
    assert _protected_lows(scan)["3m"] == (29429.75, "2026-08-19T01:38:00+00:00")
    assert _ledger_3m(cycle) == []
    for hhmm in ("03:32", "03:35", "03:37", "03:38", "03:39", "03:41"):
        scan, payload, _row = out[hhmm]
        path = scan["snapshot"]["active_path_state"]
        assert _life(path["load_bearing_structure"]) == EARLIER_1M, hhmm
        assert path["load_bearing_structure"]["intact"] is True, hhmm
        assert path["last_invalidated"]["occurrence_id"] != VIOLATION_ID, hhmm
        assert path["last_invalidated"]["owner"] == "bearish", hhmm
        nc = payload["narrative_continuity"]
        assert nc["active_leg_failure_status"] == "not_occurred", hhmm
        assert nc["active_leg_structure_source"] == "current_active_path", hhmm
        assert nc["transfer_confirmed"] is False, hhmm
        L._assert_campaign_unbound(nc)
        contested = hhmm >= "03:38"
        assert (path["owner"], path["status"]) == (
            "bullish", "contested" if contested else "active"), hhmm
        assert path["transfer_evidence"]["opposing_structure_break"] is contested, hhmm
        assert nc["control_state"] == (
            "developing_transfer" if contested else "incumbent_intact"), hhmm
        assert nc["dominant_direction"] == "bullish", hhmm
        assert [scan["campaign_lifecycle"]["state"], scan["campaign_lifecycle"]["reason"]] \
            == (L.TRANSFER_UNRESOLVED if contested else L.ACTIVE), hhmm
        assert scan["brain_block"]["output"]["invalidation_level"] == (
            29457.0 if contested else 29429.75), hhmm

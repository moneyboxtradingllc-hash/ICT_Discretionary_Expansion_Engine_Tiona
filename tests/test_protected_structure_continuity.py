"""PHASE 2 -- protected-structure continuity is factual; transfer authority is separate.

A protected high/low must not vanish from the facts merely because local
ownership changed. Neither may its survival, age or side alone become a
campaign transfer. At the frozen parent (357668e) both halves already hold.
These cases pin them on the actual graph so a later change cannot
silently trade one for the other.

* FACT. The producer's current life (`protected_swings.by_timeframe`) keeps
  its original identity -- level, timeframe, swing_id, registered_at, basis --
  across the incumbent's death. It reaches the next Brain's transported
  input in both lanes, beside the authored Phase 1 read.
* AUTHORITY. `narrative_continuity._transfer_proof` requires the NEW owner's
  own intact load-bearing structure. ActivePath binds one only from a
  producer registration/replacement observed while that owner's leg exists
  (`ActivePath._apply`, step 2). A life registered while the incumbent owned
  the tape stays a fact, not the opposing bearing. Whether such a life may
  ever bear is an unratified doctrine question. D3=B/STRICT/
  INDEPENDENT_SUPPORTING_LIFE presupposes "the transfer itself must still
  prove an intact local bearing" and does not decide it. The binder in
  f6e4013 that would answer it is not accepted.

Tape: the archived PROD-20261023-C1 settled 1m bars
(fixtures/session_20261023_settled_tape.json; provenance inside). Brain
responses are CONTROLLED mocks (stand_down only; direction labels chosen
by this test). They prove wiring, never what any model said or would say.
C2 uses the existing synthetic scenario of test_campaign_leg_scope_labels.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import ai_brain.ecu as ECU
import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
from ai_brain.narrative_continuity import _transfer_proof
from broker.luna_candidate_producer import NoCandidate
from live_scan.production_scan_cycle import ProductionScanCycle
from market_state.active_path import (ActivePath, LIQUIDITY_SWEEP,
                                      PROTECTED_SWING_REGISTERED,
                                      STRUCTURE_BREAK)

C = "CON.F.US.MNQ.Z26"
FIXTURE = Path(__file__).parent / "fixtures" / "session_20261023_settled_tape.json"
LIFE_KEYS = ("level", "timeframe", "swing_id", "registered_at", "basis")
#: The producer life the captured question is about, exactly as registered.
FRIDAY_HIGH = {"level": 29263.0, "timeframe": "1m", "swing_id": "1m:swing_high:29263",
               "registered_at": "2026-10-23T16:48:00+00:00",
               "basis": "buy_side_raid_rejected"}
DEATH = ("bullish", "1m", 29195.0, "2026-10-23T17:08:00+00:00")
ORIGIN_AT = "2026-10-23T17:09:00+00:00"


def _cut(hhmm):
    return f"2026-10-23T{hhmm}:00+00:00"


def _tape():
    data = json.loads(FIXTURE.read_text())
    tape = data["tape"]
    digest = hashlib.sha256(json.dumps(tape, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    assert digest == data["tape_canonical_sha256"] and len(tape) == data["bars"]
    return [{**b, "contract": C} for b in sorted(tape, key=lambda b: b["timestamp"])]


TAPE = _tape()


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key))
    monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def _friday_cycle(name="P2-FRIDAY"):
    return ProductionScanCycle(symbol="MNQ", contract_id=C, session_id=name)


def _scan(cycle, hhmm, brain):
    cut = _cut(hhmm)
    rows = [b for b in TAPE if b["timestamp"] <= cut][-300:]
    assert rows[-1]["timestamp"] == cut
    return cycle.scan(rows, now=datetime.fromisoformat(cut) + timedelta(minutes=1),
                      invoke_brain=brain)


def _minutes(start, end):
    t, stop = datetime.fromisoformat(_cut(start)), datetime.fromisoformat(_cut(end))
    while t <= stop:
        yield t.strftime("%H:%M")
        t += timedelta(minutes=1)


def _life(record):
    return {k: (record or {}).get(k) for k in LIFE_KEYS}


def _candidate(scan):
    try:
        RF._produce_candidate(scan)
    except NoCandidate as exc:
        return exc.reason
    return None


def _controlled(output, ordinal, payload):
    """CONTROLLED stand-down response. Calls 1-2 (17:07, 17:08) author bullish,
    later calls bearish; no entry, objective or invalidation is ever proposed."""
    direction = "bullish" if ordinal <= 2 else "bearish"
    return {**output, "narrative_direction": direction,
            "narrative_phase": "continuation" if direction == "bullish" else "reversal",
            "market_story": f"CONTROLLED {direction} read #{ordinal}",
            "allowed_direction": direction,
            "forbidden_direction": "bearish" if direction == "bullish" else "bullish",
            "current_action": "stand_down", "recommended_playbook_family": "none",
            "recommended_tool_family": ["none"], "preferred_playbooks": [],
            "preferred_tools": [], "objective_id": None, "invalidation_id": None,
            "invalidation_level": None, "active_draw": "",
            "campaign_scope_proposal": None}


def _friday_lane(monkeypatch, ecu):
    """Every settled minute 16:40-17:06 brainless, 17:07-17:15 with cognition."""
    cycle = _friday_cycle()
    for hhmm in _minutes("16:40", "17:06"):
        _scan(cycle, hhmm, False)
    calls = []
    RF._mock_current_brain(monkeypatch, calls, output_mutator=_controlled)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    sent = H._capture_transport(monkeypatch)
    scans = {}
    for hhmm in _minutes("17:07", "17:15"):
        scans[hhmm] = _scan(cycle, hhmm, True)
    assert len(calls) == 9
    return cycle, scans, [copy for _, copy in sent]


# ── 1. Friday: the fact survives the ownership change; authority does not ──
@TA.ECU_MODES
def test_friday_retained_high_reaches_next_brain_but_bears_no_transfer(monkeypatch, ecu):
    cycle, scans, sent = _friday_lane(monkeypatch, ecu)
    path_0707 = scans["17:07"]["snapshot"]["active_path_state"]
    assert path_0707["owner"] == "bullish"
    assert path_0707["load_bearing_structure"]["level"] == DEATH[2]
    for hhmm, scan in scans.items():
        # The producer's exact current life, original identity, every minute.
        assert _life(scan["snapshot"]["protected_swings"]["by_timeframe"]["highs"]["1m"]) \
            == FRIDAY_HIGH, hhmm
    for payload in sent:
        # ... and the actual transported input carries the same record.
        assert _life(payload["protected_swings"]["by_timeframe"]["highs"]["1m"]) == FRIDAY_HIGH

    scan = scans["17:15"]
    path = scan["snapshot"]["active_path_state"]
    died = path["last_invalidated"]
    assert (died["owner"], died["source_tf"], died["level"], died["at"]) == DEATH
    assert path["origin"]["proof_family"] == "rejected_raid_reclaim"
    assert path["origin"]["at"] == ORIGIN_AT and path["origin"]["direction"] == "bearish"
    assert (path["owner"], path["status"]) == ("bearish", "active")
    assert path["progression"]["supporting_timeframes"] == ["1m"]
    # Registered at 16:48 while the bullish leg owned the tape: a fact, not
    # the new owner's bearing. The first missing transfer witness is exactly it.
    assert path["load_bearing_structure"] is None
    assert path["progression"]["favourable_ladder"] == []
    assert _transfer_proof(path, "bullish", "bearish") is None

    nc = scan["brain_block"]["narrative_continuity"]
    assert nc["control_state"] != "confirmed_transfer"
    assert nc["transfer_confirmed"] is False and nc["transfer_proof"] is None
    assert scan["campaign_lifecycle"]["state"] != "ACTIVE_DELIVERY"
    assert _candidate(scan) == "campaign_lifecycle_refused"

    # Phase 1 survives: the 17:15 input carries the 17:14 AUTHORED bearish read
    # as observational history, while the guarded continuity stays unconfirmed.
    last = sent[-1]["market_narrative_history"]["last"]
    assert last["status"] == "AVAILABLE" and last["authority"] == "OBSERVATIONAL_ONLY"
    assert last["narrative_direction"] == "bearish"
    assert last["recorded_at_cutoff"] == _cut("17:14")
    assert sent[-1]["narrative_continuity"]["control_state"] != "confirmed_transfer"

    # One registration receipt for the life; nothing re-dated or re-minted.
    receipts = [r for r in cycle.occurrence_ledger.occurrences()
                if r.get("event_type") == PROTECTED_SWING_REGISTERED
                and r.get("swing_id") == FRIDAY_HIGH["swing_id"]
                and r.get("registered_at") == FRIDAY_HIGH["registered_at"]]
    assert len({r["occurrence_id"] for r in receipts}) == 1
    assert receipts[0]["event_time"] == FRIDAY_HIGH["registered_at"]


# ── 2. Same price is not the same life ──────────────────────────────────────
def test_friday_same_price_earlier_life_is_retired_not_current():
    cycle = _friday_cycle()
    for hhmm in _minutes("16:40", "17:15"):
        scan = _scan(cycle, hhmm, False)
    rows = [r for r in cycle.occurrence_ledger.occurrences()
            if r.get("side") == "high" and r.get("level") == 29263.0
            and r.get("source_tf") == "1m"]
    lives = {(r["event_type"], r["registered_at"]) for r in rows}
    # 29263 @16:45 was violated at 16:46; a different life at the same price
    # registered at 16:48. Only the latter is current.
    assert ("PROTECTED_SWING_VIOLATED", _cut("16:45")) in lives
    assert ("PROTECTED_SWING_REGISTERED", _cut("16:48")) in lives
    current = scan["snapshot"]["protected_swings"]["by_timeframe"]["highs"]["1m"]
    assert current["registered_at"] == _cut("16:48") != _cut("16:45")


# ── 3. Restart, duplicate cutoff and continuous prefix agree ────────────────
_PATH_FIELDS = ("owner", "status", "forming_direction", "origin", "load_bearing_structure",
                "last_invalidated", "progression")


def _facts(scan):
    path = scan["snapshot"]["active_path_state"]
    view = {k: copy.deepcopy(path.get(k)) for k in _PATH_FIELDS}
    for key in ("origin", "last_invalidated"):
        if isinstance(view[key], dict):
            view[key].pop("observed_at", None)   # scan-clock stamp, not a market fact
    bt = scan["snapshot"]["protected_swings"]["by_timeframe"]
    return view, {s: {tf: _life(r) for tf, r in (bt.get(s) or {}).items()}
                  for s in ("highs", "lows")}


def test_friday_cold_restart_and_duplicate_cutoff_equal_continuous_prefix(tmp_path,
                                                                          monkeypatch):
    continuous = _friday_cycle("P2-CONT")
    for hhmm in _minutes("16:40", "17:15"):
        cont = _scan(continuous, hhmm, False)
    repeat = _scan(continuous, "17:15", False)          # duplicate cutoff
    monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path / "fresh_process_ledger"))
    cold = _scan(_friday_cycle("P2-COLD"), "17:15", False)   # fresh process
    assert _facts(cont) == _facts(repeat)
    # A fresh process derives the same path authority and the same high-side
    # lives. (Its LOW registry can differ: the production horizon is 300
    # settled minutes, so a cold start cannot see lows its window evicted.
    # That bounded-horizon boundary is pre-existing and not this question.)
    assert _facts(cold)[0] == _facts(cont)[0]
    assert _facts(cold)[1]["highs"] == _facts(cont)[1]["highs"]
    assert _facts(cold)[0]["load_bearing_structure"] is None
    assert _life(_facts(cold)[1]["highs"]["1m"]) == FRIDAY_HIGH


def _context_view(scan):
    snap = scan["snapshot"]
    catalog = snap.get("campaign_premise_catalog") or {}
    # Catalog rows compare as a set: their ORDER can follow earlier scans in the
    # same process (observed across a full-suite shard), and order is not a fact.
    rows = [{k: row.get(k) for k in ("supports", "life_ref", "raids")}
            for row in catalog.get("rows") or []]
    return {"facts": _facts(scan), "session_context": snap.get("session_context"),
            "catalog_rows": sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))}


def test_future_session_bars_offered_as_deep_context_are_never_used(tmp_path, monkeypatch):
    """A later suffix handed to the scan must not reach any 17:15 fact or catalog."""
    def at_1715(tag, deep):
        monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path / tag))
        cut = _cut("17:15")
        rows = [b for b in TAPE if b["timestamp"] <= cut][-300:]
        return _friday_cycle(tag).scan(
            rows, now=datetime.fromisoformat(cut) + timedelta(minutes=1),
            invoke_brain=False, deep_1m=deep)
    later = [b for b in TAPE if b["timestamp"] > _cut("17:15")]
    assert len(later) == 44
    settled = at_1715("settled", [b for b in TAPE if b["timestamp"] <= _cut("17:15")])
    offered = at_1715("future", copy.deepcopy(TAPE))
    assert _context_view(offered) == _context_view(settled)
    assert _life(_facts(offered)[1]["highs"]["1m"]) == FRIDAY_HIGH


# ── 4. C2: the surviving 5m high is transported, never promoted ─────────────
@TA.ECU_MODES
def test_c2_surviving_pre_death_high_is_fact_not_transfer(tmp_path, monkeypatch, ecu):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu)
    sent = H._capture_transport(monkeypatch)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    H._brain_scan(cycle, calls, TA.LATER)
    rows = list(TA.LATER)
    seen_owner = False
    for b in L.SCENARIOS["C2"]:
        rows = rows + [b]
        scan, _ = H._brain_scan(cycle, calls, rows)
        hhmm = b["timestamp"][11:16]
        path = scan["snapshot"]["active_path_state"]
        high = _life(sent[-1][1]["protected_swings"]["by_timeframe"]["highs"]["5m"])
        assert high == {"level": 29500.0, "timeframe": "5m",
                        "swing_id": "5m:swing_high:29500",
                        "registered_at": "2026-08-19T03:04:00+00:00",
                        "basis": "buy_side_raid_rejected"}, hhmm
        if hhmm >= "03:07":
            seen_owner = True
            assert (path["owner"], path["status"]) == ("bearish", "active")
            assert path["last_invalidated"]["at"] == "2026-08-19T03:06:00+00:00"
            assert path["load_bearing_structure"] is None
            nc = scan["brain_block"]["narrative_continuity"]
            assert nc["control_state"] == "developing_transfer"
            assert nc["transfer_proof"] is None
            assert L._candidate(scan) == "campaign_lifecycle_refused"
    assert seen_owner


# ── 5. The existing rule, matched pair: WHEN the producer event is observed ─
def _events(direction, *, birth_before_origin):
    side = "high" if direction == "bearish" else "low"
    sweep = "above_high" if direction == "bearish" else "below_low"
    incumbent = "bullish" if direction == "bearish" else "bearish"
    inc_side = "low" if incumbent == "bullish" else "high"
    inc_sweep = "below_low" if incumbent == "bullish" else "above_high"

    def ev(kind, at, **extra):
        stamp = f"2026-10-23T17:{at:02d}:00+00:00"
        return {"event_type": kind, "contract": "CONTROL", "source_tf": "1m",
                "event_time": stamp, "source_bar_time": stamp, "observed_at": stamp,
                "occurrence_id": f"CONTROL:{kind}:{at}:{extra.get('side', '')}", **extra}

    life = {"side": side, "level": 100.0, "swing_id": f"CONTROL-{side}",
            "registered_at": "2026-10-23T17:%02d:00+00:00" % (2 if birth_before_origin else 7),
            "basis": "control"}
    birth = ev(PROTECTED_SWING_REGISTERED, 2 if birth_before_origin else 7, **life)
    incumbent_life = {"side": inc_side, "level": 50.0, "swing_id": f"CONTROL-{inc_side}",
                      "registered_at": "2026-10-23T17:01:00+00:00", "basis": "control"}
    seq = [ev(LIQUIDITY_SWEEP, 0, sweep_direction=inc_sweep, reclaimed=True),
           ev(STRUCTURE_BREAK, 1, direction=incumbent),
           ev(PROTECTED_SWING_REGISTERED, 1, **incumbent_life)]
    if birth_before_origin:
        seq.append(birth)
    seq += [ev("PROTECTED_SWING_VIOLATED", 4, **incumbent_life),
            ev(LIQUIDITY_SWEEP, 5, sweep_direction=sweep, reclaimed=True),
            ev(STRUCTURE_BREAK, 6, direction=direction)]
    if not birth_before_origin:
        seq.append(birth)
    return seq


@pytest.mark.parametrize("direction", ["bearish", "bullish"])
def test_same_life_bears_only_when_registered_inside_the_new_leg(direction):
    """FICTIONAL symmetric control of existing ActivePath law, both directions."""
    incumbent = "bullish" if direction == "bearish" else "bearish"
    states = {}
    for before in (True, False):
        ap = ActivePath()
        ap.enforce_lifecycle("2026-10-23T17:07:00+00:00", "CONTROL")
        ap.ingest(_events(direction, birth_before_origin=before))
        states[before] = ap.state()
    healthy, retained = states[False], states[True]
    assert healthy["owner"] == retained["owner"] == direction
    assert healthy["load_bearing_structure"]["swing_id"] == f"CONTROL-{'high' if direction == 'bearish' else 'low'}"
    assert _transfer_proof(healthy, incumbent, direction) is not None
    assert retained["load_bearing_structure"] is None
    assert _transfer_proof(retained, incumbent, direction) is None


# ── 6. Progression: a real new event once; replay never ─────────────────────
def test_duplicate_or_replayed_registration_awards_no_progression():
    events = _events("bearish", birth_before_origin=False)
    ap = ActivePath()
    ap.enforce_lifecycle("2026-10-23T17:07:00+00:00", "CONTROL")
    ap.ingest(events)
    once = ap.state()
    assert once["progression"]["favourable_ladder"] == [100.0]
    assert once["progression"]["successive_favourable"] is False
    ap.ingest(copy.deepcopy(events))                  # restart replay / duplicate
    ap.ingest([copy.deepcopy(events[-1])])            # the same registration again
    again = ap.state()
    assert again["progression"] == once["progression"]
    assert again["load_bearing_structure"] == once["load_bearing_structure"]
    # A genuinely new, more favourable producer event advances exactly once.
    lower = {**copy.deepcopy(events[-1]), "event_type": "PROTECTED_SWING_REPLACED",
             "occurrence_id": "CONTROL:REPLACED:8", "level": 99.0,
             "swing_id": "CONTROL-high-2", "registered_at": "2026-10-23T17:08:00+00:00",
             "event_time": "2026-10-23T17:08:00+00:00"}
    ap.ingest([lower, copy.deepcopy(lower)])
    after = ap.state()
    assert after["progression"]["favourable_ladder"] == [100.0, 99.0]
    assert after["progression"]["successive_favourable"] is True
    assert after["load_bearing_structure"]["swing_id"] == "CONTROL-high-2"
    # Replaying the whole history (restart/catch-up) re-awards nothing and
    # cannot re-point the bearing at the superseded older life.
    ap.ingest(copy.deepcopy(events + [lower]))
    replayed = ap.state()
    assert replayed["progression"] == after["progression"]
    assert replayed["load_bearing_structure"] == after["load_bearing_structure"]
    assert replayed["adverse_replacements"] == after["adverse_replacements"] == []
    assert replayed["status"] == after["status"] == "active"

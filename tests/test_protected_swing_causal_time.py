"""PROTECTED-SWING-CAUSAL-TIME-1 — one protected-swing life, one birthday.

THE DEFECT. `ProtectedSwingTracker._update` performed a blind whole-record
assignment, so a fresh raid rejection at a level it was ALREADY protecting
re-stamped `registered_at` to now. Four lifecycle states collapsed into two:
formation and re-affirmation became indistinguishable.

WHY THAT MATTERS BEYOND IDENTITY. `brain_prompt` tells the Brain that
`registered_at` is "WHEN the raid was rejected and the level was born", that a
still-listed level "has not been violated since `registered_at`", and instructs
it to "compare `registered_at` against the current timestamp and say how long
the level has survived". The tracker was resetting exactly that clock. In the
ARCHIVED LIVE PAYLOADS for 2026-08-24 the 3m protected low at 29171.5 reached
the Brain on four consecutive scans with `registered_at` equal to the scan every
time, while the level had been defended since 12:41.

The direction of the error is what makes it expensive: a re-affirmation is a
SECOND raid rejected at the same level -- strengthening evidence -- and it made
the level look YOUNGER. The best-defended levels read as newborn.

MEASURED, before -> after, on two archived tapes:

    2026-08-24   24 of 33 lives re-stamped (worst 18)  ->  0
    2026-08-25    5 of 11 lives re-stamped (worst  5)  ->  0
    occurrence counts, Active Path state               ->  IDENTICAL
    the only published field that changed              ->  registered_at

NO BROKER, NO PROVIDER, NO NETWORK.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed.timeframe_builder import build_timeframes             # noqa: E402
from market_data.snapshot_builder import build_snapshot              # noqa: E402
from market_state.active_path import extract_occurrences             # noqa: E402
from narrative_authority.protected_swings import (                   # noqa: E402
    ProtectedSwingTracker, timeframe_role)

CID = "CON.F.US.MNQ.U26"
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")

#: Every field the record carries, classified. `registered_at` is the ONLY one
#: a re-affirmation could move -- everything else is identity or a per-side
#: constant -- which is why preserving it is the whole fix.
FORMATION_PROVENANCE = ("registered_at",)
IDENTITY_OR_DERIVED = ("level", "timeframe", "role", "swing_id", "basis")


def snap(ts, price, *, low=None, high=None):
    """A snapshot in the shape the real tracker consumes."""
    liq, st = {"1m": {}}, {"1m": {}}
    if low is not None or high is not None:
        liq["1m"] = {"sweep_detected": True, "reclaim_detected": True,
                     "sweep_direction": "below_low" if low is not None
                     else "above_high"}
    if low is not None:
        st["1m"]["last_swing_low"] = low
    if high is not None:
        st["1m"]["last_swing_high"] = high
    return {"timestamp": ts, "liquidity": liq, "structure": st,
            "market": {"current_price": price},
            "timeframes": {"1m": {"last_candle": {"close": price}}}}


def drive(steps):
    """Run the real tracker and return (state_after_each_step, tracker)."""
    tracker = ProtectedSwingTracker()
    out = []
    for ts, price, kw in steps:
        tracker.update(snap(ts, price, **kw))
        out.append(tracker.state())
    return out, tracker


def low_1m(state):
    return ((state.get("by_timeframe") or {}).get("lows") or {}).get("1m")


def tape(day):
    seen = {}
    for f in sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                s = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        for c in ((s.get("timeframes") or {}).get("1m") or {}).get(
                "recent_candles") or []:
            if c.get("timestamp"):
                seen[str(c["timestamp"])] = c
    return [seen[k] for k in sorted(seen)]


def replay(bars, *, upto=None, tracker=None, min_bars=30):
    """Canonical growing-window rebuild, carrying the tracker across steps."""
    tracker = tracker or ProtectedSwingTracker()
    prior, rows = {}, []
    for end in range(min_bars, len(bars) + 1):
        w = bars[:end]
        at = str(w[-1]["timestamp"])
        if upto and at > upto:
            break
        s = build_snapshot(build_timeframes(w), ref_timestamp=at, symbol="MNQ",
                           swing_tracker=tracker, contract_id=CID,
                           execution_price=None)
        rows.extend(extract_occurrences(s, prior, CID))
        prior = ((s.get("protected_swings") or {}).get("by_timeframe") or prior)
    return prior, rows, tracker


@pytest.fixture(scope="module")
def real():
    bars = tape("20260825")
    if len(bars) < 40:
        pytest.skip("archived 1m tape absent")
    return bars


X = 29145.5


# ══ THE FOUR LIFECYCLE STATES ═══════════════════════════════════════════════
class TestLifecycleStatesAreDistinguished:

    def test_formation_assigns_a_birthday_once(self):
        states, _t = drive([("2026-08-25T13:10:00+00:00", X + 20, {"low": X})])
        rec = low_1m(states[0])
        assert rec["level"] == X
        assert rec["registered_at"] == "2026-08-25T13:10:00+00:00"

    def test_reaffirmation_does_not_move_the_birthday(self):
        """THE DEFECT, in one assertion. A second rejection at the same live
        level is stronger evidence -- it may not make the level younger."""
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),
            ("2026-08-25T13:14:00+00:00", X + 18, {"low": X}),
            ("2026-08-25T13:19:00+00:00", X + 22, {"low": X}),
        ])
        for s in states:
            assert low_1m(s)["registered_at"] == "2026-08-25T13:10:00+00:00"

    def test_many_reaffirmations_keep_the_original(self):
        steps = [("2026-08-25T13:10:00+00:00", X + 20, {"low": X})]
        steps += [(f"2026-08-25T13:{m}:00+00:00", X + 15, {"low": X})
                  for m in range(11, 40)]
        states, _t = drive(steps)
        assert {low_1m(s)["registered_at"] for s in states} == \
            {"2026-08-25T13:10:00+00:00"}

    def test_replacement_at_a_different_level_is_a_new_life(self):
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),
            ("2026-08-25T13:20:00+00:00", X + 30, {"low": X + 10}),
        ])
        assert low_1m(states[0])["registered_at"] == "2026-08-25T13:10:00+00:00"
        assert low_1m(states[1])["registered_at"] == "2026-08-25T13:20:00+00:00"
        assert low_1m(states[1])["level"] == X + 10

    def test_violation_ends_the_life(self):
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),
            ("2026-08-25T13:20:00+00:00", X - 60, {}),
        ])
        assert low_1m(states[0]) is not None
        assert low_1m(states[1]) is None

    def test_highs_obey_the_same_law(self):
        """The two sides share one implementation; proving one is not proving
        both, and a copy-paste divergence here would be invisible."""
        H = 29500.0
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", H - 20, {"high": H}),
            ("2026-08-25T13:15:00+00:00", H - 18, {"high": H}),
        ])
        highs = [((s.get("by_timeframe") or {}).get("highs") or {})["1m"]
                 for s in states]
        assert {h["registered_at"] for h in highs} == {"2026-08-25T13:10:00+00:00"}


# ══ A NEW LIFE AT THE SAME PRICE ════════════════════════════════════════════
class TestSamePriceNewLife:
    """Preserving formation time through re-affirmation must NOT extend a
    birthday across a DEATH. This is the property that lets
    (swing_id, registered_at) become identity in 1B."""

    @pytest.fixture(scope="class")
    def lives(self):
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),    # life A born
            ("2026-08-25T13:11:00+00:00", X + 15, {}),
            ("2026-08-25T13:20:00+00:00", X - 60, {}),            # A dies
            ("2026-08-25T13:30:00+00:00", X + 20, {"low": X}),    # life B born
            ("2026-08-25T13:31:00+00:00", X + 18, {}),
        ])
        return states

    def test_the_level_really_did_die_in_between(self, lives):
        assert low_1m(lives[2]) is None

    def test_both_lives_share_a_swing_id(self, lives):
        assert low_1m(lives[0])["swing_id"] == low_1m(lives[3])["swing_id"]

    def test_but_they_do_not_share_a_birthday(self, lives):
        assert low_1m(lives[0])["registered_at"] == "2026-08-25T13:10:00+00:00"
        assert low_1m(lives[3])["registered_at"] == "2026-08-25T13:30:00+00:00"

    def test_the_pair_is_therefore_a_usable_identity(self, lives):
        a = (low_1m(lives[0])["swing_id"], low_1m(lives[0])["registered_at"])
        b = (low_1m(lives[3])["swing_id"], low_1m(lives[3])["registered_at"])
        assert a[0] == b[0] and a != b


# ══ THE RECORD'S FIELD SEMANTICS ════════════════════════════════════════════
class TestFieldSemantics:

    def test_reaffirmation_changes_nothing_at_all(self):
        """The field audit as a regression: `registered_at` was the only field a
        re-affirmation could move, so a correctly handled one is a no-op. If a
        mutable field is ever added to this record, this fails and forces the
        preserve/overwrite decision to be made deliberately."""
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),
            ("2026-08-25T13:15:00+00:00", X + 18, {"low": X}),
        ])
        assert low_1m(states[0]) == low_1m(states[1])

    def test_the_record_carries_exactly_the_audited_fields(self):
        states, _t = drive([("2026-08-25T13:10:00+00:00", X + 20, {"low": X})])
        assert set(low_1m(states[0])) == set(FORMATION_PROVENANCE) | \
            set(IDENTITY_OR_DERIVED)

    def test_basis_is_a_per_side_constant(self):
        """Audited, not assumed: `basis` is fixed by which side's slot this is,
        so it cannot differ between two registrations in one slot -- which is
        why it needs no preserve-or-update rule."""
        states, _t = drive([
            ("2026-08-25T13:10:00+00:00", X + 20, {"low": X}),
            ("2026-08-25T13:15:00+00:00", X + 18, {"low": X}),
            ("2026-08-25T13:20:00+00:00", X + 30, {"low": X + 10}),
        ])
        assert {low_1m(s)["basis"] for s in states} == {"sell_side_raid_rejected"}

    def test_identity_fields_are_unchanged_by_this_unit(self):
        """`level` rounding, `swing_id` spelling and `role` are load-bearing for
        consumers across brain_input, the invalidation catalog and memory."""
        states, _t = drive([("2026-08-25T13:10:00+00:00", X + 20, {"low": X})])
        rec = low_1m(states[0])
        assert rec["swing_id"] == f"1m:swing_low:{round(X, 4):g}"
        assert rec["level"] == round(X, 4)
        assert rec["role"] == timeframe_role("1m")
        assert rec["timeframe"] == "1m"


# ══ THE LIVE PERCEPTION REGRESSION ══════════════════════════════════════════
class TestLunaCanNowJudgeSurvival:
    """`brain_prompt` asks the Brain to compute survival duration as
    (now - registered_at). Before this unit that answer was forced toward zero
    on a re-affirmed level."""

    def test_survival_duration_grows_while_the_level_lives(self):
        steps = [("2026-08-25T13:10:00+00:00", X + 20, {"low": X})]
        steps += [(f"2026-08-25T13:{m}:00+00:00", X + 15,
                   {"low": X} if m % 4 == 0 else {})
                  for m in range(11, 50)]
        states, _t = drive(steps)
        ages = []
        for (ts, _p, _k), s in zip(steps, states):
            rec = low_1m(s)
            assert rec is not None, "the level should not have been violated"
            ages.append((datetime.fromisoformat(ts) -
                         datetime.fromisoformat(rec["registered_at"])).total_seconds())
        assert ages[0] == 0
        assert all(b >= a for a, b in zip(ages, ages[1:])), "age went backwards"
        assert ages[-1] >= 38 * 60

    def test_the_2026_08_24_specimen_is_repaired(self):
        """The exact level that reached the live Brain misreported. It was
        defended from 12:41; the payload said it was born on the current scan."""
        bars = tape("20260824")
        if len(bars) < 60:
            pytest.skip("independent archive absent")
        tracker = ProtectedSwingTracker()
        prior, seen = {}, []
        for end in range(30, len(bars) + 1):
            w = bars[:end]
            at = str(w[-1]["timestamp"])
            s = build_snapshot(build_timeframes(w), ref_timestamp=at,
                               symbol="MNQ", swing_tracker=tracker,
                               contract_id=CID, execution_price=None)
            extract_occurrences(s, prior, CID)
            by = (s.get("protected_swings") or {}).get("by_timeframe") or {}
            rec = (by.get("lows") or {}).get("3m") or {}
            if rec.get("swing_id") == "3m:swing_low:29171.5":
                seen.append((at, rec["registered_at"]))
            prior = by or prior
        if not seen:
            pytest.skip("the 29171.5 specimen is absent from this archive")
        assert len({r for _s, r in seen}) == 1, "the life was re-stamped"
        oldest = max((datetime.fromisoformat(s) - datetime.fromisoformat(r))
                     for s, r in seen).total_seconds() / 60
        assert oldest > 18, ("the Brain still cannot see a level older than the "
                            "pre-fix ceiling")


# ══ THE REAL TAPE ═══════════════════════════════════════════════════════════
class TestOnTheRealTape:

    def test_no_living_swing_is_restamped(self, real):
        """A slot VACANCY ends a life, so state is cleared on it -- otherwise a
        genuinely new life at a repeated price reads as a re-stamp."""
        tracker = ProtectedSwingTracker()
        prior, live, restamped = {}, {}, []
        for end in range(30, len(real) + 1):
            w = real[:end]
            at = str(w[-1]["timestamp"])
            s = build_snapshot(build_timeframes(w), ref_timestamp=at,
                               symbol="MNQ", swing_tracker=tracker,
                               contract_id=CID, execution_price=None)
            extract_occurrences(s, prior, CID)
            by = (s.get("protected_swings") or {}).get("by_timeframe") or {}
            for side in ("lows", "highs"):
                block = by.get(side) or {}
                for tf, rec in block.items():
                    slot, sid = (side, tf), rec["swing_id"]
                    was = live.get(slot)
                    if was and was[0] == sid and was[1] != rec["registered_at"]:
                        restamped.append((at, sid, was[1], rec["registered_at"]))
                    live[slot] = (sid, rec["registered_at"])
                for slot in [k for k in live if k[0] == side and k[1] not in block]:
                    live.pop(slot, None)
            prior = by or prior
        assert restamped == [], restamped

    def test_occurrence_emission_is_unchanged(self, real):
        """A re-affirmation never emitted a REGISTERED or REPLACED occurrence
        before this unit -- `extract_occurrences` compares levels, and the level
        did not move -- and it must not start now. Measured identical on both
        archived tapes."""
        _prior, rows, _t = replay(real)
        counts = {}
        for r in rows:
            counts[r["event_type"]] = counts.get(r["event_type"], 0) + 1
        assert counts == {"LIQUIDITY_SWEEP": 23, "STRUCTURE_BREAK": 44,
                          "PROTECTED_SWING_REGISTERED": 8,
                          "PROTECTED_SWING_REPLACED": 4,
                          "PROTECTED_SWING_VIOLATED": 5}


# ══ PROCESS START TIME IS STILL NOT A VARIABLE ══════════════════════════════
class TestRecoveryEquivalence:
    """A birthday derived from the tape must not depend on when a process
    started looking at the tape."""

    def test_continuous_and_late_recovery_agree(self, real):
        from market_state import session_recovery as SR
        continuous, _r, _t = replay(real)
        recovered = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                               session_start="2026-08-25T13:00:00+00:00")
        assert recovered["sufficient"]
        assert recovered["protected_swings"] == continuous

    def test_every_handoff_agrees_with_the_continuous_run(self, real):
        from market_state import session_recovery as SR
        for h in ("13:31", "14:00", "14:15", "14:31", "14:47"):
            at = f"2026-08-25T{h}:00+00:00"
            continuous, _r, _t = replay(real, upto=at)
            recovered = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                                   session_start="2026-08-25T13:00:00+00:00",
                                   handoff=at)
            assert recovered["protected_swings"] == continuous, at

    def test_restart_after_recovery_keeps_the_same_birthdays(self, real):
        """Process A recovers and runs on; process B starts cold later. Neither
        may invent a different birthday for the same swing life."""
        from market_state import session_recovery as SR
        a = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start="2026-08-25T13:00:00+00:00",
                       handoff="2026-08-25T14:30:00+00:00")
        b = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start="2026-08-25T13:00:00+00:00",
                       handoff="2026-08-25T14:47:00+00:00")
        continuous, _r, _t = replay(real)
        assert a["sufficient"] and b["sufficient"]
        assert b["protected_swings"] == continuous
        for side in ("lows", "highs"):
            early = (a["protected_swings"] or {}).get(side) or {}
            late = (b["protected_swings"] or {}).get(side) or {}
            for tf, rec in early.items():
                other = late.get(tf)
                if other and other["swing_id"] == rec["swing_id"]:
                    assert other["registered_at"] == rec["registered_at"], tf

    def test_the_transition_provenance_is_start_time_independent(self, real):
        from market_state import session_recovery as SR
        early = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                           session_start="2026-08-25T13:00:00+00:00",
                           handoff="2026-08-25T14:47:00+00:00")
        late = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                          session_start="2026-08-25T13:00:00+00:00")
        assert SR.transition_provenance(early) == SR.transition_provenance(late)


# ══ NOTHING ELSE MOVED ══════════════════════════════════════════════════════
class TestScopeIsHeld:

    def test_qualification_and_violation_rules_are_untouched(self):
        import inspect
        src = inspect.getsource(ProtectedSwingTracker._update)
        # registration still requires sweep AND reclaim
        assert 'liq.get("sweep_detected") and liq.get("reclaim_detected")' in src
        # violation is still a buffered close beyond the level
        assert "_violation_buffer_pct()" in src
        assert 'price > rec["level"] + buf' in src
        assert 'price < rec["level"] - buf' in src

    def test_the_tracker_reaches_no_broker_or_provider(self):
        import inspect

        from narrative_authority import protected_swings as PS
        src = inspect.getsource(PS).lower()
        for banned in ("requests", "topstepx", "place_order", "modify_order",
                       "socket", "openai", "occurrenceledger"):
            assert banned not in src, banned

    def test_category_b_identity_is_still_not_minted(self):
        """PROTECTED-SWING-CAUSAL-TIME-1 makes the provenance TRUE. Turning it
        into a key is CAUSAL-OCCURRENCE-IDENTITY-1B, and must not have leaked
        backwards into this unit."""
        from market_data import causal_identity as CI
        occ = {"event_type": CI.PROTECTED_SWING_REGISTERED, "contract": CID,
               "source_tf": "1m", "swing_id": "1m:swing_low:29145.5",
               "registered_at": "2026-08-25T13:10:00+00:00"}
        assert CI.causal_event_key(occ) is None
        assert CI.refusal_reason(occ) == CI.CATEGORY_B_BLOCKED

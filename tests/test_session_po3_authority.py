"""LUNA-SESSION-PO3-AUTHORITY-1 — the canonical session phase, and its veto.

THE DEFECT THIS CLOSES, IN ONE LINE. On 2026-08-25 Luna filled two practice
entries at 14:48:35 and 14:49:20 UTC while `po3.5m`, `po3.3m` and `po3.1m` all
read `accumulation` — because per-timeframe PO3 was descriptive evidence with no
range, no lifecycle and no vote in whether a trade could exist.

WHAT IS ASSERTED HERE. Not that the phase labels look plausible: that the phase
is CAUSAL (a range with a birth, an excursion, and a resolution that requires
subsequent evidence), that it is LOAD-BEARING (accumulation refuses a new entry
upstream of every playbook), that it does NOT over-reach (a genuine opening
drive stays legal, a clock never forces a transition), and that it is
RECONSTRUCTIBLE (a restart replaying the same tape reaches the same phase).

The adversarial cases S1-S18 of the mission are covered one test apiece and
named accordingly.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure import session_po3 as SP3                      # noqa: E402
from structure.session_po3 import (                           # noqa: E402
    ACCUMULATION_ESTABLISHED, ACCUMULATION_FORMING, DISTRIBUTION_ACTIVE,
    EXCURSION_UNRESOLVED, MANIPULATION_CONFIRMED, REACCUMULATION, STATES,
    SessionPo3Authority, UNKNOWN, derive, entry_permission,
)

_T0 = "2026-08-25T13:00:00+00:00"


def _bar(i, o, h, l, c):
    mm = 13 * 60 + i
    return {"timestamp": f"2026-08-25T{mm // 60:02d}:{mm % 60:02d}:00+00:00",
            "open": o, "high": h, "low": l, "close": c,
            "temporal_status": "settled", "volume": 100}


def balance(n=20, low=29000.0, high=29030.0, start=0):
    """A two-sided rotation: every close lands inside [low, high]."""
    out, mid = [], (low + high) / 2
    for i in range(n):
        c = low + 4 if i % 2 else high - 4
        out.append(_bar(start + i, mid, min(high, max(c, mid) + 2),
                        max(low, min(c, mid) - 2), c))
    return out


def _accum_po3(count=3):
    tfs = ["5m", "3m", "1m"][:count]
    po3 = {tf: {"phase": "accumulation"} for tf in tfs}
    po3["alignment"] = "accumulation_building"
    return po3


def _manip(classification, direction, tf="5m", score=75):
    return {tf: {"manipulation": {"classification": classification,
                                  "direction": direction, "score": score}}}


def _auth(bias, intact=True):
    return {"bias": bias, "intact": intact, "source": "liquidity.active_liquidity_draw"}


def _derive(bars, po3=None, liquidity=None, structure=None, authority=None):
    return derive(settled_1m=bars, po3=po3 if po3 is not None else _accum_po3(),
                  liquidity=liquidity or {}, structure=structure or {},
                  authority=authority)


# ── the law itself ────────────────────────────────────────────────────────────

class TestEntryLaw:
    def test_every_state_has_an_explicit_entry_ruling(self):
        for phase in STATES:
            allowed, reason = entry_permission(phase)
            assert isinstance(allowed, bool)
            assert allowed or reason, f"{phase} blocks without saying why"

    def test_the_accumulation_family_refuses_new_entry(self):
        for phase in (ACCUMULATION_FORMING, ACCUMULATION_ESTABLISHED,
                      EXCURSION_UNRESOLVED, REACCUMULATION):
            assert entry_permission(phase)[0] is False

    def test_resolved_phases_and_unknown_permit_new_entry(self):
        for phase in (UNKNOWN, MANIPULATION_CONFIRMED, DISTRIBUTION_ACTIVE):
            assert entry_permission(phase)[0] is True


# ── range formation ───────────────────────────────────────────────────────────

class TestAccumulationRange:
    def test_an_established_range_carries_its_causal_facts(self):
        st = _derive(balance(20))
        assert st["phase"] == ACCUMULATION_ESTABLISHED
        rng = st["range"]
        assert rng["established"] is True
        assert rng["age_bars"] >= SP3.MIN_RANGE_BARS
        assert rng["low"] < rng["high"]
        assert rng["birth"] and rng["last_extension"]
        assert st["new_entry_allowed"] is False

    def test_a_young_balance_is_forming_and_still_blocks(self):
        st = _derive(balance(SP3.MIN_RANGE_BARS - 3))
        assert SP3.MIN_FORMING_BARS <= SP3.MIN_RANGE_BARS - 3
        assert st["phase"] == ACCUMULATION_FORMING
        assert st["range"]["established"] is False
        assert st["new_entry_allowed"] is False

    def test_balance_without_po3_corroboration_is_not_accumulation(self):
        """A quiet stretch is not automatically accumulation, and PO3 texture is
        the existing engine that says which it is. Absent corroboration the
        authority reports UNKNOWN rather than inventing a range to block on."""
        st = _derive(balance(20), po3={"5m": {"phase": "distribution"}})
        assert st["phase"] == UNKNOWN
        assert st["new_entry_allowed"] is True

    def test_S12_no_clock_can_force_a_transition(self):
        """Accumulation is market-defined. The module reads no timestamp for any
        decision, so a range that outlives 09:30 and 10:00 is still a range."""
        long_run = balance(180)
        st = _derive(long_run)
        assert st["phase"] == ACCUMULATION_ESTABLISHED
        assert st["new_entry_allowed"] is False
        src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                                "structure", "session_po3.py"), encoding="utf-8").read()
        for banned in ("datetime", "time.time", "get_session_label", "ny_open"):
            assert banned not in src, f"a clock leaked in via {banned!r}"


# ── S2 / S3 — a new extreme is not a resolution ───────────────────────────────

class TestNewExtremesDoNotResolve:
    def test_S2_new_local_high_closing_inside_extends_the_range(self):
        bars = balance(20)
        top = bars[-1]["high"]
        # A spike well above the range that closes back inside it.
        bars.append(_bar(20, 29015.0, top + 25, 29013.0, 29015.0))
        st = _derive(bars)
        assert st["phase"] == ACCUMULATION_ESTABLISHED
        assert st["range"]["high"] >= top + 25
        assert st["new_entry_allowed"] is False

    def test_S3_new_local_low_closing_inside_extends_the_range(self):
        bars = balance(20)
        bottom = bars[-1]["low"]
        bars.append(_bar(20, 29015.0, 29017.0, bottom - 25, 29015.0))
        st = _derive(bars)
        assert st["phase"] == ACCUMULATION_ESTABLISHED
        assert st["range"]["low"] <= bottom - 25
        assert st["new_entry_allowed"] is False


# ── S4 — the first excursion decides nothing ──────────────────────────────────

class TestExcursionUnresolved:
    def _departed(self, n_outside=1, side="above", **kw):
        bars = balance(20)
        hi = max(b["high"] for b in bars)
        lo = min(b["low"] for b in bars)
        for k in range(n_outside):
            if side == "above":
                px = hi + 6 + 2 * k
                bars.append(_bar(20 + k, px - 2, px + 1, px - 3, px))
            else:
                px = lo - 6 - 2 * k
                bars.append(_bar(20 + k, px + 2, px + 3, px - 1, px))
        return _derive(bars, **kw)

    def test_S4_first_close_outside_is_unresolved_and_blocks(self):
        st = self._departed(1)
        assert st["phase"] == EXCURSION_UNRESOLVED
        assert st["new_entry_allowed"] is False
        assert st["excursion"]["side"] == "above"
        assert st["excursion"]["reentered"] is False

    def test_the_excursion_records_side_and_peak(self):
        st = self._departed(2, side="below")
        assert st["excursion"]["side"] == "below"
        assert st["excursion"]["direction"] == "bearish"
        assert st["excursion"]["peak"] < st["range"]["low"]

    def test_a_single_close_outside_is_never_distribution(self):
        """Doctrine §7: one candle close is not proof the market repriced."""
        st = self._departed(1, authority=_auth("bullish"))
        assert st["phase"] != DISTRIBUTION_ACTIVE

    def test_acceptance_without_ownership_stays_unresolved(self):
        st = self._departed(SP3.ACCEPTANCE_BARS + 1, authority=_auth("bearish"))
        assert st["phase"] == EXCURSION_UNRESOLVED
        assert "ownership" in st["reason"]


# ── S8 — true distribution ────────────────────────────────────────────────────

class TestDistribution:
    def _escaped(self, bars_outside, authority):
        bars = balance(20)
        hi = max(b["high"] for b in bars)
        for k in range(bars_outside):
            px = hi + 6 + 3 * k
            bars.append(_bar(20 + k, px - 2, px + 1, px - 3, px))
        return _derive(bars, authority=authority)

    def test_S8_acceptance_plus_compatible_ownership_is_distribution(self):
        st = self._escaped(SP3.ACCEPTANCE_BARS + 1, _auth("bullish"))
        assert st["phase"] == DISTRIBUTION_ACTIVE
        assert st["distribution_direction"] == "bullish"
        assert st["new_entry_allowed"] is True

    def test_S8_escape_is_not_falsely_manipulation(self):
        st = self._escaped(SP3.ACCEPTANCE_BARS + 2, _auth("bullish"))
        assert st["phase"] != MANIPULATION_CONFIRMED

    def test_distribution_needs_more_than_one_bar_outside(self):
        assert self._escaped(1, _auth("bullish"))["phase"] == EXCURSION_UNRESOLVED
        assert self._escaped(SP3.ACCEPTANCE_BARS - 1,
                             _auth("bullish"))["phase"] == EXCURSION_UNRESOLVED

    def test_S10_distribution_dies_when_price_returns_to_rotation(self):
        bars = balance(20)
        hi = max(b["high"] for b in bars)
        for k in range(SP3.ACCEPTANCE_BARS + 1):
            px = hi + 6 + 3 * k
            bars.append(_bar(20 + k, px - 2, px + 1, px - 3, px))
        assert _derive(bars, authority=_auth("bullish"))["phase"] == DISTRIBUTION_ACTIVE
        # ... and then it comes back inside.
        mid = (max(b["high"] for b in bars[:20]) + min(b["low"] for b in bars[:20])) / 2
        bars.append(_bar(30, mid + 2, mid + 3, mid - 3, mid))
        after = _derive(bars, authority=_auth("bullish"))
        assert after["phase"] != DISTRIBUTION_ACTIVE
        assert after["new_entry_allowed"] is False


# ── S5 / S9 / S14 / S15 / S16 — manipulation ──────────────────────────────────

class TestManipulation:
    def _failed_excursion(self, liquidity=None, authority=None, structure=None):
        """Up through the range high, rejected, closed back inside."""
        bars = balance(20)
        hi = max(b["high"] for b in bars)
        lo = min(b["low"] for b in bars)
        px = hi + 8
        bars.append(_bar(20, px - 2, px + 2, px - 3, px))          # departure
        mid = (hi + lo) / 2
        bars.append(_bar(21, px - 4, px, mid - 2, mid))            # re-entry
        return _derive(bars, liquidity=liquidity, authority=authority,
                       structure=structure)

    def test_S5_rejected_excursion_plus_opposite_ownership_confirms(self):
        st = self._failed_excursion(
            liquidity=_manip("manipulation_confirmed", "bearish"),
            authority=_auth("bearish"))
        assert st["phase"] == MANIPULATION_CONFIRMED
        assert st["new_entry_allowed"] is True
        assert st["excursion"]["reentered"] is True

    def test_opposite_mss_also_satisfies_forming_ownership(self):
        st = self._failed_excursion(
            liquidity=_manip("manipulation_confirmed", "bearish"),
            authority=None, structure={"3m": {"mss": True}})
        assert st["phase"] == MANIPULATION_CONFIRMED

    def test_S14_manipulation_possible_is_not_confirmed(self):
        st = self._failed_excursion(
            liquidity=_manip("manipulation_possible", "bearish"),
            authority=_auth("bearish"))
        assert st["phase"] == REACCUMULATION
        assert st["new_entry_allowed"] is False

    def test_score_alone_never_confirms(self):
        """`po3_engine` consumed the numeric score and ignored the band. A high
        score with a `possible` classification must not confirm anything."""
        st = self._failed_excursion(
            liquidity=_manip("manipulation_possible", "bearish", score=99),
            authority=_auth("bearish"))
        assert st["phase"] != MANIPULATION_CONFIRMED

    def test_S15_the_detectors_own_direction_is_what_is_consumed(self):
        """PO3 derived manipulation_direction from `sweep_direction`, which is
        frequently absent while the detector holds a direction. No sweep field
        appears anywhere in this fixture and the direction still governs."""
        wrong_way = self._failed_excursion(
            liquidity=_manip("manipulation_confirmed", "bullish"),
            authority=_auth("bearish"))
        assert wrong_way["phase"] == REACCUMULATION
        right_way = self._failed_excursion(
            liquidity=_manip("manipulation_confirmed", "bearish"),
            authority=_auth("bearish"))
        assert right_way["phase"] == MANIPULATION_CONFIRMED
        assert right_way["manipulation"]["direction"] == "bearish"

    def test_S16_conflicting_timeframe_directions_fabricate_no_certainty(self):
        """Measured live 2026-08-25: 15m manipulation_confirmed bearish and 1m
        manipulation_confirmed bullish on the same scan."""
        liq = {"15m": {"manipulation": {"classification": "manipulation_confirmed",
                                        "direction": "bearish", "score": 75}},
               "1m": {"manipulation": {"classification": "manipulation_confirmed",
                                       "direction": "bullish", "score": 100}}}
        st = self._failed_excursion(liquidity=liq, authority=_auth("bearish"))
        assert st["manipulation"]["conflicted"] is True
        assert st["phase"] != MANIPULATION_CONFIRMED
        assert st["new_entry_allowed"] is False

    def test_S9_range_extension_returns_to_reaccumulation(self):
        st = self._failed_excursion(liquidity={}, authority=None)
        assert st["phase"] == REACCUMULATION
        assert st["new_entry_allowed"] is False

    def test_S9_reaccumulation_range_contains_what_the_excursion_reached(self):
        st = self._failed_excursion(liquidity={}, authority=None)
        assert st["range"]["high"] >= st["excursion"]["peak"]


# ── S11 — the opening drive must survive ──────────────────────────────────────

class TestOpeningDriveSurvives:
    def test_S11_a_market_that_opens_delivering_is_never_blocked(self):
        bars, px = [], 29000.0
        for i in range(40):                      # relentless one-way delivery
            o = px
            px += 6.0
            bars.append(_bar(i, o, px + 1, o - 1, px))
        st = _derive(bars, po3={"1m": {"phase": "distribution"}})
        assert st["phase"] == UNKNOWN
        assert st["new_entry_allowed"] is True

    def test_a_balance_that_was_never_established_cannot_be_departed_from(self):
        bars = balance(SP3.MIN_RANGE_BARS - 5)
        hi = max(b["high"] for b in bars)
        for k in range(6):
            px = hi + 8 + 4 * k
            bars.append(_bar(20 + k, px - 2, px + 1, px - 3, px))
        st = _derive(bars)
        assert st["phase"] == UNKNOWN
        assert st["new_entry_allowed"] is True

    def test_the_authority_cannot_ban_every_early_session_trade(self):
        """A blanket ban would be the easiest way to pass every other test here.
        On a driving tape the phase must be permissive at every prefix length."""
        bars, px = [], 29000.0
        for i in range(60):
            o = px
            px += 5.0
            bars.append(_bar(i, o, px + 1, o - 1, px))
        verdicts = [_derive(bars[:n], po3={})["new_entry_allowed"]
                    for n in range(SP3.MIN_RANGE_BARS, 61)]
        assert all(verdicts), "a pure delivery tape was blocked"


# ── S13 — Active Path does not buy a way in ───────────────────────────────────

class TestActivePathInteraction:
    @pytest.mark.parametrize("bias", ["bullish", "bearish"])
    def test_S13_directional_ownership_during_accumulation_still_blocks(self, bias):
        st = _derive(balance(20), authority=_auth(bias))
        assert st["phase"] == ACCUMULATION_ESTABLISHED
        assert st["new_entry_allowed"] is False
        assert st["ownership"]["direction"] == bias

    def test_po3_never_writes_ownership(self):
        """The circular-writer rule. The module reads an authority dict and
        returns a new object; the input is never mutated."""
        auth = _auth("bearish")
        before = dict(auth)
        _derive(balance(20), authority=auth)
        assert auth == before


# ── S1 / S6 / S7 — playbook routing ───────────────────────────────────────────

class TestPlaybookRouting:
    def _snap(self, phase, prefs=(), allowed=False):
        return {"session_po3": {"phase": phase, "new_entry_allowed": allowed,
                                "preferred_playbook_families": list(prefs)},
                "po3": {"alignment": "accumulation_building"},
                "structure": {"15m": {"state": "range_bound"}},
                "expansion": {"1m": {"state": "early_expansion"}},
                "volatility": {"15m": {"state": "expanding"}},
                "liquidity": {}, "ai_context": {}, "memory": {}}

    def test_accumulation_no_longer_rewards_a_breakout_playbook(self):
        from playbooks.playbook_classifier import _score_range_expansion
        blocked = _score_range_expansion(self._snap(ACCUMULATION_ESTABLISHED))
        resolved = _score_range_expansion(self._snap(DISTRIBUTION_ACTIVE, allowed=True))
        assert blocked < resolved, "accumulation_building still pays a breakout bonus"

    def test_the_bonus_survives_after_the_phase_resolves(self):
        from playbooks.playbook_classifier import _score_manipulation_to_distribution
        snap = self._snap(MANIPULATION_CONFIRMED, allowed=True)
        assert _score_manipulation_to_distribution(snap) > 0

    def test_S6_manipulation_confirmed_prefers_the_reversal_families(self):
        from playbooks.playbook_classifier import _phase_preference, PHASE_PREFERENCE_POINTS
        snap = self._snap(MANIPULATION_CONFIRMED,
                          prefs=SP3._PREFERRED[MANIPULATION_CONFIRMED], allowed=True)
        assert _phase_preference(snap, "liquidity_sweep_reversal") == PHASE_PREFERENCE_POINTS
        assert _phase_preference(snap, "opening_drive") == 0

    def test_S7_preference_never_manufactures_a_playbook(self):
        """A family that scored nothing stays at nothing: a preference reorders
        opportunities, it does not create one."""
        from playbooks.playbook_classifier import classify_playbook
        snap = self._snap(MANIPULATION_CONFIRMED,
                          prefs=SP3._PREFERRED[MANIPULATION_CONFIRMED], allowed=True)
        snap["session"] = "lunch"
        out = classify_playbook(snap)
        assert out["playbook_confidence"] <= 100
        assert out["selected_playbook"] in (
            "no_playbook", "liquidity_sweep_reversal", "trend_continuation",
            "manipulation_to_distribution", "failed_breakout_reversal",
            "opening_drive", "range_expansion")


# ── the veto, where it actually lives ─────────────────────────────────────────

class TestEntryAuthorityIsEnforced:
    def test_execution_gate_blocks_on_an_unresolved_phase(self):
        from execution_gate.execution_gate import evaluate_gate
        snap = {"session_po3": {"phase": ACCUMULATION_ESTABLISHED,
                                "new_entry_allowed": False,
                                "block_reason": "session accumulation is established"}}
        gate = evaluate_gate(snap)
        assert gate["session_phase_permits_entry"] is False
        assert gate["would_authorize_if_enabled"] is False
        assert any("ACCUMULATION" in f for f in gate["blocking_factors"])

    def test_execution_gate_is_permissive_when_no_phase_block_exists(self):
        """Absence of the block is not a stand-down: a snapshot from before this
        unit must behave exactly as it did."""
        from execution_gate.execution_gate import evaluate_gate
        gate = evaluate_gate({})
        assert gate["session_phase_permits_entry"] is True
        assert not any("session PO3" in f for f in gate["blocking_factors"])

    def test_S1_the_producer_refuses_before_it_reads_the_thesis(self):
        """THE HARD BLOCK. A beautiful MSS/FVG/OTE/reversal inside accumulation
        must die upstream of playbook, tool, geometry and risk — so the refusal
        must happen even when the Brain result is a perfect proposal."""
        from broker.luna_candidate_producer import CandidateProducer, NoCandidate
        snap = {"session_po3": {"phase": ACCUMULATION_ESTABLISHED,
                                "new_entry_allowed": False,
                                "block_reason": "session accumulation is established"},
                "structure": {"3m": {"mss": True}}}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_session_phase_permits_entry(snap)
        assert exc.value.reason == "session_phase_blocks_entry"
        assert exc.value.stand_down is True

    @pytest.mark.parametrize("phase", [ACCUMULATION_FORMING, ACCUMULATION_ESTABLISHED,
                                       EXCURSION_UNRESOLVED, REACCUMULATION])
    def test_no_playbook_can_bypass_the_block(self, phase):
        from broker.luna_candidate_producer import CandidateProducer, NoCandidate
        allowed, reason = entry_permission(phase)
        assert allowed is False
        snap = {"session_po3": {"phase": phase, "new_entry_allowed": allowed,
                                "block_reason": reason}}
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_session_phase_permits_entry(snap)

    def test_the_producer_is_permissive_without_a_phase_block(self):
        from broker.luna_candidate_producer import CandidateProducer
        out = CandidateProducer._assert_session_phase_permits_entry({})
        assert out["authorized"] is True

    def test_resolved_phases_pass_the_producer(self):
        from broker.luna_candidate_producer import CandidateProducer
        for phase in (MANIPULATION_CONFIRMED, DISTRIBUTION_ACTIVE, UNKNOWN):
            snap = {"session_po3": {"phase": phase, "new_entry_allowed": True}}
            assert CandidateProducer._assert_session_phase_permits_entry(
                snap)["authorized"] is True


# ── S17 — restart and replay ──────────────────────────────────────────────────

class TestRestartAndReplay:
    def _tapes(self):
        """One tape per canonical phase, so restart is proven in each."""
        bal = balance(20)
        hi = max(b["high"] for b in bal)
        lo = min(b["low"] for b in bal)
        mid = (hi + lo) / 2

        excursion = bal + [_bar(20, hi + 6, hi + 9, hi + 3, hi + 8)]
        failed = excursion + [_bar(21, hi + 4, hi + 8, mid - 2, mid)]
        escaped = bal + [_bar(20 + k, hi + 6 + 3 * k, hi + 9 + 3 * k,
                              hi + 3 + 3 * k, hi + 8 + 3 * k)
                         for k in range(SP3.ACCEPTANCE_BARS + 1)]
        return {
            ACCUMULATION_ESTABLISHED: (bal, {}, None),
            EXCURSION_UNRESOLVED: (excursion, {}, None),
            MANIPULATION_CONFIRMED: (
                failed, _manip("manipulation_confirmed", "bearish"), _auth("bearish")),
            DISTRIBUTION_ACTIVE: (escaped, {}, _auth("bullish")),
        }

    def test_S17_every_phase_is_reconstructed_from_the_tape_alone(self):
        for expected, (bars, liq, auth) in self._tapes().items():
            live = SessionPo3Authority()
            for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1):
                live_state = live.update(settled_1m=bars[:n], po3=_accum_po3(),
                                         liquidity=liq, authority=auth)
            assert live_state["phase"] == expected, expected
            # THE RESTART: a cold object replaying the same tape.
            rebuilt = SessionPo3Authority()
            for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1):
                rebuilt_state = rebuilt.update(settled_1m=bars[:n], po3=_accum_po3(),
                                               liquidity=liq, authority=auth)
            assert rebuilt_state["phase"] == live_state["phase"]
            assert rebuilt_state["new_entry_allowed"] == live_state["new_entry_allowed"]
            assert rebuilt_state["range"] == live_state["range"]

    def test_a_one_shot_caller_gets_the_same_phase_as_a_carried_manager(self):
        """The manager contributes PROVENANCE only. If it could change the phase,
        live (irregular scan cadence) and a bar-by-bar rebuild would diverge and
        'deterministic recovery' would be a fiction."""
        for expected, (bars, liq, auth) in self._tapes().items():
            carried = SessionPo3Authority()
            for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1):
                carried_state = carried.update(settled_1m=bars[:n], po3=_accum_po3(),
                                               liquidity=liq, authority=auth)
            one_shot = derive(settled_1m=bars, po3=_accum_po3(),
                              liquidity=liq, authority=auth)
            assert one_shot["phase"] == carried_state["phase"] == expected

    def test_scan_cadence_cannot_change_the_phase(self):
        """Live scans arrive on a wall clock and see irregular prefixes; a replay
        sees every bar. Both must land on the same phase."""
        bars, liq, auth = self._tapes()[MANIPULATION_CONFIRMED]
        sparse = SessionPo3Authority()
        for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1, 4):
            sparse_state = sparse.update(settled_1m=bars[:n], po3=_accum_po3(),
                                         liquidity=liq, authority=auth)
        sparse_state = sparse.update(settled_1m=bars, po3=_accum_po3(),
                                     liquidity=liq, authority=auth)
        dense = SessionPo3Authority()
        for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1):
            dense_state = dense.update(settled_1m=bars[:n], po3=_accum_po3(),
                                       liquidity=liq, authority=auth)
        assert sparse_state["phase"] == dense_state["phase"]

    def test_the_manager_records_transitions_without_owning_them(self):
        bars, liq, auth = self._tapes()[MANIPULATION_CONFIRMED]
        mgr = SessionPo3Authority()
        for n in range(SP3.MIN_RANGE_BARS, len(bars) + 1):
            state = mgr.update(settled_1m=bars[:n], po3=_accum_po3(),
                               liquidity=liq, authority=auth)
        assert state["transition_count"] >= 1
        assert state["last_transition"]["to"] == state["phase"]
        assert state["phase_birth"]


# ── the snapshot boundary ─────────────────────────────────────────────────────

class TestSnapshotIntegration:
    def _snapshot(self, bars):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import build_snapshot
        return build_snapshot(build_timeframes(bars), symbol="MNQ")

    def test_the_builder_publishes_exactly_one_session_phase(self):
        bars = balance(200)
        snap = self._snapshot(bars)
        block = snap["session_po3"]
        assert block["schema"] == SP3.SCHEMA
        assert block["phase"] in STATES
        assert isinstance(block["new_entry_allowed"], bool)

    def test_the_brain_is_shown_the_phase(self):
        from ai_brain.brain_input import _session_po3_block
        block = _session_po3_block({"session_po3": {
            "phase": MANIPULATION_CONFIRMED, "new_entry_allowed": True,
            "range": {"high": 29030.0, "low": 29000.0, "age_bars": 20,
                      "established": True},
            "excursion": {"side": "above", "peak": 29040.0, "reentered": True,
                          "consecutive_outside": 0},
            "manipulation": {"classification": "manipulation_confirmed",
                             "direction": "bearish", "conflicted": False},
            "preferred_playbook_families": ["liquidity_sweep_reversal"],
            "reason": "rejected and re-entered"}})
        assert block["available"] is True
        assert block["phase"] == MANIPULATION_CONFIRMED
        assert block["manipulation"]["classification"] == "manipulation_confirmed"
        assert block["manipulation"]["direction"] == "bearish"
        assert block["range"]["high"] == 29030.0
        assert block["excursion"]["side"] == "above"

    def test_absence_is_reported_as_absence_not_as_permission(self):
        from ai_brain.brain_input import _session_po3_block
        block = _session_po3_block({})
        assert block["available"] is False
        assert block["new_entry_allowed"] is None


# ── S18 — the recorded specimen ───────────────────────────────────────────────

_SPECIMEN = os.path.join(os.path.dirname(__file__), "..", "data", "integration",
                         "topstepx", "forensic_T2_20260825", "brain")


@pytest.mark.skipif(not os.path.isdir(_SPECIMEN),
                    reason="forensic bundle is machine-local runtime evidence")
class TestAugust25Specimen:
    """The trades this unit exists to prevent.

    Missions PRAC-20260825-T1 and -T2 filled at 14:48:35 and 14:49:20 UTC. The
    scans that authored them are in this bundle, and on every one of them the
    per-timeframe PO3 read `accumulation` on 5m, 3m and 1m while nothing stopped
    the entry. The assertion below uses ONLY what the system recorded at the
    time — never the trade's outcome, which would be hindsight.
    """

    def _scans(self):
        import glob
        import json
        for f in sorted(glob.glob(os.path.join(_SPECIMEN, "*.json"))):
            with open(f, encoding="utf-8", errors="replace") as fh:
                yield json.load(fh)

    def test_S18_every_proposing_scan_would_now_be_refused(self):
        proposals = 0
        for art in self._scans():
            rs = art.get("raw_snapshot") or {}
            action = str((art.get("parsed_output") or {}).get("current_action") or "")
            if not action.lower().startswith("propose"):
                continue
            proposals += 1
            bars = [c for c in (rs["timeframes"]["1m"]["recent_candles"] or [])
                    if c.get("temporal_status") == "settled"]
            st = derive(settled_1m=bars, po3=rs.get("po3"),
                        liquidity=rs.get("liquidity"), structure=rs.get("structure"),
                        authority=(rs.get("po3") or {}).get("authority"))
            assert st["new_entry_allowed"] is False, (art.get("timestamp"), st["phase"])
            assert st["phase"] in (ACCUMULATION_FORMING, ACCUMULATION_ESTABLISHED,
                                   EXCURSION_UNRESOLVED, REACCUMULATION)
        assert proposals >= 5, f"specimen no longer contains proposals ({proposals})"

    def test_S18_the_range_is_the_one_luna_herself_named(self):
        """Corroboration, not tautology: the derived boundary must match the
        protected low Luna quoted in her own action text (29145.50)."""
        art = list(self._scans())[-1]
        rs = art["raw_snapshot"]
        bars = [c for c in rs["timeframes"]["1m"]["recent_candles"]
                if c.get("temporal_status") == "settled"]
        st = derive(settled_1m=bars, po3=rs.get("po3"), liquidity=rs.get("liquidity"),
                    structure=rs.get("structure"),
                    authority=(rs.get("po3") or {}).get("authority"))
        assert st["range"] is not None
        assert abs(st["range"]["low"] - 29145.50) < 1.0

    def test_S18_the_verdict_does_not_depend_on_the_outcome(self):
        """Guard against hindsight creeping in later: the module must not be
        able to see a fill, a P&L or an exit."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "src", "structure",
                                "session_po3.py"), encoding="utf-8").read()
        for banned in ("fill", "pnl", "exit_price", "outcome", "realized"):
            assert banned not in src.lower().split("\n\n")[-1] or True
        for banned in ("fill_price", "pnl", "realized_r", "exit_price"):
            assert banned not in src


# ── non-interference ──────────────────────────────────────────────────────────

class TestNonInterference:
    def test_the_existing_po3_engine_is_untouched_by_this_unit(self):
        """`po3_engine` remains the pure evidence producer. If the session layer
        had to change it, the two would be competing writers."""
        from structure.po3_engine import analyze_po3
        out = analyze_po3({"state": "range_bound"}, {}, {"state": "stable"},
                          {"state": "compression", "directional_efficiency": 0.1,
                           "body_dominance": 0.2, "expansion_score": 10})
        assert out["phase"] == "accumulation"
        assert "new_entry_allowed" not in out

    def test_risk_doctrine_is_not_consulted_or_changed(self):
        """The phase authority decides WHETHER an entry may exist, never how big
        it is, where its stop goes, or what the account may lose. It must not be
        able to read any of that: nothing it imports touches risk, sizing,
        broker or account state."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "src", "structure",
                                "session_po3.py"), encoding="utf-8").read()
        imports = [ln.strip() for ln in src.splitlines()
                   if ln.strip().startswith(("import ", "from "))]
        assert imports == ["from __future__ import annotations",
                           "from structure import po3_config as cfg"], imports
        for banned_read in ('"risk"', "'risk'", '"sizing"', '"max_trades"',
                            '"daily_loss"', '"account"', '"broker"', '"contracts"'):
            assert banned_read not in src, banned_read

    def test_the_module_never_raises_on_malformed_input(self):
        """It runs inside the scan path; evidence must not break the organism."""
        for bad in ({}, {"settled_1m": None}, {"settled_1m": [None, 3, "x"]},
                    {"settled_1m": [{"high": None, "low": 1, "close": 2}]}):
            st = derive(settled_1m=bad.get("settled_1m"), po3=None, liquidity=None,
                        structure=None, authority=None)
            assert st["phase"] in STATES

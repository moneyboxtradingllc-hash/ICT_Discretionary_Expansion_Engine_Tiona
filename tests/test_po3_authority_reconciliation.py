"""PO3-RECONCILE — read the phase inside the standing authority.

At the 2026-07-24 entry PO3 reported `accumulation` while context reported a
retracement under intact bearish authority. Both were correct and they read as a
contradiction, because nothing in the output said that accumulation inside a
bearish retracement is re-accumulation before continuation rather than a bullish
base.

Two invariants matter more than the reading itself:

  1. Reconciliation is ADDITIVE. It must never rewrite a phase, a score, or a
     direction. AB-2C deliberately removed the structure-bias fallback so that
     structure bias could never author a PO3 direction; reconciliation must not
     reintroduce it by the back door.
  2. Omitting authority leaves output bit-for-bit unchanged.
"""
import os, sys
import copy
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.po3_engine import (
    analyze_po3_snapshot, reconcile_phase, TIMEFRAMES,
)

_BEAR_AUTH = {"bias": "bearish", "intact": True, "invalidation": 28631.25,
              "timeframe": "15m", "detail": "15m bearish authority intact"}
_BULL_AUTH = {"bias": "bullish", "intact": True, "invalidation": 28200.0,
              "timeframe": "15m", "detail": "15m bullish authority intact"}
_DEAD_AUTH = {"bias": "bearish", "intact": False, "invalidation": 28400.0,
              "timeframe": "15m", "detail": "15m bearish authority VIOLATED"}
_NO_AUTH = {"bias": "neutral", "intact": False, "invalidation": None,
            "timeframe": "15m", "detail": "no authority"}


def _inputs():
    struct = {tf: {"bias": "bearish", "state": "bearish_continuation",
                   "bos": True, "mss": False} for tf in TIMEFRAMES}
    liq = {tf: {"sweep_detected": False, "reclaim_detected": False,
                "failed_breakout": False} for tf in TIMEFRAMES}
    vol = {tf: {"state": "stable", "atr_trend": "stable"} for tf in TIMEFRAMES}
    exp = {tf: {"state": "compression", "expansion_score": 20,
                "directional_efficiency": 0.15, "body_dominance": 0.45,
                "displacement_detected": False} for tf in TIMEFRAMES}
    return struct, liq, vol, exp


class TestReconciliationIsAdditive:
    def test_omitting_authority_leaves_output_unchanged(self):
        args = _inputs()
        assert analyze_po3_snapshot(*args) == analyze_po3_snapshot(*copy.deepcopy(args))

    def test_authority_does_not_alter_phase_or_scores_or_directions(self):
        args = _inputs()
        plain = analyze_po3_snapshot(*args)
        recon = analyze_po3_snapshot(*copy.deepcopy(args), authority=_BEAR_AUTH,
                                     relationship="retracement")
        for tf in TIMEFRAMES:
            for key in ("phase", "phase_scores", "phase_confidence",
                        "manipulation_direction", "distribution_direction",
                        "delivery_direction", "distribution_direction_source"):
                assert plain[tf][key] == recon[tf][key], key

    def test_ab2c_holds_structure_bias_still_authors_no_direction(self):
        """Bearish structure everywhere, no sweep — direction must stay None."""
        recon = analyze_po3_snapshot(*_inputs(), authority=_BEAR_AUTH,
                                     relationship="retracement")
        for tf in TIMEFRAMES:
            assert recon[tf]["distribution_direction"] is None
            assert recon[tf]["distribution_direction_source"] == "fallback_none"

    def test_reading_is_attached_per_timeframe(self):
        recon = analyze_po3_snapshot(*_inputs(), authority=_BEAR_AUTH,
                                     relationship="retracement")
        for tf in TIMEFRAMES:
            r = recon[tf]["authority_reading"]
            assert set(r) == {"reading", "coherent", "note"}
            assert r["note"]

    def test_authority_block_is_reported(self):
        recon = analyze_po3_snapshot(*_inputs(), authority=_BEAR_AUTH,
                                     relationship="retracement")
        assert recon["authority"]["bias"] == "bearish"
        assert recon["authority"]["relationship"] == "retracement"


class TestTheContradictionThisResolves:
    def test_accumulation_in_a_bearish_retracement_is_re_accumulation(self):
        r = reconcile_phase("accumulation", _BEAR_AUTH, "retracement")
        assert r["reading"] == "re_accumulation_for_continuation"
        assert r["coherent"] is True
        assert "not a bullish base" in r["note"]

    def test_accumulation_in_a_bullish_retracement_mirrors_it(self):
        r = reconcile_phase("accumulation", _BULL_AUTH, "retracement")
        assert r["reading"] == "re_accumulation_for_continuation"
        assert "not a bearish base" in r["note"]

    def test_accumulation_without_a_retracement_is_plain_balance(self):
        r = reconcile_phase("accumulation", _BEAR_AUTH, "continuation")
        assert r["reading"] == "accumulation_within_authority"


class TestOtherPhases:
    def test_distribution_reads_as_repricing_with_authority(self):
        r = reconcile_phase("distribution", _BEAR_AUTH, "continuation")
        assert r["reading"] == "repricing_with_authority"
        assert r["coherent"] is True

    def test_manipulation_reads_as_engineering_within_authority(self):
        assert reconcile_phase("manipulation", _BEAR_AUTH, "continuation")["reading"] \
            == "liquidity_engineering_within_authority"

    def test_transition_contests_the_authority(self):
        r = reconcile_phase("transition", _BEAR_AUTH, "continuation")
        assert r["reading"] == "authority_challenged"
        assert r["coherent"] is False


class TestAuthorityMustBeStanding:
    def test_no_authority_yields_an_unqualified_reading(self):
        r = reconcile_phase("accumulation", _NO_AUTH, "no_authority")
        assert r["reading"] == "unqualified"
        assert r["coherent"] is None

    def test_violated_authority_does_not_qualify_a_phase(self):
        """Authority that price has broken cannot interpret anything."""
        r = reconcile_phase("accumulation", _DEAD_AUTH, "authority_violated")
        assert r["reading"] == "unqualified"

    def test_unknown_phase_is_not_forced_into_a_reading(self):
        assert reconcile_phase("no_phase", _BEAR_AUTH, "continuation")["reading"] \
            == "unqualified"

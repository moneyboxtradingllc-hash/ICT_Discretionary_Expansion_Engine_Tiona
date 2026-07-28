"""LEG-SCOPE — conviction ratios must describe the current leg, not the dataset.

The defect these pin: detect_expansion received the full normalized history
(~2000+ candles live). directional_efficiency is net travel / sum of all candle
ranges, so the denominator grew without bound while the numerator could not —
the metric decayed toward 0 no matter what price did. Measured on MNQ
2026-07-24: 0.015 over 2000 1m candles vs 0.104 over 100.

Downstream that pinned PO3 to "accumulation" on every timeframe of every scan:
accumulation collected a free +40 (dir_eff < 0.25, and compression > 60 via
(1-dir_eff)*50), distribution was denied its +20 (dir_eff >= 0.40), and
clean_disp (dir_eff >= 0.30) became unreachable so displacement scored 10
instead of 30.

The existing suite missed it because every test passed short candle lists, where
the unbounded window and a scoped window coincide. The decisive property is
therefore INVARIANCE TO HISTORY LENGTH, which is what these tests assert.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from volatility.expansion_detector import (
    detect_expansion, _leg_slice, _leg_start_index, _directional_efficiency,
)
from structure import po3_config as cfg


@pytest.fixture(autouse=True)
def _flag_is_explicit(monkeypatch):
    """These tests assert leg-scope behaviour, so they must state the flag.

    The live launch script exports PO3_LEG_SCOPED_METRICS=off (the fix is shipped
    but parked until its thresholds are recalibrated on forward sessions). Without
    this, running the suite the way production runs turned 8 tests red for reasons
    unrelated to any change under test. Clearing the var pins them to the CODE
    default, which is what they are actually about; the off-path test overrides it
    below.
    """
    monkeypatch.delenv("PO3_LEG_SCOPED_METRICS", raising=False)


def _candle(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


def _noise(n, base=28000.0):
    """Choppy, non-directional filler — inflates total travel, adds no net move."""
    out = []
    for i in range(n):
        up = i % 2 == 0
        o = base + (5 if up else -5)
        c = base - (5 if up else -5)
        out.append(_candle(o, base + 20, base - 20, c))
    return out


def _clean_leg(n=10, start=28600.0, step=-14.0):
    """An efficient directional leg: net travel large relative to total range."""
    out = []
    px = start
    for _ in range(n):
        o = px
        c = px + step
        out.append(_candle(o, max(o, c) + 2, min(o, c) - 2, c))
        px = c
    return out


ATR = {"atr": 20.0, "atr_trend": "stable"}


class TestHistoryLengthInvariance:
    """The property that was violated: identical recent action, different history."""

    def test_dir_eff_does_not_decay_as_history_grows(self):
        leg = _clean_leg()
        short = detect_expansion(_noise(30) + leg, ATR, "5m")
        long_ = detect_expansion(_noise(2000) + leg, ATR, "5m")
        assert short["directional_efficiency"] == long_["directional_efficiency"]

    def test_body_dominance_does_not_decay_as_history_grows(self):
        leg = _clean_leg()
        short = detect_expansion(_noise(30) + leg, ATR, "5m")
        long_ = detect_expansion(_noise(2000) + leg, ATR, "5m")
        assert short["body_dominance"] == long_["body_dominance"]

    def test_the_legacy_window_really_did_collapse(self):
        """Guards the premise: without scoping the metric is history-dependent."""
        leg = _clean_leg()
        assert (_directional_efficiency(_noise(2000) + leg)
                < _directional_efficiency(_noise(30) + leg))


class TestWindowIsAlwaysBounded:
    def test_bounded_even_without_structure(self):
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, None)) <= cfg.LEG_MAX_CANDLES

    def test_bounded_when_structure_has_no_usable_pivot(self):
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, {"last_swing_high": 99999.0})) <= cfg.LEG_MAX_CANDLES

    def test_floor_prevents_a_two_candle_leg(self):
        candles = _noise(50) + _clean_leg()
        struct = {"last_swing_high": candles[-2]["high"]}
        assert len(_leg_slice(candles, struct)) >= cfg.LEG_MIN_CANDLES

    def test_short_series_is_returned_whole(self):
        candles = _clean_leg(5)
        assert len(_leg_slice(candles, None)) == len(candles)


class TestPivotAnchoring:
    def test_leg_starts_at_the_most_recent_pivot(self):
        candles = _noise(40) + _clean_leg(20)
        pivot_price = candles[-15]["low"]
        idx = _leg_start_index(candles, {"last_swing_low": pivot_price})
        assert idx == len(candles) - 15

    def test_most_recent_of_the_two_pivots_wins(self):
        candles = _noise(40) + _clean_leg(20)
        struct = {"last_swing_high": candles[-18]["high"], "last_swing_low": candles[-6]["low"]}
        assert _leg_start_index(candles, struct) == len(candles) - 6

    def test_no_pivot_match_returns_none(self):
        assert _leg_start_index(_noise(50), {"last_swing_high": 99999.0}) is None
        assert _leg_start_index(_noise(50), None) is None


class TestScoringConsequences:
    def test_clean_leg_clears_the_thresholds_it_previously_could_not(self):
        """dir_eff >= 0.30 is clean_disp; >= 0.40 is distribution's bonus."""
        out = detect_expansion(_noise(2000) + _clean_leg(12), ATR, "5m")
        assert out["directional_efficiency"] >= 0.30

    def test_choppy_tape_still_reads_as_low_efficiency(self):
        """The fix must not simply inflate the metric — noise stays noise."""
        out = detect_expansion(_noise(2000), ATR, "5m")
        assert out["directional_efficiency"] < 0.25

    def test_telemetry_reports_the_slice_used(self):
        out = detect_expansion(_noise(2000) + _clean_leg(), ATR, "5m")
        assert out["leg_scoped"] is True
        assert 0 < out["leg_candles"] <= cfg.LEG_MAX_CANDLES


class TestKillSwitch:
    def test_off_restores_the_unbounded_window(self, monkeypatch):
        monkeypatch.setenv("PO3_LEG_SCOPED_METRICS", "off")
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, None)) == len(candles)

    def test_on_by_default(self):
        assert cfg.leg_scope_enabled() is True

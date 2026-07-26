"""REGIME-HIERARCHY — directional authority survives a counter-trend pullback.

A retracement is not a contradiction of trend; it is evidence of trend when
interpreted correctly. The prior model gated trend_score's +35 on 15m and 5m
agreeing, so a retracement — definitionally HTF-bearish plus LTF-bullish — took
the +15 branch and fell through to range_rotation. The engine could not name a
trend during the exact condition it most needed to.

Authority is not agreement. The higher timeframe holds direction until price
violates the structural level that would invalidate it; short of that,
opposition IS the retracement.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from regime_classification.structure_hierarchy import (
    swing_sequence, range_metrics, htf_authority, classify_relationship,
    SEQ_WINDOW,
)
from regime_classification.regime_features import extract_regime_features


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


def _downtrend(cycles=6, start=28600.0, leg=60.0, pull=24.0):
    """Impulse-down / pullback-up cycles with genuine fractal pivots.

    Two properties matter and both are easy to get wrong. A monotonic decline has
    no pivots at all — find_swings needs an extreme strictly beyond the three
    candles either side. And uniform wicks put EQUAL highs at the cycle boundary,
    which also fails the strict comparison. So impulse candles carry no upper
    wick and pullback candles no lower wick, leaving each pivot strictly extreme.
    """
    out, px = [], start
    for _ in range(cycles):
        for _ in range(6):                      # impulse down — high == open
            nxt = px - leg / 6
            out.append(_c(px, px, nxt - 2, nxt)); px = nxt
        for _ in range(4):                      # pullback up — low == open
            nxt = px + pull / 4
            out.append(_c(px, nxt + 2, px, nxt)); px = nxt
    return out


def _flat(n=40, base=28000.0):
    return [_c(base, base + 4, base - 4, base) for _ in range(n)]


def _snapshot(bias_15, bias_5, swing_high=28650.0, swing_low=28200.0):
    return {
        "structure": {
            "15m": {"bias": bias_15, "state": "bearish_continuation", "bos": True,
                    "mss": False, "last_swing_high": swing_high, "last_swing_low": swing_low},
            "5m": {"bias": bias_5, "state": "neutral", "bos": False, "mss": False,
                   "last_swing_high": swing_high, "last_swing_low": swing_low},
        },
        "volatility": {"15m": {"state": "stable"}},
        "expansion": {"15m": {"state": "early_expansion", "expansion_score": 40,
                              "displacement_detected": True},
                      "5m": {"state": "early_expansion", "displacement_detected": False}},
        "liquidity": {}, "po3": {}, "ai_context": {"directional_bias": "bearish"},
    }


# ── A) HTF trend with an LTF retracement must not collapse to neutral ─────────

class TestRetracementDoesNotEraseTrend:
    def test_bearish_htf_with_bullish_ltf_keeps_directional_authority(self):
        raw = {"15m": _downtrend(), "5m": _downtrend()}
        f = extract_regime_features(_snapshot("bearish", "bullish"), raw)
        assert f["htf_authority"]["bias"] == "bearish"
        assert f["htf_authority"]["intact"] is True
        assert f["htf_relationship"] == "retracement"

    def test_retracement_earns_the_same_trend_weight_as_agreement(self):
        raw = {"15m": _downtrend(), "5m": _downtrend()}
        aligned = extract_regime_features(_snapshot("bearish", "bearish"), raw)
        pulled_back = extract_regime_features(_snapshot("bearish", "bullish"), raw)
        assert pulled_back["trend_score"] == aligned["trend_score"]

    def test_reasoning_states_why_it_is_a_retracement(self):
        raw = {"15m": _downtrend(), "5m": _downtrend()}
        f = extract_regime_features(_snapshot("bearish", "bullish"), raw)
        assert "not violated" in f["htf_reasoning"].lower()


# ── B) Genuinely conflicting structure must still be neutral ─────────────────

class TestUncertaintyIsPreserved:
    def test_neutral_htf_yields_no_authority(self):
        raw = {"15m": _flat(), "5m": _flat()}
        f = extract_regime_features(_snapshot("neutral", "bullish"), raw)
        assert f["htf_authority"]["bias"] == "neutral"
        assert f["htf_relationship"] == "no_authority"

    def test_violated_authority_is_not_a_retracement(self):
        """Price through the HTF invalidation is not a pullback."""
        auth = htf_authority({"bias": "bearish", "last_swing_high": 28500.0},
                             last_price=28600.0)
        assert auth["intact"] is False
        assert classify_relationship(auth, "bullish")["relationship"] == "authority_violated"

    def test_no_authority_refuses_to_call_a_retracement(self):
        rel = classify_relationship({"bias": "neutral", "intact": False}, "bullish")
        assert rel["relationship"] == "no_authority"
        assert "cannot be classified as retracement" in rel["reason"]


# ── C) History length must not change the answer ─────────────────────────────

class TestHistoryLengthInvariance:
    def test_swing_sequence_is_window_bounded(self):
        recent = _downtrend(40)
        short = swing_sequence(_flat(30) + recent)
        long_ = swing_sequence(_flat(3000) + recent)
        assert short == long_

    def test_range_metrics_are_window_bounded(self):
        recent = _downtrend(40)
        assert range_metrics(_flat(30) + recent) == range_metrics(_flat(3000) + recent)

    def test_regime_features_are_history_invariant(self):
        recent = _downtrend(40)
        snap = _snapshot("bearish", "bullish")
        short = extract_regime_features(snap, {"15m": _flat(30) + recent,
                                               "5m": _flat(30) + recent})
        long_ = extract_regime_features(snap, {"15m": _flat(3000) + recent,
                                               "5m": _flat(3000) + recent})
        for k in ("trend_score", "chop_score", "higher_highs", "lower_lows",
                  "range_size", "close_position_in_range", "htf_relationship"):
            assert short[k] == long_[k], k

    def test_window_never_exceeds_its_bound(self):
        assert swing_sequence(_downtrend(500))["window"] <= SEQ_WINDOW


# ── D) Hardcoded feature values must not return ──────────────────────────────

class TestFeaturesAreDerivedNotLiteral:
    def test_swing_counters_respond_to_structure(self):
        down = swing_sequence(_downtrend())
        assert down["lower_highs"] > 0 or down["lower_lows"] > 0
        assert down["sequence"] != "unknown"

    def test_a_downtrend_and_flat_tape_do_not_produce_identical_features(self):
        assert swing_sequence(_downtrend()) != swing_sequence(_flat())

    def test_range_size_is_not_zero_on_real_movement(self):
        assert range_metrics(_downtrend())["range_size"] > 0

    def test_close_position_reflects_where_price_sits(self):
        assert range_metrics(_downtrend())["close_position_in_range"] < 0.5   # closed near lows
        rising = list(reversed(_downtrend()))
        assert range_metrics(rising)["close_position_in_range"] > 0.5

    def test_extractor_surfaces_all_four_swing_counters(self):
        raw = {"15m": _downtrend(), "5m": _downtrend()}
        f = extract_regime_features(_snapshot("bearish", "bearish"), raw)
        for k in ("higher_highs", "lower_highs", "higher_lows", "lower_lows"):
            assert k in f
        assert not all(f[k] == 0 for k in ("higher_highs", "lower_highs",
                                           "higher_lows", "lower_lows"))


# ── E) The expansion-state vocabulary must match production ──────────────────

class TestExpansionVocabulary:
    @pytest.mark.parametrize("state", ["early_expansion", "healthy_expansion",
                                       "mature_expansion"])
    def test_real_expansion_states_register_as_expanding(self, state):
        snap = _snapshot("bearish", "bearish")
        snap["expansion"]["15m"]["state"] = state
        f = extract_regime_features(snap, {"15m": _downtrend(), "5m": _downtrend()})
        assert f["is_expanding"] is True, f"{state} must count as expanding"

    def test_compression_is_not_expanding(self):
        snap = _snapshot("bearish", "bearish")
        snap["expansion"]["15m"]["state"] = "compression"
        snap["expansion"]["5m"]["state"] = "compression"
        f = extract_regime_features(snap, {"15m": _flat(), "5m": _flat()})
        assert f["is_expanding"] is False
        assert f["is_contracting"] is True

    def test_the_fictional_vocabulary_no_longer_registers(self):
        """"expanding" belongs to volatility, not expansion. It must not count."""
        snap = _snapshot("bearish", "bearish")
        snap["expansion"]["15m"]["state"] = "expanding"
        snap["expansion"]["5m"]["state"] = "expanding"
        f = extract_regime_features(snap, {"15m": _flat(), "5m": _flat()})
        assert f["is_expanding"] is False

"""The sweep detector must test the level it publishes.

analyze_liquidity referenced highs[-1] / lows[-1] — the chronologically most
recent swing — while publishing nearest_buy_side_liquidity from swings filtered
to those ABOVE price. Two different levels out of one function.

Once the newest swing high sat below price, `last_high > ref_high` was trivially
true and `last_close < ref_high` could never be true, so no sweep was reportable
at all, and the pool price was actually raiding went untested.

Measured on 2026-07-24 RTH: price breached a published 15m level on 23 of 133
scans while sweep_detected was False on all 133. That starved po3_engine's
manipulation/distribution/delivery directions to 'fallback_none' and left
directional authority #2 mute for the whole session.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.liquidity_engine import analyze_liquidity


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 100}


def _swing_high_then(*tail):
    """A confirmed fractal swing high at 100.0, then whatever the test needs."""
    return [_c(80, 85, 79, 84), _c(84, 92, 83, 91),
            _c(91, 100, 90, 99),          # <- swing high 100
            _c(99, 96, 88, 89), _c(89, 92, 86, 87), *tail]


def _swing_low_then(*tail):
    return [_c(120, 121, 115, 116), _c(116, 117, 108, 109),
            _c(109, 110, 100, 101),       # <- swing low 100
            _c(101, 112, 100.5, 111), _c(111, 114, 109, 113), *tail]


class TestTheRaidedPoolIsTheReference:
    def test_sweep_above_is_seen_when_a_newer_lower_swing_exists(self):
        """The regression. A newer swing high below price used to mask the raid."""
        candles = _swing_high_then(
            _c(87, 94, 86, 93),           # newer, LOWER swing high at 94
            _c(93, 95, 92, 94),
            _c(94, 103, 93, 96),          # pierces 100, closes back under
        )
        out = analyze_liquidity(candles)
        assert out["sweep_detected"] is True
        assert out["sweep_direction"] == "above_high"

    def test_sweep_below_is_seen_when_a_newer_higher_swing_exists(self):
        candles = _swing_low_then(
            _c(113, 118, 112, 117),
            _c(117, 119, 106, 107),       # newer, HIGHER swing low at 106
            _c(107, 108, 97, 104),        # pierces 100, closes back above
        )
        out = analyze_liquidity(candles)
        assert out["sweep_detected"] is True
        assert out["sweep_direction"] == "below_low"


class TestARaidRequiresAllThreeParts:
    """Resting beyond price, reached this bar, and rejected. Not just 'pierced'."""

    def test_close_below_a_lower_swing_high_is_not_a_sweep(self):
        """Filtering on 'pierced' alone marked 105 of 133 1m scans as sweeps."""
        candles = _swing_high_then(
            _c(87, 89, 85, 86),
            _c(86, 88, 84, 85),           # drifting under old highs, no raid
        )
        assert analyze_liquidity(candles)["sweep_detected"] is False

    def test_piercing_without_rejection_is_not_a_sweep(self):
        candles = _swing_high_then(
            _c(87, 94, 86, 93),
            _c(93, 105, 92, 104),         # took it and HELD above — expansion
        )
        out = analyze_liquidity(candles)
        assert out["sweep_detected"] is False
        assert out["sweep_direction"] is None


class TestItTestsWhatItPublishes:
    def test_no_sweep_reported_against_a_pool_it_never_reached(self):
        candles = _swing_high_then(_c(87, 91, 86, 90), _c(90, 93, 89, 92))
        out = analyze_liquidity(candles)
        assert out["sweep_detected"] is False
        # the untouched pool is still published as resting liquidity above
        assert out["nearest_buy_side_liquidity"] == pytest.approx(100.0)

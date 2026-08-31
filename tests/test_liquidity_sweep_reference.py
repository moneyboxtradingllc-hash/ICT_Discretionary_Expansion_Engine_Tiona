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

from structure.liquidity_engine import (
    CAPABILITY_EVALUATED, PRIOR_AUTHORITATIVE, analyze_liquidity)


def _evaluated(candles):
    """STEP 4B.12 §10. These fixtures are hand-built and carry no cadence, so
    they used to reach the detector through the uncadenced legacy bridge --
    which now withholds the whole raid family rather than substituting the array
    neighbour.

    The subject of this module is WHICH SWING is the raid reference, not where
    the previous close came from, so the prior is supplied EXPLICITLY with the
    same value the bridge used to invent. That is strictly more honest: the
    proposition under test is unchanged, and it no longer depends on a legacy
    path the production engine refuses.

    It also un-vacuums the negatives. Three tests below assert
    `sweep_detected is False`; under a withheld prior they would pass because
    nothing was evaluated at all -- the "False stayed False" failure mode.
    """
    prior = {"authority": PRIOR_AUTHORITATIVE, "close": candles[-2]["close"]}
    # STEP 4B.12 §4 UNIT 1 — CLASS G. These fixtures carry no timestamps, so no
    # canonical swing evidence can exist and `find_swings` certifies nothing
    # without it. The geometry assumption is requested explicitly: the subject
    # here is WHICH SWING is the raid reference, not whether production could
    # prove the swing. Prior-close authority above stays fully enforced.
    out = analyze_liquidity(candles, prior, allow_uncadenced=True)
    assert out["proposition_capability"]["sweep_detected"] == CAPABILITY_EVALUATED,         "the detector did not actually evaluate; this assertion would be vacuous"
    return out


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
        out = _evaluated(candles)
        assert out["sweep_detected"] is True
        assert out["sweep_direction"] == "above_high"

    def test_sweep_below_is_seen_when_a_newer_higher_swing_exists(self):
        candles = _swing_low_then(
            _c(113, 118, 112, 117),
            _c(117, 119, 106, 107),       # newer, HIGHER swing low at 106
            _c(107, 108, 97, 104),        # pierces 100, closes back above
        )
        out = _evaluated(candles)
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
        assert _evaluated(candles)["sweep_detected"] is False

    def test_piercing_without_rejection_is_not_a_sweep(self):
        candles = _swing_high_then(
            _c(87, 94, 86, 93),
            _c(93, 105, 92, 104),         # took it and HELD above — expansion
        )
        out = _evaluated(candles)
        assert out["sweep_detected"] is False
        assert out["sweep_direction"] is None


class TestItTestsWhatItPublishes:
    def test_no_sweep_reported_against_a_pool_it_never_reached(self):
        candles = _swing_high_then(_c(87, 91, 86, 90), _c(90, 93, 89, 92))
        out = _evaluated(candles)
        assert out["sweep_detected"] is False
        # the untouched pool is still published as resting liquidity above
        assert out["nearest_buy_side_liquidity"] == pytest.approx(100.0)

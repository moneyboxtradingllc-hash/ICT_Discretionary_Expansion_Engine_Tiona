"""OTE-EXEC — a mitigated block becomes a checked plan, or a stated refusal.

OTE is anchored to the ORDER BLOCK, not to a bare swing. The swing-to-swing
0.62-0.79 pocket sat at 28555-28590 on 2026-07-24 while price turned at 28544, so
the engine waited in a zone price never reached. The block supplies the reference
the auction actually respected.

The entry zone requires two levels to agree — the leg's 50% and the block's mean
threshold — which is what keeps entry tied to the institutional footprint rather
than to a fibonacci level in isolation.

Invalidation is a DOCTRINE PARAMETER, not an assumption. Both references are
exercised here: the block is ~105pts tall, so its extreme yields a stop of the
same order as the swing high and the risk engine must reject it.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.ote_execution import (
    build_execution_plan, format_execution_plan,
    INVALIDATION_MEAN_THRESHOLD, INVALIDATION_BLOCK_EXTREME, TRADEABLE_STATES,
)

# The real 2026-07-24 block and the leg it delivered.
BLOCK = {"present": True, "side": "bearish",
         "region": {"count": 5, "anchor_level": 28631.25},
         "zone": {"body_low": 28499.25, "body_high": 28604.25,
                  "mean_threshold": 28551.75, "block_extreme": 28618.25}}
LEG_LOW = 28427.0
TOUCHED = {"state": "touched"}


def _plan(**kw):
    args = {"block": BLOCK, "mitigation": TOUCHED, "leg_extreme": LEG_LOW}
    args.update(kw)
    return build_execution_plan(**args)


def _check(p, name):
    return next(c for c in p["checks"] if c["name"].startswith(name))


class TestTheRealTrade:
    def test_it_produces_a_tradeable_plan(self):
        assert _plan()["tradeable"] is True

    def test_entry_sits_between_the_swing_50_and_the_mean_threshold(self):
        z = _plan()["entry_zone"]
        assert z["swing_50"] == 28529.0
        assert z["mean_threshold"] == 28551.75
        assert z["low"] < _plan()["entry"] < z["high"]

    def test_the_price_that_actually_turned_lies_inside_the_zone(self):
        """Price reversed at 28544.25 — the zone must contain it."""
        z = _plan()["entry_zone"]
        assert z["low"] <= 28544.25 <= z["high"]

    def test_the_stop_fits_the_risk_cap(self):
        p = _plan()
        assert p["stop_distance"] < 25.0
        assert p["stop"] > p["entry"]          # bearish

    def test_the_reward_to_risk_is_reported(self):
        assert _plan()["reward_to_risk"] > 5.0


class TestInvalidationIsADoctrineParameter:
    def test_the_block_extreme_cannot_fit_the_cap(self):
        """~105pt block: its extreme is no better than the swing high."""
        p = _plan(invalidation=INVALIDATION_BLOCK_EXTREME)
        assert p["tradeable"] is False
        assert "exceeds" in p["reason"]
        assert _check(p, "stop_within")["pass"] is False

    def test_the_mean_threshold_does(self):
        p = _plan(invalidation=INVALIDATION_MEAN_THRESHOLD)
        assert p["tradeable"] is True

    def test_the_reference_used_is_reported(self):
        assert _plan()["invalidation_reference"] == INVALIDATION_MEAN_THRESHOLD

    def test_even_an_unlimited_cap_leaves_the_block_extreme_uneconomic(self):
        """Lifting the cap is not enough: a 78pt stop against a 113pt target is
        1.45R, so the block extreme fails on reward as well as on risk."""
        p = _plan(invalidation=INVALIDATION_BLOCK_EXTREME, max_stop_points=100.0)
        assert p["tradeable"] is False
        assert "R" in p["reason"]


class TestItRefusesRatherThanImprovising:
    def test_no_block_no_plan(self):
        p = _plan(block={"present": False, "reason": "displacement not confirmed"})
        assert p["tradeable"] is False
        assert "no confirmed order block" in p["reason"]

    def test_an_unmitigated_block_is_not_tradeable(self):
        p = _plan(mitigation={"state": "unmitigated"})
        assert p["tradeable"] is False
        assert "has not returned" in p["reason"]

    def test_an_invalidated_block_is_not_tradeable(self):
        assert _plan(mitigation={"state": "invalidated"})["tradeable"] is False

    def test_a_fully_mitigated_block_is_spent(self):
        assert _plan(mitigation={"state": "fully_mitigated"})["tradeable"] is False

    def test_only_the_declared_states_trade(self):
        assert set(TRADEABLE_STATES) == {"touched", "mean_threshold_tagged"}

    def test_a_missing_leg_extreme_is_refused(self):
        p = _plan(leg_extreme=None)
        assert p["tradeable"] is False
        assert "extreme" in p["reason"]

    def test_a_leg_too_short_to_clear_invalidation_is_refused(self):
        """A short leg lifts the swing 50% above the mean threshold, leaving the
        entry zone beyond invalidation. Refuse, and name the cause."""
        p = _plan(leg_extreme=28535.0)
        assert p["tradeable"] is False
        assert "too short" in p["reason"]
        assert _check(p, "entry_zone_inside_invalidation")["pass"] is False


class TestBullishSymmetry:
    def test_a_bullish_setup_mirrors(self):
        block = {"present": True, "side": "bullish",
                 "region": {"count": 3, "anchor_level": 28400.0},
                 "zone": {"body_low": 28440.0, "body_high": 28470.0,
                          "mean_threshold": 28455.0, "block_extreme": 28430.0}}
        p = build_execution_plan(block, TOUCHED, leg_extreme=28600.0)
        assert p["tradeable"] is True
        assert p["stop"] < p["entry"] < p["target"]


class TestTelemetry:
    def test_every_check_is_reported_with_a_reason(self):
        for c in _plan()["checks"]:
            assert c["detail"]

    def test_refusals_still_show_the_checks_that_passed(self):
        p = _plan(invalidation=INVALIDATION_BLOCK_EXTREME)
        assert any(c["pass"] for c in p["checks"])
        assert any(not c["pass"] for c in p["checks"])

    def test_format_renders_the_plan(self):
        out = format_execution_plan(_plan())
        assert "entry zone" in out and "reward:risk" in out
        assert "mean threshold" in out

    def test_format_explains_a_refusal(self):
        out = format_execution_plan(_plan(mitigation={"state": "unmitigated"}))
        assert "NO TRADE" in out

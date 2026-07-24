"""MARKET-CONTEXT — stage 1 authority.

A local event has no directional meaning on its own. These pin that the layer
supplies interpretation authority rather than pattern-matching direction, that it
refuses to interpret when it has none, and that it derives the one environment no
upstream label expresses: retracement, a trending market whose current leg
opposes the dominant bias.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.market_context import (
    analyze_market_context, interpret_local_event, format_market_context,
    HTF, OPERATIVE, LTF,
)


def _structure(htf_bias="bearish", op_bias="bearish", ltf_bias=None,
               alignment="full", hi=28631.25, lo=28254.25):
    return {
        HTF: {"bias": htf_bias, "state": "bearish_continuation",
              "last_swing_high": hi, "last_swing_low": lo},
        OPERATIVE: {"bias": op_bias, "state": "bearish_continuation",
                    "last_swing_high": hi, "last_swing_low": lo},
        LTF: {"bias": ltf_bias or op_bias, "state": "neutral"},
        "alignment": alignment,
    }


def _liq():
    return {HTF: {"nearest_buy_side_liquidity": 28607.25,
                  "nearest_sell_side_liquidity": 28485.75}}


def _ctx(regime="trend_down", price=28542.5, **kw):
    return analyze_market_context(_structure(**kw), _liq(), {}, {},
                                  {"regime_label": regime}, last_price=price)


def _component(ctx, name):
    return next(c for c in ctx["components"] if c["name"] == name)


class TestAlignmentIsADegreeNotADirection:
    """compute_alignment returns full/partial/neutral. Reading it for 'bull'/'bear'
    substrings meant the component could never vote."""

    def test_alignment_confirms_the_htf_direction(self):
        ctx = _ctx(alignment="full")
        c = _component(ctx, "structure_alignment")
        assert c["direction"] == "bearish"
        assert c["weight"] > 0

    def test_partial_alignment_confirms_at_reduced_weight(self):
        full = _component(_ctx(alignment="full"), "structure_alignment")["weight"]
        part = _component(_ctx(alignment="partial"), "structure_alignment")["weight"]
        assert 0 < part < full

    def test_neutral_alignment_casts_no_vote(self):
        assert _component(_ctx(alignment="neutral"), "structure_alignment")["weight"] == 0

    def test_alignment_never_originates_a_direction(self):
        """With no HTF bias, alignment must not manufacture one."""
        ctx = _ctx(htf_bias="neutral", op_bias="neutral", alignment="full")
        assert _component(ctx, "structure_alignment")["direction"] == "neutral"


class TestRetracementEnvironment:
    def test_trending_with_opposing_local_leg_is_retracement(self):
        ctx = _ctx(regime="trend_down", htf_bias="bearish",
                   op_bias="bullish", ltf_bias="bullish")
        assert ctx["environment"] == "retracement"
        assert ctx["alignment"] == "opposed"

    def test_trending_with_agreeing_local_leg_is_trending(self):
        assert _ctx(regime="trend_down")["environment"] == "trending"

    def test_expansion_label_is_preserved_when_aligned(self):
        assert _ctx(regime="expansion_down")["environment"] == "expansion"

    def test_reversal_conditions_take_priority(self):
        ctx = _ctx(regime="reversal_attempt", op_bias="bullish", ltf_bias="bullish")
        assert ctx["environment"] == "reversal_conditions"

    def test_range_labels_map_to_ranging(self):
        for label in ("chop", "range_rotation", "low_volatility"):
            assert _ctx(regime=label)["environment"] == "ranging"


class TestInterpretationAuthority:
    def test_event_agreeing_with_htf_is_continuation(self):
        assert interpret_local_event(_ctx(), "bearish")["reading"] == "continuation"

    def test_counter_trend_event_in_the_wrong_half_is_liquidity_engineering(self):
        """Bullish event, bearish HTF, price in premium — the 2026-07-24 shape."""
        ctx = _ctx(price=28542.5)          # above midpoint 28442.75 -> premium
        assert ctx["dealing_range"]["zone"] == "premium"
        assert interpret_local_event(ctx, "bullish")["reading"] == "liquidity_engineering"

    def test_counter_trend_event_elsewhere_is_a_retracement(self):
        ctx = _ctx(price=28300.0)          # discount
        assert interpret_local_event(ctx, "bullish")["reading"] == "retracement"

    def test_counter_trend_event_under_reversal_conditions_is_a_reversal_candidate(self):
        ctx = _ctx(regime="reversal_attempt", price=28300.0)
        assert interpret_local_event(ctx, "bullish")["reading"] == "reversal_candidate"

    def test_refuses_to_interpret_without_htf_authority(self):
        """The layer must say it does not know, not guess a direction."""
        ctx = _ctx(htf_bias="neutral", op_bias="neutral",
                   ltf_bias="neutral", alignment="neutral", regime="chop")
        assert ctx["htf_bias"] == "neutral"
        for d in ("bullish", "bearish"):
            assert interpret_local_event(ctx, d)["reading"] == "undetermined"

    def test_unknown_event_direction_is_undetermined(self):
        assert interpret_local_event(_ctx(), None)["reading"] == "undetermined"


class TestDealingRange:
    def test_premium_discount_is_relative_to_the_midpoint(self):
        assert _ctx(price=28600.0)["dealing_range"]["zone"] == "premium"
        assert _ctx(price=28300.0)["dealing_range"]["zone"] == "discount"
        assert _ctx(price=28442.75)["dealing_range"]["zone"] == "equilibrium"

    def test_range_is_reported_with_its_source_timeframe(self):
        dr = _ctx()["dealing_range"]
        assert dr["source_tf"] == HTF
        assert dr["high"] > dr["low"] and dr["midpoint"] == 28442.75

    def test_liquidity_positions_are_carried(self):
        dr = _ctx()["dealing_range"]
        assert dr["buy_side_liquidity"] == 28607.25
        assert dr["sell_side_liquidity"] == 28485.75

    def test_missing_swings_do_not_fabricate_a_range(self):
        ctx = analyze_market_context({HTF: {"bias": "bearish"}, "alignment": "neutral"},
                                     {}, {}, {}, {"regime_label": "chop"}, 28500.0)
        assert ctx["dealing_range"]["zone"] == "unknown"


class TestTelemetry:
    def test_every_bias_component_is_reported(self):
        names = {c["name"] for c in _ctx()["components"]}
        assert names == {"htf_structure", "structure_alignment",
                         "regime_label", "operative_structure"}

    def test_each_component_explains_itself(self):
        for c in _ctx()["components"]:
            assert c["detail"]

    def test_both_event_directions_are_pre_read(self):
        readings = _ctx()["event_readings"]
        assert set(readings) == {"bullish", "bearish"}
        assert all("reason" in r for r in readings.values())

    def test_format_renders_range_and_readings(self):
        out = format_market_context(_ctx())
        assert "Market Context:" in out
        assert "Dealing range:" in out and "HTF bias:" in out
        assert "reads as" in out

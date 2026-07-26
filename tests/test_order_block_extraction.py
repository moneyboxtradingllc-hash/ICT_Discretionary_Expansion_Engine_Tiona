"""OB-EXTRACT — the institutional footprint, with candle count as an OUTPUT.

An order block is a variable-length accumulation/distribution region. A valid
block may hold one candle or six and the number carries no predictive value, so
nothing here asserts a count as an input — the counts asserted are results of the
compression walk.

The real 2026-07-24 block is pinned: five candles 11:45-12:05, body zone
28499.25-28604.25, mean threshold 28551.75, anchored to the 12:10 swing at
28631.25. Those OHLC values are real; the leading candles are synthetic and exist
only to establish an ATR baseline, which is called out where it matters.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.order_block_extractor import (
    extract_order_block, format_order_block, COMPRESSION_AT, MAX_REGION,
)


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


# Synthetic prefix — wide-range candles establishing an ~80pt ATR baseline, so the
# real ranges below read as compressed. Not claimed to be real tape.
_PREFIX = [_c(28600 + i, 28640 + i, 28560 + i, 28590 + i) for i in range(14)]

# Real MNQ 5m OHLC, 2026-07-24.
_REAL = [
    _c(28553.5,  28577.0,  28489.5,  28498.75),   # 11:40  range 87.50 — breaks compression
    _c(28499.25, 28531.0,  28491.75, 28512.5),    # 11:45  range 39.25
    _c(28512.75, 28548.5,  28494.25, 28546.5),    # 11:50  range 54.25
    _c(28546.5,  28580.0,  28532.5,  28575.0),    # 11:55  range 47.50
    _c(28575.5,  28583.75, 28548.75, 28580.0),    # 12:00  range 35.00
    _c(28579.75, 28618.25, 28578.5,  28604.25),   # 12:05  range 39.75
    _c(28605.0,  28631.25, 28576.25, 28577.25),   # 12:10  anchor — the failure swing
    _c(28577.25, 28587.5,  28552.5,  28565.25),   # 12:15
]
BARS = _PREFIX + _REAL
STRUCT = {"last_swing_high": 28631.25, "last_swing_low": 28427.0}
AUTH = {"bias": "bearish", "intact": True}
DISP_OK = {"score": 55}
MANIP_OK = {"score": 50}


def _extract(**kw):
    args = {"candles": BARS, "atr": 80.0, "struct": STRUCT, "authority": AUTH,
            "manipulation": MANIP_OK, "displacement": DISP_OK}
    args.update(kw)
    return extract_order_block(args["candles"], args["atr"], args["struct"],
                               args["authority"], args["manipulation"],
                               args["displacement"])


class TestTheRealBlock:
    def test_it_finds_the_2026_07_24_block(self):
        ob = _extract()
        assert ob["present"] is True
        assert ob["side"] == "bearish"
        assert ob["region"]["count"] == 5

    def test_geometry_matches_the_confirmed_block(self):
        z = _extract()["zone"]
        assert z["body_low"] == 28499.25
        assert z["body_high"] == 28604.25
        assert z["mean_threshold"] == 28551.75

    def test_it_anchors_to_the_failure_swing(self):
        r = _extract()["region"]
        assert r["anchor_level"] == 28631.25
        assert r["anchor_index"] == BARS.index(_REAL[6])

    def test_the_uncompressed_candle_bounds_the_region(self):
        """11:40 ranges 87.50 and must terminate the walk-back."""
        r = _extract()["region"]
        assert r["start_index"] == BARS.index(_REAL[1])      # 11:45, not 11:40

    def test_mean_threshold_and_block_extreme_are_both_reported(self):
        z = _extract()["zone"]
        assert z["mean_threshold"] < z["block_extreme"]
        assert z["block_extreme"] == 28618.25                # region high, not the swing


class TestCountIsAnOutput:
    def test_a_single_candle_region_is_valid(self):
        bars = _PREFIX + [
            _c(28500, 28590, 28480, 28580),      # wide — breaks compression
            _c(28580, 28600, 28575, 28595),      # the whole block: one candle
            _c(28595, 28650, 28590, 28600),      # anchor
        ]
        ob = extract_order_block(bars, 80.0, {"last_swing_high": 28650.0},
                                 AUTH, MANIP_OK, DISP_OK)
        assert ob["present"] is True
        assert ob["region"]["count"] == 1

    def test_the_region_is_bounded(self):
        assert _extract()["region"]["count"] <= MAX_REGION

    def test_uniformly_flat_tape_yields_no_block(self):
        """Compression is RELATIVE. Rolling ATR adapts, so a permanently quiet
        market has no compressed candles — it has no contrast to detect. This
        also self-limits the region to roughly the ATR period, which is why
        MAX_REGION is a backstop rather than the usual binding constraint.
        """
        flat = [_c(28500, 28510, 28495, 28505) for _ in range(40)]
        bars = _PREFIX + flat + [_c(28505, 28650, 28500, 28520)]
        ob = extract_order_block(bars, 80.0, {"last_swing_high": 28650.0},
                                 AUTH, MANIP_OK, DISP_OK)
        assert ob["present"] is False
        assert "inventory was not built here" in ob["reason"]


class TestCompressionIsMeasuredAgainstPrevailingVolatility:
    def test_a_frozen_atr_would_misjudge_a_changing_session(self):
        """ATR is evaluated per candle. Judging an earlier region by a later,
        contracted ATR made a genuinely compressed run read as expansion."""
        ob = _extract(atr=40.0)          # a much lower fallback must not shrink it
        assert ob["region"]["count"] == 5

    def test_expansion_candles_are_not_absorbed_into_the_block(self):
        assert all(
            BARS[i]["range"] < COMPRESSION_AT * 80.0 * 1.35
            for i in range(_extract()["region"]["start_index"],
                           _extract()["region"]["end_index"] + 1))


class TestItRefusesRatherThanCompensating:
    def test_no_authority_no_block(self):
        ob = _extract(authority={"bias": "neutral", "intact": False})
        assert ob["present"] is False
        assert "no standing directional authority" in ob["reason"]

    def test_violated_authority_no_block(self):
        ob = _extract(authority={"bias": "bearish", "intact": False})
        assert ob["present"] is False

    def test_unconfirmed_displacement_no_block(self):
        """A compressed region without repricing is not an order block."""
        ob = _extract(displacement={"score": 20})
        assert ob["present"] is False
        assert "compensating" in ob["reason"]

    def test_the_region_is_still_reported_when_refused(self):
        """Refusing must stay auditable — the evidence is shown, not hidden."""
        ob = _extract(displacement={"score": 20})
        assert ob["region"]["count"] == 5
        assert any(e["name"] == "displacement" and not e["present"]
                   for e in ob["evidence"])

    def test_missing_swing_is_reported(self):
        ob = _extract(struct={"last_swing_high": 99999.0})
        assert ob["present"] is False
        assert "does not map" in ob["reason"]

    def test_no_atr_is_reported(self):
        ob = _extract(atr=None)
        assert ob["present"] is False


class TestDirectionComesFromAuthority:
    def test_bullish_authority_anchors_to_the_swing_low(self):
        bars = _PREFIX + [
            _c(28600, 28620, 28510, 28520),     # wide — breaks compression
            _c(28520, 28535, 28505, 28515),
            _c(28515, 28525, 28500, 28510),
            _c(28510, 28520, 28450, 28460),     # anchor at the low
        ]
        ob = extract_order_block(bars, 80.0, {"last_swing_low": 28450.0},
                                 {"bias": "bullish", "intact": True},
                                 MANIP_OK, DISP_OK)
        assert ob["present"] is True
        assert ob["side"] == "bullish"
        assert ob["zone"]["block_extreme"] == min(
            c["low"] for c in bars[ob["region"]["start_index"]:
                                   ob["region"]["end_index"] + 1])


class TestTelemetry:
    def test_every_evidence_item_is_reported_with_a_reason(self):
        ob = _extract()
        names = {e["name"] for e in ob["evidence"]}
        assert names == {"compression", "authority", "displacement", "manipulation"}
        for e in ob["evidence"]:
            assert e["detail"]

    def test_format_states_the_count_is_an_output(self):
        out = format_order_block(_extract())
        assert "an output, not an input" in out
        assert "mean threshold" in out

    def test_format_explains_a_refusal(self):
        out = format_order_block(_extract(displacement={"score": 20}))
        assert "NOT MARKED" in out

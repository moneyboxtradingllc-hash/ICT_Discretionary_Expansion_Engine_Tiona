"""DISPLACEMENT-CONFLUENCE — did institutions commit, or did price drift?

`displacement_detected` was a bare bool: true when any candle in the last five
had a body over an ATR threshold. A 1.4x nudge and a 2.1x drive that tore three
gaps in the tape produced the same value, and PO3's distribution score awarded
the same 30 points for both.

Observed on 2026-07-24: the candles immediately after the order block ran 1.4x
and 0.6x average body while the real expansion and every FVG landed later. These
tests pin that the score separates those, and that the reused imbalance rule
stays identical to price_levels.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.displacement_detector import (
    detect_displacement, format_displacement,
    MAGNITUDE_ATR_MULT, CONFIRMED_AT, W_MAGNITUDE, W_IMBALANCE,
)
from structure.po3_engine import _score_phases
from toolbox.price_levels import find_fvgs, _find_fvg


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


def _drift(n=10, base=28000.0):
    """Price leaves consolidation but teeters — small bodies, no gaps."""
    out = []
    for i in range(n):
        px = base - i * 1.5
        out.append(_c(px, px + 4, px - 4, px - 1.5))
    return out


def _drive(n=10, base=28000.0, step=-30.0):
    """Aggressive expansion: large bodies, gaps between candle 1 and 3."""
    out, px = [], base
    for _ in range(n):
        nxt = px + step
        out.append(_c(px, px + 1, nxt - 1, nxt))     # gap: c1.low > c3.high
        px = nxt
    return out


def _named(d, name):
    return next(c for c in d["components"] if c["name"] == name)


class TestDriftIsNotDisplacement:
    def test_a_drift_does_not_confirm(self):
        d = detect_displacement(_drift(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert d["classification"] != "displacement_confirmed"
        assert _named(d, "displacement_magnitude")["present"] is False

    def test_a_drive_confirms(self):
        d = detect_displacement(_drive(), {"bos": True}, atr=20.0,
                                expansion={"directional_efficiency": 0.65})
        assert d["classification"] == "displacement_confirmed"
        assert d["score"] >= CONFIRMED_AT

    def test_the_two_are_separated_by_a_wide_margin(self):
        drift = detect_displacement(_drift(), {}, atr=20.0, expansion={}, tf_minutes=1)
        drive = detect_displacement(_drive(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert drive["score"] > drift["score"] + 30


class TestMagnitudeIsReportedNotJustFlagged:
    def test_magnitude_is_expressed_in_atr(self):
        d = detect_displacement(_drive(step=-40.0), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert d["magnitude_atr"] >= MAGNITUDE_ATR_MULT
        assert "x atr" in _named(d, "displacement_magnitude")["detail"]

    def test_a_1_4x_body_does_not_clear_the_bar(self):
        """The exact shape seen after the 2026-07-24 block."""
        d = detect_displacement(_drive(step=-28.0), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert d["magnitude_atr"] < MAGNITUDE_ATR_MULT
        assert _named(d, "displacement_magnitude")["present"] is False

    def test_no_atr_is_reported_rather_than_assumed(self):
        d = detect_displacement(_drive(), {}, atr=None, expansion={})
        assert _named(d, "displacement_magnitude")["present"] is False
        assert "no atr" in _named(d, "displacement_magnitude")["detail"]


class TestImbalanceEvidence:
    def test_gaps_left_behind_are_counted(self):
        d = detect_displacement(_drive(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert d["imbalance_count"] > 0
        assert _named(d, "imbalance_created")["present"] is True

    def test_a_drift_leaves_no_imbalance(self):
        d = detect_displacement(_drift(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert d["imbalance_count"] == 0

    def test_the_reused_rule_matches_price_levels(self):
        """find_fvgs must stay the single source of the 3-candle rule."""
        bars = _drive()
        gaps = find_fvgs(bars, "bearish", 1)
        assert gaps, "fixture must actually contain gaps"
        assert _find_fvg(bars, "bearish", 1) == (gaps[0]["low"], gaps[0]["high"])

    def test_no_gaps_gives_no_legacy_zone(self):
        assert _find_fvg(_drift(), "bearish", 1) is None


class TestTelemetry:
    def test_every_component_is_reported_with_a_reason(self):
        d = detect_displacement(_drift(), {}, atr=20.0, expansion={}, tf_minutes=1)
        names = {c["name"] for c in d["components"]}
        assert names == {"displacement_magnitude", "imbalance_created",
                         "structure_break", "directional_efficiency",
                         "follow_through", "no_hesitation"}
        for c in d["components"]:
            assert c["detail"]

    def test_absent_components_keep_their_weight(self):
        d = detect_displacement(_drift(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert _named(d, "imbalance_created")["points"] == 0
        assert _named(d, "imbalance_created")["weight"] == W_IMBALANCE

    def test_insufficient_candles_is_reported(self):
        d = detect_displacement(_drive(3), {}, atr=20.0, expansion={})
        assert d["score"] == 0 and "insufficient" in d["reason"]

    def test_format_renders_totals_and_components(self):
        out = format_displacement(detect_displacement(_drive(), {}, atr=20.0,
                                                      expansion={}))
        assert "Displacement Score:" in out and "/100" in out
        assert "displacement_magnitude" in out


class TestAuthorityCoherenceIsReportedNotEnforced:
    def test_displacement_against_authority_still_scores(self):
        """Counter-authority displacement is real; it is the authority that is
        then in question, and that call is not made here."""
        d = detect_displacement(_drive(), {"bos": True}, atr=20.0,
                                expansion={"directional_efficiency": 0.65},
                                authority={"bias": "bullish", "intact": True})
        assert d["classification"] == "displacement_confirmed"
        assert d["authority_coherence"]["coherent"] is False
        assert "opposes" in d["authority_coherence"]["note"]

    def test_aligned_displacement_is_marked_coherent(self):
        d = detect_displacement(_drive(), {}, atr=20.0, expansion={},
                                authority={"bias": "bearish", "intact": True})
        assert d["authority_coherence"]["coherent"] is True

    def test_no_authority_means_no_coherence_block(self):
        d = detect_displacement(_drive(), {}, atr=20.0, expansion={}, tf_minutes=1)
        assert "authority_coherence" not in d


class TestPo3Integration:
    def test_confluence_scales_the_distribution_term(self):
        strong = _score_phases({}, {}, {}, {"displacement": {"score": 100}})
        weak = _score_phases({}, {}, {}, {"displacement": {"score": 20}})
        assert strong["distribution"] > weak["distribution"]

    def test_the_thirty_point_ceiling_is_preserved(self):
        full = _score_phases({}, {}, {}, {"displacement": {"score": 100}})
        legacy = _score_phases({}, {}, {}, {"displacement_detected": True,
                                            "directional_efficiency": 0.5})
        assert full["distribution"] == legacy["distribution"]

    def test_legacy_scoring_survives_without_a_block(self):
        legacy = _score_phases({}, {}, {}, {"displacement_detected": True,
                                            "directional_efficiency": 0.5})
        assert legacy["distribution"] >= 30

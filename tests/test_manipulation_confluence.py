"""MANIP-CONFLUENCE — manipulation is scored, not pattern-matched.

The assumption being removed: manipulation == liquidity sweep. A sweep is one
expression of it. A failure swing takes no liquidity at all and is still
manipulation. These pin that the score is a confluence, that no single component
is mandatory, and that every component is reported whether or not it fired —
auditability is the deliverable at this stage, ahead of any weight tuning.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.manipulation_detector import (
    detect_manipulation, format_manipulation, CONFIRMED_AT,
    W_EXTERNAL_SWEEP, W_FAILURE_SWING,
)
from structure.po3_engine import _score_phases
from structure import po3_config as cfg


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


def _flat(n, base=28000.0):
    return [_c(base, base + 3, base - 3, base) for _ in range(n)]


def _named(m, name):
    return next(c for c in m["components"] if c["name"] == name)


class TestNoSingleEventIsMandatory:
    def test_sweep_alone_does_not_define_manipulation(self):
        """The old model: manipulation == sweep. Confluence must survive its absence."""
        candles = _flat(20) + [
            _c(28000, 28004, 27980, 27984),   # abandon the level
            _c(27984, 27988, 27960, 27964),
            _c(27964, 27968, 27940, 27944),
            _c(27944, 27948, 27920, 27924),
        ]
        m = detect_manipulation(candles, atr=15.0)
        assert _named(m, "external_sweep")["present"] is False
        assert m["score"] > 0, "confluence must score without a sweep"

    def test_every_component_is_reported_even_when_absent(self):
        m = detect_manipulation(_flat(30), atr=10.0)
        names = {c["name"] for c in m["components"]}
        assert names == {"external_sweep", "internal_raid", "failure_swing",
                         "failed_breakout", "rejection", "rapid_reversal"}
        for c in m["components"]:
            assert c["detail"], f"{c['name']} must explain a zero, not merely be missing"

    def test_absent_components_carry_zero_points_but_keep_their_weight(self):
        m = detect_manipulation(_flat(30), atr=10.0)
        sweep = _named(m, "external_sweep")
        assert sweep["points"] == 0
        assert sweep["weight"] == W_EXTERNAL_SWEEP


class TestScoreShape:
    def test_score_is_capped_at_100(self):
        candles = _flat(20) + [
            _c(28000, 28120, 27995, 28002),
            _c(28002, 28010, 27900, 27905),
            _c(27905, 27910, 27850, 27855),
            _c(27855, 27860, 27800, 27805),
        ]
        m = detect_manipulation(candles, atr=20.0)
        assert 0 <= m["score"] <= 100

    def test_flat_tape_scores_nothing(self):
        m = detect_manipulation(_flat(40), atr=10.0)
        assert m["score"] == 0
        assert m["classification"] == "none"

    def test_insufficient_candles_is_reported_not_guessed(self):
        m = detect_manipulation(_flat(3), atr=10.0)
        assert m["score"] == 0
        assert "insufficient" in m["reason"]

    def test_classification_bands(self):
        assert CONFIRMED_AT > 0
        m = detect_manipulation(_flat(40), atr=10.0)
        assert m["classification"] in ("none", "manipulation_possible",
                                       "manipulation_confirmed")


class TestWindowsAreBounded:
    """Same defect class as LEG-SCOPE: swings drawn from all history describe
    unrelated legs. Pinned as history-length invariance."""

    def test_swing_context_does_not_grow_with_history(self):
        recent = [
            _c(28000, 28040, 27995, 28002),
            _c(28002, 28010, 27950, 27955),
            _c(27955, 27960, 27900, 27905),
            _c(27905, 27910, 27860, 27865),
            _c(27865, 27870, 27820, 27825),
            _c(27825, 27830, 27790, 27795),
        ]
        short = detect_manipulation(_flat(30) + recent, atr=15.0)
        long_ = detect_manipulation(_flat(3000) + recent, atr=15.0)
        assert short["score"] == long_["score"]
        assert ([c["present"] for c in short["components"]]
                == [c["present"] for c in long_["components"]])

    def test_lookback_window_is_capped(self):
        m = detect_manipulation(_flat(500), atr=10.0)
        assert m["lookback"] <= cfg.MANIP_LOOKBACK


class TestRapidReversalRequiresAnAbandonedExtreme:
    def test_a_pure_trend_is_not_a_reversal(self):
        """Window-extreme-to-close always clears an ATR in a trend; that alone
        must not count as a reversal."""
        candles = [_c(28000 - i * 20, 28005 - i * 20, 27980 - i * 20, 27985 - i * 20)
                   for i in range(12)]
        m = detect_manipulation(candles, atr=15.0)
        assert _named(m, "rapid_reversal")["present"] is False


class TestPo3Integration:
    def test_po3_consumes_the_confluence_score(self):
        liq = {"manipulation": {"score": 72}}
        scores = _score_phases({}, liq, {}, {})
        assert scores["manipulation"] == 72

    def test_legacy_scoring_survives_when_no_block_present(self):
        """Hand-built liq dicts (and every pre-existing test) must be unchanged."""
        legacy = _score_phases({}, {"sweep_detected": True, "reclaim_detected": True},
                               {}, {})
        assert legacy["manipulation"] == 40 + 25 + 10

    def test_a_failure_swing_alone_can_carry_the_phase(self):
        """No sweep, no reclaim, no failed breakout — still manipulation."""
        liq = {"manipulation": {"score": W_FAILURE_SWING + 20},
               "sweep_detected": False, "reclaim_detected": False,
               "failed_breakout": False}
        assert _score_phases({}, liq, {}, {})["manipulation"] > 0


class TestTelemetryIsLegible:
    def test_format_lists_every_component_and_the_total(self):
        out = format_manipulation(detect_manipulation(_flat(30), atr=10.0))
        assert "Manipulation Score:" in out
        assert "external_sweep" in out and "failure_swing" in out
        assert "/100" in out and "Classification:" in out

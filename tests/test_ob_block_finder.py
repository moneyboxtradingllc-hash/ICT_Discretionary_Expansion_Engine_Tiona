"""Multi-candle order block finder — pinned to real MNQ 5m bars, 2026-07-24.

The 1:30pm PM-session short: a four/five candle bullish run builds the bearish OB,
the 12:10 failure swing rejects off it, price displaces down to the 13:10 swing low,
then retraces to just shy of the block's mean threshold before selling.

`_find_ob` (single candle, nearest-opposite) cannot represent this block and, at the
13:30 decision point, selects a candle inside the retracement whose invalidation sits
on the wrong side of entry. These tests pin both behaviours.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.price_levels import _find_ob, _find_ob_block, _ob_block_run, _make_zone


def _c(t, o, h, l, c):
    return {"t": t, "open": o, "high": h, "low": l, "close": c,
            "direction": "bullish" if c > o else ("bearish" if c < o else "doji")}


# Real MNQ 5m bars, 2026-07-24 ET.
BARS = [
    _c("11:40", 28553.5,  28577.0,  28489.5,  28498.75),
    _c("11:45", 28499.25, 28531.0,  28491.75, 28512.5),
    _c("11:50", 28512.75, 28548.5,  28494.25, 28546.5),
    _c("11:55", 28546.5,  28580.0,  28532.5,  28575.0),
    _c("12:00", 28575.5,  28583.75, 28548.75, 28580.0),
    _c("12:05", 28579.75, 28618.25, 28578.5,  28604.25),
    _c("12:10", 28605.0,  28631.25, 28576.25, 28577.25),   # failure swing
    _c("12:15", 28577.25, 28587.5,  28552.5,  28565.25),
    _c("12:30", 28577.5,  28581.0,  28527.25, 28536.25),
    _c("12:45", 28506.25, 28511.0,  28468.25, 28475.25),
    _c("13:05", 28476.75, 28488.0,  28435.0,  28443.5),
    _c("13:10", 28443.75, 28466.75, 28427.0,  28456.75),   # swing low
    _c("13:25", 28468.0,  28522.5,  28463.75, 28517.0),
    _c("13:30", 28516.5,  28536.75, 28504.25, 28533.0),
]
STRUCT = {"last_swing_high": 28631.25, "last_swing_low": 28427.0}

SWING_50 = 28529.125    # 50% of 28631.25 -> 28427.0, the entry trigger
PEAK     = 28544.25     # 13:35 retracement high
MAX_STOP = 25.0


class TestBlockSelection:
    def test_run_anchors_to_the_swing_not_the_newest_candle(self):
        run = _ob_block_run(BARS, STRUCT, "bearish")
        assert [c["t"] for c in run] == ["11:45", "11:50", "11:55", "12:00", "12:05"]
        assert all(c["direction"] == "bullish" for c in run)

    def test_run_terminates_on_the_first_opposite_candle(self):
        # 11:40 is bearish and must bound the run.
        assert "11:40" not in [c["t"] for c in _ob_block_run(BARS, STRUCT, "bearish")]

    def test_fails_closed_when_swing_matches_no_candle(self):
        assert _ob_block_run(BARS, {"last_swing_high": 99999.0}, "bearish") == []
        assert _ob_block_run(BARS, {}, "bearish") == []

    def test_single_candle_finder_picks_the_retracement_instead(self):
        # The behaviour that produced NO_TRADE on 2026-07-24.
        zl, zh, inv = _find_ob(BARS, "bearish")
        assert (zl, zh) == (28468.0, 28517.0)      # the 13:25 candle
        assert inv < PEAK                           # invalidation below entry -> wrong side


class TestBlockGeometry:
    def test_zone_spans_the_run_bodies(self):
        zl, zh, inv = _find_ob_block(BARS, STRUCT, "bearish")
        assert (zl, zh) == (28499.25, 28604.25)
        assert inv == 28618.25                      # run's extreme high

    def test_mean_threshold_sits_just_above_the_retracement_peak(self):
        zl, zh, inv = _find_ob_block(BARS, STRUCT, "bearish")
        zone = _make_zone("ob_block_zone", "bearish", zl, zh, inv, PEAK, "5m")
        mean_threshold = zone["midpoint"]
        assert mean_threshold == 28551.75
        assert 0 < mean_threshold - PEAK < 20       # "retraced just shy of the 50%"

    def test_block_extreme_cannot_serve_as_invalidation_under_the_cap(self):
        # Why re-anchoring the stop to the OB high does not rescue the trade:
        # the block is ~105pts tall, so its extreme is no better than the swing high.
        _, _, inv = _find_ob_block(BARS, STRUCT, "bearish")
        assert inv - SWING_50 > MAX_STOP * 3

    def test_mean_threshold_is_the_only_reference_that_fits_the_cap(self):
        zl, zh, inv = _find_ob_block(BARS, STRUCT, "bearish")
        mean_threshold = _make_zone("ob_block_zone", "bearish", zl, zh, inv,
                                    PEAK, "5m")["midpoint"]
        assert mean_threshold - PEAK <= MAX_STOP    # entry at the peak, stop above 50%


class TestBullishSymmetry:
    def test_bullish_setup_anchors_to_the_swing_low(self):
        run = _ob_block_run(BARS, STRUCT, "bullish")
        assert [c["t"] for c in run] == ["12:10", "12:15", "12:30", "12:45", "13:05"]
        assert all(c["direction"] == "bearish" for c in run)

    def test_bullish_invalidation_is_the_run_low(self):
        zl, zh, inv = _find_ob_block(BARS, STRUCT, "bullish")
        assert inv == 28435.0
        assert zl < zh

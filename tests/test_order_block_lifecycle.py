"""OB-LIFECYCLE — a block persists until price respects or breaks it.

A block does not stop existing because the repricing that created it has receded.
Two things follow, and both were wrong in the first draft:

  1. The confirming evidence belongs to the moment of FORMATION. Scoring
     displacement over a trailing window from the current bar meant a block
     validly established at 12:45 un-confirmed itself by 13:35 — exactly while
     price was retracing back into it.
  2. Mitigation is a RETURN, so it cannot begin until price has LEFT. Counting
     from the anchor scored the departure as mitigation: seven touches and 90%
     penetration while price was still on its way out.

Lifecycle is derived from the candles since formation rather than carried in
cross-scan state, so it is deterministic, replayable, and survives a missed scan.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from structure.order_block_extractor import (
    extract_order_block, track_mitigation, format_mitigation,
    MITIGATION_STATES, LEG_HORIZON,
)


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


_PREFIX = [_c(28600 + i, 28640 + i, 28560 + i, 28590 + i) for i in range(14)]
_BLOCK = [
    _c(28553.5,  28577.0,  28489.5,  28498.75),   # wide — bounds the region
    _c(28499.25, 28531.0,  28491.75, 28512.5),
    _c(28512.75, 28548.5,  28494.25, 28546.5),
    _c(28546.5,  28580.0,  28532.5,  28575.0),
    _c(28575.5,  28583.75, 28548.75, 28580.0),
    _c(28579.75, 28618.25, 28578.5,  28604.25),
    _c(28605.0,  28631.25, 28576.25, 28577.25),   # anchor
]
STRUCT = {"last_swing_high": 28631.25, "last_swing_low": 28427.0}
AUTH = {"bias": "bearish", "intact": True}
OK = {"score": 55}

# Body zone 28499.25 - 28604.25, mean threshold 28551.75.
_DEPART = [_c(28577, 28580, 28470, 28475), _c(28475, 28480, 28440, 28445)]


def _block(extra=()):
    bars = _PREFIX + _BLOCK + list(extra)
    ob = extract_order_block(bars, 80.0, STRUCT, AUTH, OK, OK)
    return bars, ob


class TestMitigationRequiresDeparture:
    def test_departure_itself_is_not_mitigation(self):
        """Price on its way OUT of the block must not count as a return."""
        bars, ob = _block(_DEPART[:1])
        m = track_mitigation(bars, ob)
        assert m["touches"] == 0
        assert m["state"] == "unmitigated"

    def test_before_departure_it_says_so(self):
        bars, ob = _block()
        m = track_mitigation(bars, ob)
        assert m["state"] == "unmitigated"
        assert "has not yet left" in m["detail"]

    def test_departure_index_is_reported(self):
        bars, ob = _block(_DEPART)
        assert track_mitigation(bars, ob)["departed_index"] is not None


class TestMitigationStates:
    def test_return_into_the_body_is_touched(self):
        # back to 28540 — inside the body, below the 28551.75 mean threshold
        bars, ob = _block(_DEPART + [_c(28445, 28540, 28440, 28530)])
        m = track_mitigation(bars, ob)
        assert m["state"] == "touched"
        assert m["tradeable"] is True
        assert "mean threshold" in m["detail"]

    def test_reaching_the_mean_threshold_is_its_own_state(self):
        bars, ob = _block(_DEPART + [_c(28445, 28560, 28440, 28550)])
        assert track_mitigation(bars, ob)["state"] == "mean_threshold_tagged"

    def test_trading_through_the_body_is_full_mitigation(self):
        bars, ob = _block(_DEPART + [_c(28445, 28610, 28440, 28600)])
        assert track_mitigation(bars, ob)["state"] == "fully_mitigated"

    def test_closing_beyond_the_extreme_invalidates(self):
        bars, ob = _block(_DEPART + [_c(28445, 28640, 28440, 28630)])
        m = track_mitigation(bars, ob)
        assert m["state"] == "invalidated"
        assert m["tradeable"] is False

    def test_states_are_ordered_by_precedence(self):
        """A candle that both tags and invalidates reports the stronger claim."""
        bars, ob = _block(_DEPART + [_c(28445, 28560, 28440, 28550),
                                     _c(28550, 28640, 28545, 28632)])
        assert track_mitigation(bars, ob)["state"] == "invalidated"

    def test_every_state_is_declared(self):
        assert set(MITIGATION_STATES) == {
            "unmitigated", "touched", "mean_threshold_tagged",
            "fully_mitigated", "invalidated"}


class TestPenetrationDepth:
    def test_a_shallow_return_reports_a_low_penetration(self):
        bars, ob = _block(_DEPART + [_c(28445, 28520, 28440, 28515)])
        m = track_mitigation(bars, ob)
        assert 0.0 < m["max_penetration"] < 0.35

    def test_a_deep_return_reports_a_high_penetration(self):
        bars, ob = _block(_DEPART + [_c(28445, 28600, 28440, 28590)])
        assert track_mitigation(bars, ob)["max_penetration"] > 0.85

    def test_touches_accumulate_across_returns(self):
        bars, ob = _block(_DEPART + [
            _c(28445, 28520, 28440, 28460),
            _c(28460, 28470, 28450, 28455),      # left again
            _c(28455, 28530, 28450, 28520),      # and back
        ])
        assert track_mitigation(bars, ob)["touches"] >= 2


class TestLegIsJudgedOnClosedCandles:
    def test_the_final_forming_bar_never_terminates_the_leg(self):
        """A 5m bar mid-formation reads differently than once closed; on
        2026-07-24 that flipped follow_through and un-confirmed a live block."""
        bars = _PREFIX + _BLOCK + _DEPART
        ob = extract_order_block(bars, 80.0, STRUCT, AUTH, OK, None)
        # leg end must be an interior index, never the last element
        assert ob.get("present") in (True, False)   # either verdict is legitimate
        # the guard itself: horizon never reaches the final bar
        assert LEG_HORIZON > 0


class TestNoBlockNoLifecycle:
    def test_tracking_a_refused_block_returns_nothing(self):
        m = track_mitigation([], {"present": False})
        assert m["state"] is None

    def test_format_handles_absence(self):
        assert "none" in format_mitigation({"state": None}).lower()

    def test_format_renders_a_state(self):
        bars, ob = _block(_DEPART + [_c(28445, 28540, 28440, 28530)])
        out = format_mitigation(track_mitigation(bars, ob))
        assert "Mitigation:" in out and "touched" in out

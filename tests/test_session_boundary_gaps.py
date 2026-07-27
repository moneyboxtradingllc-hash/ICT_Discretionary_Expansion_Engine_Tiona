"""SESSION-BOUNDARY — a break in the clock is not an imbalance in the market.

The 3-candle FVG rule treated the last bar before a session close and the first
bar after the reopen as adjacent, manufacturing a phantom gap out of the break.
On MNQ that is ~33 points across the nightly 17:00-18:00 close and ~195 points
across a weekend.

Observed live on 2026-07-26: the phantom became the preferred toolbox zone
(bullish_ifvg, 28308-28604.5, 296 points wide), its edge became the structural
invalidation, and the risk engine rejected a 300.25-point stop against a 25-point
cap. The bot looked fearful. It was being handed a level manufactured by a clock.

The daily case matters more than the weekend one: ~33 points clears the 25-point
stop cap on its own, every single night.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.price_levels import find_fvgs, _find_fvg, _bar_span_tolerance


def _c(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else "bearish"}


def _contiguous_with_gap():
    """A real bullish FVG inside one session: c1.high 100 < c3.low 110."""
    return [
        _c("2026-07-27T10:00:00-04:00", 95, 100, 94, 99),
        _c("2026-07-27T10:03:00-04:00", 99, 112, 98, 111),
        _c("2026-07-27T10:06:00-04:00", 111, 118, 110, 117),
    ]


def _across_the_close():
    """Same price shape, but the three bars straddle the 17:00-18:00 break."""
    return [
        _c("2026-07-27T16:54:00-04:00", 95, 100, 94, 99),
        _c("2026-07-27T16:57:00-04:00", 99, 112, 98, 111),
        _c("2026-07-27T18:03:00-04:00", 111, 118, 110, 117),
    ]


def _padded(bars):
    """Prefix contiguous bars so the median bar interval is measurable."""
    pre = [_c(f"2026-07-27T09:{30 + 3 * i:02d}:00-04:00", 90, 91, 89, 90)
           for i in range(6)]
    return pre + bars


class TestARealGapIsStillFound:
    def test_contiguous_imbalance_is_detected(self):
        gaps = find_fvgs(_padded(_contiguous_with_gap()), "bullish")
        assert gaps, "a genuine in-session FVG must still be found"
        assert gaps[0]["low"] == 100 and gaps[0]["high"] == 110

    def test_legacy_helper_agrees(self):
        bars = _padded(_contiguous_with_gap())
        g = find_fvgs(bars, "bullish")[0]
        assert _find_fvg(bars, "bullish") == (g["low"], g["high"])


class TestTheBreakIsNotAnImbalance:
    def test_a_gap_across_the_session_close_is_rejected(self):
        assert find_fvgs(_padded(_across_the_close()), "bullish") == []

    def test_the_same_prices_differ_only_by_their_timestamps(self):
        """Identical OHLC. Only the clock changes — and that must decide it."""
        inside = _padded(_contiguous_with_gap())
        across = _padded(_across_the_close())
        assert [(b["open"], b["high"], b["low"], b["close"]) for b in inside] == \
               [(b["open"], b["high"], b["low"], b["close"]) for b in across]
        assert find_fvgs(inside, "bullish") and not find_fvgs(across, "bullish")

    def test_a_weekend_break_is_rejected(self):
        bars = _padded([
            _c("2026-07-24T16:57:00-04:00", 95, 100, 94, 99),
            _c("2026-07-24T17:00:00-04:00", 99, 112, 98, 111),
            _c("2026-07-26T18:03:00-04:00", 111, 118, 110, 117),
        ])
        assert find_fvgs(bars, "bullish") == []


class TestToleranceIsDerivedFromTheSeries:
    def test_tolerance_scales_with_the_bar_interval(self):
        m3 = _padded(_contiguous_with_gap())
        m15 = [dict(b, timestamp=f"2026-07-27T{10 + i // 4:02d}:{(i % 4) * 15:02d}:00-04:00")
               for i, b in enumerate(m3)]
        assert _bar_span_tolerance(m15) > _bar_span_tolerance(m3)

    def test_no_timestamps_falls_back_to_the_price_rule(self):
        """Existing callers and fixtures pass candles without timestamps; they
        must keep working exactly as before."""
        bars = [{k: v for k, v in b.items() if k != "timestamp"}
                for b in _padded(_contiguous_with_gap())]
        assert _bar_span_tolerance(bars) is None
        assert find_fvgs(bars, "bullish")

    def test_unparseable_timestamps_fall_back(self):
        bars = [dict(b, timestamp="not-a-date")
                for b in _padded(_contiguous_with_gap())]
        assert find_fvgs(bars, "bullish")


class TestTheDailyBreakIsTheDangerousOne:
    def test_a_nightly_break_gap_would_have_cleared_the_stop_cap(self):
        """~33 points across 17:00-18:00 exceeds the 25-point structural cap on
        its own — the weekend is dramatic, the nightly break is the one that
        would have fired every session."""
        from integrations.ninjatrader.deterministic import MAX_STOP_POINTS
        assert 32.75 > MAX_STOP_POINTS

"""LEG-SCOPE — conviction ratios must describe the current leg, not the dataset.

The defect these pin: detect_expansion received the full normalized history
(~2000+ candles live). directional_efficiency is net travel / sum of all candle
ranges, so the denominator grew without bound while the numerator could not —
the metric decayed toward 0 no matter what price did. Measured on MNQ
2026-07-24: 0.015 over 2000 1m candles vs 0.104 over 100.

Downstream that pinned PO3 to "accumulation" on every timeframe of every scan:
accumulation collected a free +40 (dir_eff < 0.25, and compression > 60 via
(1-dir_eff)*50), distribution was denied its +20 (dir_eff >= 0.40), and
clean_disp (dir_eff >= 0.30) became unreachable so displacement scored 10
instead of 30.

The existing suite missed it because every test passed short candle lists, where
the unbounded window and a scoped window coincide. The decisive property is
therefore INVARIANCE TO HISTORY LENGTH, which is what these tests assert.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from volatility.expansion_detector import (
    detect_expansion, _leg_slice, _leg_start_index, _directional_efficiency,
)
from structure import po3_config as cfg
from structure.structure_engine import analyze_structure


@pytest.fixture(autouse=True)
def _flag_is_explicit(monkeypatch):
    """These tests assert leg-scope behaviour, so they must state the flag.

    The live launch script exports PO3_LEG_SCOPED_METRICS=off (the fix is shipped
    but parked until its thresholds are recalibrated on forward sessions). Without
    this, running the suite the way production runs turned 8 tests red for reasons
    unrelated to any change under test. Clearing the var pins them to the CODE
    default, which is what they are actually about; the off-path test overrides it
    below.
    """
    monkeypatch.delenv("PO3_LEG_SCOPED_METRICS", raising=False)


def _candle(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c,
            "range": h - l, "body_size": abs(c - o),
            "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
            "direction": "bullish" if c > o else ("bearish" if c < o else "neutral")}


def _noise(n, base=28000.0):
    """Choppy, non-directional filler — inflates total travel, adds no net move."""
    out = []
    for i in range(n):
        up = i % 2 == 0
        o = base + (5 if up else -5)
        c = base - (5 if up else -5)
        out.append(_candle(o, base + 20, base - 20, c))
    return out


def _clean_leg(n=10, start=28600.0, step=-14.0):
    """An efficient directional leg: net travel large relative to total range."""
    out = []
    px = start
    for _ in range(n):
        o = px
        c = px + step
        out.append(_candle(o, max(o, c) + 2, min(o, c) - 2, c))
        px = c
    return out


ATR = {"atr": 20.0, "atr_trend": "stable"}


class TestHistoryLengthInvariance:
    """The property that was violated: identical recent action, different history."""

    def test_dir_eff_does_not_decay_as_history_grows(self):
        leg = _clean_leg()
        short = detect_expansion(_noise(30) + leg, ATR, "5m")
        long_ = detect_expansion(_noise(2000) + leg, ATR, "5m")
        assert short["directional_efficiency"] == long_["directional_efficiency"]

    def test_body_dominance_does_not_decay_as_history_grows(self):
        leg = _clean_leg()
        short = detect_expansion(_noise(30) + leg, ATR, "5m")
        long_ = detect_expansion(_noise(2000) + leg, ATR, "5m")
        assert short["body_dominance"] == long_["body_dominance"]

    def test_the_legacy_window_really_did_collapse(self):
        """Guards the premise: without scoping the metric is history-dependent."""
        leg = _clean_leg()
        assert (_directional_efficiency(_noise(2000) + leg)
                < _directional_efficiency(_noise(30) + leg))


class TestWindowIsAlwaysBounded:
    def test_bounded_even_without_structure(self):
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, None)) <= cfg.LEG_MAX_CANDLES

    def test_bounded_when_structure_has_no_usable_pivot(self):
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, {"last_swing_high": 99999.0})) <= cfg.LEG_MAX_CANDLES

    def test_floor_prevents_a_two_candle_leg(self):
        candles = _noise(50) + _clean_leg()
        struct = {"last_swing_high": candles[-2]["high"]}
        assert len(_leg_slice(candles, struct)) >= cfg.LEG_MIN_CANDLES

    def test_short_series_is_returned_whole(self):
        candles = _clean_leg(5)
        assert len(_leg_slice(candles, None)) == len(candles)


def _stamped(i, o, h, l, c):
    out = _candle(o, h, l, c)
    out["timestamp"] = f"2026-08-12T15:{i:02d}:00+00:00"
    out["volume"] = 10
    return out


def _v_tape(prices, base=28000.0):
    """Real geometry: the swing detector decides what a pivot is, not the test."""
    return [_stamped(i, base + p, base + p + 1, base + p - 1, base + p + 0.5)
            for i, p in enumerate(prices)]


def _old_price_search(candles, struct):
    """The REPLACED algorithm. Kept so these regressions can be shown to fail
    against the implementation they replaced — a fixture that cannot fail
    against the defect is not evidence."""
    if not isinstance(struct, dict) or not candles:
        return None
    found = []
    for key, extreme in (("last_swing_high", "high"), ("last_swing_low", "low")):
        lvl = struct.get(key)
        if not isinstance(lvl, (int, float)):
            continue
        for i in range(len(candles) - 1, -1, -1):
            if abs(float(candles[i][extreme]) - float(lvl)) <= 1e-6:
                found.append(i)
                break
    return max(found) if found else None


class TestPivotAnchoring:
    """STEP 4B.12 §4 UNIT 4 — rebuilt around REAL occurrences.

    These fixtures used to hand `_leg_start_index` a struct containing only a
    PRICE, taken from a candle chosen by position and then called a pivot:

        pivot_price = candles[-15]["low"]
        _leg_start_index(candles, {"last_swing_low": pivot_price})

    Nothing in that tape was ever a detected swing. The old implementation could
    not tell an authoritative occurrence from any candle at the same price, which
    is precisely why the fixture passed -- it asserted the defect's contract while
    claiming to assert pivot anchoring.

    The tapes below contain real geometry, the authoritative structure engine
    decides which occurrence is the swing, and a later candle revisits that exact
    price so identity has something to be stolen by.
    """

    #: A V-shaped low that IS certified, then a revisit of the same price in the
    #: unconfirmed tail -- the live shape: on 1m the high 29843.00 was made at
    #: 15:43 and touched again at 15:51, and the old search took the touch.
    DECOY_TAPE = [50, 44, 38, 32, 26, 20, 26, 32, 38, 44, 50, 44, 38, 32, 26, 20]

    def test_leg_starts_at_the_most_recent_pivot(self):
        """Named for the proposition it must prove: the MOST RECENT occurrence.

        An earlier draft asserted only `origin != decoy` and `origin in (hi, lo)`.
        An implementation returning the OLDER of two genuine pivots would have
        satisfied that, so the assertion did not carry the test's name.
        """
        candles = _v_tape(self.DECOY_TAPE)
        struct = analyze_structure(candles, allow_uncadenced=True)

        hi = struct["last_swing_high_pivot_index"]
        lo = struct["last_swing_low_pivot_index"]
        assert lo == 5 and candles[lo]["low"] == struct["last_swing_low"]

        decoy = [i for i, c in enumerate(candles)
                 if abs(c["low"] - struct["last_swing_low"]) <= 1e-6 and i != lo]
        assert decoy == [15], "the fixture must contain a same-price decoy"

        expected = max(i for i in (hi, lo) if isinstance(i, int))
        origin = _leg_start_index(candles, struct)
        assert origin == expected, "the leg must begin at the MOST RECENT pivot"
        assert origin != 15, "a later revisit may not become the leg origin"

        # and the defect is real: the replaced algorithm chose the decoy
        assert _old_price_search(candles, struct) == 15

    def test_most_recent_of_the_two_pivots_wins(self):
        """The doctrine is unchanged: the later of the two EXACT occurrences."""
        candles = _v_tape(self.DECOY_TAPE)
        struct = analyze_structure(candles, allow_uncadenced=True)
        hi = struct["last_swing_high_pivot_index"]
        lo = struct["last_swing_low_pivot_index"]
        assert isinstance(hi, int) and isinstance(lo, int) and hi != lo

        # price and index describe the SAME object on both sides
        assert candles[hi]["high"] == struct["last_swing_high"]
        assert candles[lo]["low"] == struct["last_swing_low"]

        assert _leg_start_index(candles, struct) == max(hi, lo)
        # not the same-price revisit that the old search preferred
        assert _leg_start_index(candles, struct) != _old_price_search(candles, struct)

    def test_missing_pivot_identity_does_not_fall_back_to_price(self):
        """RENAMED from `test_no_pivot_match_returns_none`.

        That test asserted "no candle extreme matches the price, so None". The
        engine no longer matches prices at all, so it passed for a reason its
        name no longer described -- misleading green coverage. The proposition
        worth freezing is the opposite and much stronger: a matching price is
        PRESENT and is still refused, because identity is absent.
        """
        candles = _v_tape(self.DECOY_TAPE)
        struct = analyze_structure(candles, allow_uncadenced=True)
        price_only = {"last_swing_high": struct["last_swing_high"],
                      "last_swing_low": struct["last_swing_low"]}

        # the price is right there in the series and the old search finds it
        assert _old_price_search(candles, price_only) == 15
        # ...and identity being absent means the answer is unknown, not guessed
        assert _leg_start_index(candles, price_only) is None
        assert _leg_start_index(candles, None) is None

    def test_the_producer_never_pairs_a_price_with_another_occurrences_index(self):
        """Price from occurrence A + index from occurrence B would rebuild the
        defect with extra steps."""
        candles = _v_tape(self.DECOY_TAPE)
        struct = analyze_structure(candles, allow_uncadenced=True)
        for level_key, index_key, extreme in (
                ("last_swing_high", "last_swing_high_pivot_index", "high"),
                ("last_swing_low", "last_swing_low_pivot_index", "low")):
            lvl, idx = struct[level_key], struct[index_key]
            if lvl is None:
                assert idx is None
                continue
            assert candles[idx][extreme] == lvl


class TestScoringConsequences:
    def test_clean_leg_clears_the_thresholds_it_previously_could_not(self):
        """dir_eff >= 0.30 is clean_disp; >= 0.40 is distribution's bonus."""
        out = detect_expansion(_noise(2000) + _clean_leg(12), ATR, "5m")
        assert out["directional_efficiency"] >= 0.30

    def test_choppy_tape_still_reads_as_low_efficiency(self):
        """The fix must not simply inflate the metric — noise stays noise."""
        out = detect_expansion(_noise(2000), ATR, "5m")
        assert out["directional_efficiency"] < 0.25

    def test_telemetry_reports_the_slice_used(self):
        out = detect_expansion(_noise(2000) + _clean_leg(), ATR, "5m")
        assert out["leg_scoped"] is True
        assert 0 < out["leg_candles"] <= cfg.LEG_MAX_CANDLES


class TestKillSwitch:
    def test_off_restores_the_unbounded_window(self, monkeypatch):
        monkeypatch.setenv("PO3_LEG_SCOPED_METRICS", "off")
        candles = _noise(2000) + _clean_leg()
        assert len(_leg_slice(candles, None)) == len(candles)

    def test_on_by_default(self):
        assert cfg.leg_scope_enabled() is True

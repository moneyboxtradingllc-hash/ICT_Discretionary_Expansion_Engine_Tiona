"""OBSERVATION COUNT MAY NEVER MASQUERADE AS ELAPSED MARKET TIME.

`fetch_1m_candles(lookback_bars=300)` means "the last 300 records I happen to
possess". Against the sparse store V13 actually had, that reached from
2026-08-07 to 2026-08-11 -- three calendar days, six gaps, 5,414 missing
minutes -- and `timeframe_builder` calmly turned the stitched result into
apparent 3m/5m/15m bars.

`find_swings` then did exactly what it was told: compare neighbouring records.
It was MECHANICALLY CORRECT for its input. What was wrong is that its input
contract never required those records to be adjacent in TIME. 29,752.50 became
a 5m/15m swing low in that fictional topology -- it is not a pivot on any
timeframe of the continuous tape -- and from there it became the
`nearest_sell_side` draw Terra was handed.

    fictional temporal adjacency
        -> valid pivot geometry INSIDE the fiction
        -> nearest_sell_side
        -> opposing_external_liquidity
        -> Terra's active draw

Nothing hallucinated. Every component reasoned correctly inside a world whose
time had been fabricated.

A second, subtler case is covered here too: even a perfectly continuous window
yields a LEADING partial higher-timeframe bucket when it starts mid-bucket --
measured at 10 of 15 one-minute constituents, shape-identical to a complete
bar. A pivot confirmed against it is confirmed against a bar that never
existed. Aligning the window start removes the class without touching the
aggregator; the TRAILING partial bucket is deliberately kept, because that is
the forming bar live scanning wants.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.topstepx_production_loop import ProductionLoop        # noqa: E402
from data_feed import candle_continuity as CONT                   # noqa: E402
from data_feed.timeframe_builder import build_timeframes          # noqa: E402
from structure.structure_engine import find_swings                # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")


def clean() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def bars(count, start="2026-08-11T13:30:00+00:00", price=29800.0):
    base = datetime.fromisoformat(start)
    return [{"timestamp": (base + timedelta(minutes=i)).isoformat(),
             "open": price, "high": price + 2, "low": price - 2,
             "close": price, "volume": 1} for i in range(count)]


def stitched():
    """The V13 shape: two coherent islands separated by days."""
    return bars(200, "2026-08-07T15:49:00+00:00") + bars(100, "2026-08-11T13:30:00+00:00")


# ══════════════════════════════════════════════════════════════════════════════
class TestABarCountCannotCrossADiscontinuity:

    def test_the_window_stops_at_the_gap(self):
        window = CONT.coherent_window(stitched(), horizon_minutes=300,
                                      minimum_bars=60)
        assert window["sufficient"] is True
        days = {b["timestamp"][:10] for b in window["window"]}
        assert days == {"2026-08-11"}, f"the window spanned {days}"

    def test_it_never_reaches_back_days_to_fill_a_quota(self):
        window = CONT.coherent_window(stitched(), horizon_minutes=300,
                                      minimum_bars=60)
        assert window["bars"] < 300
        assert window["discarded_as_incoherent"] >= 200

    def test_the_horizon_bounds_elapsed_time_not_record_count(self):
        window = CONT.coherent_window(bars(600), horizon_minutes=120,
                                      minimum_bars=60)
        assert window["span_minutes"] <= 121, window["span_minutes"]

    def test_a_contiguous_tail_stops_at_the_first_discontinuity(self):
        tail = CONT.contiguous_tail(stitched())
        assert len(tail) == 100
        assert tail[0]["timestamp"].startswith("2026-08-11")


class TestInsufficientHistoryIsDegradationNotPermission:

    def test_too_little_coherent_history_is_refused(self):
        window = CONT.coherent_window(bars(200, "2026-08-07T15:49:00+00:00")
                                      + bars(5, "2026-08-11T13:30:00+00:00"),
                                      horizon_minutes=300, minimum_bars=60)
        assert window["sufficient"] is False
        assert window["bars"] < 60

    def test_the_refusal_names_which_kind_of_emptiness(self):
        """Nothing-at-all and too-little-to-align are different facts."""
        nothing = CONT.coherent_window([], horizon_minutes=300, minimum_bars=60)
        assert nothing["reason"] == "no contiguous history"
        thin = CONT.coherent_window(bars(2, "2026-08-11T13:31:00+00:00"),
                                    horizon_minutes=300, minimum_bars=60)
        assert "survive alignment" in thin["reason"], thin["reason"]

    def test_a_short_but_sufficient_window_is_accepted(self):
        window = CONT.coherent_window(bars(90), horizon_minutes=300, minimum_bars=60)
        assert window["sufficient"] is True and window["bars"] >= 60


class TestDerivedTimeframesInheritNoFabricatedBar:

    def test_the_window_starts_on_a_bucket_boundary(self):
        window = CONT.coherent_window(clean(), horizon_minutes=300, minimum_bars=20)
        first = CONT.parse_ts(window["window"][0]["timestamp"])
        assert first.minute % CONT.COARSEST_TIMEFRAME_MINUTES == 0

    def test_no_LEADING_partial_bucket_survives(self):
        window = CONT.coherent_window(clean(), horizon_minutes=300, minimum_bars=20)
        membership = CONT.bucket_membership(window["window"], 15)
        assert membership[0]["complete"] is True, membership[0]

    def test_the_TRAILING_forming_bucket_is_kept(self):
        """Live scanning wants the in-progress bar; it is honest, not fabricated."""
        window = CONT.coherent_window(clean(), horizon_minutes=300, minimum_bars=20)
        membership = CONT.bucket_membership(window["window"], 15)
        assert membership[-1]["complete"] is False
        assert membership[-1]["members"] < 15

    def test_the_unaligned_window_DOES_carry_a_false_leading_bar(self):
        """Proof the alignment is doing work, not decorating."""
        membership = CONT.bucket_membership(clean(), 15)
        assert membership[0]["complete"] is False
        assert membership[0]["members"] == 10

    def test_membership_is_statable_for_every_timeframe(self):
        window = CONT.coherent_window(clean(), horizon_minutes=300, minimum_bars=20)
        for minutes in (3, 5, 15):
            first = CONT.bucket_membership(window["window"], minutes)[0]
            assert first["expected"] == minutes and first["complete"] is True


class TestTheV13GoldRegression:
    """The exact store V13 had, as the shape that must never recur."""

    def store(self):
        path = os.path.join(ROOT, "data", "market_data", "topstepx",
                            "CON_F_US_MNQ_U26.jsonl")
        if not os.path.exists(path):
            pytest.skip("the live V13 store is not retained on this machine")
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return sorted([r for r in rows
                       if r["timestamp"] <= "2026-08-11T15:02:00+00:00"],
                      key=lambda r: r["timestamp"])

    def test_the_old_behaviour_really_did_span_three_days(self):
        old = self.store()[-300:]
        assert len({r["timestamp"][:10] for r in old}) == 3
        assert CONT.summarize(old)["missing_minutes"] > 5000

    def test_the_new_window_refuses_that_store(self):
        window = CONT.coherent_window(self.store(), horizon_minutes=300,
                                      minimum_bars=60)
        assert window["sufficient"] is False
        assert window["bars"] < 60

    def test_it_never_yields_a_multi_day_window(self):
        window = CONT.coherent_window(self.store(), horizon_minutes=300,
                                      minimum_bars=60)
        days = {b["timestamp"][:10] for b in window["window"]}
        assert len(days) <= 1, f"a recent window spanned {days}"

    def test_29752_50_is_not_a_pivot_on_a_COHERENT_window(self):
        """The level that became Terra's draw. Under a coherent window the
        production detector does not find it on any timeframe."""
        window = CONT.coherent_window(clean(), horizon_minutes=300, minimum_bars=20)
        for tf, series in build_timeframes(window["window"]).items():
            _, lows = find_swings(series)
            assert not any(abs(low - 29752.5) < 1e-9 for low in lows), tf


class TestTheProductionLoopUsesTheWindow:

    def test_the_scan_path_builds_a_coherent_window(self):
        import inspect
        source = inspect.getsource(ProductionLoop._scan_once)
        assert "coherent_window" in source, \
            "the scan path still reasons over a raw bar count"

    def test_it_refuses_before_the_cycle_sees_the_tape(self):
        import inspect
        source = inspect.getsource(ProductionLoop._scan_once)
        assert source.index("coherent_window") < source.index("self.cycle.scan("), \
            "the cycle scanned an incoherent tape"

    def test_the_horizon_is_expressed_in_TIME(self):
        assert ProductionLoop.HISTORY_HORIZON_MINUTES > 0
        assert ProductionLoop.HISTORY_MINIMUM_BARS > 0

    def test_the_refusal_is_reported_not_silent(self):
        import inspect
        source = inspect.getsource(ProductionLoop._scan_once)
        assert "incoherent market history" in source


class TestTheLoopACTUALLYRefuses:
    """Q6 and Q7 escaped the first campaign. Both source-inspection tests kept
    passing while the behaviour was neutered: the string `coherent_window` was
    still present, so `if False:` and a discarded result changed nothing the
    tests could see.

    A source assertion proves a call was not DELETED. It cannot prove the call
    was not DEFEATED. These run the loop.
    """

    def loop_with(self, tmp_path, tape):
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_production_scan_loop import Candles, build
        loop, _, _, _ = build(tmp_path, armed=False, candles=Candles(tape))
        return loop

    def test_a_stitched_tape_is_TRIMMED_not_refused(self, tmp_path):
        """The contract is not "block anything imperfect". A stitched tape whose
        recent island is long enough is USED -- with the older records
        discarded. My first version of this test asserted a refusal and was
        simply wrong about the contract."""
        loop = self.loop_with(tmp_path, stitched())
        loop.scan_once()
        assert loop.last_window["sufficient"] is True
        assert loop.last_window["discarded_as_incoherent"] >= 200
        days = {b["timestamp"][:10] for b in loop.last_window["window"]}
        assert days == {"2026-08-11"}, days

    def test_a_stitched_tape_with_a_SHORT_island_is_refused(self, tmp_path):
        tape = bars(200, "2026-08-07T15:49:00+00:00") + bars(8, "2026-08-11T13:30:00+00:00")
        out = self.loop_with(tmp_path, tape).scan_once()
        assert out["outcome"] == "NO_CANDLES", out
        assert "incoherent market history" in out["detail"]

    def test_a_thin_tape_produces_NO_CANDLES(self, tmp_path):
        out = self.loop_with(tmp_path, bars(10)).scan_once()
        assert out["outcome"] == "NO_CANDLES", out

    def test_a_coherent_tape_is_NOT_refused(self, tmp_path):
        """The gate must not simply block everything."""
        out = self.loop_with(tmp_path, bars(90)).scan_once()
        assert out["outcome"] != "NO_CANDLES", out

    def test_the_cycle_receives_the_TRIMMED_window_not_the_raw_tape(self, tmp_path):
        """Q7: discarding the window silently would leave the cycle reasoning
        over the stitched tape while the verdict said everything was fine."""
        seen = {}
        loop = self.loop_with(tmp_path, stitched() + bars(30, "2026-08-11T15:10:00+00:00"))
        original = loop.cycle.scan

        def spy(candles_1m, **kwargs):
            seen["days"] = {c["timestamp"][:10] for c in candles_1m}
            seen["n"] = len(candles_1m)
            return original(candles_1m, **kwargs)

        loop.cycle.scan = spy
        loop.scan_once()
        if seen:                       # only if the window was sufficient
            assert seen["days"] == {"2026-08-11"}, seen["days"]
            assert seen["n"] < 300

    def test_the_window_verdict_is_recorded_for_evidence(self, tmp_path):
        tape = bars(200, "2026-08-07T15:49:00+00:00") + bars(8, "2026-08-11T13:30:00+00:00")
        loop = self.loop_with(tmp_path, tape)
        loop.scan_once()
        assert loop.last_window is not None
        assert loop.last_window["sufficient"] is False
        assert loop.last_window["discarded_as_incoherent"] > 0

    def test_a_long_CONTINUOUS_tape_is_still_bounded_by_the_horizon(self, tmp_path):
        """Q9 escaped: contiguity alone defends most of this, because a stitched
        tape cannot cross its own gap whatever the horizon says. But a genuinely
        UNBROKEN three-day run is coherent and still not "recent history" -- the
        horizon is what makes the window a window rather than an archive."""
        long_tape = bars(3 * 24 * 60, "2026-08-08T13:30:00+00:00")
        loop = self.loop_with(tmp_path, long_tape)
        loop.scan_once()
        window = loop.last_window
        assert window["sufficient"] is True
        assert window["span_minutes"] <= ProductionLoop.HISTORY_HORIZON_MINUTES + 1, \
            f"a {window['span_minutes']}-minute window is not recent history"
        assert window["discarded_as_incoherent"] > 0

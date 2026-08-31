"""Unit tests for the deterministic expectancy backtest trade-resolution math.

Pure-function tests (no pipeline, no data files, no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.topstepx.deterministic.backtest import simulate_trade  # noqa: E402

LONG, SHORT = "long", "short"


def _b(h, l, c=None):
    return {"high": h, "low": l, "close": c if c is not None else (h + l) / 2}


class TestSimulateTrade(unittest.TestCase):
    def test_long_target_hit(self):
        bars = [_b(100, 100), _b(101, 99), _b(136, 120)]  # bar2 high reaches +35 target
        r = simulate_trade(bars, 0, LONG, fill=100.0, stop=90.0, target=135.0, exit_deadline_idx=2)
        self.assertEqual(r["exit_reason"], "target")
        self.assertEqual(r["points"], 35.0)
        self.assertEqual(r["exit_idx"], 2)

    def test_long_stop_hit(self):
        bars = [_b(100, 100), _b(101, 99), _b(102, 88)]  # bar2 low pierces stop 90
        r = simulate_trade(bars, 0, LONG, fill=100.0, stop=90.0, target=135.0, exit_deadline_idx=2)
        self.assertEqual(r["exit_reason"], "stop")
        self.assertEqual(r["points"], -10.0)

    def test_long_ambiguous_is_stop_first(self):
        bars = [_b(100, 100), _b(140, 85)]  # bar1 spans BOTH target and stop
        r = simulate_trade(bars, 0, LONG, fill=100.0, stop=90.0, target=135.0, exit_deadline_idx=1)
        self.assertEqual(r["exit_reason"], "ambiguous_stop")
        self.assertEqual(r["points"], -10.0)  # resolved pessimistically at the stop

    def test_long_time_exit(self):
        bars = [_b(100, 100), _b(105, 96), _b(104, 97, c=103.0)]  # neither hit
        r = simulate_trade(bars, 0, LONG, fill=100.0, stop=90.0, target=135.0, exit_deadline_idx=2)
        self.assertEqual(r["exit_reason"], "time")
        self.assertEqual(r["exit_price"], 103.0)
        self.assertEqual(r["points"], 3.0)

    def test_short_target_hit(self):
        bars = [_b(100, 100), _b(101, 99), _b(80, 64)]  # low reaches -35 target (65)
        r = simulate_trade(bars, 0, SHORT, fill=100.0, stop=110.0, target=65.0, exit_deadline_idx=2)
        self.assertEqual(r["exit_reason"], "target")
        self.assertEqual(r["points"], 35.0)

    def test_short_stop_hit(self):
        bars = [_b(100, 100), _b(112, 99)]  # high pierces stop 110
        r = simulate_trade(bars, 0, SHORT, fill=100.0, stop=110.0, target=65.0, exit_deadline_idx=1)
        self.assertEqual(r["exit_reason"], "stop")
        self.assertEqual(r["points"], -10.0)

    def test_earliest_bar_wins(self):
        # target reachable on bar2, but stop already hit on bar1 -> stop
        bars = [_b(100, 100), _b(101, 88), _b(140, 120)]
        r = simulate_trade(bars, 0, LONG, fill=100.0, stop=90.0, target=135.0, exit_deadline_idx=2)
        self.assertEqual(r["exit_reason"], "stop")
        self.assertEqual(r["exit_idx"], 1)


if __name__ == "__main__":
    unittest.main()

"""
REPLAY-3 — SimBroker + metrics locks (2026-07-09).

Synthetic-tape unit locks (fill at next open, stop/target/BE walk, PESSIMISM:
adverse extreme before favorable, EOD flatten, invalid specs -> None) +
scoreboard definitions (win=R>0, PF, expectancy gated at N>=5, max DD) +
safety invariants (max trades / daily loss violations FAIL the run) +
CALIBRATION: reproduces the BOT-VS-MAURICE hand-scored 2026-07-08 verdicts
(confirmed setups 4W/1L incl. the 13:12 short +1R with MFE ~1.69R) when the
candle archive is present.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.sim_broker import simulate_trade, stop_from_intent  # noqa: E402
from replay_validation.metrics import score_trades, safety_invariants     # noqa: E402

_T0 = datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)


def _bar(i, o, h, l, c):
    return {"timestamp": (_T0 + timedelta(minutes=i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c}


class TestSimulateTrade(unittest.TestCase):
    def test_long_rides_to_2r_target(self):
        # entry next open 100.0, stop 99.0 (risk 1) -> target 102.0
        tape = [_bar(1, 100.0, 100.4, 99.8, 100.2),
                _bar(2, 100.2, 101.2, 100.0, 101.0),
                _bar(3, 101.0, 102.3, 100.9, 102.0)]
        t = simulate_trade(tape, _T0.isoformat(), "long", stop=99.0,
                           breakeven_r=None, eod_flatten=False)
        self.assertEqual(t["entry"], 100.0)
        self.assertEqual(t["exit_reason"], "target")
        self.assertEqual(t["r"], 2.0)

    def test_long_stops_out(self):
        tape = [_bar(1, 100.0, 100.2, 99.9, 100.0),
                _bar(2, 100.0, 100.1, 98.8, 98.9)]
        t = simulate_trade(tape, _T0.isoformat(), "long", stop=99.0,
                           eod_flatten=False)
        self.assertEqual(t["exit_reason"], "stop")
        self.assertEqual(t["r"], -1.0)

    def test_breakeven_protects_after_1r(self):
        # +1R touched bar 2 (no stop-out) -> stop=entry; reversal exits at 0R
        tape = [_bar(1, 100.0, 100.2, 99.9, 100.1),
                _bar(2, 100.1, 101.1, 100.0, 101.0),   # touches +1R=101.0
                _bar(3, 101.0, 101.2, 99.9, 100.0)]    # reverses through entry
        t = simulate_trade(tape, _T0.isoformat(), "long", stop=99.0,
                           target_r=3.0, breakeven_r=1.0, eod_flatten=False)
        self.assertEqual(t["exit_reason"], "breakeven_stop")
        self.assertEqual(t["r"], 0.0)

    def test_pessimism_stop_before_target_same_bar(self):
        # one bar spans BOTH stop and 2R target -> pessimism takes the stop
        tape = [_bar(1, 100.0, 100.1, 99.9, 100.0),
                _bar(2, 100.0, 102.5, 98.5, 101.0)]
        t = simulate_trade(tape, _T0.isoformat(), "long", stop=99.0,
                           breakeven_r=None, eod_flatten=False)
        self.assertEqual(t["exit_reason"], "stop")
        self.assertEqual(t["r"], -1.0)

    def test_eod_flatten_closes_open_position(self):
        # 15:55 ET = 19:55 UTC on 2026-07-08
        t0 = datetime(2026, 7, 8, 19, 53, tzinfo=timezone.utc)
        tape = [{"timestamp": (t0 + timedelta(minutes=i)).isoformat(),
                 "open": 100.0, "high": 100.3, "low": 99.9, "close": 100.2}
                for i in range(1, 5)]
        t = simulate_trade(tape, t0.isoformat(), "long", stop=99.0,
                           target_r=5.0, breakeven_r=None)
        self.assertEqual(t["exit_reason"], "eod_flatten")

    def test_invalid_stop_side_returns_none(self):
        tape = [_bar(1, 100.0, 100.5, 99.5, 100.0)]
        self.assertIsNone(simulate_trade(tape, _T0.isoformat(), "long", stop=101.0))

    def test_no_forward_bars_returns_none(self):
        self.assertIsNone(simulate_trade([], _T0.isoformat(), "long", stop=99.0))

    def test_short_direction_symmetric(self):
        tape = [_bar(1, 100.0, 100.1, 99.9, 100.0),
                _bar(2, 100.0, 100.2, 98.0, 98.1)]
        t = simulate_trade(tape, _T0.isoformat(), "short", stop=101.0,
                           breakeven_r=None, eod_flatten=False)
        self.assertEqual(t["exit_reason"], "target")
        self.assertEqual(t["r"], 2.0)

    def test_stop_from_intent_prefers_invalidation_then_zone(self):
        z = {"zone_low": 708.63, "zone_high": 708.76}
        self.assertEqual(stop_from_intent(z, "short", invalidation_level=709.1), 709.1)
        self.assertEqual(stop_from_intent(z, "short", buffer=0.08), 708.84)
        self.assertEqual(stop_from_intent(z, "long", buffer=0.08), 708.55)
        self.assertIsNone(stop_from_intent({}, "long"))


class TestMetrics(unittest.TestCase):
    def _t(self, r, mfe=1.0, mae=0.5, day="2026-07-08"):
        return {"r": r, "mfe_r": mfe, "mae_r": mae, "exit_reason": "x",
                "entry_time": f"{day}T14:00:00+00:00"}

    def test_scoreboard_definitions(self):
        s = score_trades([self._t(1.0), self._t(-1.0), self._t(2.0),
                          self._t(-0.5), self._t(1.5)])
        self.assertEqual(s["trades"], 5)
        self.assertEqual(s["win_rate"], 0.6)
        self.assertEqual(s["profit_factor"], 3.0)     # 4.5 / 1.5
        self.assertEqual(s["expectancy_r"], 0.6)      # n=5 meets threshold
        self.assertEqual(s["max_drawdown_r"], 1.0)    # peak 1.0 -> trough 0.0

    def test_expectancy_gated_below_n5(self):
        s = score_trades([self._t(1.0), self._t(1.0)])
        self.assertIsNone(s["expectancy_r"])
        self.assertIn("n=2", s["expectancy_note"])

    def test_safety_invariants_fail_on_violation(self):
        ok = safety_invariants([self._t(-1.0), self._t(1.0)])
        self.assertTrue(ok["passed"])
        too_many = safety_invariants([self._t(0.1)] * 3)
        self.assertFalse(too_many["passed"])
        big_loss = safety_invariants([self._t(-1.0), self._t(-0.2)],
                                     daily_loss_limit=500.0)
        self.assertFalse(big_loss["passed"])          # $600 loss > $500 limit


class TestCalibrationHandScored0708(unittest.TestCase):
    """Engine-validation: the simulator must reproduce the BOT-VS-MAURICE
    hand-scored verdicts on the archived 2026-07-08 tape (same trade model:
    entry at zone midpoint, stop beyond far edge +0.08, first-hit 1R, no BE)."""

    # (intent_ts_utc, direction, zone_low, zone_high, hand_verdict)
    SETUPS = [
        ("2026-07-08T17:12:37+00:00", "short", 708.63, 708.76, "win"),    # 13:12 ET
        ("2026-07-08T17:16:29+00:00", "short", 708.79, 708.93, "loss"),
        ("2026-07-08T17:23:41+00:00", "short", 708.45, 708.88, "loss"),
        ("2026-07-08T17:44:42+00:00", "short", 709.86, 710.43, "win"),
        ("2026-07-08T18:02:45+00:00", "long", 708.56, 709.02, "win"),
        ("2026-07-08T18:05:44+00:00", "long", 708.57, 709.75, "win"),
        ("2026-07-08T18:26:41+00:00", "short", 709.60, 709.70, "loss"),
        ("2026-07-08T18:41:34+00:00", "short", 708.13, 709.93, "loss"),
    ]

    def setUp(self):
        path = os.path.join("data", "replay", "candles", "20260708_QQQ.json")
        if not os.path.exists(path):
            self.skipTest("candle archive not present")
        from replay_validation.candle_archive import load_session
        self.tape = load_session("20260708")

    def test_reproduces_hand_scored_verdicts(self):
        results = []
        for ts, d, zl, zh, verdict in self.SETUPS:
            mid = round((zl + zh) / 2, 3)
            stop = stop_from_intent({"zone_low": zl, "zone_high": zh}, d, buffer=0.08)
            t = simulate_trade(self.tape, ts, d, stop=stop, entry_price=mid,
                               target_r=1.0, breakeven_r=None,
                               eod_flatten=False, max_bars=50)
            self.assertIsNotNone(t, ts)
            results.append((verdict, "win" if t["r"] > 0 else "loss", t))
        mismatches = [(v, g) for v, g, _t in results if v != g]
        self.assertEqual(mismatches, [], f"verdict mismatches: {mismatches}")
        # the flagship: 13:12 short reaches ~+1.69R favorable excursion
        flagship = results[0][2]
        self.assertGreaterEqual(flagship["mfe_r"], 1.5)


if __name__ == "__main__":
    unittest.main()

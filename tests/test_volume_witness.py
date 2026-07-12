"""
VOLUME-WITNESS (2026-07-10) — relative-volume sense organ tests.

Volume flowed alpaca → timeframe_builder → normalizer and was read by NOTHING.
The organ (market_data/volume_witness.py) turns it into NON-DIRECTIONAL
participation evidence for the Brain payload, gated VOLUME_WITNESS (default
off = pipeline bit-for-bit unchanged). Witness only: no authority path may
read it (locked below).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.volume_witness import (  # noqa: E402
    build_volume_witness, volume_witness_enabled, _tf_witness,
    same_minute_percentile, _missing_bars,
)


def _bars(vols, start_minute=0, direction="neutral"):
    out = []
    for i, v in enumerate(vols):
        m = start_minute + i
        out.append({
            "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": v,
            "direction": direction,
            "timestamp": f"2026-07-09T{14 + m // 60:02d}:{m % 60:02d}:00+00:00",
        })
    return out


class TestComputation(unittest.TestCase):
    def test_normal_baseline_and_states(self):
        # 21 bars at 100, then a last bar per scenario
        for last, state in ((30, "dead"), (60, "quiet"), (100, "normal"),
                            (200, "elevated"), (300, "climactic")):
            w = _tf_witness(_bars([100] * 21 + [last]))
            self.assertEqual(w["state"], state, f"last={last}")
            self.assertEqual(w["baseline_avg"], 100.0)
            self.assertAlmostEqual(w["relative"], last / 100, places=2)

    def test_insufficient_bars_reported_explicitly(self):
        w = _tf_witness(_bars([100] * 5))
        self.assertEqual(w["state"], "insufficient_data")
        self.assertEqual(w["bars_seen"], 5)

    def test_zero_volume_baseline_is_insufficient_not_crash(self):
        w = _tf_witness(_bars([0] * 30))
        self.assertEqual(w["state"], "insufficient_data")

    def test_trend_classification(self):
        rising = _tf_witness(_bars([100] * 20 + [150, 160, 170, 180, 200]))
        self.assertEqual(rising["trend"], "rising")
        falling = _tf_witness(_bars([100] * 20 + [50, 40, 40, 30, 30]))
        self.assertEqual(falling["trend"], "falling")
        flat = _tf_witness(_bars([100] * 25))
        self.assertEqual(flat["trend"], "flat")

    def test_block_is_non_directional(self):
        block = build_volume_witness({"1m": _bars([100] * 25)})
        self.assertTrue(block["non_directional"])
        self.assertEqual(block["authority"], "witness_only")
        flat = str(block).lower()
        for word in ("bullish", "bearish", "long", "short", "direction\":"):
            self.assertNotIn(word, flat)

    def test_never_raises_on_garbage(self):
        self.assertIn("by_tf", build_volume_witness(None))
        self.assertIn("by_tf", build_volume_witness({"1m": [{"volume": "x"}]}))

    def test_determinism_identical_input_identical_output(self):
        import json
        history = {"1m": _bars([100, 120, 90] * 10 + [250])}
        a = json.dumps(build_volume_witness(history), sort_keys=True, default=str)
        b = json.dumps(build_volume_witness(history), sort_keys=True, default=str)
        self.assertEqual(a, b)

    def test_no_wall_clock_dependency(self):
        # all timestamps come from the bars themselves — freezing/moving wall
        # time must not change the output
        history = {"1m": _bars([100] * 25)}
        w1 = build_volume_witness(history)
        w2 = build_volume_witness(history)
        self.assertEqual(w1["data_quality"]["bar_timestamp"],
                         w2["data_quality"]["bar_timestamp"])
        self.assertEqual(w1["current_bar"], w2["current_bar"])

    def test_zscore_hand_computed(self):
        # baseline: ten 100s + ten 200s → mean 150, pop-std 50; last=250 → z=2.0
        vols = [100, 200] * 10 + [250]
        w = _tf_witness(_bars(vols))
        self.assertAlmostEqual(w["zscore"], 2.0, places=2)

    def test_zero_variance_zscore_unavailable_not_zero(self):
        w = _tf_witness(_bars([100] * 21 + [100]))
        self.assertIsNone(w["zscore"])
        self.assertEqual(w["state"], "normal")   # relative still computable

    def test_missing_bar_count(self):
        bars = _bars([100] * 25)
        bars[12]["timestamp"] = "2026-07-09T13:00:00+00:00"  # tear a gap
        self.assertGreaterEqual(_missing_bars(bars), 1)
        self.assertEqual(_missing_bars(_bars([100] * 25)), 0)


class TestSameMinutePercentile(unittest.TestCase):
    _TABLE = {"sessions": 21,
              "minutes": {"10:30": sorted(float(v) for v in range(100, 2200, 100))}}
    _TS = "2026-07-09T14:30:00+00:00"   # 10:30 ET

    def test_percentile_hand_computed(self):
        # values 100..2100 (n=21); volume 1050 → 10 of 21 below-or-equal → 48
        r = same_minute_percentile(1050, self._TS, self._TABLE)
        self.assertEqual(r["same_minute_sample_n"], 21)
        self.assertEqual(r["same_minute_percentile"], 48)
        top = same_minute_percentile(9999, self._TS, self._TABLE)
        self.assertEqual(top["same_minute_percentile"], 100)

    def test_thin_sample_refuses_percentile(self):
        thin = {"sessions": 3, "minutes": {"10:30": [100.0, 200.0, 300.0]}}
        r = same_minute_percentile(250, self._TS, thin)
        self.assertIsNone(r["same_minute_percentile"])
        self.assertEqual(r["same_minute_sample_n"], 3)

    def test_absent_table_is_unavailable(self):
        r = same_minute_percentile(100, self._TS, None)
        self.assertIsNone(r["same_minute_percentile"])
        self.assertEqual(r["same_minute_sample_n"], 0)


class TestEventAssociation(unittest.TestCase):
    def test_sweep_association_uses_existing_event(self):
        # liquidity sensor says sweep on 1m — the organ associates, never re-detects
        history = {"1m": _bars([100] * 21 + [320])}
        liq = {"1m": {"sweep_detected": True, "sweep_direction": "above_high"}}
        w = build_volume_witness(history, liquidity=liq)
        sc = w["sweep_context"]
        self.assertTrue(sc["event_present"])
        self.assertEqual(sc["tf"], "1m")
        self.assertEqual(sc["sweep_direction"], "above_high")
        self.assertAlmostEqual(sc["relative_volume"], 3.2, places=1)
        self.assertEqual(sc["volume_peak_timing"], "during")

    def test_no_sweep_is_honest_absence(self):
        w = build_volume_witness({"1m": _bars([100] * 25)})
        self.assertEqual(w["sweep_context"], {"event_present": False})

    def test_displacement_association_uses_existing_leg(self):
        # expansion sensor flagged displacement; leg = tail same-direction run
        history = {"1m": _bars([100] * 20, direction="neutral")
                   + _bars([150, 200, 300], start_minute=20, direction="bullish")}
        exp = {"1m": {"displacement_detected": True}}
        w = build_volume_witness(history, expansion=exp)
        dc = w["displacement_context"]
        self.assertTrue(dc["event_present"])
        self.assertEqual(dc["leg_bar_count"], 3)
        self.assertEqual(dc["total_volume"], 650.0)
        self.assertTrue(dc["volume_expanding_across_leg"])
        self.assertIsNotNone(dc["price_progress_per_volume"])

    def test_no_displacement_is_honest_absence(self):
        w = build_volume_witness({"1m": _bars([100] * 25)},
                                 expansion={"1m": {"displacement_detected": False}})
        self.assertEqual(w["displacement_context"], {"event_present": False})


class TestProvenance(unittest.TestCase):
    def test_venue_scope_and_completeness_exposed(self):
        w = build_volume_witness({"1m": _bars([100] * 25)})
        dq = w["data_quality"]
        self.assertEqual(dq["venue_scope"], "venue_limited_iex")
        self.assertIn("NOT the consolidated tape", dq["venue_note"])
        self.assertTrue(dq["bar_complete"])
        self.assertIn("completed bars only", dq["bar_complete_basis"])
        self.assertEqual(w["calculation_version"], "volume_witness_v1")
        self.assertEqual(w["authored_by"], "mechanical_sensor")
        self.assertEqual(w["authority_class"], "witness")
        self.assertFalse(w["decision_authority"])

    def test_insufficient_history_status(self):
        w = build_volume_witness({"1m": _bars([100] * 4)})
        self.assertEqual(w["data_quality"]["status"], "insufficient_history")
        self.assertFalse(w["data_quality"]["warmup_sufficient"])
        self.assertEqual(w["current_bar"], {})
        self.assertEqual(w["participation"]["state"], "unavailable")


class TestTracePersistence(unittest.TestCase):
    def test_witness_fields_last_in_stage_schema(self):
        from replay_validation.stage_trace import (_SCHEMA, _FIELD_STAGE,
                                                   build_stage_trace)
        self.assertEqual(_SCHEMA[-3:], ("volume_participation",
                                        "volume_relative_1m",
                                        "volume_sweep_relative"))
        for f in _SCHEMA[-3:]:
            self.assertEqual(_FIELD_STAGE[f], "witness")
        # populated from the snapshot block; None when the organ is off
        w = build_volume_witness({"1m": _bars([100] * 21 + [180])})
        trace_on = build_stage_trace({"volume_witness": w})
        self.assertEqual(trace_on["volume_participation"], "elevated")
        self.assertAlmostEqual(trace_on["volume_relative_1m"], 1.8, places=1)
        trace_off = build_stage_trace({})
        self.assertIsNone(trace_off["volume_participation"])

    def test_witness_not_in_calibration_fields(self):
        from replay_validation.stage_trace import CALIBRATION_FIELDS
        for f in ("volume_participation", "volume_relative_1m",
                  "volume_sweep_relative"):
            self.assertNotIn(f, CALIBRATION_FIELDS)

    def test_snapshot_store_persists_block(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "src",
                               "live_scan", "snapshot_store.py"),
                  encoding="utf-8") as fh:
            self.assertIn('"volume_witness": snapshot.get("volume_witness")',
                          fh.read())


class TestFlagGate(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VOLUME_WITNESS", None)
            self.assertFalse(volume_witness_enabled())

    def test_on(self):
        with patch.dict(os.environ, {"VOLUME_WITNESS": "on"}):
            self.assertTrue(volume_witness_enabled())


class TestPayloadWiring(unittest.TestCase):
    def test_brain_input_carries_block_only_when_present(self):
        from ai_brain.brain_input import build_brain_input
        base = {"timestamp": "t", "session": "ny"}
        without = build_brain_input(dict(base), {"available": False})
        self.assertNotIn("volume_witness", without)
        block = build_volume_witness({"1m": _bars([100] * 25)})
        with_it = build_brain_input(dict(base, volume_witness=block),
                                    {"available": False})
        self.assertIn("volume_witness", with_it)
        self.assertEqual(with_it["volume_witness"]["authority"], "witness_only")

    def test_prompt_clause_only_when_block_present(self):
        # _call_llm assembles the system prompt BEFORE the api-key check and
        # returns it on the record even on the no_api_key fallback path.
        from ai_brain.narrative_brain import _call_llm
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            os.environ.pop("OPENAI_API_KEY", None)
            bare = _call_llm({"timestamp": "t"})
            self.assertNotIn("volume_witness", bare["prompt"])
            armed = _call_llm({"timestamp": "t",
                               "volume_witness": {"by_tf": {}}})
        self.assertIn("PARTICIPATION EVIDENCE (volume_witness)", armed["prompt"])
        self.assertIn("MUST NOT derive narrative_direction", armed["prompt"])


class TestWitnessBoundary(unittest.TestCase):
    def test_no_authority_path_reads_volume_witness(self):
        # witness only: gates, risk, sizing, decisions, qualification and the
        # broker may never consume the organ
        forbidden = (
            ("execution_gate", "execution_gate.py"),
            ("risk", "risk_governor.py"),
            ("decision_authority", "decision_engine.py"),
            ("paper_execution", "order_builder.py"),
            ("paper_execution", "execution_engine.py"),
            ("paper_execution", "paper_broker.py"),
            ("qualification", "trade_qualification_engine.py"),
            ("intent_scoring", "intent_scorer.py"),
        )
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for parts in forbidden:
            path = os.path.join(src, *parts)
            self.assertTrue(os.path.exists(path), path)
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("volume_witness", fh.read(),
                                 f"{'/'.join(parts)} reads the witness organ")


if __name__ == "__main__":
    unittest.main()

"""
REPLAY-2 — session walker + RecordedBrain + stage trace locks (2026-07-09).

Real-day validation already performed (2026-07-08: 224 scans, 0 errors, 224/224
brain records served sequentially, determinism gate PASS byte-identical,
decision-level calibration 63% scan-identical / 81-100% per-field vs stored
live snapshots with declared caveats). These tests lock the offline invariants:

  * RecordedBrain: ET-date filtering kills leaked stale-timestamp fixtures;
    SEQUENTIAL consumption serves duplicate-minute records once each in order
    (the 14:03 sovereign-family bug); out-of-tolerance -> replay_no_record
    (counted, never invented); brain_replay() always restores the real function
  * stage_trace: first_divergence respects stage order + names an owner;
    CALIBRATION_FIELDS is a decision-level subset
  * walker: safety env FORCED (EXECUTION_ENABLED/ALLOW_PAPER_ORDERS false even
    if the caller passes true); runs end-to-end on synthetic candles with no
    brain records (misses counted); sandboxed dirs
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.recorded_brain import (                            # noqa: E402
    RecordedBrain, brain_replay, load_brain_records,
)
from replay_validation.stage_trace import (                               # noqa: E402
    build_stage_trace, first_divergence, CALIBRATION_FIELDS, _FIELD_STAGE,
)
from replay_validation.replay_session import replay_session, _SAFETY_ENV  # noqa: E402
from replay_validation.candle_archive import archive_session              # noqa: E402
from data_feed.provider_interface import BaseDataProvider                 # noqa: E402


def _brain_rec(ts, family="none", direction="bearish"):
    return {"timestamp": ts, "symbol": "QQQ", "source": "llm",
            "llm_enabled": True, "llm_model": "gpt-4o-mini",
            "parsed_output": {"narrative_direction": direction,
                              "recommended_playbook_family": family}}


class TestRecordedBrain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name, rec):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            json.dump(rec, fh)

    def test_stale_timestamp_fixture_filtered(self):
        # filename says 0708 but timestamp is June — must be excluded
        self._write("20260708_100000_QQQ.json",
                    _brain_rec("2026-06-11T10:29:55+00:00"))
        self._write("20260708_100100_QQQ.json",
                    _brain_rec("2026-07-08T14:02:00+00:00"))
        recs = load_brain_records("20260708", "QQQ", self.tmp)
        self.assertEqual(len(recs), 1)

    def test_sequential_consumption_of_duplicate_minute(self):
        # two records share ts 14:03; second carries the sovereign family —
        # each must be served exactly once, in order (the live bug found)
        self._write("20260708_100411_QQQ.json",
                    _brain_rec("2026-07-08T14:03:00+00:00", family="none"))
        self._write("20260708_100522_QQQ.json",
                    _brain_rec("2026-07-08T14:03:00+00:00", family="accumulation"))
        brain = RecordedBrain("20260708", "QQQ", records_dir=self.tmp)
        r1 = brain({"timestamp": "2026-07-08T14:03:00+00:00"}, "QQQ")
        r2 = brain({"timestamp": "2026-07-08T14:03:00+00:00"}, "QQQ")
        fams = [r["output"]["recommended_playbook_family"] for r in (r1, r2)]
        self.assertEqual(fams, ["none", "accumulation"])
        self.assertEqual(brain.served, 2)

    def test_out_of_tolerance_is_counted_miss(self):
        self._write("20260708_100411_QQQ.json",
                    _brain_rec("2026-07-08T14:03:00+00:00"))
        brain = RecordedBrain("20260708", "QQQ", records_dir=self.tmp)
        res = brain({"timestamp": "2026-07-08T18:00:00+00:00"}, "QQQ")
        self.assertEqual(res["source"], "replay_no_record")
        self.assertEqual(brain.misses, 1)

    def test_brain_replay_always_restores(self):
        import ai_brain.narrative_brain as nb
        original = nb.run_narrative_brain
        brain = RecordedBrain("20260708", "QQQ", records_dir=self.tmp)
        try:
            with brain_replay(brain):
                self.assertIs(nb.run_narrative_brain, brain)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertIs(nb.run_narrative_brain, original)


class TestStageTrace(unittest.TestCase):
    def test_first_divergence_names_stage_and_owner_in_order(self):
        a = build_stage_trace({"qualification": {"status": "candidate"},
                               "trade_intent": {"intent_created": True}})
        b = build_stage_trace({"qualification": {"status": "no_trade"},
                               "trade_intent": {"intent_created": False}})
        div = first_divergence(a, b)
        self.assertEqual(div["stage"], "qualification")   # earlier stage wins
        self.assertIn("trade_qualification_engine", div["owner"])

    def test_identical_traces_no_divergence(self):
        t = build_stage_trace({"qualification": {"status": "elite"}})
        self.assertIsNone(first_divergence(t, dict(t)))

    def test_calibration_fields_are_decision_level_subset(self):
        for f in CALIBRATION_FIELDS:
            self.assertIn(f, _FIELD_STAGE)
        self.assertNotIn("gate_blockers", CALIBRATION_FIELDS)      # reason text
        self.assertNotIn("qual_disqualifier", CALIBRATION_FIELDS)  # not stored


class _TapeProvider(BaseDataProvider):
    """60 synthetic 1m bars on 2026-07-08 for offline end-to-end walking."""

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return []

    def fetch_1m_candles_range(self, symbol, start, end):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 7, 8, 13, 30, tzinfo=timezone.utc)
        out, px = [], 700.0
        for i in range(60):
            px += 0.1 if i % 3 else -0.05
            ts = (base + timedelta(minutes=i)).isoformat()
            out.append({"timestamp": ts, "open": px, "high": px + 0.3,
                        "low": px - 0.3, "close": px + 0.1, "volume": 1000.0})
        return out


class TestWalker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {
            "REPLAY_CANDLES_DIR": os.path.join(self.tmp, "candles"),
            "AI_BRAIN_DIR": os.path.join(self.tmp, "no_records"),
        })
        self._e.start()
        archive_session("20260708", "QQQ", provider=_TapeProvider())

    def tearDown(self):
        self._e.stop()

    def test_end_to_end_synthetic_walk_and_forced_safety(self):
        # caller tries to enable execution — the walker must force it off
        result = replay_session(
            "20260708", "QQQ", lookback=30, max_scans=3,
            flags={"EXECUTION_ENABLED": "true", "ALLOW_PAPER_ORDERS": "true"},
            sandbox=os.path.join(self.tmp, "sandbox"))
        self.assertEqual(result["manifest"]["forced_safety"], _SAFETY_ENV)
        self.assertGreaterEqual(result["summary"]["scans"], 1)
        self.assertEqual(result["summary"]["errors"], 0)
        # no brain records → every scan is a counted miss, never invented
        self.assertEqual(result["summary"]["brain_served"], 0)
        self.assertGreaterEqual(result["summary"]["brain_misses"], 1)
        for scan in result["scans"]:
            self.assertIn("trace", scan)
        # safety env restored after the run
        self.assertEqual(os.environ.get("EXECUTION_ENABLED", "true"), "true")


if __name__ == "__main__":
    unittest.main()

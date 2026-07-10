"""
ADAPT-LOOP-3 — Brain Accuracy Table locks (2026-07-10).

The Brain graded on its OWN theses: replay-side builder joins persisted Brain
calls with the archived tape (hit = 30-bar close moved the called direction);
pipeline-side reader attaches a compact DESCRIPTIVE_ONLY self-track-record into
the Brain payload when BRAIN_ACCURACY_CONTEXT=on (default off = byte-identical
payload). No module may veto on the table.

Locks: grading math (hit/miss/excursions, insufficient tape -> None); bucket
aggregation by direction/family/confidence/family-present; only healthy-LLM
directional records graded; round-trip build -> load -> compact context;
gated attach default-off/on + creates-context-when-missing; payload-taint
safety (attached block survives scan_payload_taint); flag absent from safety
files.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.brain_accuracy import (                     # noqa: E402
    grade_scan, build_brain_accuracy,
)
from adaptive_learning.brain_accuracy import (                     # noqa: E402
    load_brain_accuracy, compact_accuracy_context, attach_accuracy_context,
)

_T0 = datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)


def _tape(drift=+0.05, n=40):
    out, px = [], 700.0
    for i in range(1, n + 1):
        px += drift
        out.append({"timestamp": (_T0 + timedelta(minutes=i)).isoformat(),
                    "open": px, "high": px + 0.2, "low": px - 0.2,
                    "close": px + drift})
    return out


class TestGrading(unittest.TestCase):
    def test_bullish_hit_on_uptape(self):
        g = grade_scan(_tape(+0.05), _T0.isoformat(), "bullish")
        self.assertTrue(g["hit"])
        self.assertGreater(g["move_pts"], 0)

    def test_bearish_miss_on_uptape(self):
        g = grade_scan(_tape(+0.05), _T0.isoformat(), "bearish")
        self.assertFalse(g["hit"])
        self.assertLess(g["move_pts"], 0)

    def test_insufficient_forward_tape_none(self):
        self.assertIsNone(grade_scan(_tape(n=2), _T0.isoformat(), "bullish"))


class TestBuilderAndReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cdir = os.path.join(self.tmp, "candles")
        bdir = os.path.join(self.tmp, "brain")
        os.makedirs(cdir), os.makedirs(bdir)
        with open(os.path.join(cdir, "20260708_QQQ.json"), "w",
                  encoding="utf-8") as fh:
            tape = _tape(+0.05, 60)
            json.dump({"symbol": "QQQ", "date": "20260708",
                       "bar_count": len(tape), "candles": tape}, fh)

        def rec(name, ts, direction, fam, conf, source="llm"):
            with open(os.path.join(bdir, name), "w", encoding="utf-8") as fh:
                json.dump({"timestamp": ts, "symbol": "QQQ", "source": source,
                           "parsed_output": {
                               "narrative_direction": direction,
                               "recommended_playbook_family": fam,
                               "phase_confidence": conf}}, fh)
        rec("20260708_100000_QQQ.json", _T0.isoformat(), "bullish",
            "trend_continuation", 75)                        # hit, family, 70+
        rec("20260708_100100_QQQ.json",
            (_T0 + timedelta(minutes=1)).isoformat(), "bearish", "none", 55)
        rec("20260708_100200_QQQ.json",
            (_T0 + timedelta(minutes=2)).isoformat(), "conflicted", "none", 60)
        rec("20260708_100300_QQQ.json",
            (_T0 + timedelta(minutes=3)).isoformat(), "bullish",
            "trend_continuation", 80, source="llm_failed_fallback")  # excluded

        self._e = patch.dict(os.environ, {"REPLAY_CANDLES_DIR": cdir,
                                          "AI_BRAIN_DIR": bdir})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_build_grades_only_healthy_directional(self):
        t = build_brain_accuracy(["20260708"], "QQQ", base_dir=self.tmp)
        self.assertEqual(t["graded_scans"], 2)   # conflicted + fallback excluded
        self.assertEqual(t["overall"]["hits"], 1)
        self.assertEqual(t["by_direction"]["bullish"]["hit_rate"], 1.0)
        self.assertEqual(t["by_direction"]["bearish"]["hit_rate"], 0.0)
        self.assertEqual(t["by_family_present"]["family_present"]["n"], 1)
        self.assertEqual(t["by_confidence"]["70+"]["hits"], 1)
        self.assertEqual(t["authority"], "descriptive_only")

    def test_round_trip_load_and_compact(self):
        build_brain_accuracy(["20260708"], "QQQ", base_dir=self.tmp)
        loaded = load_brain_accuracy("QQQ", base_dir=self.tmp)
        self.assertEqual(loaded["graded_scans"], 2)
        ctx = compact_accuracy_context("QQQ", base_dir=self.tmp)
        self.assertEqual(ctx["authority"], "descriptive_only")
        self.assertIn("by_family_present", ctx)


class TestGatedAttach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "QQQ"))
        with open(os.path.join(self.tmp, "QQQ", "brain_accuracy.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"graded_scans": 10, "horizon_bars": 30,
                       "overall": {"n": 10, "hits": 6, "hit_rate": 0.6,
                                   "avg_move_pts": 0.1},
                       "by_direction": {}, "by_family_present": {},
                       "by_confidence": {}}, fh)

    def test_default_off_payload_untouched(self):
        bi = {"adaptive_learning_context": {"x": 1}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_ACCURACY_CONTEXT", None)
            self.assertFalse(attach_accuracy_context(bi, "QQQ", base_dir=self.tmp))
        self.assertNotIn("brain_self_accuracy", bi["adaptive_learning_context"])

    def test_on_attaches_inside_learning_context(self):
        bi = {"adaptive_learning_context": {"x": 1}}
        with patch.dict(os.environ, {"BRAIN_ACCURACY_CONTEXT": "on"}):
            self.assertTrue(attach_accuracy_context(bi, "QQQ", base_dir=self.tmp))
        blk = bi["adaptive_learning_context"]["brain_self_accuracy"]
        self.assertEqual(blk["overall"]["hit_rate"], 0.6)
        self.assertEqual(blk["authority"], "descriptive_only")

    def test_on_creates_context_when_missing_and_survives_taint(self):
        bi = {"timestamp": "t", "market": {}}
        with patch.dict(os.environ, {"BRAIN_ACCURACY_CONTEXT": "on"}):
            self.assertTrue(attach_accuracy_context(bi, "QQQ", base_dir=self.tmp))
        from ai_brain.brain_validation import scan_payload_taint
        clean, hits = scan_payload_taint(bi)
        self.assertTrue(clean, f"taint: {hits}")

    def test_no_table_no_attach(self):
        bi = {}
        with patch.dict(os.environ, {"BRAIN_ACCURACY_CONTEXT": "on"}):
            self.assertFalse(attach_accuracy_context(bi, "NOPE", base_dir=self.tmp))
        self.assertEqual(bi, {})


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("execution_gate", "execution_gate.py")):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("BRAIN_ACCURACY_CONTEXT", fh.read(),
                                 f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

"""
Phase PIPE-1 — Pipeline realignment: full evidence before the canonical Brain.

Proves the structural weld:
  - the load-bearing evidence (protected_swings, narrative_authority,
    shared_context) is assembled INSIDE build_snapshot BEFORE the canonical
    Brain call, so the consumed thesis is fully-fed (delivery populated);
  - exactly ONE Brain call happens per build_snapshot (no starved-consumed +
    fed-discarded duplicate);
  - the stateful swing tracker is advanced exactly once per scan.

No prompt/behavior changes are asserted here — only call ordering and arity.
"""
import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# MEM-DECAY-1 — build_snapshot runs the adaptive policy engine, which now also
# advances scar-decay state. Isolate PERFORMANCE_TABLES_DIR so these
# integration tests can never write into live adaptive memory (DECON-2 rule).
import tempfile as _tempfile

_PREV_PERF_DIR = None
_TMP_PERF_DIR = None


def setUpModule():
    global _PREV_PERF_DIR, _TMP_PERF_DIR
    _PREV_PERF_DIR = os.environ.get("PERFORMANCE_TABLES_DIR")
    _TMP_PERF_DIR = _tempfile.mkdtemp()
    os.environ["PERFORMANCE_TABLES_DIR"] = _TMP_PERF_DIR


def tearDownModule():
    if _PREV_PERF_DIR is None:
        os.environ.pop("PERFORMANCE_TABLES_DIR", None)
    else:
        os.environ["PERFORMANCE_TABLES_DIR"] = _PREV_PERF_DIR


from data_feed.timeframe_builder import build_timeframes  # noqa: E402
import market_data.snapshot_builder as sb                 # noqa: E402
import ai_brain.narrative_brain as nb                      # noqa: E402


def _synthetic_raw(n=120, base=700.0, step=0.02):
    t0 = datetime(2026, 6, 15, 13, 33, tzinfo=timezone.utc)
    candles = []
    for i in range(n):
        o = base + i * step
        c = o + 0.03
        candles.append({"timestamp": (t0 + timedelta(minutes=i)).isoformat(),
                        "open": o, "high": c + 0.02, "low": o - 0.02,
                        "close": c, "volume": 1000})
    return build_timeframes(candles)


class _CountingTracker:
    """Stand-in protected-swing tracker that records how many times it advances."""
    def __init__(self):
        self.calls = 0

    def update(self, snapshot):
        self.calls += 1
        return {"protected_high": None, "protected_high_status": "none",
                "protected_low": None, "protected_low_status": "none"}


class Pipe1OrderingTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["BRAIN_ECU_MODE"] = "true"
        os.environ["AI_BRAIN_ENABLED"] = "true"
        os.environ["AI_BRAIN_LLM"] = "false"          # deterministic, no real LLM
        os.environ["THESIS_LIFECYCLE_MODE"] = "shadow"
        os.environ["AI_BRAIN_DIR"] = self._tmp        # isolate persisted records
        self._orig_brain = nb.run_narrative_brain

    def tearDown(self):
        nb.run_narrative_brain = self._orig_brain
        for k in ("BRAIN_ECU_MODE", "AI_BRAIN_ENABLED", "AI_BRAIN_LLM",
                  "THESIS_LIFECYCLE_MODE", "AI_BRAIN_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_exactly_one_brain_call_per_build_snapshot(self):
        calls = {"n": 0}
        orig = self._orig_brain
        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        nb.run_narrative_brain = counting
        sb.build_snapshot(_synthetic_raw(), symbol="QQQ")
        self.assertEqual(calls["n"], 1, "expected a single canonical Brain call")

    def test_evidence_assembled_in_build_snapshot(self):
        snap = sb.build_snapshot(_synthetic_raw(), symbol="QQQ")
        for key in ("protected_swings", "narrative_authority", "shared_context",
                    "candidate_thesis", "brain_thesis"):
            self.assertIn(key, snap, f"{key} missing from build_snapshot output")

    def test_consumed_thesis_is_fully_fed(self):
        """The Brain that produced candidate_thesis saw a populated delivery
        state (shared_context present at Brain time) — not the old None."""
        snap = sb.build_snapshot(_synthetic_raw(), symbol="QQQ")
        self.assertIn("candidate_thesis", snap)
        sc = snap.get("shared_context", {})
        self.assertNotIn(sc.get("delivery_state"), (None, "unknown"),
                         "shared_context delivery not populated for the Brain")
        # the persisted consumed record must show the populated delivery it saw
        bb = (snap["candidate_thesis"] or {}).get("brain_block") or {}
        import json
        rec = json.load(open(bb["persisted"], encoding="utf-8"))
        self.assertNotIn(rec["input_payload"]["delivery"]["state"], (None, "unknown"))

    def test_shared_context_built_before_brain(self):
        """At the instant the Brain runs, shared_context must already exist."""
        seen = {}
        orig_bi = nb.build_brain_input
        def spy(snapshot, hist):
            seen["has_sc"] = "shared_context" in snapshot
            seen["has_protected"] = "protected_swings" in snapshot
            return orig_bi(snapshot, hist)
        nb.build_brain_input = spy
        try:
            sb.build_snapshot(_synthetic_raw(), symbol="QQQ")
        finally:
            nb.build_brain_input = orig_bi
        self.assertTrue(seen.get("has_sc"), "shared_context absent at Brain time")
        self.assertTrue(seen.get("has_protected"), "protected_swings absent at Brain time")

    def test_swing_tracker_advanced_exactly_once(self):
        tracker = _CountingTracker()
        sb.build_snapshot(_synthetic_raw(), symbol="QQQ", swing_tracker=tracker)
        self.assertEqual(tracker.calls, 1,
                         "swing tracker must advance exactly once per scan")


if __name__ == "__main__":
    unittest.main()

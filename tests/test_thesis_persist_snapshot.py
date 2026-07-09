"""
THESIS-PERSIST (2026-07-09) — persist the canonical Brain thesis + sovereignty.

The 2026-07-09 ECU investigation found snapshot_store persisted thesis_state but
NOT brain_thesis / candidate_thesis, so every post-hoc audit saw brain_thesis=None
and wrongly concluded the Brain never converted (a storage artifact — live
reconstruction showed ~20 sovereign + 80 directional scans that day). This locks:

  * brain_thesis persisted compactly (canonical fields; brain_block excluded —
    ai_brain.output already carries the full record)
  * candidate_thesis_source persisted (the healthy-LLM check input under the
    AB-7 stabilized-thesis path)
  * brain_sovereignty derived at save time on the LIVE snapshot (sovereign,
    detail, healthy_directional) so replays measure sovereignty directly
  * absent thesis -> None + sovereign=False (no fabrication)
  * observability only — no authority, never blocks a save
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from live_scan.snapshot_store import save_snapshot, _brain_sovereignty_record  # noqa: E402


def _base(ts="2026-07-09T18:00:00"):
    return {"timestamp": ts, "symbol": "QQQ",
            # DECON-3 forensic contract — runtime blocks must exist
            "decision_authority": {}, "execution_gate": {}, "paper_execution": {},
            "position_monitor": {}, "trade_reconciliation": {},
            "ai_brain": {"enabled": True, "source": "llm", "output": {}}}


def _sovereign_thesis():
    return {"owner": "ai_brain", "source": "llm", "direction": "bearish",
            "opportunity": True, "playbook_family": "liquidity_sweep_reversal",
            "tool_family": ["ifvg"], "confidence": 70,
            "brain_block": {"full": "nested record"}}


class TestThesisPersist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {"LIVE_SNAPSHOTS_DIR": self._tmp})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def _save(self, snap):
        return json.load(open(save_snapshot(snap, "QQQ"), encoding="utf-8"))

    def test_brain_thesis_persisted_compact(self):
        d = self._save(dict(_base(), brain_thesis=_sovereign_thesis(),
                            candidate_thesis={"source": "llm"}))
        bt = d["brain_thesis"]
        self.assertEqual(bt["direction"], "bearish")
        self.assertEqual(bt["source"], "llm")
        self.assertEqual(bt["playbook_family"], "liquidity_sweep_reversal")
        self.assertNotIn("brain_block", bt)   # full record excluded (compact)

    def test_candidate_source_persisted(self):
        d = self._save(dict(_base(), brain_thesis=_sovereign_thesis(),
                            candidate_thesis={"source": "llm"}))
        self.assertEqual(d["candidate_thesis_source"], "llm")

    def test_sovereignty_derived_at_save_time(self):
        d = self._save(dict(_base(), brain_thesis=_sovereign_thesis(),
                            candidate_thesis={"source": "llm"}))
        sov = d["brain_sovereignty"]
        self.assertTrue(sov["sovereign"])
        self.assertTrue(sov["healthy_directional"])
        self.assertIn("llm_conversion:bearish", sov["detail"])

    def test_degraded_source_not_sovereign(self):
        t = dict(_sovereign_thesis(), source="llm_failed_fallback")
        d = self._save(dict(_base(), brain_thesis=t))
        self.assertFalse(d["brain_sovereignty"]["sovereign"])
        # but the thesis itself is still persisted for the audit trail
        self.assertEqual(d["brain_thesis"]["direction"], "bearish")

    def test_absent_thesis_persists_none_not_fabricated(self):
        d = self._save(_base())
        self.assertIsNone(d["brain_thesis"])
        self.assertIsNone(d["candidate_thesis_source"])
        self.assertFalse(d["brain_sovereignty"]["sovereign"])
        self.assertEqual(d["brain_sovereignty"]["detail"], "no_brain_thesis")

    def test_record_never_raises(self):
        # malformed thesis must not break the forensic save
        rec = _brain_sovereignty_record({"brain_thesis": "not_a_dict"})
        self.assertFalse(rec["sovereign"])


if __name__ == "__main__":
    unittest.main()

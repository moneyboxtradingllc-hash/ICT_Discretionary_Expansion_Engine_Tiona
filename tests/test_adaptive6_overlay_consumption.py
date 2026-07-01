"""
Adaptive Learning — Phase 6: Confidence / Size overlay consumption (DEFENSIVE_ONLY).

Proves the exposed overlays are now CONSUMED — but only ever to make trading
STRICTER: adaptive confidence lowers combined_confidence (never raises), adaptive
size lowers qty (never raises / never exceeds the caller's risk max), missing
overlays are safe no-ops, the soft block still wins, and no forbidden category
(direction / playbook / tool / qualification) is ever altered. Forensics record
the consumed flags and the final live confidence / qty.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.adaptive_live_authority import (   # noqa: E402
    consume_adaptive_overlays, resolve_final_confidence, resolve_final_qty,
    adaptive_entry_block_reason,
)


def _snap(combined=62, ac=None, asz=None, block=False, **extra):
    snap = {
        "confidence_fusion": {"combined_confidence": combined},
        "ai_context": {"confidence_score": 55},
        "qualification": {"status": "qualified", "direction": "bullish"},
        "playbook": {"selected_playbook": "strong"},
        "toolbox": {"preferred_tool": "breaker"},
    }
    if ac is not None:
        snap["adaptive_confidence"] = ac
    if asz is not None:
        snap["adaptive_size"] = asz
    snap["adaptive_block"] = {"blocked": block, "source": "adaptive_live_authority",
                              "reason": (["loss_streak 4"] if block else [])}
    snap.update(extra)
    return snap


class TestConfidenceConsumption(unittest.TestCase):
    def test_1_lower_adaptive_confidence_is_consumed(self):
        snap = _snap(combined=62, ac={"original": 55, "final": 49.5})
        rec = consume_adaptive_overlays(snap)
        self.assertTrue(rec["adaptive_confidence_consumed"])
        self.assertEqual(snap["confidence_fusion"]["combined_confidence"], 49.5)
        self.assertEqual(rec["final_live_confidence"], 49.5)

    def test_2_higher_adaptive_confidence_is_ignored(self):
        snap = _snap(combined=62, ac={"original": 55, "final": 60})
        rec = consume_adaptive_overlays(snap)
        self.assertFalse(rec["adaptive_confidence_consumed"])
        self.assertEqual(snap["confidence_fusion"]["combined_confidence"], 62)

    def test_3_missing_adaptive_confidence_is_safe(self):
        snap = _snap(combined=62, ac=None)
        rec = consume_adaptive_overlays(snap)
        self.assertFalse(rec["adaptive_confidence_consumed"])
        self.assertEqual(snap["confidence_fusion"]["combined_confidence"], 62)

    def test_7_original_confidence_preserved_when_no_overlay(self):
        self.assertEqual(resolve_final_confidence(62, {}), 62)

    def test_confidence_never_raised(self):
        # final higher than combined must never raise it
        self.assertEqual(resolve_final_confidence(40, _snap(ac={"original": 55, "final": 49.5})), 40)


class TestSizeConsumption(unittest.TestCase):
    def test_4_lower_adaptive_size_is_consumed(self):
        snap = _snap(asz={"original": 4, "final": 2})
        self.assertEqual(resolve_final_qty(4, snap), 2)
        rec = consume_adaptive_overlays(snap)
        self.assertTrue(rec["adaptive_size_consumed"])
        self.assertEqual(rec["final_live_qty"], 2)

    def test_5_higher_adaptive_size_is_ignored(self):
        snap = _snap(asz={"original": 4, "final": 5})
        self.assertEqual(resolve_final_qty(4, snap), 4)
        self.assertFalse(consume_adaptive_overlays(snap)["adaptive_size_consumed"])

    def test_6_missing_adaptive_size_is_safe(self):
        self.assertEqual(resolve_final_qty(4, {}), 4)

    def test_8_original_qty_preserved_when_no_overlay(self):
        self.assertEqual(resolve_final_qty(3, _snap()), 3)

    def test_15_overlay_never_exceeds_risk_max(self):
        # even if the overlay is larger, the caller's original (risk max) caps it
        snap = _snap(asz={"original": 10, "final": 5})
        self.assertLessEqual(resolve_final_qty(3, snap), 3)


class TestSoftBlockSupremacy(unittest.TestCase):
    def test_9_soft_block_still_wins_over_overlays(self):
        snap = _snap(combined=62, ac={"original": 55, "final": 49.5}, block=True)
        rec = consume_adaptive_overlays(snap)
        # confidence still consumed AND the soft block still vetoes entry
        self.assertTrue(rec["adaptive_confidence_consumed"])
        self.assertIsNotNone(adaptive_entry_block_reason(snap))
        self.assertIn("soft veto", adaptive_entry_block_reason(snap))


class TestNoForbiddenMutation(unittest.TestCase):
    def test_10_overlays_never_create_a_trade(self):
        snap = _snap(combined=62, ac={"original": 55, "final": 49.5})
        consume_adaptive_overlays(snap)
        self.assertNotIn("decision_authority", snap)
        self.assertNotIn("trade_authorized", snap)
        # only ever lowered
        self.assertLessEqual(snap["confidence_fusion"]["combined_confidence"], 62)

    def test_11_overlays_never_alter_direction(self):
        snap = _snap(ac={"original": 55, "final": 49.5}, block=True)
        consume_adaptive_overlays(snap)
        self.assertEqual(snap["qualification"]["direction"], "bullish")

    def test_12_overlays_never_alter_playbook(self):
        snap = _snap(ac={"original": 55, "final": 49.5})
        consume_adaptive_overlays(snap)
        self.assertEqual(snap["playbook"]["selected_playbook"], "strong")

    def test_13_overlays_never_alter_tool(self):
        snap = _snap(ac={"original": 55, "final": 49.5})
        consume_adaptive_overlays(snap)
        self.assertEqual(snap["toolbox"]["preferred_tool"], "breaker")

    def test_14_overlays_never_alter_qualification(self):
        snap = _snap(ac={"original": 55, "final": 49.5})
        consume_adaptive_overlays(snap)
        self.assertEqual(snap["qualification"]["status"], "qualified")

    def test_raw_ai_context_not_overwritten(self):
        snap = _snap(ac={"original": 55, "final": 49.5})
        consume_adaptive_overlays(snap)
        self.assertEqual(snap["ai_context"]["confidence_score"], 55)


class TestForensics(unittest.TestCase):
    def test_16_forensic_contains_consumed_flags(self):
        rec = consume_adaptive_overlays(_snap(ac={"original": 55, "final": 49.5},
                                              asz={"original": 4, "final": 2}))
        self.assertIn("adaptive_confidence_consumed", rec)
        self.assertIn("adaptive_size_consumed", rec)
        self.assertTrue(rec["adaptive_confidence_consumed"])
        self.assertTrue(rec["adaptive_size_consumed"])

    def test_17_forensic_contains_final_live_confidence(self):
        snap = _snap(combined=62, ac={"original": 55, "final": 49.5})
        rec = consume_adaptive_overlays(snap)
        self.assertIn("final_live_confidence", rec)
        self.assertEqual(rec["final_live_confidence"], 49.5)
        # persisted on snapshot for the forensic log
        self.assertEqual(snap["adaptive_live_consumption"]["final_live_confidence"], 49.5)

    def test_18_forensic_contains_final_live_qty(self):
        rec = consume_adaptive_overlays(_snap(asz={"original": 4, "final": 2}))
        self.assertIn("final_live_qty", rec)
        self.assertEqual(rec["final_live_qty"], 2)

    def test_safe_noop_records_forensics(self):
        rec = consume_adaptive_overlays(_snap())
        self.assertFalse(rec["adaptive_confidence_consumed"])
        self.assertFalse(rec["adaptive_size_consumed"])
        self.assertIn("final_live_confidence", rec)


if __name__ == "__main__":
    unittest.main()

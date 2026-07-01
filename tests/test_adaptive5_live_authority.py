"""
Adaptive Learning — Phase 5: Live Mutation Authority (LIVE, DEFENSIVE_ONLY).

Proves the live overlay is exposed correctly and constitutionally: confidence is
only ever reduced (never raised), size is exposed only when a real qty exists,
the soft block adds a no-trade reason and can never approve, and NOTHING
authoritative (ai_context / qualification / direction / playbook / tool) is
overwritten. Also proves snapshot_builder wires it and the Brain receives the
context, and that the scan_loop entry-gate consumer treats the block as no-trade.
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.adaptive_live_authority import (   # noqa: E402
    apply_adaptive_live_authority, adaptive_entry_block_reason,
    AUTHORITY_LEVEL, POSTURE,
)


def _mutation(orig_conf=55.0, new_conf=49.5, orig_qty=None, new_qty=None,
              blocked=False, types=None, reasoning=None) -> dict:
    return {
        "mutated": True,
        "mutation_type": "+".join(types or []) or "none",
        "mutation_types": types or [],
        "original_confidence": orig_conf,
        "new_confidence": new_conf,
        "original_qty": orig_qty,
        "new_qty": new_qty,
        "trade_blocked": blocked,
        "mutation_reasoning": reasoning or ["adaptive defensive"],
    }


def _snap(mutation) -> dict:
    return {
        "ai_context":     {"confidence_score": 55},
        "qualification":  {"status": "qualified", "direction": "bullish"},
        "playbook":       {"selected_playbook": "strong"},
        "toolbox":        {"preferred_tool": "breaker"},
        "adaptive_policy": {"confidence_penalty_recommended": True},
        "adaptive_mutation": mutation,
    }


class TestConfidenceAuthority(unittest.TestCase):
    def test_1_live_authority_applies_confidence_penalty(self):
        snap = _snap(_mutation(55.0, 49.5, types=["confidence_penalty"]))
        live = apply_adaptive_live_authority(snap)
        self.assertTrue(live["confidence_adjusted"])
        self.assertEqual(live["final_confidence"], 49.5)
        self.assertEqual(snap["adaptive_confidence"]["final"], 49.5)
        self.assertEqual(snap["adaptive_confidence"]["source"], "adaptive_live_authority")

    def test_2_live_authority_never_increases_confidence(self):
        # malformed upward mutation must NOT be exposed
        snap = _snap(_mutation(55.0, 60.0))
        live = apply_adaptive_live_authority(snap)
        self.assertFalse(live["confidence_adjusted"])
        self.assertEqual(live["final_confidence"], 55.0)
        self.assertNotIn("adaptive_confidence", snap)
        self.assertTrue(live["forbidden_actions_verified"])

    def test_7_raw_ai_context_confidence_not_overwritten(self):
        snap = _snap(_mutation(55.0, 49.5))
        apply_adaptive_live_authority(snap)
        self.assertEqual(snap["ai_context"]["confidence_score"], 55)


class TestSoftBlock(unittest.TestCase):
    def test_3_soft_block_creates_adaptive_block(self):
        snap = _snap(_mutation(blocked=True, types=["trade_block"],
                               reasoning=["loss_streak 4 -> trade_block"]))
        live = apply_adaptive_live_authority(snap)
        self.assertTrue(live["trade_soft_blocked"])
        self.assertTrue(snap["adaptive_block"]["blocked"])
        self.assertEqual(snap["adaptive_block"]["source"], "adaptive_live_authority")
        self.assertIn("loss_streak 4 -> trade_block", snap["adaptive_block"]["reason"])

    def test_4_no_block_when_mutation_says_no_block(self):
        snap = _snap(_mutation(blocked=False))
        apply_adaptive_live_authority(snap)
        self.assertFalse(snap["adaptive_block"]["blocked"])
        self.assertIsNone(apply_adaptive_live_authority(snap)["block_reason"])


class TestSizeAuthority(unittest.TestCase):
    def test_5_size_reduction_exposed_when_qty_exists(self):
        snap = _snap(_mutation(orig_qty=4, new_qty=2, types=["risk_reduction"]))
        live = apply_adaptive_live_authority(snap)
        self.assertTrue(live["size_adjusted"])
        self.assertEqual(snap["adaptive_size"]["original"], 4)
        self.assertEqual(snap["adaptive_size"]["final"], 2)

    def test_6_size_not_invented_when_qty_missing(self):
        snap = _snap(_mutation(orig_qty=None, new_qty=None))
        live = apply_adaptive_live_authority(snap)
        self.assertFalse(live["size_adjusted"])
        self.assertNotIn("adaptive_size", snap)


class TestNoForbiddenMutation(unittest.TestCase):
    def test_8_qualification_not_overwritten(self):
        snap = _snap(_mutation(blocked=True))
        apply_adaptive_live_authority(snap)
        self.assertEqual(snap["qualification"], {"status": "qualified", "direction": "bullish"})

    def test_9_direction_not_overwritten(self):
        snap = _snap(_mutation(55.0, 49.5, blocked=True))
        apply_adaptive_live_authority(snap)
        self.assertEqual(snap["qualification"]["direction"], "bullish")

    def test_10_playbook_not_overwritten(self):
        snap = _snap(_mutation(55.0, 49.5))
        apply_adaptive_live_authority(snap)
        self.assertEqual(snap["playbook"]["selected_playbook"], "strong")

    def test_11_tool_not_overwritten(self):
        snap = _snap(_mutation(55.0, 49.5))
        apply_adaptive_live_authority(snap)
        self.assertEqual(snap["toolbox"]["preferred_tool"], "breaker")

    def test_12_forbidden_actions_verified_true(self):
        snap = _snap(_mutation(55.0, 49.5, orig_qty=4, new_qty=2, blocked=True,
                               types=["confidence_penalty", "risk_reduction", "trade_block"]))
        live = apply_adaptive_live_authority(snap)
        self.assertTrue(live["forbidden_actions_verified"])
        self.assertEqual(live["authority_level"], AUTHORITY_LEVEL)
        self.assertEqual(live["posture"], POSTURE)


class TestSafeNoOps(unittest.TestCase):
    def test_13_missing_policy_and_mutation_is_safe_noop(self):
        snap = {"ai_context": {"confidence_score": 55}}
        live = apply_adaptive_live_authority(snap)
        self.assertFalse(live["applied"])
        self.assertFalse(snap["adaptive_block"]["blocked"])
        self.assertNotIn("adaptive_confidence", snap)
        self.assertNotIn("adaptive_size", snap)

    def test_14_malformed_mutation_is_safe_noop(self):
        snap = {"adaptive_mutation": "not-a-dict", "ai_context": {"confidence_score": 55}}
        live = apply_adaptive_live_authority(snap)
        self.assertFalse(live["applied"])
        self.assertFalse(live["confidence_adjusted"])
        self.assertEqual(snap["ai_context"]["confidence_score"], 55)


class TestEntryGateConsumer(unittest.TestCase):
    def test_17_soft_block_causes_no_trade_reason(self):
        snap = _snap(_mutation(blocked=True, reasoning=["loss_streak 4"]))
        apply_adaptive_live_authority(snap)
        reason = adaptive_entry_block_reason(snap)
        self.assertIsNotNone(reason)
        self.assertIn("soft veto", reason)

    def test_18_block_reason_preserved(self):
        snap = _snap(_mutation(blocked=True, reasoning=["regime severe degradation"]))
        apply_adaptive_live_authority(snap)
        self.assertIn("regime severe degradation", adaptive_entry_block_reason(snap))

    def test_19_block_cannot_approve(self):
        # when not blocked, the consumer returns None (never an approval)
        snap = _snap(_mutation(blocked=False))
        apply_adaptive_live_authority(snap)
        self.assertIsNone(adaptive_entry_block_reason(snap))


class TestSnapshotAndBrainIntegration(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "BRAIN_ECU_MODE")}
        os.environ["AI_BRAIN_ENABLED"] = "true"
        os.environ["AI_BRAIN_LLM"] = "false"      # deterministic — no network
        os.environ["BRAIN_ECU_MODE"] = "true"     # brain runs inside build_snapshot

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @staticmethod
    def _synthetic_raw(n=120, base=700.0, step=0.02):
        from data_feed.timeframe_builder import build_timeframes
        t0 = datetime(2026, 6, 15, 13, 33, tzinfo=timezone.utc)
        candles = [{
            "timestamp": (t0 + timedelta(minutes=i)).isoformat(),
            "open": base + i * step, "high": base + i * step + 0.05,
            "low": base + i * step - 0.02, "close": base + i * step + 0.03,
            "volume": 1000,
        } for i in range(n)]
        return build_timeframes(candles)

    def test_15_snapshot_builder_produces_adaptive_live_authority(self):
        import market_data.snapshot_builder as sb
        snap = sb.build_snapshot(self._synthetic_raw(), symbol="QQQ")
        self.assertIn("adaptive_live_authority", snap)
        self.assertIn("adaptive_mutation", snap)
        self.assertIn("adaptive_block", snap)
        self.assertEqual(snap["adaptive_live_authority"]["authority_level"], "live_defensive")

    def test_16_brain_input_receives_live_authority_context(self):
        import ai_brain.narrative_brain as nb
        import market_data.snapshot_builder as sb
        captured = {}
        orig = nb.scan_payload_taint

        def spy(bi):
            captured["bi"] = bi
            return orig(bi)

        nb.scan_payload_taint = spy
        try:
            sb.build_snapshot(self._synthetic_raw(), symbol="QQQ")
        finally:
            nb.scan_payload_taint = orig
        self.assertIn("bi", captured, "Brain never ran / taint scan not reached")
        self.assertIn("adaptive_live_authority_context", captured["bi"])
        self.assertEqual(
            captured["bi"]["adaptive_live_authority_context"]["posture"], "DEFENSIVE_ONLY")


if __name__ == "__main__":
    unittest.main()

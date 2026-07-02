"""
Adaptive Learning — Phase 7: Live Size Enforcement (DEFENSIVE_ONLY, downward-only).

Closes the final adaptive actuator: the live size owner (order_builder) now
consumes resolve_final_qty over the risk/buying-power-capped qty. Proves size can
only be reduced (4->2, 3->1, floor 1), never increased, the risk max is always the
ceiling, missing/malformed overlays fall back, forensics are written, order-build
logic is otherwise unchanged.
"""
import os
import sys
import math
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.adaptive_live_authority import (   # noqa: E402
    resolve_final_qty, record_live_size_consumption, adaptive_entry_block_reason,
)
import paper_execution.order_builder as ob_mod            # noqa: E402
from paper_execution.order_builder import build_order      # noqa: E402

ENV = {"RISK_PER_TRADE_DOLLARS": "500", "ENTRY_ORDER_TYPE": "limit"}


def _policy(risk_reduction=False):
    return {"adaptive_policy": {"risk_reduction_recommended": risk_reduction}}


def _snap(entry: float, stop: float, direction: str = "bullish") -> dict:
    intent_type = "long" if direction == "bullish" else "short"
    return {
        "trade_intent": {
            "intent_created": True, "intent_type": intent_type, "direction": direction,
            "preferred_tool": f"{direction}_ifvg",
            "entry_zone": {"zone_low": min(entry, stop), "zone_high": max(entry, stop),
                           "midpoint": entry},
        },
        "toolbox": {
            "preferred_tool": f"{direction}_ifvg",
            "tool_candidates": [{
                "tool": f"{direction}_ifvg", "score": 80,
                "raw_status": "actionable", "effective_status": "actionable",
                "price_level": {"level_type": "ifvg_zone", "direction": direction,
                                "zone_low": min(entry, stop), "zone_high": max(entry, stop),
                                "midpoint": entry, "invalidation_level": stop},
                "trigger_prep": {"execution_ready": True},
            }],
        },
    }


def _acct(bp: float) -> dict:
    return {"buying_power": bp, "cash": bp, "equity": bp, "status": "ACTIVE",
            "account_number": "TEST"}


class TestResolverMath(unittest.TestCase):
    def test_1_reduces_4_to_2(self):
        self.assertEqual(resolve_final_qty(4, _policy(True)), 2)

    def test_2_reduces_3_to_1(self):
        self.assertEqual(resolve_final_qty(3, _policy(True)), 1)

    def test_3_floors_at_1(self):
        self.assertEqual(resolve_final_qty(1, _policy(True)), 1)
        self.assertEqual(resolve_final_qty(2, _policy(True)), 1)

    def test_4_cannot_increase(self):
        # policy on, but result is always <= original
        for q in (1, 2, 3, 4, 10):
            self.assertLessEqual(resolve_final_qty(q, _policy(True)), q)
        # explicit oversized overlay is ignored
        self.assertEqual(resolve_final_qty(3, {"adaptive_size": {"original": 3, "final": 9}}), 3)

    def test_5_malformed_falls_back(self):
        self.assertEqual(resolve_final_qty(4, {"adaptive_size": "not-a-dict"}), 4)
        self.assertEqual(resolve_final_qty(4, {"adaptive_policy": "not-a-dict"}), 4)

    def test_6_missing_falls_back(self):
        self.assertEqual(resolve_final_qty(4, {}), 4)
        self.assertEqual(resolve_final_qty(4, _policy(False)), 4)

    def test_7_risk_max_still_wins(self):
        # the caller's original is the risk max; final never exceeds it
        self.assertLessEqual(resolve_final_qty(4, _policy(True)), 4)
        # even if an overlay claims a bigger 'final', capped to original
        self.assertLessEqual(resolve_final_qty(2, {"adaptive_size": {"original": 2, "final": 8}}), 2)

    def test_10_original_preserved_when_no_reduction(self):
        self.assertEqual(resolve_final_qty(4, _policy(False)), 4)
        self.assertEqual(resolve_final_qty(0, _policy(True)), 0)


class TestForensics(unittest.TestCase):
    def test_9_forensic_flags_written(self):
        snap = {}
        rec = record_live_size_consumption(snap, 4, 2)
        self.assertTrue(rec["adaptive_size_consumed"])
        self.assertEqual(rec["original_live_qty"], 4)
        self.assertEqual(rec["adaptive_final_qty"], 2)
        self.assertEqual(rec["final_live_qty"], 2)
        self.assertEqual(rec["adaptive_size_source"], "adaptive_live_authority")
        self.assertIn("adaptive_size_reason", rec)
        self.assertIs(snap["adaptive_live_consumption"], rec)

    def test_9b_updates_existing_consumption_record(self):
        # ADAPTIVE-6 confidence consumption already ran this scan
        snap = {"adaptive_live_consumption": {
            "adaptive_confidence_consumed": True, "final_live_confidence": 49.5,
            "adaptive_size_consumed": False, "notes": ["conf lowered"]}}
        rec = record_live_size_consumption(snap, 4, 2)
        self.assertTrue(rec["adaptive_confidence_consumed"])   # preserved
        self.assertTrue(rec["adaptive_size_consumed"])         # added
        self.assertEqual(rec["final_live_qty"], 2)


class TestSoftBlockPreventsBuild(unittest.TestCase):
    def test_8_soft_block_prevents_order_build(self):
        # A soft-blocked snapshot yields a deny reason in the OPS-1 entry gate
        # (scan_loop:1161), so attempt_paper_execution -> build_order is never
        # reached. build_order itself is only reached when entry is NOT denied.
        blocked = {"adaptive_block": {"blocked": True, "source": "adaptive_live_authority",
                                      "reason": ["loss_streak 4 -> trade_block"]}}
        self.assertIsNotNone(adaptive_entry_block_reason(blocked))
        self.assertIn("soft veto", adaptive_entry_block_reason(blocked))
        # not blocked -> gate does not deny (build may proceed)
        self.assertIsNone(adaptive_entry_block_reason({"adaptive_block": {"blocked": False}}))


class TestEndToEndBuildOrder(unittest.TestCase):
    """Real build_order path with the account mocked (mirrors 5E.6 harness)."""

    def _qty(self, snap, bp=1_000_000.0):
        with patch.dict(os.environ, ENV), \
                patch.object(ob_mod, "_get_account", return_value=_acct(bp)):
            result = build_order(snap, "QQQ")
        self.assertTrue(result["valid"], result.get("reject_reason"))
        return result["qty"], snap

    def test_e2e_live_size_reduced_and_capped(self):
        # control: risk-max qty with NO adaptive policy
        ctrl_qty, _ = self._qty(_snap(479.0, 354.0))          # risk_per_share=125 -> 4
        self.assertGreaterEqual(ctrl_qty, 2)

        # adaptive risk_reduction halves it (floor), never above risk max
        adj = _snap(479.0, 354.0)
        adj["adaptive_policy"] = {"risk_reduction_recommended": True}
        adj_qty, snap = self._qty(adj)
        self.assertEqual(adj_qty, max(1, ctrl_qty // 2))
        self.assertLessEqual(adj_qty, ctrl_qty)               # risk max wins
        # forensics persisted on the snapshot
        alc = snap["adaptive_live_consumption"]
        self.assertTrue(alc["adaptive_size_consumed"])
        self.assertEqual(alc["final_live_qty"], adj_qty)
        self.assertEqual(alc["original_live_qty"], ctrl_qty)

    def test_11_paper_execution_unchanged_without_policy(self):
        # identical snapshot, no adaptive policy -> qty unchanged, no consumption
        base_qty, snap = self._qty(_snap(479.0, 354.0))
        self.assertNotIn("adaptive_live_consumption", snap)
        # and with policy explicitly OFF
        off = _snap(479.0, 354.0)
        off["adaptive_policy"] = {"risk_reduction_recommended": False}
        off_qty, snap_off = self._qty(off)
        self.assertEqual(off_qty, base_qty)
        self.assertNotIn("adaptive_live_consumption", snap_off)


if __name__ == "__main__":
    unittest.main()

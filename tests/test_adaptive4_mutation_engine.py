"""
Adaptive Learning — Phase 4: Bounded Mutation Engine (SHADOW MODE).

Proves the DEFENSIVE_ONLY constitution: confidence penalty reduces confidence,
risk reduction halves qty (never below 1), trade block raises a soft veto, boosts
do nothing, defensive rules stack, and NOTHING mutates upward. The input candidate
is read-only and no categorical field (direction / playbook / tool /
qualification_status) is ever altered.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.adaptive_mutation_engine import (   # noqa: E402
    mutate_candidate, AUTHORITY_LEVEL, POSTURE,
)


def _candidate(**over) -> dict:
    c = {
        "confidence": 0.80,
        "qty": 4,
        "playbook": "strong",
        "tool": "breaker",
        "qualification_status": "qualified",
        "direction": "bullish",
    }
    c.update(over)
    return c


def _policy(**flags) -> dict:
    p = {
        "confidence_boost_recommended": False,
        "confidence_penalty_recommended": False,
        "risk_reduction_recommended": False,
        "trade_block_recommended": False,
        "recommended_adjustments": [],
    }
    p.update(flags)
    return p


class TestMutationRules(unittest.TestCase):
    def test_1_confidence_penalty_reduces_confidence(self):
        r = mutate_candidate(_candidate(confidence=0.80),
                             _policy(confidence_penalty_recommended=True))
        self.assertTrue(r["mutated"])
        self.assertAlmostEqual(r["new_confidence"], 0.72, places=6)
        self.assertEqual(r["original_confidence"], 0.80)
        self.assertIn("confidence_penalty", r["mutation_type"])

    def test_2_risk_reduction_halves_qty(self):
        r = mutate_candidate(_candidate(qty=4),
                             _policy(risk_reduction_recommended=True))
        self.assertTrue(r["mutated"])
        self.assertEqual(r["original_qty"], 4)
        self.assertEqual(r["new_qty"], 2)

    def test_3_qty_never_drops_below_one(self):
        self.assertEqual(
            mutate_candidate(_candidate(qty=3), _policy(risk_reduction_recommended=True))["new_qty"], 1)
        self.assertEqual(
            mutate_candidate(_candidate(qty=1), _policy(risk_reduction_recommended=True))["new_qty"], 1)

    def test_4_trade_block_sets_blocked_true(self):
        r = mutate_candidate(_candidate(), _policy(trade_block_recommended=True))
        self.assertTrue(r["trade_blocked"])
        self.assertTrue(r["mutated"])
        self.assertIn("trade_block", r["mutation_type"])

    def test_5_boosts_do_nothing(self):
        r = mutate_candidate(_candidate(confidence=0.80, qty=4),
                             _policy(confidence_boost_recommended=True))
        self.assertFalse(r["mutated"])
        self.assertFalse(r["trade_blocked"])
        self.assertEqual(r["new_confidence"], 0.80)
        self.assertEqual(r["new_qty"], 4)
        self.assertEqual(r["mutation_type"], "none")

    def test_6_multiple_defensive_rules_stack(self):
        r = mutate_candidate(
            _candidate(confidence=0.80, qty=4),
            _policy(confidence_penalty_recommended=True,
                    risk_reduction_recommended=True,
                    trade_block_recommended=True))
        self.assertAlmostEqual(r["new_confidence"], 0.72, places=6)
        self.assertEqual(r["new_qty"], 2)
        self.assertTrue(r["trade_blocked"])
        self.assertIn("confidence_penalty", r["mutation_type"])
        self.assertIn("risk_reduction", r["mutation_type"])
        self.assertIn("trade_block", r["mutation_type"])

    def test_7_no_upward_mutation_allowed(self):
        # even if (wrongly) boost + penalty both set, confidence only goes DOWN
        r = mutate_candidate(_candidate(confidence=0.80, qty=4),
                             _policy(confidence_boost_recommended=True,
                                     confidence_penalty_recommended=True,
                                     risk_reduction_recommended=True))
        self.assertLessEqual(r["new_confidence"], r["original_confidence"])
        self.assertLessEqual(r["new_qty"], r["original_qty"])


class TestConstitutionalPreservation(unittest.TestCase):
    def test_8_candidate_fields_preserved_and_input_readonly(self):
        original = _candidate(confidence=0.80, qty=4)
        snapshot_before = dict(original)
        r = mutate_candidate(original,
                             _policy(confidence_penalty_recommended=True,
                                     risk_reduction_recommended=True))
        # input candidate untouched (read-only)
        self.assertEqual(original, snapshot_before)
        mc = r["mutated_candidate"]
        # only confidence / qty (+trade_blocked marker) changed
        self.assertEqual(mc["playbook"], "strong")
        self.assertEqual(mc["tool"], "breaker")
        self.assertEqual(mc["qualification_status"], "qualified")
        self.assertEqual(mc["direction"], "bullish")

    def test_9_no_direction_mutation(self):
        r = mutate_candidate(_candidate(direction="bullish"),
                             _policy(confidence_penalty_recommended=True,
                                     trade_block_recommended=True))
        self.assertEqual(r["mutated_candidate"]["direction"], "bullish")

    def test_10_no_playbook_mutation(self):
        r = mutate_candidate(_candidate(playbook="strong"),
                             _policy(risk_reduction_recommended=True))
        self.assertEqual(r["mutated_candidate"]["playbook"], "strong")

    def test_11_no_tool_mutation(self):
        r = mutate_candidate(_candidate(tool="breaker"),
                             _policy(risk_reduction_recommended=True))
        self.assertEqual(r["mutated_candidate"]["tool"], "breaker")

    def test_12_no_qualification_mutation(self):
        r = mutate_candidate(_candidate(qualification_status="qualified"),
                             _policy(confidence_penalty_recommended=True,
                                     trade_block_recommended=True))
        self.assertEqual(r["mutated_candidate"]["qualification_status"], "qualified")


class TestShadowContract(unittest.TestCase):
    def test_authority_is_shadow_defensive(self):
        r = mutate_candidate(_candidate(), _policy(trade_block_recommended=True))
        self.assertEqual(r["authority_level"], "shadow")
        self.assertEqual(AUTHORITY_LEVEL, "shadow")
        self.assertEqual(r["posture"], "DEFENSIVE_ONLY")
        self.assertEqual(POSTURE, "DEFENSIVE_ONLY")

    def test_forensic_fields_present(self):
        r = mutate_candidate(_candidate(), _policy(confidence_penalty_recommended=True))
        for field in ("mutation_type", "trade_blocked", "original_confidence",
                      "new_confidence", "original_qty", "new_qty", "mutation_reasoning"):
            self.assertIn(field, r)

    def test_empty_inputs_are_safe_noop(self):
        r = mutate_candidate({}, {})
        self.assertFalse(r["mutated"])
        self.assertFalse(r["trade_blocked"])
        self.assertEqual(r["mutation_type"], "none")


if __name__ == "__main__":
    unittest.main()

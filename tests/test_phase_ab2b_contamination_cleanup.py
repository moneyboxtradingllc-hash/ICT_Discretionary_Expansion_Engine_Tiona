"""
Phase AB-2B — Structure Contamination Cleanup tests.

Proves structure can no longer move the AI debate verdict (and therefore the
gate's ai_verdict_supports_trade check), the deterministic AI direction, or the
shared-context delivery state. Structure remains witness-only.

Firewall default ON. Rollback STRUCTURE_AUTHORSHIP_FIREWALL=false restores
legacy structure scoring (proven in TestRollback).
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_layer.ai_debate_engine import build_debate, _score_bullish, _score_bearish
from ai_layer.discretionary_ai import _ai_direction
from shared_context.shared_market_context import build_shared_market_context


def _on():  os.environ["STRUCTURE_AUTHORSHIP_FIREWALL"] = "true"
def _off(): os.environ["STRUCTURE_AUTHORSHIP_FIREWALL"] = "false"
def _clear(): os.environ.pop("STRUCTURE_AUTHORSHIP_FIREWALL", None)


def _struct(bias):
    return {tf: {"bias": bias} for tf in ("15m", "5m", "3m", "1m")}


def _snapshot(struct_bias="bullish", ctx_bias="bullish", ai_dir="neutral",
              po3=None, liquidity=None, playbook_dir="neutral"):
    return {
        "structure": _struct(struct_bias),
        "ai_context": {"directional_bias": ctx_bias, "market_narrative": ""},
        "playbook": {"selected_playbook": "liquidity_sweep_reversal" if playbook_dir != "neutral" else "no_playbook",
                     "direction": playbook_dir},
        "toolbox": {"preferred_tool": "", "tool_candidates": []},
        "qualification": {"status": "no_trade", "direction": "neutral"},
        "risk": {"trade_allowed": True, "risk_tier": "normal"},
        "po3": po3 or {},
        "liquidity": liquidity or {},
        "memory": {}, "state_transition": {}, "setup_lifecycle": {},
        "session": "morning_continuation",
    }


class TestStructureNotInDebateScore(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_bullish_structure_adds_no_bullish_score(self):
        # 3/4 bullish TFs + bullish ctx bias, but NO non-structure evidence
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish")
        pts_on, *_ = _score_bullish(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        _off()
        pts_off, *_ = _score_bullish(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        # firewall removes the +10 (structure) and +5 (ctx bias) = 15 pts
        self.assertEqual(pts_off - pts_on, 15)
        _on()

    def test_bearish_structure_adds_no_bearish_score(self):
        snap = _snapshot(struct_bias="bearish", ctx_bias="bearish")
        pts_on, *_ = _score_bearish(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        _off()
        pts_off, *_ = _score_bearish(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        self.assertEqual(pts_off - pts_on, 15)
        _on()

    def test_structure_only_does_not_make_bullish_dominant(self):
        # Pure structure bullish, nothing else → debate must NOT be bullish-dominant
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish", ai_dir="neutral")
        deb = build_debate(snap, {"ai_direction": "neutral", "ai_confidence": 20})
        self.assertNotEqual(deb["final_verdict"]["dominant_thesis"], "bullish")


class TestDebateMetadata(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_metadata_fields_present(self):
        deb = build_debate(_snapshot(), {"ai_direction": "neutral", "ai_confidence": 0})
        self.assertTrue(deb["structure_used_as_witness"])
        self.assertFalse(deb["structure_contributed_to_direction_score"])
        self.assertFalse(deb["structure_contributed_to_gate_support"])
        self.assertIn("debate_direction_source", deb)

    def test_direction_source_never_structure(self):
        invalid = {"structure", "ai_context.directional_bias", "structure_bias", "bias_only"}
        for sb, cb, ad in [("bullish", "bullish", "neutral"),
                           ("bearish", "bearish", "neutral"),
                           ("bullish", "bullish", "bullish")]:
            deb = build_debate(_snapshot(struct_bias=sb, ctx_bias=cb),
                               {"ai_direction": ad, "ai_confidence": 70})
            self.assertNotIn(deb["debate_direction_source"], invalid)

    def test_directional_source_traces_to_nonstructure(self):
        # delivery-authored bearish playbook → source delivery
        snap = _snapshot(struct_bias="bullish", playbook_dir="bearish")
        snap["playbook"]["direction_source"] = "delivery_protected"
        deb = build_debate(snap, {"ai_direction": "bearish", "ai_confidence": 70})
        if deb["final_verdict"]["dominant_thesis"] == "bearish":
            self.assertEqual(deb["debate_direction_source"], "delivery")


class TestDeterministicAIDirection(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_structure_only_yields_neutral_ai_direction(self):
        # structure bullish + ctx bias bullish, no PO3/playbook/tool → neutral
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish")
        self.assertEqual(_ai_direction(snap), "neutral")

    def test_nonstructure_still_drives_direction(self):
        snap = _snapshot(struct_bias="neutral", ctx_bias="neutral",
                         po3={"15m": {"distribution_direction": "bearish"}})
        self.assertEqual(_ai_direction(snap), "bearish")

    def test_rollback_structure_votes_return(self):
        _off()
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish")
        self.assertEqual(_ai_direction(snap), "bullish")
        _on()


class TestDeliveryFallback(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def _snap_no_po3(self, bias):
        return {
            "ai_context": {"directional_bias": bias},
            "structure": {"15m": {"bias": bias}, "alignment": "strong"},
            "market_regime": {}, "qualification": {}, "playbook": {},
            "setup_lifecycle": {}, "toolbox": {},
        }

    def test_no_po3_is_insufficient_not_bullish(self):
        ctx = build_shared_market_context(self._snap_no_po3("bullish"), "QQQ")
        self.assertEqual(ctx["delivery_state"], "insufficient_delivery_evidence")
        self.assertEqual(ctx["delivery_confidence"], 0)

    def test_no_po3_bearish_bias_also_insufficient(self):
        ctx = build_shared_market_context(self._snap_no_po3("bearish"), "QQQ")
        self.assertNotIn("bias_only", ctx["delivery_state"])
        self.assertNotIn("bearish_delivery", ctx["delivery_state"])


class TestJune11(unittest.TestCase):
    """The four June 11 contamination proofs."""
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_1013_bullish_structure_no_bullish_debate_lift(self):
        # 10:13: structure bullish, above_high sweep (bearish delivery), no playbook dir
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish",
                         liquidity={"15m": {"sweep_detected": True,
                                            "sweep_direction": "above_high",
                                            "reclaim_detected": True}})
        bull_on, ev_on, *_ = _score_bullish(snap, {"ai_direction": "bullish", "ai_confidence": 65})
        # the only bullish lift is AI direction (+10); structure adds 0
        self.assertNotIn("Bullish structure on", " ".join(ev_on))

    def test_1029_long_no_gate_support_from_structure(self):
        # structure-tainted bullish should not produce prepare_long via structure
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish", ai_dir="neutral")
        deb = build_debate(snap, {"ai_direction": "neutral", "ai_confidence": 20})
        self.assertNotIn(deb["final_verdict"]["recommended_stance"],
                         ("prepare_long", "bullish_bias"))

    def test_1020_1040_bearish_delivery_without_structure(self):
        # bearish delivery present, structure NOT bearish → bearish still scores
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish",
                         po3={"15m": {"distribution_direction": "bearish"}})
        bear_pts, ev, *_ = _score_bearish(snap, {"ai_direction": "bearish", "ai_confidence": 70})
        self.assertTrue(any("PO3" in e for e in ev))   # delivery evidence stands alone

    def test_1317_bearish_structure_no_bearish_debate_lift(self):
        snap = _snapshot(struct_bias="bearish", ctx_bias="bearish",
                         liquidity={"3m": {"sweep_detected": True,
                                           "sweep_direction": "below_low",
                                           "reclaim_detected": True}})
        _, ev, *_ = _score_bearish(snap, {"ai_direction": "bearish", "ai_confidence": 65})
        self.assertNotIn("Bearish structure on", " ".join(ev))


class TestRollback(unittest.TestCase):
    def tearDown(self): _clear()

    def test_off_restores_structure_scoring(self):
        _off()
        snap = _snapshot(struct_bias="bullish", ctx_bias="bullish")
        pts, ev, *_ = _score_bullish(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        self.assertIn("Bullish structure on", " ".join(ev))
        deb = build_debate(snap, {"ai_direction": "neutral", "ai_confidence": 0})
        self.assertTrue(deb["structure_contributed_to_direction_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

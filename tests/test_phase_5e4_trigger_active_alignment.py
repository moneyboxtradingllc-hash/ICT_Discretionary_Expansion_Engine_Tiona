"""
Phase 5E.4 — Trigger Active Alignment Tests.

Root bug: ai_debate_engine._final_verdict() used:
    trig_active = trig in ("confirmed", "retest_in_progress")

Patch aligns it with decision_engine._TRIG_ACTIVE which includes "confirmation_needed":
    trig_active = trig in ("confirmed", "retest_in_progress", "confirmation_needed")

Covers:
  01  confirmation_needed + bullish dominant + execution-ready → prepare_long
  02  confirmation_needed + bearish dominant + execution-ready → prepare_short
  03  waiting_for_retest does NOT produce prepare_long/short
  04  retest_in_progress behavior unchanged (still prepare_long)
  05  confirmed behavior unchanged (still prepare_long)
  06  strong_disagreement still blocks execution gate
  07  risk blocked still prevents prepare_long/short
  08  no_tool / conflicted direction still blocks
  09  authority_level invariant unchanged
  10  confidence_modifier remains 0
  11  full regression — all key modules importable

Scan #59 regression fixture: bullish_ifvg, ACTIONABLE, confirmation_needed,
execution_ready=True, risk_allowed=True, AI/mechanical agreement, expected → prepare_long.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _scan59_snapshot():
    """Day 1 Scan #59 regression fixture — the highest-quality missed setup."""
    return {
        "timestamp": "2026-06-08T12:48:00",
        "session": "ny",
        "qualification": {
            "status": "qualified",
            "grade": "B",
            "direction": "bullish",
            "opportunity_score": 73,
        },
        "playbook": {
            "selected_playbook": "liquidity_sweep_reversal",
            "status": "active",
            "direction": "bullish",
            "playbook_confidence": 68,
        },
        "risk": {
            "trade_allowed": True,
            "risk_tier": "minimal",
            "authority_reason": "minimal risk tier",
            "blocks": [],
            "restrictions": [],
        },
        "toolbox": {
            "preferred_tool": "bullish_ifvg",
            "toolbox_status": "actionable",
            "best_available_raw_status": "actionable",
            "best_available_effective_status": "actionable",
            "tool_candidates": [
                {
                    "tool": "bullish_ifvg",
                    "score": 86,
                    "raw_status": "actionable",
                    "effective_status": "actionable",
                    "trigger_prep": {
                        "effective_trigger_status": "confirmation_needed",
                        "execution_ready": True,
                    },
                    "price_level": {"invalidation_level": 718.90},
                }
            ],
            "near_tie_tools": [],
        },
        "structure": {
            "alignment": "bullish",
            "15m": {"bias": "bullish", "last_swing_low": 716.50},
            "5m":  {"bias": "bullish", "last_swing_low": 718.10},
            "3m":  {"bias": "neutral"},
            "1m":  {"bias": "neutral"},
        },
        "volatility": {},
        "expansion": {},
        "liquidity": {
            "15m": {
                "sweep_detected": True,
                "sweep_direction": "below",
                "reclaim_detected": True,
            },
        },
        "po3": {
            "alignment": "bullish",
            "15m": {"distribution_direction": "bullish"},
            "5m":  {"distribution_direction": "neutral"},
        },
        "memory": {"available": False, "snapshot_count": 0},
        "ai_context": {
            "market_narrative": "bullish",
            "market_state": "trending",
            "directional_bias": "bullish",
            "confidence_score": 73,
            "confidence_tier": "moderate",
            "trade_personality": "aggressive",
            "coherence": {},
            "warnings": [],
            "summary": "",
        },
        "market_regime": {"enabled": False},
        "experience_summary": {"experience_enabled": False, "sample_size": 0},
        "experience_correlation": {
            "sample_size": 0,
            "correlation_confidence": "none",
            "strongest_positive_correlations": [],
            "strongest_negative_correlations": [],
        },
        "ai_feedback_summary": {"sample_size": 0},
        "decision_authority": {
            "decision": "trade_authorized_false",
            "trade_authorized": False,
            "authority_level": "observe_only",
            "confidence_modifier": 0,
            "warnings": [],
        },
        "setup_lifecycle": {"active": True, "current_phase": "maturing"},
        "state_transition": {"invalidated": False, "transition_type": "upgrade"},
        "ai_debate": {"enabled": False, "final_verdict": {}},
        "confidence_fusion": {"fusion_status": "agreement", "combined_confidence": 73},
    }


def _scan59_ai_disc():
    return {
        "ai_direction": "bullish",
        "ai_confidence": 73,
        "fallback_used": False,
        "ai_external_success": True,
        "confidence_modifier": 0,
        "authority_level": "observe_only",
    }


def _bearish_snapshot():
    """Mirror of scan59 but flipped bearish — for test_02."""
    snap = _scan59_snapshot()
    snap["qualification"]["direction"] = "bearish"
    snap["playbook"]["direction"] = "bearish"
    snap["playbook"]["selected_playbook"] = "liquidity_sweep_reversal"
    snap["toolbox"]["preferred_tool"] = "bearish_ifvg"
    snap["toolbox"]["best_available_raw_status"] = "actionable"
    snap["toolbox"]["best_available_effective_status"] = "actionable"
    snap["toolbox"]["tool_candidates"] = [
        {
            "tool": "bearish_ifvg",
            "score": 86,
            "raw_status": "actionable",
            "effective_status": "actionable",
            "trigger_prep": {
                "effective_trigger_status": "confirmation_needed",
                "execution_ready": True,
            },
            "price_level": {"invalidation_level": 722.00},
        }
    ]
    snap["structure"] = {
        "alignment": "bearish",
        "15m": {"bias": "bearish", "last_swing_high": 722.50},
        "5m":  {"bias": "bearish", "last_swing_high": 721.80},
        "3m":  {"bias": "neutral"},
        "1m":  {"bias": "neutral"},
    }
    snap["liquidity"] = {
        "15m": {
            "sweep_detected": True,
            "sweep_direction": "above",
            "reclaim_detected": True,
        }
    }
    snap["po3"] = {
        "alignment": "bearish",
        "15m": {"distribution_direction": "bearish"},
        "5m":  {"distribution_direction": "neutral"},
    }
    snap["ai_context"]["directional_bias"] = "bearish"
    return snap


def _bearish_ai_disc():
    d = _scan59_ai_disc()
    d["ai_direction"] = "bearish"
    return d


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPhase5E4TriggerActiveAlignment(unittest.TestCase):

    # 01 — confirmation_needed + bullish → prepare_long (scan #59 regression)
    def test_01_confirmation_needed_bullish_produces_prepare_long(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertEqual(stance, "prepare_long",
            f"Expected prepare_long for confirmation_needed+bullish, got {stance!r}")

    # 02 — confirmation_needed + bearish → prepare_short
    def test_02_confirmation_needed_bearish_produces_prepare_short(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _bearish_snapshot()
        result = build_debate(snap, _bearish_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertEqual(stance, "prepare_short",
            f"Expected prepare_short for confirmation_needed+bearish, got {stance!r}")

    # 03 — waiting_for_retest does NOT produce prepare_long (trigger not yet at zone)
    def test_03_waiting_for_retest_does_not_produce_prepare_long(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["effective_trigger_status"] = "waiting_for_retest"
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["execution_ready"] = False
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertNotEqual(stance, "prepare_long",
            "waiting_for_retest must not produce prepare_long")
        self.assertEqual(stance, "bullish_bias",
            f"Expected bullish_bias for waiting_for_retest, got {stance!r}")

    # 04 — retest_in_progress behavior unchanged (still prepare_long)
    def test_04_retest_in_progress_still_produces_prepare_long(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["effective_trigger_status"] = "retest_in_progress"
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertEqual(stance, "prepare_long",
            f"retest_in_progress regression broken — expected prepare_long, got {stance!r}")

    # 05 — confirmed behavior unchanged (still prepare_long)
    def test_05_confirmed_still_produces_prepare_long(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["effective_trigger_status"] = "confirmed"
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertEqual(stance, "prepare_long",
            f"confirmed regression broken — expected prepare_long, got {stance!r}")

    # 06 — strong_disagreement still blocks execution gate (even when debate says prepare_long)
    def test_06_strong_disagreement_blocks_execution_gate(self):
        from execution_gate.execution_gate import evaluate_gate
        snap = _scan59_snapshot()
        # Simulate post-fix debate engine returning prepare_long
        snap["ai_debate"] = {"enabled": True, "final_verdict": {"recommended_stance": "prepare_long"}}
        snap["confidence_fusion"] = {"fusion_status": "strong_disagreement", "combined_confidence": 45}
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "true"}):
            gate = evaluate_gate(snap)
        self.assertFalse(gate["allow_execution"],
            "strong_disagreement must block allow_execution")
        self.assertFalse(gate["would_authorize_if_enabled"],
            "strong_disagreement must block would_authorize_if_enabled")
        self.assertIn("confidence fusion: strong disagreement", gate["blocking_factors"])

    # 07 — risk blocked still prevents prepare_long/short
    def test_07_risk_blocked_prevents_prepare_long(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        snap["risk"]["trade_allowed"] = False
        snap["risk"]["risk_tier"] = "blocked"
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertNotIn(stance, ("prepare_long", "prepare_short"),
            f"Risk blocked must not produce prepare_long/short, got {stance!r}")

    # 08 — no_tool / conflicted direction still blocks
    def test_08_no_tool_conflicted_direction_blocks(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        snap["toolbox"]["preferred_tool"] = None
        snap["toolbox"]["best_available_raw_status"] = "no_tool"
        snap["toolbox"]["best_available_effective_status"] = "no_tool"
        snap["toolbox"]["tool_candidates"] = []
        snap["playbook"]["direction"] = "conflicted"
        snap["qualification"]["direction"] = "conflicted"
        snap["liquidity"] = {}
        snap["structure"] = {
            "alignment": "conflicted",
            "15m": {"bias": "bullish"},
            "5m":  {"bias": "bearish"},
            "3m":  {"bias": "neutral"},
            "1m":  {"bias": "neutral"},
        }
        result = build_debate(snap, _scan59_ai_disc())
        stance = result["final_verdict"]["recommended_stance"]
        self.assertNotIn(stance, ("prepare_long", "prepare_short"),
            f"no_tool + conflicted direction must not produce prepare_long/short, got {stance!r}")

    # 09 — authority_level remains observe_only (debate engine does not mutate it)
    def test_09_authority_level_invariant_unchanged(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        build_debate(snap, _scan59_ai_disc())
        self.assertEqual(
            snap["decision_authority"]["authority_level"],
            "observe_only",
            "build_debate must not mutate authority_level",
        )

    # 10 — confidence_modifier remains 0 (debate engine does not mutate it)
    def test_10_confidence_modifier_remains_zero(self):
        from ai_layer.ai_debate_engine import build_debate
        snap = _scan59_snapshot()
        build_debate(snap, _scan59_ai_disc())
        self.assertEqual(
            snap["decision_authority"]["confidence_modifier"],
            0,
            "build_debate must not mutate confidence_modifier",
        )

    # 11 — full regression: all key modules importable without error
    def test_11_full_regression_imports(self):
        import importlib
        modules = [
            "ai_layer.ai_debate_engine",
            "ai_layer.ai_api_adapter",
            "ai_layer.discretionary_ai",
            "ai_layer.ai_input_builder",
            "execution_gate.execution_gate",
            "decision_authority.decision_engine",
            "toolbox.entry_trigger_prep",
            "toolbox.toolbox_engine",
            "recommendation_engine.recommendation_builder",
            "memory_search.similarity_search",
            "performance_intelligence.dashboard_builder",
        ]
        for mod in modules:
            with self.subTest(module=mod):
                importlib.import_module(mod)


if __name__ == "__main__":
    unittest.main()

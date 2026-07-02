"""
DECON-3 — Forensic hardening: the black-box flight-recorder contract.

Proves the persisted scan record is the complete post-runtime truth:
post-runtime writes only (refusal on unresolved runtime), and preservation of
symbol, decision, broker_called, order_status, adaptive policy, adaptive
mutation, structured block reasons (layer + owner + exact reason), mutation
reasoning, broker request/response payloads, market commander verdict, and the
confidence/qty original->final authority trace.

All writes go to a temp dir — never live forensic state.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import live_scan.snapshot_store as ss_mod                      # noqa: E402
from live_scan.snapshot_store import (                          # noqa: E402
    save_snapshot, build_block_trace, build_mutation_trace, build_authority_trace,
)


def _post_runtime_snapshot() -> dict:
    """A representative fully-resolved scan snapshot."""
    return {
        "timestamp": "2026-07-02T14:30:00+00:00",
        "session":   "afternoon",
        "symbol":    "QQQ",
        "qualification": {"status": "qualified", "grade": "B",
                          "opportunity_score": 72, "direction": "bullish"},
        "playbook":  {"selected_playbook": "expansion_continuation",
                      "status": "confirmed", "direction": "bullish"},
        "risk":      {"risk_tier": "reduced", "trade_allowed": True,
                      "risk_multiplier": 0.75, "authority_reason": "Reduced",
                      "blocks": [], "restrictions": ["15m volatility unstable"]},
        "toolbox":   {"preferred_tool": "bullish_fvg", "tool_candidates": [
            {"tool": "bullish_fvg", "score": 80, "raw_status": "actionable",
             "effective_status": "actionable"}]},
        "structure": {"alignment": "strong"},
        "volatility": {"15m": {"state": "stable"}, "5m": {"state": "stable"},
                       "3m": {"state": "unstable"}, "1m": {"state": "stable"}},
        "market_regime": {"enabled": True, "regime_label": "expansion_up",
                          "regime_family": "trend", "confidence": 70,
                          "volatility_state": "stable", "expansion_state": "expanding"},
        "regime_permissions": {"enabled": True, "allowed": True,
                               "permission_status": "allowed",
                               "risk_multiplier_cap": 1.0,
                               "required_trigger_status": "confirmed",
                               "min_setup_age_scans": 2,
                               "management_profile": "trend",
                               "blocking_reasons": []},
        "rule_governance": {"enabled": True, "fired": ["R-001"],
                            "opportunity": True, "events": [{"e": 1}],
                            "warning": None},
        "council": {"enabled": True, "authority_level": "enforce",
                    "members": [{"member": "REGIME", "vote": "no", "confidence": 95}],
                    "report": {"dominant_position": "no", "consensus_strength": 80},
                    "veto": {"veto_triggered": True, "veto_reason": "REGIME NO@95"}},
        "thesis_lifecycle": {"enabled": True, "mode": "enforce", "action": "continue",
                             "active_thesis": {"thesis_id": "TH-1",
                                               "thesis_type": "continuation",
                                               "direction": "bullish",
                                               "status": "ACTIVE",
                                               "confidence": 66, "age_scans": 4}},
        "thesis_state": {"present": True, "thesis_status": "ACTIVE"},
        "state_transition": {}, "setup_lifecycle": {}, "ai_debate": {},
        "decision_authority": {"decision": "ready_for_execution",
                               "trade_authorized": False, "direction": "bullish",
                               "confidence": 61, "reason": "aligned",
                               "blocking_factors": ["risk blocked (reduced)"]},
        "execution_gate": {"gate_status": "blocked", "allow_execution": False,
                           "would_authorize_if_enabled": False,
                           "authorization_checks": {
                               "decision_trade_authorized": False,
                               "risk_allows_trade": True,
                               "council_permits_trade": False,
                               "narrative_permits_trade": False},
                           "narrative_permits_trade": False,
                           "narrative_reason": "trade against protected high",
                           "council_permits_trade": False,
                           "no_promoted_rule_block": False,
                           "promoted_rules_fired": [
                               {"rule_id": "R-001", "reason": "hostile regime"}],
                           "blocking_factors": []},
        "trade_intent": {"intent_type": "long", "intent_created": True},
        "intent_score": {"scored": True, "gated_score": 55, "gating_applied": True,
                         "gating_reason": "risk tier reduced caps score"},
        "intent_archive": {},
        "adaptive_policy": {"symbol": "QQQ", "authority_level": "observe_only",
                            "posture": "DEFENSIVE_ONLY",
                            "confidence_penalty_recommended": True,
                            "risk_reduction_recommended": True,
                            "trade_block_recommended": True,
                            "recommended_adjustments": ["session(morning): weak"]},
        "adaptive_mutation": {"mutated": True,
                              "mutation_type": "confidence_penalty+trade_block",
                              "mutation_types": ["confidence_penalty", "trade_block"],
                              "original_confidence": 61, "new_confidence": 54.9,
                              "original_qty": None, "new_qty": None,
                              "trade_blocked": True,
                              "mutation_reasoning": [
                                  "confidence_penalty: confidence 61 -> 54.9 (-10%)",
                                  "trade_block: soft adaptive veto"],
                              "mutated_candidate": {"confidence": 54.9},
                              "authority_level": "shadow",
                              "posture": "DEFENSIVE_ONLY"},
        "adaptive_live_authority": {"applied": True, "trade_soft_blocked": True},
        "adaptive_block": {"blocked": True, "source": "adaptive_live_authority",
                           "reason": ["session(morning): weak"]},
        "adaptive_confidence": {"original": 61, "final": 54.9},
        "adaptive_live_consumption": {"adaptive_confidence_consumed": True,
                                      "adaptive_size_consumed": True,
                                      "original_live_confidence": 61,
                                      "final_live_confidence": 54.9,
                                      "original_live_qty": 4,
                                      "final_live_qty": 2,
                                      "notes": ["combined_confidence 61 -> 54.9"]},
        "market_commander": {"authority_level": "observe_only",
                             "source": "DETERMINISTIC_FALLBACK",
                             "final_state": "COMMAND_OBSERVE",
                             "environment": {"family": "DIRECTIONAL",
                                             "type": "EXPANSION_TREND",
                                             "confidence": 58, "completeness": 70,
                                             "conflict_index": 20},
                             "participation": {"decision": "OBSERVE",
                                               "confidence": 58,
                                               "reason": "confidence below gate",
                                               "gates": [{"name": "confidence",
                                                          "passed": False}]},
                             "consistency": {"logical_state_valid": True,
                                             "contradictions": []}},
        "position_supremacy": {"mismatch": False, "block_entries": False},
        "paper_execution": {"status": "skipped",
                            "reason": "execution gate blocked",
                            "order_summary": "", "alpaca_order_id": None,
                            "trade_id": None, "qty": 2,
                            "broker_trace": {"broker_called": False,
                                             "adapter": "alpaca_paper",
                                             "request": None, "response": None,
                                             "error": None, "latency_ms": None,
                                             "not_called_reason": "execution gate blocked"}},
        "position_monitor": {"enabled": True, "has_open_position": False},
        "stop_enforcer": {}, "broker_stop": {},
        "trade_reconciliation": {"status": "no_active_trade"},
        "pending_entry_order": {"status": "none"},
        "trade_management": {"action": "none"},
        "thesis_monitor": {"would_exit": False},
        "scar_writer": None, "eod_authority": None,
        "ai_shadow": {"enabled": True, "success": True, "stance": "prepare_long",
                      "confidence": 60, "agrees_with_live": True, "latency_ms": 900},
        "experience_summary": {}, "experience_report": {},
        "experience_correlation": {},
        "paper_activation_plan": {}, "paper_activation": {},
        "operational_readiness": {}, "activation_controller": {},
        "ai_feedback_summary": {}, "recommendations": {},
        "performance_dashboard": {}, "memory_search": {},
        "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 60},
        "confidence_fusion": {"combined_confidence": 54.9},
        "ai_context": {"market_narrative": "bullish_continuation",
                       "confidence_score": 61, "confidence_tier": "moderate",
                       "summary": "test"},
        "ai_brain": {"enabled": True, "authority": "ecu", "source": "llm",
                     "input_degraded": False, "output": {}},
        "ai_divergence": {}, "narrative_authority": {}, "protected_swings": {},
    }


def _persist(snap) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"LIVE_SNAPSHOTS_DIR": tmpdir}):
            fpath = save_snapshot(snap, "QQQ")
            with open(fpath, encoding="utf-8") as fh:
                return json.load(fh)


class TestPostRuntimeOnly(unittest.TestCase):
    def test_1_refuses_pre_runtime_write(self):
        snap = _post_runtime_snapshot()
        del snap["paper_execution"]
        with self.assertRaises(ValueError) as ctx:
            _persist(snap)
        self.assertIn("runtime incomplete", str(ctx.exception))
        self.assertIn("paper_execution", str(ctx.exception))

    def test_2_refuses_when_reconciliation_missing(self):
        snap = _post_runtime_snapshot()
        del snap["trade_reconciliation"]
        with self.assertRaises(ValueError):
            _persist(snap)

    def test_3_complete_runtime_writes(self):
        saved = _persist(_post_runtime_snapshot())
        self.assertEqual(saved["symbol"], "QQQ")


class TestForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = _persist(_post_runtime_snapshot())

    def test_symbol_and_core_context_preserved(self):
        s = self.saved
        self.assertEqual(s["symbol"], "QQQ")
        self.assertEqual(s["session"], "afternoon")
        self.assertEqual(s["volatility_states"]["3m"], "unstable")
        self.assertEqual(s["structure_alignment"], "strong")
        self.assertEqual(s["market_regime"]["regime_label"], "expansion_up")

    def test_decision_preserved(self):
        self.assertEqual(self.saved["decision_authority"]["decision"],
                         "ready_for_execution")

    def test_broker_called_and_order_status_preserved(self):
        bt = self.saved["broker_trace"]
        self.assertFalse(bt["broker_called"])
        self.assertEqual(bt["not_called_reason"], "execution gate blocked")
        self.assertEqual(self.saved["paper_execution"]["status"], "skipped")

    def test_adaptive_policy_preserved(self):
        ap = self.saved["adaptive_policy"]
        self.assertTrue(ap["trade_block_recommended"])
        self.assertEqual(ap["authority_level"], "observe_only")

    def test_adaptive_mutation_preserved_with_reasoning(self):
        am = self.saved["adaptive_mutation"]
        self.assertEqual(am["mutation_types"],
                         ["confidence_penalty", "trade_block"])
        self.assertTrue(any("confidence_penalty" in r
                            for r in am["mutation_reasoning"]))
        self.assertNotIn("mutated_candidate", am)   # compacted, fields preserved

    def test_mutation_trace_contract(self):
        mt = self.saved["mutation_trace"]
        self.assertEqual(mt["original_confidence"], 61)
        self.assertEqual(mt["new_confidence"], 54.9)
        self.assertTrue(mt["trade_blocked"])
        self.assertEqual(mt["authority_level"], "shadow")
        self.assertTrue(mt["consumed_live"]["confidence_consumed"])

    def test_block_trace_names_layer_owner_and_exact_reason(self):
        layers = {b["layer"]: b for b in self.saved["block_trace"]}
        self.assertIn("council", layers)
        self.assertIn("REGIME NO@95", layers["council"]["reason"])
        self.assertIn("narrative_authority", layers)
        self.assertIn("protected high", layers["narrative_authority"]["reason"])
        self.assertIn("rule_governance", layers)
        self.assertIn("R-001", layers["rule_governance"]["reason"])
        self.assertIn("adaptive_live_authority", layers)
        self.assertIn("intent_score", layers)
        self.assertIn("execution_engine", layers)
        self.assertIn("decision_authority", layers)
        # every entry carries layer + reason + field (no generic "blocked")
        for b in self.saved["block_trace"]:
            self.assertTrue(b["layer"])
            self.assertTrue(b["reason"])
            self.assertNotEqual(b["reason"].strip().lower(), "blocked")

    def test_constitutional_false_is_not_a_veto(self):
        # decision_trade_authorized is always False pre-gate by constitution —
        # it must NOT appear as a block
        gate_fields = [b.get("field") for b in self.saved["block_trace"]
                       if b["layer"] == "execution_gate"]
        self.assertNotIn("decision_trade_authorized", gate_fields)

    def test_authority_trace_confidence_and_qty(self):
        at = self.saved["authority_trace"]
        self.assertEqual(at["confidence_original"], 61)
        self.assertEqual(at["confidence_final"], 54.9)
        self.assertEqual(at["qty_original"], 4)
        self.assertEqual(at["qty_final"], 2)
        self.assertIn("order_builder", at["qty_owner"])

    def test_market_commander_preserved(self):
        mc = self.saved["market_commander"]
        self.assertEqual(mc["final_state"], "COMMAND_OBSERVE")
        self.assertEqual(mc["environment"]["family"], "DIRECTIONAL")
        self.assertEqual(mc["participation"]["decision"], "OBSERVE")
        self.assertEqual(mc["authority_level"], "observe_only")

    def test_governance_council_regime_preserved(self):
        self.assertEqual(self.saved["rule_governance"]["fired"], ["R-001"])
        self.assertTrue(self.saved["council"]["veto"]["veto_triggered"])
        self.assertTrue(self.saved["regime_permissions"]["allowed"])


class TestBrokerTracePreserved(unittest.TestCase):
    def test_submitted_broker_payload_response_latency(self):
        snap = _post_runtime_snapshot()
        snap["paper_execution"] = {
            "status": "submitted", "reason": "paper order submitted successfully",
            "order_summary": "buy 2 QQQ market 700.5",
            "alpaca_order_id": "abc-123", "trade_id": "PT_QQQ_X", "qty": 2,
            "broker_trace": {
                "broker_called": True, "adapter": "alpaca_paper",
                "request": {"symbol": "QQQ", "side": "buy", "qty": 2,
                            "order_type": "market", "entry_reference": 700.5,
                            "stop_reference": 699.0, "decision_price": 700.5,
                            "time_in_force": "day", "bracket_used": None},
                "response": {"alpaca_order_id": "abc-123", "status": "accepted"},
                "error": None, "latency_ms": 142,
            },
        }
        saved = _persist(snap)
        bt = saved["broker_trace"]
        self.assertTrue(bt["broker_called"])
        self.assertEqual(bt["adapter"], "alpaca_paper")
        self.assertEqual(bt["request"]["side"], "buy")
        self.assertEqual(bt["request"]["stop_reference"], 699.0)
        self.assertEqual(bt["response"]["status"], "accepted")
        self.assertEqual(bt["latency_ms"], 142)
        self.assertIsNone(bt["error"])

    def test_rejected_broker_error_payload(self):
        snap = _post_runtime_snapshot()
        snap["paper_execution"] = {
            "status": "rejected", "reason": "Order submission failed: boom",
            "order_summary": "", "alpaca_order_id": None, "trade_id": "PT_QQQ_Y",
            "broker_trace": {
                "broker_called": True, "adapter": "alpaca_paper",
                "request": {"symbol": "QQQ", "side": "buy", "qty": 2},
                "response": None,
                "error": "Order submission failed: boom", "latency_ms": 88,
            },
        }
        saved = _persist(snap)
        bt = saved["broker_trace"]
        self.assertTrue(bt["broker_called"])
        self.assertIn("boom", bt["error"])
        self.assertIsNone(bt["response"])

    def test_missing_broker_trace_synthesizes_not_called(self):
        snap = _post_runtime_snapshot()
        snap["paper_execution"] = {"status": "disabled",
                                   "reason": "EXECUTION_ENABLED=false"}
        saved = _persist(snap)
        self.assertFalse(saved["broker_trace"]["broker_called"])


class TestExecutionEngineBrokerTrace(unittest.TestCase):
    def test_disabled_path_carries_broker_trace(self):
        from paper_execution.execution_engine import attempt_paper_execution
        with patch.dict(os.environ, {"EXECUTION_ENABLED": "false"}):
            res = attempt_paper_execution({}, "QQQ")
        self.assertEqual(res["status"], "disabled")
        bt = res["broker_trace"]
        self.assertFalse(bt["broker_called"])
        self.assertEqual(bt["adapter"], "alpaca_paper")
        self.assertEqual(bt["not_called_reason"], "EXECUTION_ENABLED=false")


class TestTraceBuildersPure(unittest.TestCase):
    def test_builders_never_raise_on_empty(self):
        self.assertEqual(build_block_trace({}), [])
        self.assertEqual(build_block_trace(None), [])
        mt = build_mutation_trace({})
        self.assertFalse(mt["trade_blocked"])
        at = build_authority_trace({})
        self.assertIsNone(at["confidence_final"])

    def test_clean_scan_has_empty_block_trace(self):
        snap = _post_runtime_snapshot()
        snap["execution_gate"] = {"authorization_checks": {
            "decision_trade_authorized": False}, "narrative_permits_trade": True,
            "council_permits_trade": True, "no_promoted_rule_block": True}
        snap["decision_authority"]["blocking_factors"] = []
        snap["adaptive_block"] = {"blocked": False}
        snap["intent_score"] = {"gating_applied": False}
        snap["paper_execution"] = {"status": "submitted", "reason": "ok"}
        snap["council"] = {}
        self.assertEqual(build_block_trace(snap), [])


if __name__ == "__main__":
    unittest.main()

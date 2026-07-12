"""
TIER-2A (2026-07-10) — Legacy AI wrapper retirement lock.

Deleted organs: ai_layer discretionary_ai / ai_debate_engine / ai_input_builder /
shadow_ai_evaluator, live_scan ai_refresh_controller, ai_brain divergence.
KEPT: narrative_builder (fallback core), ai_api_adapter (Brain client),
ai_snapshot_formatter, confidence_engine (mechanical witness — NOT wrapper).

Replay parity (recorded brain, current stack, 0708+0709): 372/372 scans,
ZERO first_divergence; funnels identical (sov 49/38, qual 111/93,
intents 38/25, would_authorize 6/7). The wrapper was pure dead weight.

These tests keep the corpse buried: no module revival, no re-wiring, no
wrapper fields re-entering the snapshot pipeline.
"""
import importlib
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")

RETIRED_MODULES = (
    "ai_layer.discretionary_ai",
    "ai_layer.ai_debate_engine",
    "ai_layer.ai_input_builder",
    "ai_layer.shadow_ai_evaluator",
    "live_scan.ai_refresh_controller",
    "ai_brain.divergence",
    # TIER-2B (2026-07-10) — dead Phase-3 stub package (pass-only, zero
    # importers); the REAL journal is paper_execution/trade_journal.py
    "journal.trade_journal",
)

KEPT_MODULES = (
    "ai_layer.narrative_builder",
    "ai_layer.ai_api_adapter",
    "ai_layer.ai_snapshot_formatter",
    "ai_layer.confidence_engine",
)

# Wrapper output keys that must never be produced again. Reading them from
# HISTORICAL stored snapshots stays legal (forensics); producing them is not.
RETIRED_PRODUCED_KEYS = (
    'snapshot["ai_discretionary"]', "snapshot['ai_discretionary']",
    'snapshot["confidence_fusion"]', "snapshot['confidence_fusion']",
    'snapshot["ai_debate"]', "snapshot['ai_debate']",
    'snapshot["ai_shadow"]', "snapshot['ai_shadow']",
    'snapshot["ai_divergence"]', "snapshot['ai_divergence']",
)


def _walk_src():
    for root, _dirs, files in os.walk(_SRC):
        for fn in files:
            if fn.endswith(".py"):
                path = os.path.join(root, fn)
                with open(path, encoding="utf-8") as fh:
                    yield os.path.relpath(path, _SRC), fh.read()


class TestModulesGone(unittest.TestCase):
    def test_retired_modules_not_importable(self):
        for mod in RETIRED_MODULES:
            with self.assertRaises(ModuleNotFoundError, msg=mod):
                importlib.import_module(mod)

    def test_kept_modules_importable(self):
        for mod in KEPT_MODULES:
            importlib.import_module(mod)


class TestNoRewiring(unittest.TestCase):
    def test_no_source_imports_retired_modules(self):
        # match the exact dotted path or "from <pkg> import <leaf>"; bare leaf
        # substrings would false-positive on rule_governance.divergence_ledger
        patterns = []
        for mod in RETIRED_MODULES:
            pkg, leaf = mod.rsplit(".", 1)
            patterns += [mod, f"from {pkg} import {leaf}"]
        for rel, txt in _walk_src():
            for line in txt.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("import" in stripped
                        and any(p in stripped for p in patterns)):
                    self.fail(f"{rel}: retired-module import: {stripped}")

    def test_no_source_produces_wrapper_blocks(self):
        for rel, txt in _walk_src():
            for key in RETIRED_PRODUCED_KEYS:
                self.assertNotIn(f"{key} =", txt,
                                 f"{rel} assigns retired block {key}")

    def test_launcher_carries_no_shadow_flags(self):
        launcher = os.path.join(os.path.dirname(__file__), "..",
                                "launch_paper_session_fc.ps1")
        with open(launcher, encoding="utf-8") as fh:
            txt = fh.read()
        for flag in ("AI_SHADOW_ENABLED", "AI_SHADOW_MODE",
                     "AI_PROVIDER_SHADOW", "AI_MODEL_SHADOW"):
            self.assertNotIn(f"$env:{flag}", txt, flag)


class TestGateAndDecisionClean(unittest.TestCase):
    def test_gate_output_has_no_wrapper_fields(self):
        from execution_gate.execution_gate import evaluate_gate
        gate = evaluate_gate({})
        self.assertNotIn("ai_debate_stance_observed", gate)
        self.assertNotIn("fusion_status_observed", gate)

    def test_decision_confidence_reports_zero(self):
        # reporting-only key kept for record-schema stability across eras
        from decision_authority.decision_engine import make_decision
        da = make_decision({"qualification": {"status": "no_trade"}})
        self.assertEqual(da.get("confidence"), 0)


if __name__ == "__main__":
    unittest.main()

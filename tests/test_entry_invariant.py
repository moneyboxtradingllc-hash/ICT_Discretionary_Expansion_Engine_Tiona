"""
BRAIN-INVALIDATION-ENTRY-INVARIANT (2026-07-13) — audit + narrow repair.

Audit verdict (entry_invariant_audit_20260713.json): Outcome B. The Brain's
invalidation_level was dropped by BOTH thesis projections (produce_thesis and
as_brain_thesis) and consulted by NOTHING in the funnel — the order builder's
same-named stop field is the TOOLBOX zone's mechanical level, a name
collision. Measured: 37/80 (46%) of directional authorized scans across 22
sessions rode a thesis with no valid correct-side invalidation, own or
inherited.

The invariant: a directional Brain-owned thesis may not author FRESH exposure
until it names where it is wrong. The thesis is NOT neutralized — it stays
directional, persistent, lifecycle-visible, repairable. Neutral and
degraded-source theses are exempt (mechanical era untouched). Position safety
is unconditional (gate-only check; management never consults the gate).
Default off = byte-identical legacy.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.ecu import thesis_entry_eligible, _empty, produce_thesis  # noqa: E402
from execution_gate.execution_gate import evaluate_gate                 # noqa: E402

_ON = {"BRAIN_INVALIDATION_ENTRY_INVARIANT": "on"}


def _snap(direction="bearish", source="llm", inv=None, px=700.0):
    return {
        "brain_thesis": {"owner": "ai_brain", "source": source,
                         "direction": direction, "invalidation_level": inv},
        "trade_intent": {"entry_zone": {"current_price": px}},
    }


class TestEligibility(unittest.TestCase):
    def test_default_off_everything_eligible(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_INVALIDATION_ENTRY_INVARIANT", None)
            rec = thesis_entry_eligible(_snap(inv=None))
        self.assertTrue(rec["eligible"])
        self.assertEqual(rec["code"], "off")

    def test_bare_directional_sovereign_ineligible(self):
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(_snap(inv=None))
        self.assertFalse(rec["eligible"])
        self.assertEqual(rec["code"], "missing_invalidation")
        self.assertIn("ENTRY-INVARIANT", rec["reason"])

    def test_wrong_side_ineligible(self):
        # a bearish thesis "dying" below price is not a valid invalidation
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(_snap(inv=698.0, px=700.0))
        self.assertFalse(rec["eligible"])
        self.assertEqual(rec["code"], "wrong_side_invalidation")

    def test_own_valid_eligible(self):
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(_snap(inv=702.5, px=700.0))
        self.assertTrue(rec["eligible"])
        self.assertEqual(rec["code"], "valid")

    def test_inherited_via_active_thesis_eligible(self):
        # the served ab7_active_thesis carries the lifecycle's KEPT level
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(
                _snap(source="ab7_active_thesis", inv=702.5, px=700.0))
        self.assertTrue(rec["eligible"])

    def test_neutral_thesis_exempt(self):
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(_snap(direction="neutral"))
        self.assertTrue(rec["eligible"])
        self.assertEqual(rec["code"], "non_directional")

    def test_degraded_source_exempt_mechanical_era_untouched(self):
        for src in ("deterministic", "llm_failed_fallback", "degraded",
                    "contaminated_input", ""):
            with patch.dict(os.environ, _ON):
                rec = thesis_entry_eligible(_snap(source=src, inv=None))
            self.assertTrue(rec["eligible"], src)
            self.assertEqual(rec["code"], "non_sovereign_source", src)

    def test_unknown_price_denies_fresh_exposure(self):
        # HARDENED (2026-07-13): an entry authority must not infer permission
        # from uncertainty — unverifiable side = no fresh exposure
        snap = _snap(inv=698.0)
        snap["trade_intent"] = {}
        with patch.dict(os.environ, _ON):
            rec = thesis_entry_eligible(snap)
        self.assertFalse(rec["eligible"])
        self.assertEqual(rec["code"], "missing_current_price")
        self.assertIn("current price unavailable", rec["reason"])


class TestProjections(unittest.TestCase):
    def test_empty_candidate_carries_field(self):
        self.assertIn("invalidation_level", _empty("x"))

    def test_produce_thesis_projects_output_invalidation(self):
        fake = {"enabled": True, "source": "llm", "output": {
            "narrative_direction": "bearish", "narrative_phase": "manipulation",
            "forbidden_direction": "bullish", "phase_confidence": 60,
            "recommended_playbook_family": "liquidity_sweep_reversal",
            "recommended_tool_family": ["ifvg"],
            "dominant_reasoning": "r", "invalidation_level": 702.5}}
        with patch.dict(os.environ, {"AI_BRAIN_ENABLED": "true"}), \
             patch("ai_brain.narrative_brain.run_narrative_brain",
                   return_value=fake), \
             patch("ai_brain.narrative_brain.enabled", return_value=True):
            cand = produce_thesis({"symbol": "QQQ"})
        self.assertEqual(cand["invalidation_level"], 702.5)

    def test_as_brain_thesis_projects_inherited_level(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "src",
                               "ai_brain", "thesis_lifecycle.py"),
                  encoding="utf-8") as fh:
            txt = fh.read()
        # the served projection carries the ACTIVE thesis's kept level
        self.assertIn('"invalidation_level": a.get("invalidation_level")', txt)


class TestGateWiring(unittest.TestCase):
    def test_gate_blocks_and_names_the_invariant(self):
        snap = _snap(inv=None)
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(snap)
        self.assertFalse(gate["authorization_checks"]["thesis_invalidation_ok"])
        self.assertFalse(gate["would_authorize_if_enabled"])
        self.assertTrue(any("entry invariant" in b
                            for b in gate["blocking_factors"]))

    def test_gate_check_passes_when_covered(self):
        snap = _snap(inv=702.5, px=700.0)
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(snap)
        self.assertTrue(gate["authorization_checks"]["thesis_invalidation_ok"])

    def test_default_off_gate_check_true(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_INVALIDATION_ENTRY_INVARIANT", None)
            gate = evaluate_gate(_snap(inv=None))
        self.assertTrue(gate["authorization_checks"]["thesis_invalidation_ok"])


class TestPositionSafetyUnconditional(unittest.TestCase):
    def test_flag_absent_from_position_and_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for parts in (("paper_execution", "position_monitor.py"),
                      ("paper_execution", "stop_enforcer.py"),
                      ("paper_execution", "trade_manager.py"),
                      ("paper_execution", "order_builder.py"),
                      ("paper_execution", "paper_broker.py"),
                      ("paper_execution", "position_supremacy.py"),
                      ("risk", "risk_governor.py"),
                      ("operational_readiness", "eod_authority.py")):
            path = os.path.join(src, *parts)
            self.assertTrue(os.path.exists(path), path)
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("BRAIN_INVALIDATION_ENTRY_INVARIANT",
                                 fh.read(), "/".join(parts))

    def test_launcher_carries_flag(self):
        launcher = os.path.join(os.path.dirname(__file__), "..",
                                "launch_paper_session_fc.ps1")
        with open(launcher, encoding="utf-8") as fh:
            self.assertIn('$env:BRAIN_INVALIDATION_ENTRY_INVARIANT = "on"',
                          fh.read())


if __name__ == "__main__":
    unittest.main()

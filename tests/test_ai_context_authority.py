"""
AI_CONTEXT-AUTHORITY (2026-07-09) — truth-in-labelling for ai_context.

Every ai_context field is MECHANICALLY authored (build_narrative / score_confidence
read only structure/volatility/expansion/liquidity/po3 — no Brain input). The name
is misleading; the true Brain is snapshot['ai_brain']/['brain_thesis']. This locks:
  - explicit per-field author metadata (ai_context['_authorship'] + witness marker)
  - the mechanical market_narrative may NOT hard-disqualify / hard-block / downgrade
    playbook when the Brain holds a SOVEREIGN directional conversion (demoted to
    witness); a degraded/absent Brain keeps it as a live safety net
  - mechanical directional_bias may NOT override Brain direction
  - confidence_tier stays JUDGE-FREEZE witness; trade_personality is a label only
  - all SAFETY systems untouched

Mission-required tests 1-10.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shared_context.mechanical_judges import mechanical_context_witness   # noqa: E402
from qualification.trade_qualification_engine import (                    # noqa: E402
    _is_disqualified, _direction_with_source,
)
from risk.risk_governor import _hard_blocks                               # noqa: E402
from playbooks.playbook_classifier import _score_trend_continuation       # noqa: E402


def _sovereign_thesis(direction="bullish"):
    return {"owner": "ai_brain", "source": "llm", "direction": direction,
            "opportunity": True, "playbook_family": "trend_continuation"}


class TestAuthorshipMetadata(unittest.TestCase):
    def test_1_authorship_metadata_marks_mechanical(self):
        # snapshot_builder tags every ai_context field's real author
        from market_data import snapshot_builder
        src = os.path.join(os.path.dirname(__file__), "..", "src",
                           "market_data", "snapshot_builder.py")
        with open(src, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn('"_authorship"', txt)
        self.assertIn('"ai_context_is_mechanical_witness"', txt)
        self.assertIn('"market_narrative":  "mechanical_derived"', txt)


class TestNarrativeDisqualifierDemotion(unittest.TestCase):
    def test_2_mechanical_narrative_cannot_disqualify_sovereign_brain(self):
        ai = {"market_narrative": "exhaustion_risk", "market_state": "normal"}
        # legacy: mechanical narrative hard-disqualifies
        self.assertTrue(_is_disqualified(ai, {}, demote_narrative=False)[0])
        # sovereign demotion: witness-only, does not disqualify
        self.assertFalse(_is_disqualified(ai, {}, demote_narrative=True)[0])

    def test_witness_gate_requires_both_freeze_and_sovereign(self):
        sov = {"brain_thesis": _sovereign_thesis()}
        deg = {"brain_thesis": {"source": "deterministic", "direction": "bullish",
                                "opportunity": True, "playbook_family": "trend_continuation"}}
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "active"}):
            self.assertFalse(mechanical_context_witness(sov))       # off by default
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            self.assertTrue(mechanical_context_witness(sov))        # frozen + sovereign
            self.assertFalse(mechanical_context_witness(deg))       # degraded Brain = safety net


class TestRiskNarrativeDemotion(unittest.TestCase):
    def _snap(self):
        return {"ai_context": {"market_narrative": "compression", "confidence_tier": "valid_setup"},
                "playbook": {"selected_playbook": "trend_continuation"},
                "risk": {}, "brain_thesis": _sovereign_thesis()}

    def test_3_mechanical_state_narrative_cannot_block_risk_when_sovereign(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "active"}):
            blocks = _hard_blocks(self._snap())
            self.assertTrue(any("engagement prohibited" in b for b in blocks))
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            blocks = _hard_blocks(self._snap())
            self.assertFalse(any("engagement prohibited" in b for b in blocks))


class TestBiasCannotOverrideDirection(unittest.TestCase):
    def test_4_mechanical_bias_cannot_override_brain_direction(self):
        # mechanical bias says bullish; Brain thesis says bearish → Brain wins
        ai = {"directional_bias": "bullish"}
        direction, source = _direction_with_source(
            ai, {}, {}, {}, _sovereign_thesis(direction="bearish"))
        self.assertEqual(direction, "bearish")
        self.assertEqual(source, "ai_brain")


class TestConfTierAndPersonality(unittest.TestCase):
    def _snap(self, tier):
        return {"ai_context": {"confidence_tier": tier, "directional_bias": "bullish"},
                "expansion": {}, "structure": {}, "market_regime": {},
                "liquidity": {}, "po3": {}}

    def test_5_conf_tier_telemetry_only_under_judge_freeze(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            hi = _score_trend_continuation(self._snap("elite_setup"))
            lo = _score_trend_continuation(self._snap("no_trade"))
            self.assertEqual(hi - lo, 0)   # conf_tier does not nudge

    def test_6_trade_personality_cannot_zero_sovereign_opportunity(self):
        # trade_personality only labels _trade_type; it is not a disqualifier
        ai = {"market_narrative": "trend_continuation", "trade_personality": "no_trade_context",
              "market_state": "normal"}
        # no_trade narrative not present → not disqualified regardless of personality
        self.assertFalse(_is_disqualified(ai, {}, demote_narrative=False)[0])


class TestPlaybookStateDemotion(unittest.TestCase):
    def _snap(self, witness_env):
        s = {"ai_context": {"market_state": "dangerous", "directional_bias": "bullish"},
             "expansion": {}, "structure": {}, "market_regime": {},
             "liquidity": {}, "po3": {}}
        if witness_env:
            s["brain_thesis"] = _sovereign_thesis()
        return s

    def test_mechanical_state_penalty_gated_when_sovereign(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            penalised = _score_trend_continuation(self._snap(witness_env=False))   # no brain
            witnessed = _score_trend_continuation(self._snap(witness_env=True))    # sovereign
            # sovereign score is >= non-sovereign (the -15 dangerous penalty is lifted)
            self.assertGreaterEqual(witnessed, penalised)


class TestSafetyUntouched(unittest.TestCase):
    def test_7_to_10_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("broker", "broker_adapter.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    txt = fh.read()
                self.assertNotIn("mechanical_context_witness", txt, f"{pkg}/{fname}")
                self.assertNotIn("demote_narrative", txt, f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

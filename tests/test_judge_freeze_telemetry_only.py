"""
JUDGE-FREEZE (2026-07-09) — mechanical judges frozen to telemetry_only.

The mechanical confidence_tier still influenced decisions off the execution gate:
it disqualified in qualification, hard-blocked in risk, and boosted playbook
scores — a second opinion competing with the sovereign AI Brain. MECHANICAL_
JUDGES_MODE=telemetry_only freezes that: the tier may observe/warn/log/record but
may NOT block execution or alter qualification / decision / playbook. Regime and
council are already gate-demoted (REGIME-DEMOTE / MC-ENFORCE); the regime risk cap
(reduce-only) and all safety systems are untouched. Default active = legacy.

Locks:
  1. default is active; telemetry_only detected
  2. conf_tier no_trade disqualifies in active, NOT in telemetry_only
  3. conf_tier no_trade hard-blocks risk in active, NOT in telemetry_only
  4. witness telemetry preserved in telemetry_only (restriction recorded)
  5. conf_tier playbook boost applied in active, NOT in telemetry_only
  6. safety untouched — flag absent from order_builder/broker/stops; regime cap stays
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shared_context.mechanical_judges import (                          # noqa: E402
    mechanical_judges_mode, judges_telemetry_only,
)
from qualification.trade_qualification_engine import _is_disqualified   # noqa: E402
from risk.risk_governor import _hard_blocks, evaluate_risk              # noqa: E402
from playbooks.playbook_classifier import _score_trend_continuation     # noqa: E402


class TestMode(unittest.TestCase):
    def test_1_default_active(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MECHANICAL_JUDGES_MODE", None)
            self.assertEqual(mechanical_judges_mode(), "active")
            self.assertFalse(judges_telemetry_only())

    def test_1b_telemetry_only_detected(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            self.assertTrue(judges_telemetry_only())


class TestQualificationFreeze(unittest.TestCase):
    def _ai(self):
        return {"confidence_tier": "no_trade", "market_state": "normal",
                "market_narrative": "trend_continuation"}

    def test_2_conf_tier_disqualifies_active_not_frozen(self):
        active, _ = _is_disqualified(self._ai(), {}, demote_conf_tier=False)
        self.assertTrue(active)   # legacy: conf_tier no_trade disqualifies
        frozen, reason = _is_disqualified(self._ai(), {}, demote_conf_tier=True)
        self.assertFalse(frozen)  # frozen: conf_tier is witness-only


class TestRiskFreeze(unittest.TestCase):
    def _snap(self):
        return {"ai_context": {"confidence_tier": "no_trade",
                               "market_narrative": "trend_continuation"},
                "playbook": {"selected_playbook": "trend_continuation"},
                "risk": {}}

    def test_3_conf_tier_blocks_risk_active_not_frozen(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "active"}):
            blocks = _hard_blocks(self._snap())
            self.assertTrue(any("confidence tier is no_trade" in b for b in blocks))
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            blocks = _hard_blocks(self._snap())
            self.assertFalse(any("confidence tier is no_trade" in b for b in blocks))

    def test_4_witness_restriction_preserved_when_frozen(self):
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            verdict = evaluate_risk(self._snap())
            joined = " ".join(verdict.get("restrictions", []))
            self.assertIn("witness only", joined)
            self.assertIn("JUDGE-FREEZE", joined)


class TestPlaybookFreeze(unittest.TestCase):
    def _snap(self, tier):
        # directional_bias keeps the score above the max(0, ...) floor so the
        # +10 conf-tier nudge is observable rather than clipped.
        return {"ai_context": {"confidence_tier": tier, "directional_bias": "bullish"},
                "expansion": {}, "structure": {}, "market_regime": {},
                "liquidity": {}, "po3": {}}

    def test_5_conf_tier_boost_applied_active_not_frozen(self):
        # elite_setup gives trend_continuation a +10 conf-tier nudge in active mode
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "active"}):
            hi = _score_trend_continuation(self._snap("elite_setup"))
            lo = _score_trend_continuation(self._snap("no_trade"))
            self.assertEqual(hi - lo, 10)   # legacy nudge present
        with patch.dict(os.environ, {"MECHANICAL_JUDGES_MODE": "telemetry_only"}):
            hi = _score_trend_continuation(self._snap("elite_setup"))
            lo = _score_trend_continuation(self._snap("no_trade"))
            self.assertEqual(hi - lo, 0)    # frozen: conf_tier does not nudge


class TestSafetyUntouched(unittest.TestCase):
    def test_6_flag_absent_from_safety_systems(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("broker", "broker_adapter.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("MECHANICAL_JUDGES_MODE", fh.read(), f"{pkg}/{fname}")

    def test_6b_regime_risk_cap_still_reduces(self):
        # the regime risk-multiplier cap (safety) is reduce-only and independent
        # of judge-freeze — order_builder still takes min(governor, regime_cap)
        src = os.path.join(os.path.dirname(__file__), "..", "src", "paper_execution", "order_builder.py")
        with open(src, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("risk_multiplier_cap", txt)
        self.assertIn("min(", txt)


if __name__ == "__main__":
    unittest.main()

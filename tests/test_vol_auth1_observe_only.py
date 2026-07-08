"""
VOL-AUTH-1 — volatility authority demotion (observe_only): regression lock.

During ADAPTIVE-8 validation, volatility is demoted from VETO authority to
OBSERVE-ONLY (VOLATILITY_AUTHORITY_MODE=observe_only): it still calculates,
logs toxic/dangerous/explosive states, and records would_have_vetoed, but it may
NOT zero qualification, hard-block risk, or prevent execution. Default 'enforce'
keeps full veto authority byte-identical. Flip the flag to roll back.

The three demoted hard-block sites (single owner: volatility_authority):
  * confidence_engine._apply_caps — the dangerous-state cap (->49)
  * qualification._is_disqualified — dangerous + multi-TF-toxic branches
  * risk_governor._hard_blocks — dangerous + multi-TF-toxic blocks

Locks (all against the real 2026-07-08 10:58 toxic/dangerous environment):
  1. toxic volatility no longer hard-zeroes qualification in observe_only
  2. dangerous state no longer hard-blocks risk in observe_only
  3. volatility warnings remain visible in both modes
  4. would_have_vetoed recorded in both modes
  5-8. FC-0B / sizing / loss+trade limits / broker safeguards untouched (guard)
  9. enforce restores full veto authority (byte-identical verdict)
  + conflicted / no_trade_context caps are NOT volatility — always apply
  + a non-volatility no_trade still stands down in observe_only
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_layer.confidence_engine import score_confidence               # noqa: E402
from qualification.trade_qualification_engine import qualify_trade    # noqa: E402
from risk.risk_governor import evaluate_risk                          # noqa: E402
from volatility_authority.volatility_authority import (               # noqa: E402
    observe_only, volatility_veto_reason,
)

_TOXIC_VOL = {"15m": {"state": "toxic"}, "5m": {"state": "explosive"},
              "3m": {"state": "toxic"}}


def _confidence(mode):
    with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": mode}):
        return score_confidence(
            {"alignment": "full"}, _TOXIC_VOL,
            {"15m": {"state": "healthy_expansion"}},
            {"5m": {"sweep_detected": True, "reclaim_detected": True}},
            "ny_open",
            {"market_narrative": "liquidity_sweep_reversal",
             "trade_personality": "liquidity_sweep_reversal",
             "market_state": "dangerous"},
            {"alignment": "full_distribution_alignment"}, {})


def _snap(mode):
    conf = _confidence(mode)
    ai = {"market_narrative": "liquidity_sweep_reversal",
          "confidence_tier": conf["confidence_tier"],
          "confidence_score": conf["confidence_score"],
          "market_state": "dangerous", "directional_bias": "bearish",
          "trade_personality": "liquidity_sweep_reversal"}
    return conf, {
        "ai_context": ai, "structure": {"alignment": "full"},
        "po3": {"alignment": "full_distribution_alignment"}, "memory": {},
        "liquidity": {"5m": {"sweep_detected": True, "reclaim_detected": True}},
        "volatility": _TOXIC_VOL, "expansion": {"15m": {"state": "healthy_expansion"}},
        "toolbox": {"best_available_raw_status": "ready",
                    "preferred_tool": "bearish_ifvg"},
    }


class TestObserveOnlyDemotion(unittest.TestCase):
    def test_toxic_no_longer_zeroes_qualification(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            _c, snap = _snap("observe_only")
            q = qualify_trade(snap)
        self.assertNotEqual(q["status"], "no_trade")
        self.assertGreater(q["opportunity_score"], 0)
        self.assertFalse(q["qualification_zeroed_by_volatility"])
        self.assertEqual(q["volatility_authority"], "observe_only")
        self.assertEqual(q["volatility_effect_on_score"], "advisory_only")

    def test_dangerous_no_longer_hard_blocks_risk(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            _c, snap = _snap("observe_only")
            snap["qualification"] = qualify_trade(snap)
            snap["playbook"] = {"status": "active",
                                "selected_playbook": "liquidity_sweep_reversal",
                                "warnings": []}
            snap["session"] = "ny_open"
            r = evaluate_risk(snap)
        self.assertTrue(r["trade_allowed"])
        self.assertFalse(any("toxic" in b for b in r["blocks"]))
        self.assertFalse(any("dangerous market state" in b for b in r["blocks"]))

    def test_would_have_vetoed_recorded_both_modes(self):
        for mode in ("enforce", "observe_only"):
            with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": mode}):
                _c, snap = _snap(mode)
                q = qualify_trade(snap)
            self.assertTrue(q["volatility_would_have_vetoed"], mode)
            self.assertIsNotNone(q["volatility_veto_reason"], mode)

    def test_volatility_warnings_remain_visible(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            _c, snap = _snap("observe_only")
            q = qualify_trade(snap)
        # both the raw _qual_warnings volatility lines AND the VOL-AUTH note
        self.assertTrue(any("volatil" in w.lower() for w in q["warnings"]))
        self.assertTrue(any("would have vetoed" in w.lower() for w in q["warnings"]))

    def test_risk_records_would_have_vetoed_restriction(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            _c, snap = _snap("observe_only")
            snap["qualification"] = qualify_trade(snap)
            snap["playbook"] = {"status": "active",
                                "selected_playbook": "liquidity_sweep_reversal",
                                "warnings": []}
            r = evaluate_risk(snap)
        self.assertEqual(r["volatility_authority"], "observe_only")
        self.assertTrue(r["volatility_would_have_vetoed"])
        self.assertTrue(any("would_have_vetoed" in s for s in r["restrictions"]))


class TestEnforceUnchanged(unittest.TestCase):
    def test_enforce_still_zeroes_and_blocks(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "enforce"}):
            conf, snap = _snap("enforce")
            q = qualify_trade(snap)
            snap["qualification"] = q
            snap["playbook"] = {"status": "active",
                                "selected_playbook": "liquidity_sweep_reversal",
                                "warnings": []}
            r = evaluate_risk(snap)
        self.assertEqual(conf["confidence_score"], 49)      # cap intact
        self.assertEqual(q["status"], "no_trade")
        self.assertEqual(q["opportunity_score"], 0)
        self.assertTrue(q["qualification_zeroed_by_volatility"])
        self.assertFalse(r["trade_allowed"])
        self.assertTrue(any("toxic" in b for b in r["blocks"]))

    def test_default_is_enforce(self):
        # no env var set → enforce (full veto authority)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VOLATILITY_AUTHORITY_MODE", None)
            self.assertFalse(observe_only())


class TestNonVolatilityUnaffected(unittest.TestCase):
    def test_conflicted_cap_still_applies_in_observe_only(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            c = score_confidence(
                {"alignment": "full"}, _TOXIC_VOL,
                {"15m": {"state": "healthy_expansion"}},
                {"5m": {"sweep_detected": True, "reclaim_detected": True}},
                "ny_open",
                {"market_narrative": "conflicted",
                 "trade_personality": "no_trade_context",
                 "market_state": "dangerous"},
                {"alignment": "full_distribution_alignment"}, {})
        self.assertLessEqual(c["confidence_score"], 49)
        self.assertEqual(c["confidence_tier"], "no_trade")

    def test_no_trade_narrative_still_stands_down_in_observe_only(self):
        with patch.dict(os.environ, {"VOLATILITY_AUTHORITY_MODE": "observe_only"}):
            snap = {"ai_context": {"market_narrative": "exhaustion_risk",
                                   "confidence_tier": "no_trade",
                                   "market_state": "dangerous"},
                    "structure": {}, "po3": {}, "memory": {}, "liquidity": {},
                    "volatility": _TOXIC_VOL}
            q = qualify_trade(snap)
        self.assertEqual(q["status"], "no_trade")
        self.assertFalse(q["qualification_zeroed_by_volatility"])
        self.assertIn("exhaustion_risk", q["disqualifier_reason"])


class TestSafetyUntouched(unittest.TestCase):
    def test_flag_does_not_reach_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution", "order_builder.py"),       # FC-0B
                ("paper_execution", "execution_engine.py"),
                ("operational_readiness", "startup_authority.py"),  # limits
        ):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("VOLATILITY_AUTHORITY_MODE", body, f"{pkg}/{fname}")
            self.assertNotIn("volatility_authority", body, f"{pkg}/{fname}")

    def test_veto_oracle_matches_demoted_conditions(self):
        # dangerous + no safe harbor
        self.assertIsNotNone(volatility_veto_reason(
            {"market_state": "dangerous"},
            {"5m": {"state": "toxic"}, "3m": {"state": "toxic"}}))
        # dangerous but safe harbor → no veto
        self.assertIsNone(volatility_veto_reason(
            {"market_state": "dangerous"},
            {"5m": {"state": "stable"}, "3m": {"state": "stable"}}))
        # multi-TF toxic
        self.assertIsNotNone(volatility_veto_reason(
            {}, {"15m": {"state": "toxic"}, "5m": {"state": "explosive"}}))
        # calm → no veto
        self.assertIsNone(volatility_veto_reason(
            {}, {"15m": {"state": "stable"}, "5m": {"state": "expanding"}}))


if __name__ == "__main__":
    unittest.main()

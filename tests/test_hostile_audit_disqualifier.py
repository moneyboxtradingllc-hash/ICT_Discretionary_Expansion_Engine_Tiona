"""
HOSTILE-AUDIT — truthful hard-disqualifier reporting: regression lock.

2026-07-08 10:58 ET: bearish_ifvg raw=READY, playbook liquidity_sweep_reversal
ACTIVE bearish, narrative bearish — yet qualification collapsed to no_trade /
score 0 and the organism reported "no opportunity identified". The verdict was
LEGITIMATE: between 10:47 (qualified 81, healthy) and 10:58 the 1m tape printed
1.00 then 1.96-pt ranges, flipping 15m+5m volatility to toxic/explosive and the
market state to dangerous — a real multi-timeframe danger refusal. The DEFECT
was audit truth: the READY setup WAS seen and the ENVIRONMENT was refused for
danger, but the bot said "no opportunity identified".

Repair (audit-truth only; verdict byte-identical, proven by bool-equivalence):
  * _is_disqualified returns (bool, reason); the boolean is unchanged (control
    flow order preserved — conf_tier check stays first)
  * the reason names the ROOT (dangerous / multi-TF toxic behind a no_trade tier)
  * qualification exposes disqualifier_reason + a hard-disqualifier warning
  * decision_engine names the environment refusal and the READY tool instead
    of "no opportunity identified" (post-toolbox, tool-aware)
  * risk block message defers to the reason (block logic/tier unchanged)

Locks:
  * a READY bearish_ifvg zeroed by danger reports the NAMED disqualifier, not
    "no opportunity identified"
  * the disqualification verdict itself is unchanged (safety preserved)
  * risk is an ECHO, not the owner; trigger/no-intent are downstream
  * a genuinely-weak (non-danger) no_trade still reads confidence_tier_no_trade
  * qualified scans carry no disqualifier_reason
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qualification.trade_qualification_engine import (                  # noqa: E402
    _is_disqualified, qualify_trade,
)
from decision_authority.decision_engine import _build_reason           # noqa: E402
from risk.risk_governor import evaluate_risk                           # noqa: E402


def _orig_bool(ai, vol, demote=False):
    """The pre-repair boolean logic — the equivalence reference."""
    ms = ai.get("market_state", ""); ct = ai.get("confidence_tier", "")
    n = ai.get("market_narrative", "")
    if n in {"conflicted", "exhaustion_risk", "compression"}:
        return True
    if ct == "no_trade" and not demote:
        return True
    if ms == "dangerous":
        v5 = vol.get("5m", {}).get("state", ""); v3 = vol.get("3m", {}).get("state", "")
        if v5 in ("stable", "expanding") and v3 in ("stable", "expanding"):
            return False
        return True
    tox = sum(1 for tf in ["15m", "5m"]
              if vol.get(tf, {}).get("state") in ("toxic", "explosive"))
    return tox >= 2


class TestVerdictUnchanged(unittest.TestCase):
    def test_bool_equivalence_matrix(self):
        states = ["stable", "expanding", "toxic", "explosive", ""]
        narrs = ["bearish_continuation", "liquidity_sweep_reversal",
                 "conflicted", "exhaustion_risk"]
        tiers = ["elite_setup", "valid_setup", "observe", "no_trade"]
        n = 0
        for nar in narrs:
            for ct in tiers:
                for ms in ("", "dangerous"):
                    for v15 in states:
                        for v5 in states:
                            for v3 in states:
                                for dem in (False, True):
                                    ai = {"market_narrative": nar,
                                          "confidence_tier": ct,
                                          "market_state": ms}
                                    vol = {"15m": {"state": v15},
                                           "5m": {"state": v5},
                                           "3m": {"state": v3}}
                                    got = _is_disqualified(ai, vol, dem)[0]
                                    self.assertEqual(got, _orig_bool(ai, vol, dem))
                                    n += 1
        self.assertGreater(n, 5000)


class TestReasonNamesRoot(unittest.TestCase):
    def test_1058_toxic_danger_reason(self):
        dq, reason = _is_disqualified(
            {"market_narrative": "liquidity_sweep_reversal",
             "confidence_tier": "no_trade", "market_state": "dangerous"},
            {"15m": {"state": "toxic"}, "5m": {"state": "explosive"},
             "3m": {"state": "toxic"}})
        self.assertTrue(dq)
        self.assertIn("dangerous", reason)
        self.assertNotEqual(reason, "confidence_tier_no_trade")

    def test_multi_tf_toxic_without_dangerous_flag(self):
        dq, reason = _is_disqualified(
            {"market_narrative": "bearish_continuation",
             "confidence_tier": "no_trade", "market_state": ""},
            {"15m": {"state": "toxic"}, "5m": {"state": "explosive"}})
        self.assertTrue(dq)
        self.assertIn("toxic", reason)

    def test_genuinely_weak_confidence_stays_plain(self):
        dq, reason = _is_disqualified(
            {"market_narrative": "bearish_continuation",
             "confidence_tier": "no_trade", "market_state": ""},
            {"15m": {"state": "stable"}, "5m": {"state": "stable"}})
        self.assertTrue(dq)
        self.assertEqual(reason, "confidence_tier_no_trade")

    def test_no_trade_narrative_named(self):
        dq, reason = _is_disqualified(
            {"market_narrative": "exhaustion_risk", "confidence_tier": "observe",
             "market_state": ""}, {})
        self.assertTrue(dq)
        self.assertIn("exhaustion_risk", reason)

    def test_qualified_has_no_disqualifier(self):
        dq, reason = _is_disqualified(
            {"market_narrative": "bearish_continuation",
             "confidence_tier": "elite_setup", "market_state": ""},
            {"15m": {"state": "expanding"}, "5m": {"state": "stable"}})
        self.assertFalse(dq)
        self.assertIsNone(reason)


class TestQualificationSurface(unittest.TestCase):
    def _snap_1058(self):
        return {
            "ai_context": {"market_narrative": "liquidity_sweep_reversal",
                           "confidence_tier": "no_trade", "confidence_score": 49,
                           "market_state": "dangerous"},
            "structure": {}, "po3": {}, "memory": {}, "liquidity": {},
            "volatility": {"15m": {"state": "toxic"}, "5m": {"state": "explosive"},
                           "3m": {"state": "toxic"}},
        }

    def test_disqualifier_reason_surfaced(self):
        out = qualify_trade(self._snap_1058())
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)
        self.assertIsNotNone(out["disqualifier_reason"])
        self.assertIn("dangerous", out["disqualifier_reason"])
        self.assertTrue(any("hard disqualifier" in w for w in out["warnings"]))

    def test_qualified_scan_no_disqualifier_field(self):
        snap = self._snap_1058()
        snap["ai_context"].update({"market_narrative": "bearish_continuation",
                                   "confidence_tier": "elite_setup",
                                   "market_state": ""})
        snap["volatility"] = {"15m": {"state": "expanding"}, "5m": {"state": "stable"}}
        snap["po3"] = {"alignment": "full_distribution_alignment"}
        snap["structure"] = {"alignment": "full"}
        out = qualify_trade(snap)
        self.assertIsNone(out["disqualifier_reason"])


class TestDecisionReportsTruth(unittest.TestCase):
    def _snap(self, raw_status, disq="multi_timeframe_toxic_volatility(15m+5m)"):
        return {
            "qualification": {"status": "no_trade", "disqualifier_reason": disq},
            "toolbox": {"best_available_raw_status": raw_status,
                        "preferred_tool": "bearish_ifvg"},
            "playbook": {"selected_playbook": "liquidity_sweep_reversal"},
            "risk": {"trade_allowed": False},
            "state_transition": {"invalidated": False},
        }

    def test_ready_tool_says_environment_refused(self):
        reason = _build_reason(self._snap("ready"), "stand_down", "bearish")
        self.assertIn("Environment refused", reason)
        self.assertIn("READY", reason)
        self.assertIn("bearish_ifvg", reason)
        self.assertNotIn("no opportunity identified", reason)

    def test_no_tool_says_environment_not_tradeable(self):
        reason = _build_reason(self._snap("no_tool"), "stand_down", "bearish")
        self.assertIn("not tradeable", reason)
        self.assertNotIn("no opportunity identified", reason)

    def test_fallback_when_no_disqualifier(self):
        snap = self._snap("no_tool", disq=None)
        reason = _build_reason(snap, "stand_down", "bearish")
        self.assertEqual(reason, "Qualification is no_trade — no opportunity identified.")

    def test_lifecycle_invalidation_still_wins(self):
        snap = self._snap("ready")
        snap["state_transition"]["invalidated"] = True
        reason = _build_reason(snap, "stand_down", "bearish")
        self.assertIn("lifecycle is invalidated", reason)


class TestRiskIsEchoNotOwner(unittest.TestCase):
    def test_risk_block_names_disqualifier_and_stays_blocked(self):
        snap = {
            "ai_context": {"market_narrative": "liquidity_sweep_reversal",
                           "confidence_tier": "no_trade", "market_state": "dangerous"},
            "volatility": {"15m": {"state": "toxic"}, "5m": {"state": "explosive"},
                           "3m": {"state": "toxic"}},
            "qualification": {"status": "no_trade", "grade": "F", "warnings": [],
                              "disqualifier_reason": "multi_timeframe_toxic_volatility(15m+5m)"},
            "playbook": {"status": "active", "selected_playbook": "liquidity_sweep_reversal",
                         "warnings": []},
            "session": "morning_continuation",
        }
        out = evaluate_risk(snap)
        self.assertFalse(out["trade_allowed"])       # verdict unchanged — echo
        self.assertTrue(any("multi_timeframe_toxic" in b for b in out["blocks"]))
        self.assertFalse(any("no opportunity identified" in b for b in out["blocks"]))

    def test_risk_fallback_message_without_reason(self):
        snap = {
            "ai_context": {}, "volatility": {},
            "qualification": {"status": "no_trade", "grade": "F", "warnings": []},
            "playbook": {"status": "none", "warnings": []},
        }
        out = evaluate_risk(snap)
        self.assertTrue(any("no opportunity identified" in b for b in out["blocks"]))


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_no_audit_logic_in_execution_authorities(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution", "order_builder.py"),   # FC-0B
                ("shared_context",  "council.py"),
                ("toolbox",         "price_levels.py"),    # RELATION-TRUTH
        ):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("HOSTILE-AUDIT", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

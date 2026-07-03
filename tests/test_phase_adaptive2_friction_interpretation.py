"""
Adaptive Learning — Phase 2A/2B: Adaptive Friction + Interpretation.

Proves friction levels scale with historical danger, the engine produces a
historical objection + rebuttal requirement, the interpretation engine identifies
success/failure profiles and an experience-based read, the Brain payload carries
both blocks, telemetry records the objection — and that NONE of it can mechanically
alter confidence, direction, execution, risk, or qualification (observe_only).
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

from adaptive_learning.learning_signal import build_learning_signal
from adaptive_learning.friction_engine import build_friction_report, friction_to_dict
from adaptive_learning.interpretation_engine import build_adaptive_interpretation
from adaptive_learning.context_formatter import build_adaptive_telemetry
from ai_brain.brain_prompt import ADAPTIVE_FRICTION_ADDENDUM

_NON_LUNCH = "2026-06-15T18:00:00+00:00"   # 14:00 EDT — not lunch
_LUNCH = "2026-06-15T16:30:00+00:00"       # 12:30 EDT — lunch


def _sig(rs, ts=_NON_LUNCH, regime="expansion_up", **kw):
    analogs = []
    for r in rs:
        a = {"similarity": 0.9, "r_multiple": r, "regime": regime,
             "active_playbook": "expansion_continuation", "timestamp": ts}
        a.update(kw)
        analogs.append(a)
    return build_learning_signal(analogs, authority_level="advisory")


_WINNER_SNAP = {
    "session": "morning_continuation", "market_regime": {"regime_label": "expansion_up"},
    "expansion": {"1m": {"state": "healthy_expansion", "magnitude_gated": False},
                  "5m": {"state": "mature_expansion", "magnitude_gated": False}},
    "po3": {"alignment": "full_distribution_alignment"},
    "shared_context": {"delivery_state": "bullish_delivery", "exhaustion_present": False},
    "narrative_authority": {"narrative_direction": "bullish", "active_liquidity_draw": "sell_side"},
}
_FAILURE_SNAP = {
    "session": "lunch", "market_regime": {"regime_label": "expansion_up"},
    "expansion": {"1m": {"state": "compression", "magnitude_gated": True},
                  "5m": {"state": "compression", "magnitude_gated": True}},
    "po3": {"alignment": "mixed"},
    "shared_context": {"delivery_state": "unknown", "exhaustion_present": True},
    "narrative_authority": {"narrative_direction": "bullish"},
}


class TestFrictionLevels(unittest.TestCase):
    def test_1_positive_support_low_friction(self):
        sig = _sig([2.6] * 15 + [-0.4] * 2, mae=0.3, entry_price=740.5, stop_price=739.8)
        fr = build_friction_report(sig, _WINNER_SNAP)
        self.assertEqual(fr.friction_level, 0)
        self.assertFalse(fr.required_rebuttal)

    def test_2_mixed_history_mild_friction(self):
        sig = _sig([1.0] * 4 + [-1.0] * 4)   # n=8 weak sample, win 0.5 mixed
        fr = build_friction_report(sig, _WINNER_SNAP)
        self.assertEqual(fr.friction_level, 1)

    def test_3_negative_history_level_2(self):
        sig = _sig([1.0] * 4 + [-0.6] * 7)   # n=11, win 0.36 (<0.40, n>=10), avg<0
        fr = build_friction_report(sig, _WINNER_SNAP)
        self.assertEqual(fr.friction_level, 2)
        self.assertTrue(fr.required_rebuttal)
        self.assertTrue(fr.rebuttal_questions)

    def test_4_severe_history_level_3(self):
        sig = _sig([-1.4] * 13 + [0.6] * 3)  # n=16, win 0.19 (<0.30, n>=15)
        fr = build_friction_report(sig, _WINNER_SNAP)
        self.assertEqual(fr.friction_level, 3)
        self.assertTrue(fr.required_rebuttal)
        self.assertGreaterEqual(fr.objection_strength, 75)

    def test_objection_text_present(self):
        sig = _sig([-1.4] * 13 + [0.6] * 3)
        fr = build_friction_report(sig, _FAILURE_SNAP)
        self.assertIn("History objects", fr.historical_objection)


class TestAuthoritySafety(unittest.TestCase):
    def test_5_friction_cannot_change_confidence(self):
        sig = _sig([-1.4] * 13 + [0.6] * 3)   # severe
        fr = build_friction_report(sig, _FAILURE_SNAP)
        it = build_adaptive_interpretation(sig, fr, _FAILURE_SNAP)
        tel = build_adaptive_telemetry(70, sig, friction=fr, interpretation=it, output={})
        self.assertEqual(tel["adaptive_confidence_adjustment"], 0)
        self.assertEqual(tel["final_confidence"], 70)        # unchanged despite severe friction
        self.assertEqual(tel["friction_level"], 3)

    def test_6_friction_cannot_change_direction(self):
        sig = _sig([-1.4] * 13 + [0.6] * 3)
        fr = build_friction_report(sig, _FAILURE_SNAP)
        it = build_adaptive_interpretation(sig, fr, _FAILURE_SNAP)
        # neither report exposes an applied direction; both are observe_only
        self.assertEqual(fr.authority_level, "observe_only")
        self.assertEqual(it["authority_level"], "observe_only")
        self.assertNotIn("applied_direction", friction_to_dict(fr))

    def test_7_no_execution_risk_qualification_coupling(self):
        # engines must not IMPORT execution/risk/qualification/decision modules.
        # (reading snapshot.get("qualification") for direction inference is an
        # observe-only snapshot read, not module coupling.)
        for mod in ("friction_engine", "interpretation_engine"):
            with open(os.path.join(_ROOT, "src", "adaptive_learning", f"{mod}.py"),
                      encoding="utf-8") as fh:
                import_lines = [l for l in fh
                                if l.lstrip().startswith(("import ", "from "))]
            joined = "\n".join(import_lines)
            for forbidden in ("risk", "execution", "qualification",
                              "decision_authority", "paper_execution", "order"):
                self.assertNotIn(f"import {forbidden}", joined,
                                 f"{mod} imports {forbidden}")
                self.assertNotIn(f"from {forbidden}", joined,
                                 f"{mod} imports from {forbidden}")

    def test_7b_only_expected_files_changed(self):
        try:
            out = subprocess.check_output(["git", "diff", "--name-only"], cwd=_ROOT, text=True)
        except Exception:
            self.skipTest("git not available")
        changed = [f.strip() for f in out.splitlines() if f.strip()]
        forbidden = ("risk_governor", "src/risk/", "execution_gate", "qualification",
                     "decision_authority", "paper_execution", "intent_scoring")
        # ADAPTIVE-7 — the ONE deliberate, scoped constitutional revision: the live
        # size owner may consume resolve_final_qty (downward-only, risk-capped). All
        # other execution/risk files remain forbidden.
        # DECON-2 — second deliberate, scoped revision: execution_engine's journal
        # snapshot_summary captures the executed tool (data integrity for the
        # performance tables' tool dimension; no authority/behavior change).
        # AI-AUTH-1 — third deliberate, scoped revision: legacy-wrapper authority
        # purge (decision_engine, execution_gate, intent_scorer become wrapper-
        # free; ECU Brain is the sole live AI). Locked by
        # tests/test_ai_auth1_sovereignty.py.
        allowed = ("paper_execution/order_builder.py",
                   "paper_execution/execution_engine.py",
                   "decision_authority/decision_engine.py",
                   "execution_gate/execution_gate.py",
                   "intent_scoring/intent_scorer.py")
        offenders = [f for f in changed
                     if any(p in f for p in forbidden)
                     and not any(a in f for a in allowed)]
        self.assertEqual(offenders, [], f"forbidden files modified: {offenders}")


class TestPromptDirective(unittest.TestCase):
    def test_8_prompt_includes_rebuttal_requirement(self):
        self.assertIn("ADAPTIVE FRICTION", ADAPTIVE_FRICTION_ADDENDUM)
        self.assertIn("REBUTTAL", ADAPTIVE_FRICTION_ADDENDUM.upper())
        self.assertIn("friction_level >= 2", ADAPTIVE_FRICTION_ADDENDUM)
        self.assertIn("friction_level == 3", ADAPTIVE_FRICTION_ADDENDUM)


class TestTelemetry(unittest.TestCase):
    def test_9_telemetry_records_objection(self):
        sig = _sig([1.0] * 4 + [-0.6] * 7)   # level 2
        fr = build_friction_report(sig, _WINNER_SNAP)
        it = build_adaptive_interpretation(sig, fr, _WINNER_SNAP)
        # rebuttal text referencing history -> present
        out = {"dominant_reasoning": "History objects but current displacement is stronger."}
        tel = build_adaptive_telemetry(60, sig, friction=fr, interpretation=it, output=out)
        for k in ("friction_level", "friction_label", "historical_objection",
                  "required_rebuttal", "brain_rebuttal_present",
                  "disagreement_resolution", "interpretation_bias",
                  "confidence_posture", "fragility_flags"):
            self.assertIn(k, tel)
        self.assertEqual(tel["friction_level"], 2)
        self.assertTrue(tel["required_rebuttal"])
        self.assertTrue(tel["brain_rebuttal_present"])
        self.assertEqual(tel["disagreement_resolution"], "rebuttal_present")

    def test_rebuttal_missing_detected(self):
        sig = _sig([1.0] * 4 + [-0.6] * 7)   # level 2 -> required
        fr = build_friction_report(sig, _WINNER_SNAP)
        it = build_adaptive_interpretation(sig, fr, _WINNER_SNAP)
        out = {"dominant_reasoning": "Bullish delivery into sell-side draw."}  # no history ref
        tel = build_adaptive_telemetry(60, sig, friction=fr, interpretation=it, output=out)
        self.assertFalse(tel["brain_rebuttal_present"])
        self.assertEqual(tel["disagreement_resolution"], "rebuttal_missing")


class TestInterpretation(unittest.TestCase):
    def test_10_identifies_success_profile(self):
        sig = _sig([2.6] * 15 + [-0.4] * 2, mae=0.3, entry_price=740.5, stop_price=739.8)
        fr = build_friction_report(sig, _WINNER_SNAP)
        it = build_adaptive_interpretation(sig, fr, _WINNER_SNAP)
        self.assertTrue(it["current_matches_success_profile"])
        self.assertEqual(it["interpretation_bias"], "historically_supportive")
        self.assertEqual(it["confidence_posture"], "reinforced")
        self.assertIn("WINNERS", it["experience_based_read"])

    def test_11_identifies_failure_profile(self):
        sig = _sig([-1.4] * 13 + [0.6] * 3)
        fr = build_friction_report(sig, _FAILURE_SNAP)
        it = build_adaptive_interpretation(sig, fr, _FAILURE_SNAP)
        self.assertTrue(it["current_matches_failure_profile"])
        self.assertEqual(it["interpretation_bias"], "historically_opposed")
        self.assertEqual(it["confidence_posture"], "challenged")
        self.assertIn("LOSERS", it["experience_based_read"])
        self.assertIn("lunch_session", it["fragility_flags"])

    def test_insufficient_history(self):
        it = build_adaptive_interpretation(None, build_friction_report(None, {}), {})
        self.assertEqual(it["interpretation_bias"], "insufficient_history")


class TestBrainPayloadInjection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._env = {k: os.environ.get(k) for k in ("AI_BRAIN_DIR", "AI_BRAIN_ENABLED")}
        os.environ["AI_BRAIN_DIR"] = self._tmp
        os.environ["AI_BRAIN_ENABLED"] = "true"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_12_payload_includes_friction_and_interpretation(self):
        from ai_brain.narrative_brain import run_narrative_brain
        import glob, json
        analogs = [{"similarity": 0.9, "r_multiple": -1.4, "regime": "expansion_up",
                    "active_playbook": "expansion_continuation", "timestamp": _LUNCH}
                   for _ in range(16)]
        snap = {"timestamp": "2026-06-16T15:30:00+00:00", "session": "lunch", "symbol": "QQQ",
                "ai_retrieval": {"analogs": analogs},
                "market_regime": {"regime_label": "expansion_up"}}
        res = run_narrative_brain(snap, "QQQ", None)
        rec = json.load(open(glob.glob(os.path.join(self._tmp, "*_QQQ.json"))[0], encoding="utf-8"))
        ip = rec["input_payload"]
        self.assertIn("adaptive_friction_report", ip)
        self.assertIn("adaptive_interpretation_context", ip)
        self.assertEqual(ip["adaptive_friction_report"]["authority_level"], "observe_only")
        # telemetry carries friction + applied-0 invariant intact
        tel = res["adaptive_telemetry"]
        self.assertIn("friction_level", tel)
        self.assertEqual(tel["adaptive_confidence_adjustment"], 0)
        self.assertEqual(tel["final_confidence"], tel["base_confidence"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

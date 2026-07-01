"""
Adaptive Learning — Phase 1C: Context injection & observability (OBSERVE_ONLY).

Proves the Brain can SEE the adaptive-learning context and that telemetry keeps
the RECOMMENDED adjustment strictly separate from the APPLIED one — which is
hard-locked to 0 so final_confidence ALWAYS equals base_confidence, for positive,
negative, and mixed analogs. Also proves the prompt directive carries the
OBSERVE_ONLY cognitive boundary, and that no qualification/risk/execution file
was modified.
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
from adaptive_learning.context_formatter import (
    format_adaptive_learning_context, neutral_adaptive_context,
    build_adaptive_telemetry, inject_adaptive_context,
)
from ai_brain.brain_prompt import ADAPTIVE_LEARNING_ADDENDUM


def _set(rs, **over):
    out = []
    for r in rs:
        a = {"similarity": 0.9, "r_multiple": r, "regime": "expansion_up",
             "active_playbook": "expansion_continuation",
             "timestamp": "2026-06-15T18:00:00+00:00"}
        a.update(over)
        out.append(a)
    return out


_POS = _set([3.0] * 8 + [-0.5] * 2)     # win 0.8, avg 2.3  -> advisory rec +3
_NEG = _set([-1.5] * 8 + [0.5] * 2)     # win 0.2, avg -1.1 -> advisory rec -5
_MIX = _set([1.0] * 5 + [-1.0] * 5)     # win 0.5           -> advisory rec  0


def _adv(analogs):
    return build_learning_signal(analogs, authority_level="advisory")


class TestFormatter(unittest.TestCase):
    def test_authority_hard_locked_observe_only(self):
        # signal built at a HIGHER authority must still be exposed as observe_only
        sig = build_learning_signal(_POS, authority_level="bounded_modifier")
        ctx = format_adaptive_learning_context(sig)
        self.assertEqual(ctx["authority_level"], "observe_only")
        # the recommendation is preserved and non-zero…
        self.assertNotEqual(ctx["confidence_adjustment_recommendation"], 0)

    def test_schema_fields(self):
        ctx = format_adaptive_learning_context(_adv(_POS))
        for f in ("sample_size", "win_rate", "avg_r", "mae_risk", "warning_tags",
                  "supporting_evidence", "conflicting_evidence",
                  "confidence_adjustment_recommendation", "authority_level",
                  "explanation"):
            self.assertIn(f, ctx)
        self.assertIsInstance(ctx["win_rate"], float)   # 80.0 (percent)
        self.assertEqual(ctx["win_rate"], 80.0)

    def test_neutral_context(self):
        ctx = neutral_adaptive_context()
        self.assertEqual(ctx["sample_size"], 0)
        self.assertEqual(ctx["authority_level"], "observe_only")
        self.assertEqual(ctx["warning_tags"], ["no_adaptive_learning_signal"])
        self.assertEqual(ctx["confidence_adjustment_recommendation"], 0)


class TestTelemetryHardLock(unittest.TestCase):
    def _check_unchanged(self, analogs):
        sig = _adv(analogs)
        tel = build_adaptive_telemetry(60, sig)
        self.assertEqual(tel["base_confidence"], 60)
        self.assertEqual(tel["final_confidence"], 60)          # unchanged
        self.assertEqual(tel["adaptive_confidence_adjustment"], 0)  # never applied
        self.assertEqual(tel["adaptive_authority_level"], "observe_only")
        # recommended is tracked SEPARATELY from applied
        self.assertEqual(tel["adaptive_recommended_adjustment"], sig.confidence_adjustment)
        return tel

    def test_positive_does_not_change_final(self):
        tel = self._check_unchanged(_POS)
        self.assertGreater(tel["adaptive_recommended_adjustment"], 0)

    def test_negative_does_not_change_final(self):
        tel = self._check_unchanged(_NEG)
        self.assertLess(tel["adaptive_recommended_adjustment"], 0)

    def test_mixed_does_not_change_final(self):
        tel = self._check_unchanged(_MIX)
        self.assertEqual(tel["adaptive_recommended_adjustment"], 0)

    def test_recommended_and_applied_are_separate_keys(self):
        tel = build_adaptive_telemetry(75, _adv(_NEG))
        self.assertIn("adaptive_recommended_adjustment", tel)
        self.assertIn("adaptive_confidence_adjustment", tel)
        self.assertNotEqual(tel["adaptive_recommended_adjustment"],
                            tel["adaptive_confidence_adjustment"])  # -5 vs 0
        self.assertEqual(tel["adaptive_confidence_adjustment"], 0)

    def test_applied_always_zero_and_final_equals_base(self):
        for base in (0, 33, 60, 100):
            for analogs in (_POS, _NEG, _MIX, []):
                sig = _adv(analogs) if analogs else None
                tel = build_adaptive_telemetry(base, sig)
                self.assertEqual(tel["adaptive_confidence_adjustment"], 0)
                self.assertEqual(tel["final_confidence"], base)


class TestInjection(unittest.TestCase):
    def test_context_injected_with_analogs(self):
        bi = {}
        sig = inject_adaptive_context(bi, _POS, {"market_regime": {"regime_label": "expansion_up"}})
        self.assertIn("adaptive_learning_context", bi)
        self.assertEqual(bi["adaptive_learning_context"]["authority_level"], "observe_only")
        self.assertIsNotNone(sig)

    def test_neutral_injected_without_analogs(self):
        bi = {}
        sig = inject_adaptive_context(bi, [], {})
        self.assertIsNone(sig)
        self.assertEqual(bi["adaptive_learning_context"]["warning_tags"],
                         ["no_adaptive_learning_signal"])


class TestPromptDirective(unittest.TestCase):
    def test_directive_has_observe_only_and_current_outranks_historical(self):
        self.assertIn("OBSERVE_ONLY", ADAPTIVE_LEARNING_ADDENDUM)
        self.assertIn("outranks historical", ADAPTIVE_LEARNING_ADDENDUM.lower())
        self.assertIn("forbidden", ADAPTIVE_LEARNING_ADDENDUM.lower())


class TestEndToEndBrain(unittest.TestCase):
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

    def test_payload_and_telemetry_present_and_neutral(self):
        from ai_brain.narrative_brain import run_narrative_brain
        import glob, json
        snap = {"timestamp": "2026-06-16T15:30:00+00:00", "session": "afternoon",
                "symbol": "QQQ", "ai_retrieval": {"analogs": _POS},
                "market_regime": {"regime_label": "expansion_up"}}
        res = run_narrative_brain(snap, "QQQ", None)
        tel = res.get("adaptive_telemetry")
        self.assertIsNotNone(tel)
        # applied 0; final == base regardless of a positive recommendation
        self.assertEqual(tel["adaptive_confidence_adjustment"], 0)
        self.assertEqual(tel["final_confidence"], tel["base_confidence"])
        self.assertGreater(tel["adaptive_recommended_adjustment"], 0)   # saw the scar
        # persisted payload carries the OBSERVE_ONLY context
        rec = json.load(open(glob.glob(os.path.join(self._tmp, "*_QQQ.json"))[0],
                             encoding="utf-8"))
        alc = rec["input_payload"]["adaptive_learning_context"]
        self.assertEqual(alc["authority_level"], "observe_only")


class TestNoForbiddenFilesModified(unittest.TestCase):
    def test_only_brain_and_adaptive_files_changed(self):
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only"], cwd=_ROOT, text=True)
        except Exception:
            self.skipTest("git not available")
        changed = [f.strip() for f in out.splitlines() if f.strip()]
        forbidden = ("qualification", "risk_governor", "risk/", "execution_gate",
                     "paper_execution", "decision_authority", "intent_scoring")
        # ADAPTIVE-7 — the ONE deliberate, scoped constitutional revision: the live
        # size owner may consume resolve_final_qty (downward-only, risk-capped). All
        # other execution/risk files remain forbidden.
        allowed = ("paper_execution/order_builder.py",)
        offenders = [f for f in changed
                     if any(p in f for p in forbidden)
                     and not any(a in f for a in allowed)]
        self.assertEqual(offenders, [], f"forbidden files modified: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

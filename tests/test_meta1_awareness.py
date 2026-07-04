"""
META-1 — Meta-Awareness Engine regression lock.

The organism watches the market. Now it watches itself.

TEST A: brain drift detected (fallbacks, thesis flips, confidence swings)
TEST B: authority contradiction detected (divergence + MC contradictions)
TEST C: suppression overblock / false-suppression cluster detected
TEST D: probation instability detected (repeated re-locks)
TEST E: execution denial cluster detected
TEST F: data mismatch detected (tables vs ledger; metrics self-consistency)
TEST G: healthy organism scores healthy (score 0)
TEST H: critical organism scores critical
Plus: observe-only lock (no authority fields, no store writes).

All store reads point at temp dirs — never live adaptive memory.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.meta_awareness_engine import (   # noqa: E402
    MetaAwarenessEngine, STATE_HEALTHY, STATE_CRITICAL,
)


def _scan(direction="bullish", confidence=60, fallback=False, diverged=False,
          contradictions=None, mutated=False, opportunity=False,
          submitted=False, broker_error=None, blocks=None):
    """Minimal settled-scan snapshot for the observer."""
    snap = {
        "ai_brain": {"enabled": True,
                     "source": "deterministic" if fallback else "llm",
                     "input_degraded": ["feed gap"] if fallback else [],
                     "output": {"narrative_direction": direction,
                                "phase_confidence": confidence}},
        "ai_divergence": {"enabled": True, "diverged": diverged},
        "market_commander": {"consistency": {
            "contradictions": contradictions or []}},
        "narrative_authority": {"conflict_flags": []},
        "adaptive_mutation": {"mutated": mutated},
        "decision_authority": {"decision": "ready_for_execution" if opportunity
                               else "stand_down"},
        "trade_intent": {"intent_created": False},
        "paper_execution": {"status": "submitted" if submitted else "skipped",
                            "reason": "gate blocked",
                            "broker_trace": {"error": broker_error}},
        "risk": {"blocks": blocks or []},
        "execution_gate": {"authorization_checks": {}},
    }
    return snap


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.engine = MetaAwarenessEngine(symbol="QQQ", window=30,
                                          base_dir=self._tmp)

    def _qdir(self):
        d = os.path.join(self._tmp, "QQQ")
        os.makedirs(d, exist_ok=True)
        return d

    def _write(self, fname, data):
        with open(os.path.join(self._qdir(), fname), "w", encoding="utf-8") as fh:
            json.dump(data, fh)


class TestA_BrainDrift(_Sandbox):
    def test_fallback_frequency_detected(self):
        for _ in range(10):
            rep = self.engine.observe(_scan(fallback=True))
        self.assertIn("fallback_frequency",
                      [s["signal"] for s in rep["drift_signals"]])
        self.assertNotEqual(rep["brain_health"], STATE_HEALTHY)

    def test_thesis_flip_and_confidence_instability(self):
        for i in range(12):
            rep = self.engine.observe(_scan(
                direction="bullish" if i % 2 == 0 else "bearish",
                confidence=20 if i % 2 == 0 else 80))
        names = [s["signal"] for s in rep["drift_signals"]]
        self.assertIn("thesis_flip_frequency", names)
        self.assertIn("confidence_instability", names)

    def test_stable_brain_stays_healthy(self):
        for _ in range(12):
            rep = self.engine.observe(_scan(direction="bullish", confidence=62))
        self.assertEqual(rep["brain_health"], STATE_HEALTHY)


class TestB_AuthorityConflict(_Sandbox):
    def test_contradiction_spike_detected(self):
        for _ in range(10):
            rep = self.engine.observe(_scan(
                diverged=True,
                contradictions=["STAND_DOWN_WITH_EXECUTABLE_THESIS"]))
        self.assertIn("contradiction_spike",
                      [s["signal"] for s in rep["drift_signals"]])
        self.assertNotEqual(rep["authority_health"], STATE_HEALTHY)


class TestC_SuppressionInstability(_Sandbox):
    def test_false_suppression_cluster_detected(self):
        self._write("suppression_metrics.json", {"session": {"morning": {
            "suppressed_total": 5, "correct_suppressions": 1,
            "false_suppressions": 4, "neutral_suppressions": 0,
            "expired_suppressions": 0, "suppression_accuracy": 0.2}}})
        rep = self.engine.observe(_scan())
        self.assertIn("false_suppression_cluster",
                      [s["signal"] for s in rep["drift_signals"]])
        self.assertNotEqual(rep["suppression_health"], STATE_HEALTHY)

    def test_overblocking_owner_detected(self):
        for _ in range(8):
            rep = self.engine.observe(_scan(
                opportunity=True, submitted=False,
                blocks=["blocked: qualification is watchlist"]))
        self.assertIn("overblocking_owner",
                      [s["signal"] for s in rep["drift_signals"]])


class TestD_ProbationInstability(_Sandbox):
    def test_repeated_relocks_detected(self):
        self._write("scar_state.json", {"session:morning": {
            "status": "scarred", "lock_count": 3, "cooldown_required": 8,
            "history": []}})
        rep = self.engine.observe(_scan())
        self.assertIn("repeated_relocks",
                      [s["signal"] for s in rep["drift_signals"]])
        self.assertNotEqual(rep["adaptive_health"], STATE_HEALTHY)


class TestE_ExecutionInstability(_Sandbox):
    def test_denial_cluster_detected(self):
        for _ in range(8):
            rep = self.engine.observe(_scan(opportunity=True, submitted=False))
        self.assertIn("denial_cluster",
                      [s["signal"] for s in rep["drift_signals"]])
        self.assertNotEqual(rep["execution_health"], STATE_HEALTHY)

    def test_broker_error_detected(self):
        for _ in range(6):
            rep = self.engine.observe(_scan(broker_error="Order submission failed"))
        self.assertIn("broker_error_observed",
                      [s["signal"] for s in rep["drift_signals"]])


class TestF_DataMismatch(_Sandbox):
    def test_table_ledger_mismatch_is_critical(self):
        self._write("applied_writes.json", {"k1": {"trade_id": "T1"}})
        self._write("playbook_performance.json", {"sweep": {
            "trades": 3, "wins": 0, "losses": 3, "breakevens": 0,
            "sum_r": -3.0, "expectancy": -1.0, "loss_streak": 3}})
        rep = self.engine.observe(_scan())
        self.assertIn("table_ledger_mismatch", rep["critical_flags"])
        self.assertEqual(rep["memory_health"], STATE_CRITICAL)
        self.assertEqual(rep["health_state"], STATE_CRITICAL)

    def test_suppression_metrics_self_consistency(self):
        self._write("suppression_metrics.json", {"tool": {"fvg": {
            "suppressed_total": 5, "correct_suppressions": 1,
            "false_suppressions": 1, "neutral_suppressions": 0,
            "expired_suppressions": 0, "suppression_accuracy": 0.5}}})
        rep = self.engine.observe(_scan())
        self.assertIn("suppression_metrics_mismatch", rep["critical_flags"])


class TestG_Healthy(_Sandbox):
    def test_healthy_organism_scores_healthy(self):
        for _ in range(12):
            rep = self.engine.observe(_scan(direction="bullish", confidence=60))
        self.assertEqual(rep["health_state"], STATE_HEALTHY)
        self.assertEqual(rep["instability_score"], 0)
        for organ, state in rep["organ_health"].items():
            self.assertEqual(state, STATE_HEALTHY, organ)
        self.assertEqual(rep["watch_flags"], [])
        self.assertEqual(rep["critical_flags"], [])


class TestH_Critical(_Sandbox):
    def test_critical_organism_scores_critical(self):
        # stacked failure: data mismatch (critical) + brain fallback storm +
        # authority contradictions + denial cluster
        self._write("applied_writes.json", {"k1": {"trade_id": "T1"}})
        self._write("session_performance.json", {"m": {
            "trades": 9, "wins": 0, "losses": 9, "breakevens": 0,
            "sum_r": -9.0, "expectancy": -1.0, "loss_streak": 9}})
        for _ in range(10):
            rep = self.engine.observe(_scan(
                fallback=True, diverged=True,
                contradictions=["AI_PARTICIPATE_OVERRULED_BY_GATES"],
                opportunity=True, submitted=False))
        self.assertEqual(rep["health_state"], STATE_CRITICAL)
        self.assertGreaterEqual(rep["instability_score"], 50)
        self.assertIn("table_ledger_mismatch", rep["critical_flags"])


class TestObserveOnlyLock(_Sandbox):
    def test_no_authority_and_no_store_writes(self):
        before = sorted(os.listdir(self._qdir())) if os.path.isdir(self._qdir()) else []
        for _ in range(10):
            rep = self.engine.observe(_scan(opportunity=True))
        self.assertEqual(rep["authority_level"], "observe_only")
        for k in ("blocked", "allow_execution", "trade_blocked",
                  "confidence", "qty"):
            self.assertNotIn(k, rep)
        after = sorted(os.listdir(self._qdir())) if os.path.isdir(self._qdir()) else []
        self.assertEqual(before, after, "meta engine must write nothing")

    def test_never_raises_on_garbage(self):
        rep = self.engine.observe(None)
        self.assertEqual(rep["authority_level"], "observe_only")
        rep = self.engine.observe({"ai_brain": "not-a-dict"})
        self.assertIn(rep["health_state"],
                      ("healthy", "watchlist", "degraded", "critical"))


if __name__ == "__main__":
    unittest.main()

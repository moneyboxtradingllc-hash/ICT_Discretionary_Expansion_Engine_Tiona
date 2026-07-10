"""
AI-BRAIN-REQUIRED (2026-07-10) — operating-policy locks.

Doctrine: NEW judgment requires the AI Brain; EXISTING-position safety never
depends on it. With AI_BRAIN_REQUIRED=true the session refuses to start unless
a live-model preflight succeeds; in-session, N consecutive Brain failures
revoke NEW-ENTRY authority only (restored on the next healthy scan). Default
false = byte-identical legacy (diagnostics keep the fallback).

Locks: default off; gate threshold/restore semantics; the gate record always
carries positions_managed=True (constitutional); preflight classification
(quota / auth / model_access / transport / ok) from mocked client failures;
scan_loop wires preflight refusal + the entry-denial rail; safety files clean.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.brain_preflight import (      # noqa: E402
    brain_required, preflight, BrainHealthGate, max_consecutive_failures,
)


class TestPolicyGate(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_BRAIN_REQUIRED", None)
            self.assertFalse(brain_required())

    def test_threshold_revokes_and_healthy_restores(self):
        g = BrainHealthGate(threshold=3)
        for i in range(2):
            v = g.update("llm_failed_fallback")
            self.assertTrue(v["entry_allowed"])       # below threshold
        v = g.update("deterministic")                 # 3rd consecutive
        self.assertFalse(v["entry_allowed"])
        self.assertTrue(v["revoked_now"])
        v = g.update("llm")                           # healthy scan
        self.assertTrue(v["entry_allowed"])
        self.assertTrue(v["restored_now"])
        self.assertEqual(v["consecutive_failures"], 0)

    def test_healthy_scans_never_accumulate(self):
        g = BrainHealthGate(threshold=2)
        for _ in range(10):
            v = g.update("llm")
        self.assertTrue(v["entry_allowed"])
        self.assertFalse(v["degraded"])

    def test_positions_managed_is_constitutional(self):
        g = BrainHealthGate(threshold=1)
        v = g.update("llm_failed_fallback")           # revoked immediately
        self.assertFalse(v["entry_allowed"])
        self.assertTrue(v["positions_managed"])       # NEVER Brain-dependent

    def test_threshold_env(self):
        with patch.dict(os.environ, {"AI_BRAIN_REQUIRED_MAX_FAILURES": "7"}):
            self.assertEqual(max_consecutive_failures(), 7)
        with patch.dict(os.environ, {"AI_BRAIN_REQUIRED_MAX_FAILURES": "junk"}):
            self.assertEqual(max_consecutive_failures(), 5)


def _fake_openai(exc=None, reply="OK"):
    class _Msg:
        content = reply

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            if exc:
                raise exc
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, **_kw):
            self.chat = _Chat()

    class _Module:
        OpenAI = _Client

    return _Module()


class TestPreflightClassification(unittest.TestCase):
    def _run(self, exc=None):
        import ai_layer.ai_api_adapter as adapter
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}), \
             patch.object(adapter, "_openai", _fake_openai(exc)), \
             patch.object(adapter, "_OPENAI_AVAILABLE", True):
            return preflight()

    def test_ok(self):
        pf = self._run()
        self.assertTrue(pf["ok"])
        self.assertEqual(pf["classification"], "ok")

    def test_quota(self):
        pf = self._run(RuntimeError(
            "Error code: 429 - insufficient_quota: You exceeded your current quota"))
        self.assertFalse(pf["ok"])
        self.assertEqual(pf["classification"], "quota")

    def test_auth(self):
        pf = self._run(RuntimeError("Error code: 401 - Incorrect API key provided"))
        self.assertEqual(pf["classification"], "auth")

    def test_model_access(self):
        pf = self._run(RuntimeError("The model 'gpt-9' does not exist or you "
                                    "do not have access to it"))
        self.assertEqual(pf["classification"], "model_access")

    def test_no_key_is_auth(self):
        import ai_layer.ai_api_adapter as adapter
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
             patch.object(adapter, "_OPENAI_AVAILABLE", True):
            pf = preflight()
        self.assertEqual(pf["classification"], "auth")


class TestScanLoopWiring(unittest.TestCase):
    def test_startup_refusal_and_denial_rail_wired(self):
        with open(os.path.join("src", "live_scan", "scan_loop.py"),
                  encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("STARTUP DENIED — AI_BRAIN_REQUIRED", txt)
        self.assertIn("brain_gate.entry_allowed", txt)
        self.assertIn("positions remain managed", txt)
        # the revocation gates ENTRIES via the ops rail, never the stop enforcer
        stop_section = txt.split("Stop Enforcer")[1][:400]
        self.assertNotIn("brain_gate", stop_section)


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py")):
            path = os.path.join("src", pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("AI_BRAIN_REQUIRED", fh.read(),
                                     f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

"""
REPLAY-4 — Counterfactual Decision Laboratory locks (2026-07-10).

One authority verdict flipped per run; safety caps are NOT counterfactual
variables (registry locked); overrides mutate only at their named seam; the
walker's hooks fire in order and hook failures never masquerade as organism
behavior; alternate histories are SimBroker-scored with safety invariants;
descriptive only.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.counterfactual_lab import (       # noqa: E402
    OVERRIDES, FORBIDDEN_OVERRIDE_TERMS, run_lab,
    _ov_council_yes, _ov_adaptive_unblocked, _ov_trigger_confirmed,
)
from replay_validation.replay_session import replay_session  # noqa: E402
from replay_validation.candle_archive import archive_session  # noqa: E402
from data_feed.provider_interface import BaseDataProvider     # noqa: E402


class TestRegistryDoctrine(unittest.TestCase):
    def test_safety_caps_are_not_variables(self):
        for name in OVERRIDES:
            for term in FORBIDDEN_OVERRIDE_TERMS:
                self.assertNotIn(term, name.lower(),
                                 f"override '{name}' touches safety term '{term}'")

    def test_unknown_override_rejected(self):
        with self.assertRaises(ValueError):
            run_lab("20260708", "risk_doubled")

    def test_v1_registry_contents(self):
        self.assertEqual(set(OVERRIDES),
                         {"council_yes", "adaptive_unblocked",
                          "trigger_confirmed"})


class TestOverrideSeams(unittest.TestCase):
    def test_council_yes_flips_only_at_post_council(self):
        snap = {"council": {"veto": {"veto_triggered": True, "veto_reason": "x"}}}
        _ov_council_yes("post_build", snap)
        self.assertTrue(snap["council"]["veto"]["veto_triggered"])   # wrong seam
        _ov_council_yes("post_council", snap)
        self.assertFalse(snap["council"]["veto"]["veto_triggered"])
        self.assertIn("council_yes", snap["_lab_mutations"])

    def test_council_yes_noop_when_no_veto(self):
        snap = {"council": {"veto": {"veto_triggered": False}}}
        _ov_council_yes("post_council", snap)
        self.assertNotIn("_lab_mutations", snap)

    def test_adaptive_unblocked_lifts_soft_veto(self):
        snap = {"adaptive_block": {"blocked": True, "reason": ["streak"]}}
        _ov_adaptive_unblocked("pre_decision", snap)
        self.assertFalse(snap["adaptive_block"]["blocked"])
        self.assertIn("adaptive_unblocked", snap["_lab_mutations"])

    def test_trigger_confirmed_waives_wait_but_not_invalidation(self):
        def _snap(invalidated=False, status="waiting_for_retest"):
            return {"toolbox": {"preferred_tool": "bearish_ifvg",
                                "tool_candidates": [{
                                    "tool": "bearish_ifvg",
                                    "price_level": {"invalidated": invalidated},
                                    "trigger_prep": {
                                        "raw_trigger_status": status,
                                        "execution_ready": False}}]}}
        s = _snap()
        _ov_trigger_confirmed("pre_decision", s)
        tp = s["toolbox"]["tool_candidates"][0]["trigger_prep"]
        self.assertEqual(tp["raw_trigger_status"], "confirmed")
        self.assertTrue(tp["execution_ready"])
        # an INVALIDATED setup must never be counterfactually confirmed
        s2 = _snap(invalidated=True)
        _ov_trigger_confirmed("pre_decision", s2)
        tp2 = s2["toolbox"]["tool_candidates"][0]["trigger_prep"]
        self.assertNotEqual(tp2.get("raw_trigger_status"), "confirmed")
        # already-confirmed / no_trigger states untouched
        s3 = _snap(status="no_trigger")
        _ov_trigger_confirmed("pre_decision", s3)
        self.assertEqual(
            s3["toolbox"]["tool_candidates"][0]["trigger_prep"]
            ["raw_trigger_status"], "no_trigger")


class _TapeProvider(BaseDataProvider):
    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return []

    def fetch_1m_candles_range(self, symbol, start, end):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 7, 8, 13, 30, tzinfo=timezone.utc)
        out, px = [], 700.0
        for i in range(50):
            px += 0.1 if i % 3 else -0.05
            out.append({"timestamp": (base + timedelta(minutes=i)).isoformat(),
                        "open": px, "high": px + 0.3, "low": px - 0.3,
                        "close": px + 0.1, "volume": 1000.0})
        return out


class TestWalkerHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {
            "REPLAY_CANDLES_DIR": os.path.join(self.tmp, "candles"),
            "AI_BRAIN_DIR": os.path.join(self.tmp, "no_records"),
        })
        self._e.start()
        archive_session("20260708", "QQQ", provider=_TapeProvider())

    def tearDown(self):
        self._e.stop()

    def test_hooks_fire_in_order_and_manifest_records_them(self):
        seen = []

        def hook(stage, snapshot):
            seen.append(stage)

        res = replay_session("20260708", lookback=25, max_scans=2,
                             post_stage_hook=hook,
                             sandbox=os.path.join(self.tmp, "sb"))
        self.assertTrue(res["manifest"]["counterfactual_hook"])
        per_scan = ["post_build", "post_council", "pre_decision", "post_gate"]
        self.assertEqual(seen[:4], per_scan)
        self.assertEqual(len(seen) % 4, 0)

    def test_broken_hook_errors_scan_never_fakes_behavior(self):
        def hook(stage, snapshot):
            raise RuntimeError("hook bug")

        res = replay_session("20260708", lookback=25, max_scans=2,
                             post_stage_hook=hook,
                             sandbox=os.path.join(self.tmp, "sb2"))
        self.assertEqual(res["summary"]["scans"], 0)
        self.assertGreaterEqual(res["summary"]["errors"], 1)

    def test_scan_records_carry_intent_zone_field(self):
        res = replay_session("20260708", lookback=25, max_scans=1,
                             sandbox=os.path.join(self.tmp, "sb3"))
        self.assertIn("intent_zone", res["scans"][0])


if __name__ == "__main__":
    unittest.main()

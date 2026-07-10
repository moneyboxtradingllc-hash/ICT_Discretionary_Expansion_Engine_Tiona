"""
ADAPT-LOOP-2 — Adaptive Effect Ledger locks (2026-07-09).

The second-order loop: adaptive actuations (soft-block / confidence-lower /
size-reduce) are RECORDED by the pipeline (telemetry only, gated
ADAPTIVE_EFFECT_LEDGER default off) and RESOLVED by the replay engine into
helped/hurt via SimBroker counterfactuals — the adaptive layer graded on its
own decisions. Evidence flows through data files; the pipeline never imports
the replay engine.

Locks: default-off = zero writes; no measurable intent context = no record;
idempotency per (timestamp, action_type); resolver classification math
(soft_block helped on loser / hurt on winner; size_reduce effect_r =
reduction_fraction × −R; expired when never filled); metrics aggregation;
round-trip read-back; safety files clean of the flag.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.adaptive_effect import (                       # noqa: E402
    record_adaptive_actions, load_open_actions, load_effect_metrics,
)
from replay_validation.adaptive_effect_resolver import (              # noqa: E402
    resolve_effects, _classify,
)

_T0 = datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)


def _snap(block=False, conf=False, size=False, intent=True):
    s = {"timestamp": _T0.isoformat(),
         "adaptive_live_consumption": {
             "adaptive_confidence_consumed": conf,
             "original_live_confidence": 70, "final_live_confidence": 55,
             "adaptive_size_consumed": size,
             "original_live_qty": 100, "final_live_qty": 50},
         "adaptive_block": {"blocked": block, "reason": ["streak"]},
         "toolbox": {"preferred_tool": "bearish_ifvg", "tool_candidates": [
             {"tool": "bearish_ifvg",
              "price_level": {"invalidation_level": 101.0}}]}}
    if intent:
        s["trade_intent"] = {"intent_created": True, "direction": "bearish",
                             "playbook": "liquidity_sweep_reversal",
                             "entry_zone": {"zone_low": 100.4, "zone_high": 100.6,
                                            "midpoint": 100.5}}
    else:
        s["trade_intent"] = {"intent_created": False}
    return s


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()


class TestRecorder(_Base):
    def test_default_off_writes_nothing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADAPTIVE_EFFECT_LEDGER", None)
            r = record_adaptive_actions(_snap(size=True), "QQQ", base_dir=self.tmp)
        self.assertFalse(r["enabled"])
        self.assertEqual(load_open_actions("QQQ", base_dir=self.tmp), [])

    def test_no_intent_context_no_record(self):
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on"}):
            r = record_adaptive_actions(_snap(size=True, intent=False), "QQQ",
                                        base_dir=self.tmp)
        self.assertEqual(r["recorded"], 0)
        self.assertIn("skip_reason", r)

    def test_records_each_fired_action_with_context(self):
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on"}):
            r = record_adaptive_actions(_snap(block=True, conf=True, size=True),
                                        "QQQ", base_dir=self.tmp)
        self.assertEqual(r["recorded"], 3)
        rows = load_open_actions("QQQ", base_dir=self.tmp)
        self.assertEqual({x["action_type"] for x in rows},
                         {"soft_block", "confidence_lower", "size_reduce"})
        self.assertEqual(rows[0]["invalidation_level"], 101.0)

    def test_idempotent_per_scan_and_action(self):
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on"}):
            record_adaptive_actions(_snap(size=True), "QQQ", base_dir=self.tmp)
            r2 = record_adaptive_actions(_snap(size=True), "QQQ", base_dir=self.tmp)
        self.assertEqual(r2["recorded"], 0)
        self.assertEqual(len(load_open_actions("QQQ", base_dir=self.tmp)), 1)

    def test_never_raises_on_garbage(self):
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on"}):
            r = record_adaptive_actions({"adaptive_block": "junk"}, "QQQ",
                                        base_dir=self.tmp)
        self.assertIsInstance(r, dict)


class TestClassification(unittest.TestCase):
    def test_soft_block_helped_on_loser_hurt_on_winner(self):
        a = {"action_type": "soft_block"}
        self.assertEqual(_classify(a, {"r": -1.0})["outcome"], "helped")
        self.assertEqual(_classify(a, {"r": -1.0})["effect_r"], 1.0)
        self.assertEqual(_classify(a, {"r": 2.0})["outcome"], "hurt")

    def test_size_reduce_effect_math(self):
        a = {"action_type": "size_reduce",
             "detail": {"original_qty": 100, "final_qty": 50}}
        helped = _classify(a, {"r": -1.0})
        self.assertEqual(helped["outcome"], "helped")
        self.assertEqual(helped["effect_r"], 0.5)     # saved half a loss
        hurt = _classify(a, {"r": 2.0})
        self.assertEqual(hurt["outcome"], "hurt")
        self.assertEqual(hurt["effect_r"], -1.0)      # surrendered half of +2R

    def test_never_filled_is_expired_not_judged(self):
        out = _classify({"action_type": "soft_block"}, None)
        self.assertEqual(out["outcome"], "expired")
        self.assertEqual(out["effect_r"], 0.0)


class TestResolverRoundTrip(_Base):
    def _archive(self, candles):
        cdir = os.path.join(self.tmp, "candles")
        os.makedirs(cdir, exist_ok=True)
        with open(os.path.join(cdir, "20260708_QQQ.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"symbol": "QQQ", "date": "20260708",
                       "bar_count": len(candles), "candles": candles}, fh)
        return cdir

    def test_end_to_end_record_resolve_metrics(self):
        # bearish zone 100.4-100.6, stop 101.0; tape rallies through the stop
        # -> counterfactual LOSS -> soft_block HELPED, size_reduce HELPED
        candles = []
        px = 100.3
        for i in range(1, 30):
            px += 0.05
            candles.append({"timestamp": (_T0 + timedelta(minutes=i)).isoformat(),
                            "open": px, "high": px + 0.1, "low": px - 0.05,
                            "close": px + 0.05})
        cdir = self._archive(candles)
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on",
                                     "REPLAY_CANDLES_DIR": cdir}):
            record_adaptive_actions(_snap(block=True, size=True), "QQQ",
                                    base_dir=self.tmp)
            out = resolve_effects("20260708", "QQQ", base_dir=self.tmp)
        self.assertEqual(out["resolved"], 2)
        m = load_effect_metrics("QQQ", base_dir=self.tmp)["by_action_type"]
        self.assertEqual(m["soft_block"]["helped"], 1)
        self.assertGreater(m["soft_block"]["net_effect_r"], 0)
        self.assertEqual(m["size_reduce"]["helped"], 1)

    def test_resolver_idempotent(self):
        cdir = self._archive([{"timestamp": (_T0 + timedelta(minutes=1)).isoformat(),
                               "open": 100.5, "high": 101.2, "low": 100.4,
                               "close": 101.1}])
        with patch.dict(os.environ, {"ADAPTIVE_EFFECT_LEDGER": "on",
                                     "REPLAY_CANDLES_DIR": cdir}):
            record_adaptive_actions(_snap(block=True), "QQQ", base_dir=self.tmp)
            resolve_effects("20260708", "QQQ", base_dir=self.tmp)
            out2 = resolve_effects("20260708", "QQQ", base_dir=self.tmp)
        self.assertEqual(out2["resolved"], 0)   # already resolved — no dupes


class TestSafetyClean(unittest.TestCase):
    def test_flag_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py"),
                           ("broker", "broker_adapter.py"),
                           ("execution_gate", "execution_gate.py")):
            path = os.path.join(src, pkg, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    self.assertNotIn("ADAPTIVE_EFFECT_LEDGER", fh.read(),
                                     f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

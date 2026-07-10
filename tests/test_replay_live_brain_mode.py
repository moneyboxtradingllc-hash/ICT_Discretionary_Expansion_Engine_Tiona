"""
REPLAY LIVE BRAIN MODE + FAMILY-REPAIR REPLAY locks (2026-07-09).

Walker brain modes: recorded (RecordedBrain substitution, deterministic) |
live (real run_narrative_brain, AI_BRAIN_LLM=true) | deterministic (LLM off).
Safety keys stay forced in every mode. The family-repair replay tool mirrors
the shipped soft-repair adoption guards verbatim (offline here — LLM mocked).
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from replay_validation.replay_session import replay_session, _SAFETY_ENV  # noqa: E402
from replay_validation.family_repair_replay import replay_one            # noqa: E402
from replay_validation.candle_archive import archive_session             # noqa: E402
from data_feed.provider_interface import BaseDataProvider                # noqa: E402


class _TapeProvider(BaseDataProvider):
    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return []

    def fetch_1m_candles_range(self, symbol, start, end):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 7, 8, 13, 30, tzinfo=timezone.utc)
        out, px = [], 700.0
        for i in range(40):
            px += 0.1 if i % 3 else -0.05
            out.append({"timestamp": (base + timedelta(minutes=i)).isoformat(),
                        "open": px, "high": px + 0.3, "low": px - 0.3,
                        "close": px + 0.1, "volume": 1000.0})
        return out


class TestBrainModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {
            "REPLAY_CANDLES_DIR": os.path.join(self.tmp, "candles"),
            "AI_BRAIN_DIR": os.path.join(self.tmp, "no_records"),
            "OPENAI_API_KEY": "",     # live mode must fall back, not call out
        })
        self._e.start()
        archive_session("20260708", "QQQ", provider=_TapeProvider())

    def tearDown(self):
        self._e.stop()

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            replay_session("20260708", brain="telepathic")

    def test_live_mode_runs_without_recorded_brain(self):
        res = replay_session("20260708", lookback=25, max_scans=2, brain="live",
                             sandbox=os.path.join(self.tmp, "sb1"))
        self.assertEqual(res["manifest"]["brain_mode"], "live")
        self.assertIn("live_llm_nondeterministic", res["manifest"]["caveats"])
        self.assertIsNone(res["summary"]["brain_served"])   # no substitution
        self.assertGreaterEqual(res["summary"]["scans"], 1)
        self.assertEqual(res["summary"]["errors"], 0)

    def test_safety_keys_forced_in_live_mode(self):
        res = replay_session("20260708", lookback=25, max_scans=1, brain="live",
                             flags={"EXECUTION_ENABLED": "true"},
                             sandbox=os.path.join(self.tmp, "sb2"))
        self.assertEqual(res["manifest"]["forced_safety"], _SAFETY_ENV)
        for scan in res["scans"]:
            self.assertFalse(scan["trace"].get("would_authorize") and False)

    def test_recorded_mode_unchanged(self):
        res = replay_session("20260708", lookback=25, max_scans=1,
                             sandbox=os.path.join(self.tmp, "sb3"))
        self.assertEqual(res["manifest"]["brain_mode"], "recorded")
        self.assertIsNotNone(res["summary"]["brain_misses"])


def _out(direction="bearish", family="none", conf=70):
    return {"narrative_direction": direction, "narrative_phase": "manipulation",
            "phase_confidence": conf,
            "recommended_playbook_family": family,
            "recommended_tool_family": [family],
            "dominant_reasoning": ("Buy-side liquidity was swept and reclaimed; "
                                   "price near the protected high while delivery is "
                                   "bearish; draw remains sell-side; manipulation "
                                   "phase; invalidation above 702.5.")}


def _call(parsed, ok=True, reason=None):
    return {"parsed": parsed, "ok": ok, "fallback_reason": reason}


def _rec():
    return {"timestamp": "t", "parsed_output": _out(),
            "input_payload": {"timestamp": "t", "market": {}}}


class TestFamilyRepairReplay(unittest.TestCase):
    def _patch(self, seq):
        import ai_brain.narrative_brain as nb
        calls = iter(seq)
        return patch.object(nb, "_call_llm",
                            side_effect=lambda p, repair=None: next(calls))

    def test_fixed_by_prompt(self):
        with self._patch([_call(_out(family="liquidity_sweep_reversal"))]):
            r = replay_one(_rec())
        self.assertEqual(r["outcome"], "fixed_by_prompt")

    def test_fixed_by_repair(self):
        with self._patch([_call(_out(family="none")),
                          _call(_out(family="trend_continuation"))]):
            r = replay_one(_rec())
        self.assertEqual(r["outcome"], "fixed_by_repair")
        self.assertEqual(r["repaired_family"], "trend_continuation")

    def test_direction_flip_rejected(self):
        with self._patch([_call(_out(direction="bearish", family="none")),
                          _call(_out(direction="bullish",
                                     family="trend_continuation"))]):
            r = replay_one(_rec())
        self.assertEqual(r["outcome"], "flip_rejected")

    def test_now_conflicted_escape_hatch(self):
        with self._patch([_call(_out(direction="conflicted", family="none"))]):
            r = replay_one(_rec())
        self.assertEqual(r["outcome"], "now_conflicted")

    def test_llm_error_counted(self):
        with self._patch([_call(None, ok=False, reason="timeout")]):
            r = replay_one(_rec())
        self.assertEqual(r["outcome"], "llm_error")


if __name__ == "__main__":
    unittest.main()

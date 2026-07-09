"""
PERCEPTION-1 — expansion state hysteresis: regression lock.

2026-07-08 perception assassination proved the 5m expansion classifier is the
primary oscillation source: state 29 transitions / 11 one-scan reversals;
exhaustion level 51 / 21 one-scan reversals (avg persistence 3.1 scans), vs a
stable 15m (2 transitions). `_exhaustion_risk` reads a 3-candle window against
hard thresholds with no hysteresis, so the state flips as the window rolls;
38/48 exhaustion_risk narratives were driven by this flickering fast-TF signal.

Repair (config-gated, default off = bit-for-bit legacy; FC launcher = on):
ExpansionStabilityManager debounces the per-TF expansion `state` — a raw change
must persist EXPANSION_STABILITY_CONFIRM (default 2) consecutive scans before it
is accepted; otherwise the previous stable state is held. Only `state` is
stabilized; scores and all other fields pass through untouched.

Locks:
  * default off: input returned unchanged (byte-identical legacy)
  * on: one-scan state flip is HELD (flicker killed)
  * on: a change that persists >= window is ACCEPTED (not stuck forever)
  * hysteresis is symmetric (enter and leave both debounced)
  * only `state` is altered; expansion_score and other fields untouched
  * first sighting / unknown accepted immediately (no startup lag)
  * never raises on malformed input
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from volatility.expansion_stability import (                    # noqa: E402
    ExpansionStabilityManager, stability_enabled,
)


def _exp(state, score=60):
    return {"5m": {"state": state, "expansion_score": score,
                   "exhaustion_risk": "low"}}


class TestDefaultOff(unittest.TestCase):
    def test_disabled_returns_unchanged(self):
        with patch.dict(os.environ, {"EXPANSION_STABILITY_MODE": "off"}):
            m = ExpansionStabilityManager()
            a = _exp("mature_expansion")
            b = _exp("exhaustion_risk")
            self.assertEqual(m.update(a)["5m"]["state"], "mature_expansion")
            self.assertEqual(m.update(b)["5m"]["state"], "exhaustion_risk")  # no hold

    def test_default_env_is_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EXPANSION_STABILITY_MODE", None)
            self.assertFalse(stability_enabled())


class TestHysteresisOn(unittest.TestCase):
    def setUp(self):
        self._e = patch.dict(os.environ, {"EXPANSION_STABILITY_MODE": "on",
                                          "EXPANSION_STABILITY_CONFIRM": "2"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_one_scan_flip_is_held(self):
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))          # confirm mature
        out = m.update(_exp("exhaustion_risk"))     # single-scan flip -> HELD
        self.assertEqual(out["5m"]["state"], "mature_expansion")
        self.assertEqual(out["5m"]["expansion_stability"]["raw_state"], "exhaustion_risk")

    def test_flip_back_before_confirm_stays_stable(self):
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))
        m.update(_exp("exhaustion_risk"))           # held (pending 1)
        out = m.update(_exp("mature_expansion"))    # reverted -> still mature, no flicker
        self.assertEqual(out["5m"]["state"], "mature_expansion")
        self.assertNotIn("expansion_stability", out["5m"])

    def test_sustained_change_is_accepted(self):
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))
        m.update(_exp("exhaustion_risk"))           # pending 1 (held)
        out = m.update(_exp("exhaustion_risk"))     # pending 2 -> ACCEPTED
        self.assertEqual(out["5m"]["state"], "exhaustion_risk")

    def test_symmetric_leaving_exhaustion_also_debounced(self):
        m = ExpansionStabilityManager()
        m.update(_exp("exhaustion_risk"))           # confirm exhaustion (first sighting)
        out = m.update(_exp("mature_expansion"))    # single flip out -> HELD at exhaustion
        self.assertEqual(out["5m"]["state"], "exhaustion_risk")

    def test_only_state_altered_scores_untouched(self):
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion", score=60))
        out = m.update(_exp("exhaustion_risk", score=44))
        self.assertEqual(out["5m"]["state"], "mature_expansion")   # held
        self.assertEqual(out["5m"]["expansion_score"], 44)          # score passes through

    def test_first_sighting_accepted_immediately(self):
        m = ExpansionStabilityManager()
        out = m.update(_exp("exhaustion_risk"))
        self.assertEqual(out["5m"]["state"], "exhaustion_risk")

    def test_per_tf_independent(self):
        m = ExpansionStabilityManager()
        m.update({"15m": {"state": "mature_expansion"}, "5m": {"state": "mature_expansion"}})
        out = m.update({"15m": {"state": "mature_expansion"},
                        "5m": {"state": "exhaustion_risk"}})
        self.assertEqual(out["15m"]["state"], "mature_expansion")
        self.assertEqual(out["5m"]["state"], "mature_expansion")   # 5m flip held

    def test_never_raises_on_garbage(self):
        m = ExpansionStabilityManager()
        self.assertEqual(m.update(None), None)
        self.assertEqual(m.update({"5m": "notadict"})["5m"], "notadict")
        self.assertEqual(m.update({"alignment": "full"})["alignment"], "full")


class TestConfirmWindow3(unittest.TestCase):
    """BOT-VS-MAURICE (2026-07-08): the FC launcher runs confirm=3 because the
    13:12 +1.69R winner was killed by a transient 2-scan exhaustion blip that
    confirm=2 accepted. Session episodes split cleanly (<=2 noise vs >=4
    sustained; zero 3-scan), so a 3-scan window absorbs every blip while still
    accepting genuine sustained exhaustion."""

    def setUp(self):
        self._e = patch.dict(os.environ, {"EXPANSION_STABILITY_MODE": "on",
                                          "EXPANSION_STABILITY_CONFIRM": "3"})
        self._e.start()

    def tearDown(self):
        self._e.stop()

    def test_two_scan_exhaustion_blip_is_held(self):
        # mature -> exhaustion,exhaustion (2-scan blip) -> the 13:12 kill pattern
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))
        out1 = m.update(_exp("exhaustion_risk"))   # pending 1 -> held
        out2 = m.update(_exp("exhaustion_risk"))   # pending 2 -> STILL held (confirm=3)
        self.assertEqual(out1["5m"]["state"], "mature_expansion")
        self.assertEqual(out2["5m"]["state"], "mature_expansion")

    def test_two_scan_blip_then_revert_never_accepts(self):
        # the exact 131237 sequence: mature -> exh -> exh -> early_expansion
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))
        m.update(_exp("exhaustion_risk"))          # held (pending 1)
        m.update(_exp("exhaustion_risk"))          # held (pending 2) — confirm=2 would ACCEPT here
        out = m.update(_exp("early_expansion"))    # blip over; never became exhaustion
        self.assertNotEqual(out["5m"]["state"], "exhaustion_risk")

    def test_three_scan_sustained_exhaustion_is_accepted(self):
        # a genuine >=3-scan exhaustion still gets through — safety preserved
        m = ExpansionStabilityManager()
        m.update(_exp("mature_expansion"))
        m.update(_exp("exhaustion_risk"))          # pending 1 (held)
        m.update(_exp("exhaustion_risk"))          # pending 2 (held)
        out = m.update(_exp("exhaustion_risk"))    # pending 3 -> ACCEPTED
        self.assertEqual(out["5m"]["state"], "exhaustion_risk")


class TestSafetyUntouched(unittest.TestCase):
    def test_flag_absent_from_execution_safeguards(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (("paper_execution", "order_builder.py"),
                           ("risk", "risk_governor.py")):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                self.assertNotIn("EXPANSION_STABILITY", fh.read(), f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

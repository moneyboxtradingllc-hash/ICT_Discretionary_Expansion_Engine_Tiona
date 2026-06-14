"""
Phase AB-5B — ECU migration tests.

Default (BRAIN_ECU_MODE off): mechanical pipeline unchanged.
ECU on: the Brain thesis OWNS direction; qualification/playbook become validators
that inherit it; mechanical direction is witness/fallback only.
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qualification.trade_qualification_engine import _direction_with_source, qualify_trade
from playbooks.playbook_classifier import _direction as pb_direction
from ai_brain.ecu import ecu_enabled


def _on():  os.environ["BRAIN_ECU_MODE"] = "true"
def _off(): os.environ.pop("BRAIN_ECU_MODE", None)


def _thesis(direction="bearish"):
    return {"owner": "ai_brain", "source": "llm", "direction": direction,
            "forbidden_direction": "bullish" if direction == "bearish" else "bearish",
            "opportunity": direction in ("bullish", "bearish"),
            "playbook_family": "liquidity_sweep_reversal", "tool_family": ["bearish_ifvg"],
            "confidence": 70}


class TestEnvGate(unittest.TestCase):
    def tearDown(self): _off()
    def test_default_off(self):
        _off(); self.assertFalse(ecu_enabled())
    def test_on(self):
        _on(); self.assertTrue(ecu_enabled())


class TestDirectionOwnership(unittest.TestCase):
    def tearDown(self): _off()

    def test_brain_thesis_owns_direction(self):
        d, src = _direction_with_source({"directional_bias": "bullish"}, {}, {}, {},
                                        _thesis("bearish"))
        self.assertEqual(d, "bearish")        # brain bearish overrides structure bullish
        self.assertEqual(src, "ai_brain")

    def test_brain_thesis_bullish_owns(self):
        d, src = _direction_with_source({"directional_bias": "bearish"}, {}, {}, {},
                                        _thesis("bullish"))
        self.assertEqual((d, src), ("bullish", "ai_brain"))

    def test_brain_neutral_falls_back_to_mechanical_witness(self):
        # Brain non-directional → mechanical firewall path resumes (no thesis ownership)
        d, src = _direction_with_source({"directional_bias": "bullish"}, {}, {}, {},
                                        _thesis("neutral"))
        self.assertNotEqual(src, "ai_brain")   # mechanical witness/firewall

    def test_no_thesis_is_legacy_mechanical(self):
        d, src = _direction_with_source({"directional_bias": "bullish"}, {}, {}, {}, None)
        self.assertNotEqual(src, "ai_brain")


class TestQualifyTradeECU(unittest.TestCase):
    def tearDown(self): _off()

    def _snap(self, brain_dir):
        return {
            "ai_context": {"directional_bias": "bullish", "market_narrative": ""},
            "structure": {"15m": {"bias": "bullish"}},
            "volatility": {"15m": {"state": "stable"}},
            "po3": {}, "liquidity": {},
            "brain_thesis": _thesis(brain_dir),
        }

    def test_qualification_inherits_brain_direction(self):
        q = qualify_trade(self._snap("bearish"))
        self.assertEqual(q["direction"], "bearish")
        self.assertEqual(q["direction_source"], "ai_brain")

    def test_playbook_inherits_brain_direction(self):
        snap = self._snap("bearish")
        snap["qualification"] = qualify_trade(snap)
        self.assertEqual(pb_direction(snap), "bearish")


class TestECUOffUnchanged(unittest.TestCase):
    """With no brain_thesis, behavior is the pre-AB-5B mechanical path."""
    def test_mechanical_direction_when_no_thesis(self):
        snap = {"ai_context": {"directional_bias": "bullish"},
                "structure": {}, "volatility": {"15m": {"state": "stable"}},
                "po3": {"15m": {"distribution_direction": "bearish"}}, "liquidity": {}}
        q = qualify_trade(snap)
        # delivery (po3) authors under the firewall — NOT ai_brain
        self.assertNotEqual(q["direction_source"], "ai_brain")


if __name__ == "__main__":
    unittest.main(verbosity=2)

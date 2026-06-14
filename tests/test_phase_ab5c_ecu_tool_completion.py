"""
Phase AB-5C — ECU tool & playbook completion tests.

Brain owns tool selection (recommended_tool_family) and all 6 playbooks.
toolbox_engine becomes validator/ranker. Gated BRAIN_ECU_MODE (default off).
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from toolbox.toolbox_engine import run_toolbox, _brain_preferred_tool
from toolbox.tool_library import VALID_TOOLS, eligible_tools
from playbooks.playbook_classifier import classify_playbook


def _on():  os.environ["BRAIN_ECU_MODE"] = "true"
def _off(): os.environ.pop("BRAIN_ECU_MODE", None)


def _snap(pb, direction, tool_family, status="actionable"):
    """Minimal snapshot with a Brain thesis + a playbook so run_toolbox scores
    the eligible set. Evidence is rich enough for tools to score > 40."""
    return {
        "brain_thesis": {"owner": "ai_brain", "opportunity": True,
                         "direction": direction, "playbook_family": pb,
                         "tool_family": [tool_family], "confidence": 70,
                         "opportunity_type": "manipulation"},
        "playbook": {"selected_playbook": pb, "direction": direction},
        "risk": {"trade_allowed": True},
        "structure": {tf: {"bias": direction, "mss": True, "bos": True,
                           "last_swing_high": 702.5, "last_swing_low": 700.0}
                      for tf in ("15m", "5m", "3m", "1m")},
        "liquidity": {tf: {"sweep_detected": True,
                           "sweep_direction": "above_high" if direction == "bearish" else "below_low",
                           "reclaim_detected": True, "failed_breakout": True}
                      for tf in ("15m", "5m", "3m", "1m")},
        "volatility": {tf: {"state": "expanding"} for tf in ("15m", "5m", "3m", "1m")},
        "expansion": {tf: {"state": "early_expansion", "displacement_detected": True}
                      for tf in ("15m", "5m", "3m", "1m")},
        "po3": {"15m": {"phase": "manipulation"}, "alignment": "manipulation_to_distribution"},
    }


class TestBrainToolResolution(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _off()

    def test_family_token_resolves_with_direction(self):
        cand = ["bearish_ifvg", "bearish_breaker"]
        tool, note = _brain_preferred_tool(
            {"brain_thesis": {"tool_family": ["ifvg"]}}, "bearish", cand)
        self.assertEqual(tool, "bearish_ifvg")
        self.assertEqual(note, "ai_brain_selected")

    def test_ineligible_family_rejected(self):
        cand = ["bearish_ifvg", "bearish_breaker"]
        tool, note = _brain_preferred_tool(
            {"brain_thesis": {"tool_family": ["order_block"]}}, "bearish", cand)
        self.assertIsNone(tool)
        self.assertIn("not_eligible", note)

    def test_off_mode_no_brain_pick(self):
        _off()
        tool, note = _brain_preferred_tool(
            {"brain_thesis": {"tool_family": ["ifvg"]}}, "bearish", ["bearish_ifvg"])
        self.assertIsNone(tool)
        self.assertIsNone(note)


class TestToolboxBrainOwnership(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _off()

    def test_brain_selects_preferred_tool(self):
        # LSR bearish, Brain picks breaker → preferred must be bearish_breaker
        tb = run_toolbox(_snap("liquidity_sweep_reversal", "bearish", "breaker"))
        self.assertEqual(tb["preferred_tool"], "bearish_breaker")
        self.assertEqual(tb["preferred_tool_source"], "ai_brain_selected")

    def test_brain_picks_different_tool_same_set(self):
        tb = run_toolbox(_snap("liquidity_sweep_reversal", "bearish", "rejection_block"))
        self.assertEqual(tb["preferred_tool"], "bearish_rejection_block")
        self.assertEqual(tb["preferred_tool_source"], "ai_brain_selected")

    def test_ineligible_tool_falls_back_to_mechanical(self):
        # order_block not eligible for liquidity_sweep_reversal
        tb = run_toolbox(_snap("liquidity_sweep_reversal", "bearish", "order_block"))
        self.assertEqual(tb["preferred_tool_source"], "mechanical")
        self.assertTrue(any("not_eligible" in w for w in tb["warnings"]))

    def test_neutral_tool_family_derives_from_brain_playbook(self):
        # Brain emits no concrete tool ("none") → tool derived from the
        # Brain-chosen playbook's preferred (still Brain-owned, not mechanical)
        snap = _snap("liquidity_sweep_reversal", "bearish", "none")
        tb = run_toolbox(snap)
        self.assertEqual(tb["preferred_tool_source"], "ai_brain_playbook_derived")
        self.assertEqual(tb["preferred_tool"], "bearish_ifvg")  # LSR bearish preferred[0]


class TestAllSixPlaybooksReachable(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _off()

    def test_each_playbook_originated_by_brain(self):
        for pb in ("liquidity_sweep_reversal", "trend_continuation",
                   "manipulation_to_distribution", "failed_breakout_reversal",
                   "opening_drive", "range_expansion"):
            snap = {"brain_thesis": {"owner": "ai_brain", "opportunity": True,
                                     "direction": "bearish", "playbook_family": pb,
                                     "confidence": 70, "opportunity_type": "x"},
                    "qualification": {"status": "candidate", "direction": "bearish"},
                    "structure": {}, "liquidity": {}, "po3": {}}
            res = classify_playbook(snap)
            self.assertEqual(res["selected_playbook"], pb, f"{pb} not originated")
            self.assertEqual(res["direction_source"], "ai_brain")


class TestAll22ToolsReachable(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _off()

    def test_every_canonical_tool_is_brain_selectable_via_some_playbook(self):
        # For each tool, find a playbook+direction whose eligible set contains it,
        # and confirm the Brain family token resolves to it.
        from toolbox.tool_library import _ELIGIBLE
        reachable = set()
        for pb, dirs in _ELIGIBLE.items():
            for direction, tools in dirs.items():
                for tool in tools:
                    fam = tool.replace(f"{direction}_", "")
                    picked, note = _brain_preferred_tool(
                        {"brain_thesis": {"tool_family": [fam]}}, direction, [tool])
                    if picked == tool:
                        reachable.add(tool)
        self.assertEqual(reachable, set(VALID_TOOLS),
                         f"unreachable: {set(VALID_TOOLS) - reachable}")


class TestECUOffUnchanged(unittest.TestCase):
    def test_off_uses_mechanical_preferred(self):
        _off()
        tb = run_toolbox(_snap("liquidity_sweep_reversal", "bearish", "breaker"))
        # no brain ownership when ECU off
        self.assertEqual(tb.get("preferred_tool_source"), "mechanical")


if __name__ == "__main__":
    unittest.main(verbosity=2)

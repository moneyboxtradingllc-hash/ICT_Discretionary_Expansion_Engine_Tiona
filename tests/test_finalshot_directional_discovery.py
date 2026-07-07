"""
FINAL-SHOT — directional discovery: regression lock.

2026-07-07 14:32 ET QQQ short (proven homicide): the HEALTHY LLM Brain
authored direction=bearish@45, opportunity=True, phase="accumulation",
family/playbooks/tools = none. classify_playbook's Brain path found no
mappable family, fell through to the qualification hard block, and returned
no_playbook with the MISLEADING warning "Qualification status is no_trade"
— silently discarding the directional thesis. run_toolbox (line 472) is
hard-gated on the playbook, so the real 1m bearish FVG (712.47-712.77,
retested 14:31-14:32, then -1.5pts) was never scored, and no downstream
authority ever evaluated the trade.

Locks:
  * healthy directional thesis + family none -> MECHANICAL DISCOVERY at the
    existing >=45 threshold (unchanged); discovered playbook opens the
    toolbox sensors; origination fully audited
  * discovery failure -> TRUTHFUL no_playbook audit naming the Brain
    direction/confidence/phase/family and the best mechanical score
  * discovery grants NO sovereignty: qualification/AI-AUTH-2 unchanged —
    the mechanical layer may not author opportunity
  * degraded/fallback Brain sources fail closed: legacy path byte-identical
    (degraded AI can never create executable opportunity)
  * existing AB-5B family path and mechanical path unchanged (plus audit key)
  * FC-0B / risk / council / RELATION-TRUTH untouched (source guard)
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from playbooks.playbook_classifier import classify_playbook       # noqa: E402
from toolbox.toolbox_engine import run_toolbox                    # noqa: E402
from qualification.trade_qualification_engine import qualify_trade  # noqa: E402


def _thesis_1432(source="llm"):
    """The recorded 14:32:04 Brain thesis shape."""
    return {
        "owner": "ai_brain", "source": source, "direction": "bearish",
        "forbidden_direction": "bullish", "opportunity": True,
        "opportunity_type": "accumulation",           # unmapped phase
        "playbook_family": "none", "tool_family": ["none"],
        "confidence": 45, "dominant_reasoning": "observe and assess",
    }


def _snap_1432(brain_thesis, with_sweep=False):
    """14:32 geometry. `with_sweep` adds mechanical sweep+reclaim evidence so
    the liquidity_sweep_reversal scorer clears the existing 45 threshold."""
    liquidity = ({"5m": {"sweep_detected": True, "reclaim_detected": True}}
                 if with_sweep else {})
    return {
        "ai_context": {
            "market_narrative": "accumulation_before_expansion",
            "confidence_tier": "no_trade", "confidence_score": 49,
            "market_state": "", "directional_bias": "neutral",
        },
        "structure": {}, "volatility": {}, "liquidity": liquidity,
        "expansion": {}, "po3": {}, "memory": {},
        "qualification": {"status": "no_trade", "grade": "F",
                          "direction": "bearish",
                          "direction_source": "ai_brain"},
        "brain_thesis": brain_thesis,
    }


class TestDiscoverySucceeds(unittest.TestCase):
    def test_healthy_directional_thesis_discovers_playbook(self):
        out = classify_playbook(_snap_1432(_thesis_1432(), with_sweep=True))
        self.assertEqual(out["selected_playbook"], "liquidity_sweep_reversal")
        self.assertEqual(out["direction"], "bearish")
        self.assertEqual(out["direction_source"], "ai_brain")
        self.assertEqual(out["origination"], "brain_directional_discovery")
        self.assertGreaterEqual(out["playbook_confidence"], 45)
        self.assertTrue(any("no sovereignty granted" in w
                            for w in out["warnings"]))

    def test_discovered_playbook_opens_toolbox_gate(self):
        snap = _snap_1432(_thesis_1432(), with_sweep=True)
        snap["playbook"] = classify_playbook(snap)
        snap["risk"] = {"trade_allowed": True}
        out = run_toolbox(snap)
        # the sensors RAN: the no-playbook gate warning must be absent
        self.assertNotIn("no playbook selected — toolbox cannot activate",
                         out.get("warnings", []))

    def test_discovery_grants_no_sovereignty(self):
        """The 14:32 thesis stays non-sovereign: qualification unchanged.
        Mechanical discovery must never author opportunity."""
        out = qualify_trade(_snap_1432(_thesis_1432(), with_sweep=True))
        self.assertFalse(out["brain_sovereign"])
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)


class TestDiscoveryFailsTruthfully(unittest.TestCase):
    def test_1432_as_recorded_no_silent_collapse(self):
        """The recorded 14:32 (no mechanical sweep evidence): still
        no_playbook — but the audit now tells the truth."""
        out = classify_playbook(_snap_1432(_thesis_1432(), with_sweep=False))
        self.assertEqual(out["selected_playbook"], "no_playbook")
        self.assertEqual(out["direction"], "bearish")           # not discarded
        self.assertEqual(out["direction_source"], "ai_brain")
        self.assertEqual(out["origination"],
                         "brain_directional_discovery_failed")
        w = " ".join(out["warnings"])
        self.assertIn("bearish@45", w)
        self.assertIn("phase='accumulation'", w)
        self.assertIn("family='none'", w)
        # the misleading legacy message must be gone for this path
        self.assertNotIn("Qualification status is no_trade", w)


class TestFallbackFailsClosed(unittest.TestCase):
    def test_degraded_brain_cannot_discover(self):
        """Fallback thesis + strong mechanical sweep evidence: discovery must
        NOT run — degraded AI can never create executable opportunity. The
        legacy qualification hard block resumes byte-identically."""
        for src in ("llm_failed_fallback", "deterministic",
                    "contaminated_input", "degraded"):
            out = classify_playbook(
                _snap_1432(_thesis_1432(source=src), with_sweep=True))
            self.assertEqual(out["selected_playbook"], "no_playbook", src)
            self.assertEqual(out["origination"], "none", src)
            self.assertIn("Qualification status is no_trade — no playbook eligible",
                          out["warnings"], src)

    def test_missing_thesis_unchanged(self):
        snap = _snap_1432(None)
        snap.pop("brain_thesis")
        out = classify_playbook(snap)
        self.assertEqual(out["selected_playbook"], "no_playbook")
        self.assertIn("Qualification status is no_trade — no playbook eligible",
                      out["warnings"])


class TestExistingPathsUnchanged(unittest.TestCase):
    def test_brain_family_path_still_originates(self):
        t = _thesis_1432()
        t["playbook_family"] = "trend_continuation"
        out = classify_playbook(_snap_1432(t))
        self.assertEqual(out["selected_playbook"], "trend_continuation")
        self.assertEqual(out["origination"], "ai_brain_family")
        self.assertEqual(out["direction"], "bearish")

    def test_brain_phase_map_path_still_originates(self):
        t = _thesis_1432()
        t["opportunity_type"] = "distribution"     # mapped phase
        out = classify_playbook(_snap_1432(t))
        self.assertEqual(out["selected_playbook"], "manipulation_to_distribution")
        self.assertEqual(out["origination"], "ai_brain_family")

    def test_conflicted_direction_never_discovers(self):
        t = _thesis_1432()
        t["direction"] = "conflicted"
        t["opportunity"] = True
        out = classify_playbook(_snap_1432(t, with_sweep=True))
        self.assertEqual(out["selected_playbook"], "no_playbook")


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_untouched_files_have_no_finalshot_logic(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution",   "order_builder.py"),     # FC-0B
                ("risk",              "risk_governor.py"),
                ("shared_context",    "council.py"),
                ("toolbox",           "price_levels.py"),      # RELATION-TRUTH
                ("toolbox",           "toolbox_engine.py"),    # gate unchanged
                ("qualification",     "trade_qualification_engine.py"),
        ):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("FINAL-SHOT", body, f"{pkg}/{fname}")
            self.assertNotIn("healthy_directional_thesis", body,
                             f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

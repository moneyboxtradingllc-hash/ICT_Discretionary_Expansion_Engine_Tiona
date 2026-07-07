"""
SCAR-TISSUE — distribution_in_progress personality blacklist: regression lock.

The Tiona-class defect found in Mainline (2026-07-07): narrative_builder's
_trade_personality blacklisted "distribution_in_progress" — ACTIVE directional
delivery, worth 22 pts in qualification's own NARRATIVE_QUALITY table (the
second-highest tradeable narrative) — as "no_trade_context". That personality
fed confidence_engine._apply_caps, hard-capping confidence at 49 (one point
below the observe tier), forcing confidence_tier="no_trade" -> qualification
disqualified -> opportunity 0 -> risk hard block -> toolbox demoted. It also
labeled active distribution "no_trade_context" inside the Brain's own input
payload. Live proof: 10:43:33 ET carried full MTF alignment + 15m BOS + PO3
full distribution + confirmed displacement and scored EXACTLY 49.

Locks:
  * distribution_in_progress -> trend_continuation personality (delivery
    continuation); NOT capped; mechanical perception restored end-to-end
  * the six genuine no-trade environments keep the blacklist AND the cap
    (conflicted / exhaustion_risk / compression / neutral /
    manipulation_without_distribution / accumulation_before_expansion)
  * conflicted-narrative cap and dangerous-state cap untouched (safety)
  * no thresholds changed: tier boundaries, scoring tables byte-identical
  * end-to-end: distribution evidence now qualifies mechanically WITHOUT any
    Brain sovereignty involved (perception repair, not authority change)
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_layer.narrative_builder import _trade_personality        # noqa: E402
from ai_layer.confidence_engine import score_confidence, TIERS   # noqa: E402
from qualification.trade_qualification_engine import qualify_trade  # noqa: E402


def _strong_distribution_evidence():
    """The 10:43-style mechanical evidence shape: full alignment, healthy
    environment, PO3 full distribution."""
    return {
        "structure":  {"alignment": "full"},
        "volatility": {},
        "expansion":  {},
        "liquidity":  {},
        "session":    "ny_open",
        "po3":        {"alignment": "full_distribution_alignment"},
    }


def _narr(market_narrative, personality=None, market_state="trending"):
    if personality is None:
        personality = _trade_personality(market_narrative, market_state,
                                         "bearish", {}, "ny_open")
    return {"market_narrative": market_narrative,
            "trade_personality": personality,
            "market_state": market_state}


class TestPersonalityMap(unittest.TestCase):
    def test_distribution_in_progress_is_delivery_continuation(self):
        self.assertEqual(
            _trade_personality("distribution_in_progress", "trending",
                               "bearish", {}, "morning_continuation"),
            "trend_continuation")

    def test_genuine_no_trade_environments_keep_blacklist(self):
        for narrative in ("conflicted", "exhaustion_risk", "compression",
                          "neutral", "manipulation_without_distribution",
                          "accumulation_before_expansion"):
            self.assertEqual(
                _trade_personality(narrative, "trending", "bearish", {},
                                   "morning_continuation"),
                "no_trade_context", narrative)


class TestCapRepaired(unittest.TestCase):
    def test_distribution_day_no_longer_capped_at_49(self):
        ev = _strong_distribution_evidence()
        out = score_confidence(ev["structure"], ev["volatility"],
                               ev["expansion"], ev["liquidity"], ev["session"],
                               _narr("distribution_in_progress"), ev["po3"])
        self.assertGreater(out["confidence_score"], 49,
                           "the Tiona cap is back")
        self.assertNotEqual(out["confidence_tier"], "no_trade")

    def test_conflicted_cap_untouched(self):
        ev = _strong_distribution_evidence()
        out = score_confidence(ev["structure"], ev["volatility"],
                               ev["expansion"], ev["liquidity"], ev["session"],
                               _narr("conflicted"), ev["po3"])
        self.assertLessEqual(out["confidence_score"], 49)
        self.assertEqual(out["confidence_tier"], "no_trade")

    def test_wait_state_narratives_still_capped(self):
        """accumulation_before_expansion (the 14:32 label) keeps the cap —
        wait-state doctrine unchanged, no threshold lowered."""
        ev = _strong_distribution_evidence()
        out = score_confidence(ev["structure"], ev["volatility"],
                               ev["expansion"], ev["liquidity"], ev["session"],
                               _narr("accumulation_before_expansion"), ev["po3"])
        self.assertLessEqual(out["confidence_score"], 49)
        self.assertEqual(out["confidence_tier"], "no_trade")

    def test_dangerous_state_cap_untouched(self):
        ev = _strong_distribution_evidence()
        out = score_confidence(ev["structure"],
                               {"5m": {"state": "toxic"},
                                "3m": {"state": "toxic"}},
                               ev["expansion"], ev["liquidity"], ev["session"],
                               _narr("distribution_in_progress",
                                     market_state="dangerous"),
                               ev["po3"])
        self.assertLessEqual(out["confidence_score"], 49)

    def test_tier_boundaries_unchanged(self):
        self.assertEqual(TIERS, [(85, "elite_setup"), (70, "valid_setup"),
                                 (50, "observe"), (0, "no_trade")])


class TestEndToEndPerceptionRestored(unittest.TestCase):
    def test_1043_replay_distribution_evidence_qualifies_mechanically(self):
        """The 10:43:33 shape: full alignment + PO3 full distribution +
        distribution_in_progress. Pre-repair: capped 49 -> tier no_trade ->
        disqualified -> F 0. Post-repair: honest tier, honest opportunity —
        with NO Brain thesis involved (pure mechanical perception)."""
        ev = _strong_distribution_evidence()
        conf = score_confidence(ev["structure"], ev["volatility"],
                                ev["expansion"], ev["liquidity"],
                                ev["session"],
                                _narr("distribution_in_progress"), ev["po3"])
        snap = {
            "ai_context": {
                "market_narrative": "distribution_in_progress",
                "confidence_tier":  conf["confidence_tier"],
                "confidence_score": conf["confidence_score"],
                "market_state":     "trending",
                "directional_bias": "bearish",
                "trade_personality": "trend_continuation",
            },
            "structure":  ev["structure"],
            "volatility": ev["volatility"],
            "liquidity":  ev["liquidity"],
            "expansion":  ev["expansion"],
            "po3":        ev["po3"],
            "memory":     {},
            # NO brain_thesis — this is the mechanical plane standing alone
        }
        out = qualify_trade(snap)
        self.assertFalse(out["brain_sovereign"])
        self.assertGreater(out["opportunity_score"], 0,
                           "tier disqualifier fired — scar is back")
        self.assertNotEqual(out["status"], "no_trade")

    def test_danger_states_still_zero_end_to_end(self):
        ev = _strong_distribution_evidence()
        snap = {
            "ai_context": {"market_narrative": "conflicted",
                           "confidence_tier": "no_trade",
                           "confidence_score": 49, "market_state": "",
                           "trade_personality": "no_trade_context"},
            "structure": ev["structure"], "volatility": {}, "liquidity": {},
            "expansion": {}, "po3": ev["po3"], "memory": {},
        }
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_untouched_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution", "order_builder.py"),   # FC-0B
                ("shared_context",  "council.py"),
                ("toolbox",         "price_levels.py"),    # RELATION-TRUTH
                ("risk",            "risk_governor.py"),
                ("qualification",   "trade_qualification_engine.py"),
        ):
            with open(os.path.join(src, pkg, fname), encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("SCAR-TISSUE", body, f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

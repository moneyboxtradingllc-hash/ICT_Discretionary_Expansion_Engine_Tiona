"""
AI-AUTH-2 — Brain opportunity sovereignty: regression lock.

2026-07-07 proven defect: the legacy mechanical confidence tier
(ai_context.confidence_tier, score_confidence) held a BINARY kill inside
qualification (`conf_tier == "no_trade"` -> disqualified -> opportunity 0)
and a duplicated kill inside the risk governor. At 10:59:32 ET the healthy
LLM Brain authored a complete bullish conversion (direction+family+playbook+
tool, conf 80) and the legacy tier (score 49) zeroed it before council,
regime, risk, trigger, or FC-0B ever saw it.

Locks:
  * sovereignty predicate: healthy LLM + directional opportunity + real family
  * 10:59 replay: conversion SURVIVES qualification (floor=candidate),
    legacy disagreement logged as witness warning
  * 11:14 replay AS RECORDED: families were "none" — NOT a conversion ->
    legacy behavior byte-identical (sovereignty never manufactures conversions)
  * 11:14 mission-premise variant (converted shape) -> survives
  * every degraded Brain source (llm_failed_fallback / deterministic /
    contaminated_input / degraded / missing) -> full legacy authority restored
  * environment-danger disqualifiers keep full authority even when sovereign
  * floor only raises: mechanical elite stays elite; disqualified never floored
  * risk governor: duplicated conf-tier kill demoted only when sovereign;
    fallback keeps the hard block; floored candidate caps at MINIMAL tier
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.ecu import sovereign_conversion                       # noqa: E402
from qualification.trade_qualification_engine import qualify_trade  # noqa: E402
from risk.risk_governor import evaluate_risk                        # noqa: E402


def _thesis(source="llm", direction="bullish", opportunity=True,
            playbook_family="continuation", tool_family=None, confidence=80):
    return {
        "owner": "ai_brain", "source": source, "direction": direction,
        "forbidden_direction": "bearish" if direction == "bullish" else "bullish",
        "opportunity": opportunity, "opportunity_type": "continuation",
        "playbook_family": playbook_family,
        "tool_family": tool_family if tool_family is not None
        else ["confirmation_required"],
        "confidence": confidence, "dominant_reasoning": "test",
    }


def _snap_1059(brain_thesis):
    """The 10:59:32 geometry: legacy stack lagging the reversal at 49/no_trade
    while the Brain authored a bullish continuation conversion."""
    return {
        "ai_context": {
            "market_narrative": "distribution_in_progress",
            "confidence_tier":  "no_trade",
            "confidence_score": 49,
            "market_state":     "",
            "directional_bias": "neutral",
        },
        "structure":  {"alignment": "neutral"},
        "volatility": {},
        "liquidity":  {},
        "expansion":  {},
        "po3":        {"alignment": "mixed"},
        "memory":     {},
        "brain_thesis": brain_thesis,
    }


class TestSovereigntyPredicate(unittest.TestCase):
    def test_healthy_full_conversion_is_sovereign(self):
        ok, detail = sovereign_conversion({"brain_thesis": _thesis()})
        self.assertTrue(ok, detail)

    def test_every_degraded_source_fails_closed(self):
        for src in ("llm_failed_fallback", "deterministic",
                    "contaminated_input", "degraded", "ecu_error:x",
                    "brain_disabled", None):
            ok, detail = sovereign_conversion(
                {"brain_thesis": _thesis(source=src)})
            self.assertFalse(ok, f"source={src} must fail closed ({detail})")

    def test_missing_thesis_fails_closed(self):
        self.assertFalse(sovereign_conversion({})[0])
        self.assertFalse(sovereign_conversion({"brain_thesis": None})[0])

    def test_non_directional_or_no_opportunity_fails(self):
        self.assertFalse(sovereign_conversion(
            {"brain_thesis": _thesis(direction="neutral")})[0])
        self.assertFalse(sovereign_conversion(
            {"brain_thesis": _thesis(opportunity=False)})[0])

    def test_hedge_tokens_are_not_conversions(self):
        # the recorded 11:14 shape: families all "none"/"confirmation_required"
        ok, detail = sovereign_conversion({"brain_thesis": _thesis(
            playbook_family="none", tool_family=["none"])})
        self.assertFalse(ok, detail)
        ok, _ = sovereign_conversion({"brain_thesis": _thesis(
            playbook_family=None, tool_family=["confirmation_required"])})
        self.assertFalse(ok)

    def test_tool_family_alone_converts(self):
        ok, _ = sovereign_conversion({"brain_thesis": _thesis(
            playbook_family="none", tool_family=["fvg"])})
        self.assertTrue(ok)

    def test_ab7_stabilized_source_resolves_via_candidate(self):
        stabilized = _thesis(source="ab7_active_thesis")
        snap = {"brain_thesis": stabilized,
                "candidate_thesis": _thesis(source="llm")}
        self.assertTrue(sovereign_conversion(snap)[0])
        snap["candidate_thesis"] = _thesis(source="llm_failed_fallback")
        self.assertFalse(sovereign_conversion(snap)[0])


class TestReplay1059(unittest.TestCase):
    """The flagship kill: Brain conversion must now survive qualification."""

    def test_conversion_survives_with_witness_warning(self):
        out = qualify_trade(_snap_1059(_thesis()))
        self.assertTrue(out["brain_sovereign"])
        self.assertEqual(out["direction"], "bullish")
        self.assertEqual(out["status"], "candidate")
        self.assertTrue(out["brain_conversion_floor_applied"])
        # mechanical verdict stays recorded honestly (score ~41 -> watchlist)
        self.assertIn(out["mechanical_status"], ("watchlist", "no_trade"))
        # the opportunity score is NEVER fabricated
        self.assertLess(out["opportunity_score"], 55)
        self.assertTrue(any("AI-AUTH-2" in w and "demoted to witness" in w
                            for w in out["warnings"]))
        self.assertTrue(any("floored at candidate" in w
                            for w in out["warnings"]))

    def test_quota_fallback_restores_legacy_exactly(self):
        """Same geometry, Brain dead (429 insufficient_quota) -> today's
        afternoon behavior byte-identical."""
        out = qualify_trade(_snap_1059(_thesis(source="llm_failed_fallback")))
        self.assertFalse(out["brain_sovereign"])
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)
        self.assertEqual(out["grade"], "F")
        self.assertFalse(out["brain_conversion_floor_applied"])

    def test_contaminated_input_restores_legacy(self):
        out = qualify_trade(_snap_1059(_thesis(source="contaminated_input")))
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)

    def test_ecu_off_restores_legacy(self):
        out = qualify_trade(_snap_1059(None))
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)


class TestReplay1114(unittest.TestCase):
    def test_as_recorded_no_family_stays_legacy(self):
        """11:14:26 as it actually happened: bullish conf 85 but families all
        'none' — the Brain never converted. Sovereignty must NOT manufacture
        a conversion the Brain didn't make."""
        out = qualify_trade(_snap_1059(_thesis(
            confidence=85, playbook_family="none", tool_family=["none"])))
        self.assertFalse(out["brain_sovereign"])
        self.assertEqual(out["status"], "no_trade")
        self.assertEqual(out["opportunity_score"], 0)

    def test_mission_premise_converted_shape_survives(self):
        """The same 11:14 read, had the Brain emitted its family: survives."""
        out = qualify_trade(_snap_1059(_thesis(confidence=85)))
        self.assertEqual(out["status"], "candidate")
        self.assertTrue(out["brain_conversion_floor_applied"])


class TestSafetyBoundaries(unittest.TestCase):
    def test_environment_danger_keeps_full_authority(self):
        """Sovereign Brain + hostile environment -> still disqualified.
        Sovereignty transfers OPPORTUNITY authority, never SAFETY authority."""
        for narrative in ("conflicted", "exhaustion_risk", "compression"):
            snap = _snap_1059(_thesis())
            snap["ai_context"]["market_narrative"] = narrative
            out = qualify_trade(snap)
            self.assertEqual(out["status"], "no_trade", narrative)
            self.assertEqual(out["opportunity_score"], 0, narrative)
            self.assertFalse(out["brain_conversion_floor_applied"], narrative)

    def test_multi_tf_toxicity_keeps_full_authority(self):
        snap = _snap_1059(_thesis())
        snap["volatility"] = {"15m": {"state": "toxic"},
                              "5m":  {"state": "explosive"}}
        out = qualify_trade(snap)
        self.assertEqual(out["status"], "no_trade")

    def test_floor_only_raises_never_lowers(self):
        """Mechanically elite + sovereign -> elite unchanged, floor unused."""
        snap = _snap_1059(_thesis(direction="bearish"))
        snap["ai_context"].update({
            "market_narrative": "liquidity_sweep_reversal",
            "confidence_tier": "elite_setup", "confidence_score": 97,
        })
        snap["po3"] = {"alignment": "full_distribution_alignment"}
        snap["structure"] = {"alignment": "full"}
        snap["liquidity"] = {"5m": {"sweep_detected": True,
                                    "reclaim_detected": True}}
        out = qualify_trade(snap)
        self.assertIn(out["status"], ("elite", "qualified"))
        self.assertFalse(out["brain_conversion_floor_applied"])

    def test_direction_contradiction_never_floors(self):
        from qualification.trade_qualification_engine import (
            _apply_brain_conversion_floor)
        status, applied = _apply_brain_conversion_floor(
            "no_trade", "bearish", False, _thesis(direction="bullish"), True)
        self.assertEqual(status, "no_trade")
        self.assertFalse(applied)


class TestRiskGovernorDemotion(unittest.TestCase):
    def _risk_snap(self, brain_thesis, qual_status="candidate"):
        snap = _snap_1059(brain_thesis)
        snap["qualification"] = {"status": qual_status, "grade": "C",
                                 "warnings": []}
        snap["playbook"] = {"status": "valid", "selected_playbook":
                            "trend_continuation", "warnings": []}
        snap["session"] = "morning_continuation"
        return snap

    def test_sovereign_demotes_duplicated_tier_block(self):
        out = evaluate_risk(self._risk_snap(_thesis()))
        self.assertFalse(any("confidence tier is no_trade" in b
                             for b in out["blocks"]), out["blocks"])
        self.assertTrue(any("witness only" in r for r in out["restrictions"]))
        self.assertTrue(out["trade_allowed"], out)
        # floored candidate stays capped at MINIMAL risk tier (0.5x) — the
        # defensive ceiling is untouched
        self.assertEqual(out["risk_tier"], "minimal")
        self.assertEqual(out["risk_multiplier"], 0.5)

    def test_fallback_keeps_hard_block(self):
        out = evaluate_risk(
            self._risk_snap(_thesis(source="llm_failed_fallback")))
        self.assertTrue(any("confidence tier is no_trade" in b
                            for b in out["blocks"]))
        self.assertFalse(out["trade_allowed"])

    def test_qualification_no_trade_still_blocks(self):
        """Sovereignty does not bypass a no_trade qualification at risk."""
        out = evaluate_risk(self._risk_snap(_thesis(),
                                            qual_status="no_trade"))
        self.assertFalse(out["trade_allowed"])


class TestAuthoritiesUntouched(unittest.TestCase):
    def test_untouched_files_have_no_sovereignty_logic(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for pkg, fname in (
                ("paper_execution", "order_builder.py"),      # FC-0B
                ("shared_context",  "council.py"),
                ("toolbox",         "price_levels.py"),       # RELATION-TRUTH
                ("adaptive_learning", "suppression_cost_engine.py"),
                ("adaptive_learning", "capital_intelligence_engine.py"),
                ("market_data",     "htf_memory_engine.py"),
                ("ai_layer",        "confidence_engine.py"),  # scorer untouched
        ):
            path = os.path.join(src, pkg, fname)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("sovereign_conversion", body, f"{pkg}/{fname}")
            self.assertNotIn("AI-AUTH-2", body, f"{pkg}/{fname}")


if __name__ == "__main__":
    unittest.main()

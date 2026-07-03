"""
MARKET COMMANDER — Layer 1 (Environment Intelligence) + Layer 2 (Participation Governor).

Proves the adjudication architecture:
  * domain isolation (account-blind, setup-blind)
  * witness qualification + evidence completeness (missing → lower completeness)
  * confidence bounded by completeness; a lone witness cannot overconfide
  * hard guardian vetoes (NEWS_CHAOS / LIQUIDITY_VACUUM / DEAD_MARKET) un-outvotable
  * environment FAMILIES with family-first resolution (no sibling cannibalisation)
  * conflict intelligence (close families → high conflict → confidence cap)
  * cognitive override record (agree / override / unclear)
  * four-gate Participation Governor (Environment, Confidence, Completeness, Conflict)
  * qualification may downgrade PARTICIPATE, never upgrade
  * authority stays observe_only; L3/L4 do not exist.
"""
import copy
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_commander.market_commander import (  # noqa: E402
    build_market_commander_matrix, validate_market_commander_matrix,
    format_market_commander_summary, SOURCE_AI, SOURCE_DETERMINISTIC,
    ENVIRONMENT_TYPES, PARTICIPATION_DECISIONS, FINAL_STATES, FAMILIES,
    FAM_DIRECTIONAL, FAM_ROTATIONAL, FAM_INERT, FAM_HOSTILE, FAM_UNKNOWN,
    MEMBER_TO_FAMILY, CONF_PARTICIPATE, COMPLETENESS_PARTICIPATE, CONFLICT_MAX,
    OVERRIDE_AGREES, OVERRIDE_ACTIVE,
)
from ai_brain.brain_prompt import MARKET_COMMANDER_ADDENDUM  # noqa: E402


def _gate(part, name):
    return next(g for g in part["gates"] if g["name"] == name)


def _expansion(state="healthy_expansion", gated=False, deff=0.7, bdom=0.64, escore=72):
    return {"5m": {"state": state, "magnitude_gated": gated, "directional_efficiency": deff,
                   "body_dominance": bdom, "expansion_score": escore},
            "1m": {"state": state, "magnitude_gated": gated, "directional_efficiency": deff - 0.04,
                   "body_dominance": bdom - 0.04, "expansion_score": escore - 4}}


def rich_directional(regime="expansion_up", qual="qualified", **over):
    """A fully-evidenced DIRECTIONAL world that passes all four participation gates."""
    s = {
        "market_regime": {"regime_label": regime, "confidence": 84,
                          "volatility_state": "stable", "expansion_state": "healthy_expansion"},
        "expansion": _expansion(),
        "shared_context": {"delivery_state": "bullish_delivery", "continuation_intact": True,
                           "exhaustion_present": False, "delivery_confidence": 0.8},
        "structure": {"5m": {"state": "bullish_continuation"},
                      "1m": {"state": "bullish_continuation"}, "alignment": "bullish"},
        "liquidity": {"5m": {"sweep_detected": False, "reclaim_detected": False}},
        "narrative_authority": {"narrative_phase": "continuation", "active_liquidity_draw": "sell_side"},
        "po3": {"alignment": "full_distribution_alignment"},
        "confidence_fusion": {"fusion_status": "aligned", "combined_confidence": 78},
        "session": "ny_am",
        "qualification": {"status": qual, "opportunity_score": 80},
        "thesis_state": {"status": "FORMING"},
    }
    s.update(over)
    return s


def rich_rotational(regime="trend_up", **over):
    """Overlap / compression / failed-continuation / two-sided liquidity world."""
    s = {
        "market_regime": {"regime_label": regime, "confidence": 84,
                          "volatility_state": "stable", "expansion_state": "compression"},
        "expansion": _expansion("compression", gated=True, deff=0.18, bdom=0.29, escore=24),
        "shared_context": {"delivery_state": "unknown", "continuation_intact": False},
        "structure": {"5m": {"state": "range_bound"}, "1m": {"state": "range_bound"},
                      "alignment": "neutral"},
        "liquidity": {"5m": {"nearest_buy_side_liquidity": 1, "nearest_sell_side_liquidity": 1,
                             "sweep_detected": False}},
        "po3": {"alignment": "no_clear"},
        "narrative_authority": {"narrative_phase": "transition"},
        "qualification": {"status": "watchlist", "opportunity_score": 0},
        "thesis_state": {"status": "FORMING"},
    }
    s.update(over)
    return s


def conflicted(**over):
    """DIRECTIONAL and ROTATIONAL evidence in a near tie → high conflict."""
    s = {
        "market_regime": {"regime_label": "range_rotation", "confidence": 70,
                          "volatility_state": "stable", "expansion_state": "healthy_expansion"},
        "expansion": _expansion("healthy_expansion", gated=False, deff=0.62, bdom=0.56, escore=62),
        "shared_context": {"delivery_state": "unknown", "continuation_intact": False},
        "structure": {"5m": {"state": "range_bound"}, "1m": {"state": "bullish_continuation"},
                      "alignment": "neutral"},
        "liquidity": {"5m": {"nearest_buy_side_liquidity": 1, "nearest_sell_side_liquidity": 1}},
        "po3": {"alignment": "full_distribution_alignment"},
        "narrative_authority": {"narrative_phase": "continuation"},
        "qualification": {"status": "qualified", "opportunity_score": 70},
        "thesis_state": {"status": "FORMING"},
    }
    s.update(over)
    return s


class _McMode(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("MARKET_COMMANDER_MODE")
        os.environ["MARKET_COMMANDER_MODE"] = "true"

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("MARKET_COMMANDER_MODE", None)
        else:
            os.environ["MARKET_COMMANDER_MODE"] = self._prev


# ── Prompt doctrine ────────────────────────────────────────────────────────────
class TestPrompt(unittest.TestCase):
    def test_asks_environment_first(self):
        a = MARKET_COMMANDER_ADDENDUM
        self.assertIn("What market am I trading in?", a)
        self.assertLess(a.index("L1 ENVIRONMENT"), a.index("L2 PARTICIPATION"))

    def test_asks_participation_second(self):
        a = MARKET_COMMANDER_ADDENDUM
        self.assertIn("Does this market deserve capital?", a)
        self.assertLess(a.index("What market am I trading in?"),
                        a.index("Does this market deserve capital?"))

    def test_forbids_hunting_and_demands_multi_evidence(self):
        u = MARKET_COMMANDER_ADDENDUM.upper()
        self.assertIn("STAND_DOWN YOU MUST STOP", u)
        self.assertIn("DO NOT HUNT FOR A PLAYBOOK", u)
        self.assertIn("DO NOT PROMOTE A THESIS TO EXECUTABLE", u)
        self.assertIn("environment_scorecard", MARKET_COMMANDER_ADDENDUM)
        self.assertIn("at least THREE", MARKET_COMMANDER_ADDENDUM)
        self.assertIn("label-copier", MARKET_COMMANDER_ADDENDUM)


# ── Layer 1: evidence interpreter ──────────────────────────────────────────────
class TestLayer1Intelligence(unittest.TestCase):
    def test_01_sparse_single_regime_cannot_overconfide(self):
        m = build_market_commander_matrix({"market_regime": {"regime_label": "trend_up",
                                                             "confidence": 84}})
        e = m["environment"]
        self.assertLess(e["confidence"], 50)           # not loud-and-confident
        self.assertLessEqual(e["confidence"], e["completeness"])

    def test_02_confidence_never_exceeds_completeness(self):
        for s in (rich_directional(), rich_rotational(), conflicted(),
                  {"market_regime": {"regime_label": "trend_up"}}, {}):
            e = build_market_commander_matrix(s)["environment"]
            self.assertLessEqual(e["confidence"], e["completeness"],
                                 f"{e['type']} conf {e['confidence']} > complete {e['completeness']}")

    def test_04_news_chaos_cannot_be_outvoted(self):
        m = build_market_commander_matrix(rich_directional(
            news_context={"risk_state": "high_risk"}))
        self.assertEqual(m["environment"]["family"], FAM_HOSTILE)
        self.assertEqual(m["environment"]["type"], "NEWS_CHAOS")
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")

    def test_05_liquidity_vacuum_cannot_be_outvoted(self):
        m = build_market_commander_matrix(rich_directional(
            market_regime={"regime_label": "liquidity_vacuum", "confidence": 84,
                           "volatility_state": "stable", "expansion_state": "healthy_expansion"}))
        self.assertEqual(m["environment"]["family"], FAM_HOSTILE)
        self.assertEqual(m["environment"]["type"], "LIQUIDITY_VACUUM")
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")

    def test_06_family_first_prevents_sibling_cannibalisation(self):
        # Strong directional evidence under a trend regime stays DIRECTIONAL — the
        # EXPANSION/TREND/MATURE siblings pool evidence instead of splitting it.
        e = build_market_commander_matrix(rich_directional("trend_up"))["environment"]
        self.assertEqual(e["family"], FAM_DIRECTIONAL)
        self.assertIn(e["type"], MEMBER_TO_FAMILY)
        self.assertEqual(MEMBER_TO_FAMILY[e["type"]], FAM_DIRECTIONAL)

    def test_07_trend_plus_confirming_resolves_directional_and_agrees(self):
        e = build_market_commander_matrix(rich_directional("trend_up"))["environment"]
        self.assertEqual(e["family"], FAM_DIRECTIONAL)
        self.assertTrue(e["agrees_with_mechanical_regime"])
        self.assertEqual(e["commander_vs_regime_status"], OVERRIDE_AGREES)

    def test_08_trend_plus_overlap_resolves_rotational_override_active(self):
        e = build_market_commander_matrix(rich_rotational("trend_up"))["environment"]
        self.assertEqual(e["family"], FAM_ROTATIONAL)
        self.assertFalse(e["agrees_with_mechanical_regime"])
        self.assertEqual(e["commander_vs_regime_status"], OVERRIDE_ACTIVE)
        self.assertIsNotNone(e["disagreement_reason"])

    def test_09_range_plus_displacement_resolves_directional_override_active(self):
        e = build_market_commander_matrix(rich_directional("range_rotation"))["environment"]
        self.assertEqual(e["family"], FAM_DIRECTIONAL)
        self.assertFalse(e["agrees_with_mechanical_regime"])
        self.assertEqual(e["commander_vs_regime_status"], OVERRIDE_ACTIVE)

    def test_10_conflict_rises_when_families_close(self):
        low = build_market_commander_matrix(rich_directional())["environment"]["conflict_index"]
        high = build_market_commander_matrix(conflicted())["environment"]["conflict_index"]
        self.assertLess(low, 20)
        self.assertGreater(high, CONFLICT_MAX)

    def test_11_high_conflict_caps_confidence(self):
        clean = build_market_commander_matrix(rich_directional())["environment"]
        warred = build_market_commander_matrix(conflicted())["environment"]
        self.assertLess(warred["confidence"], clean["confidence"])

    def test_12_missing_witnesses_lower_completeness(self):
        rich = build_market_commander_matrix(rich_directional())["environment"]
        sparse = build_market_commander_matrix(
            {"market_regime": {"regime_label": "trend_up", "confidence": 84}})["environment"]
        self.assertGreater(rich["completeness"], sparse["completeness"])
        self.assertTrue(sparse["witnesses_missing"])  # listed, not silently dropped

    def test_explainability_record_complete(self):
        e = build_market_commander_matrix(rich_directional())["environment"]
        for k in ("witnesses_called", "witnesses_missing", "supporting_evidence",
                  "contradicting_evidence", "family_scorecard", "member_scorecard",
                  "confidence_breakdown", "completeness", "conflict_index",
                  "counterfactual_flip_condition"):
            self.assertIn(k, e)
        self.assertTrue(e["counterfactual_flip_condition"])


# ── DEAD_MARKET guardian: corroboration required ───────────────────────────────
class TestDeadMarketGuardian(unittest.TestCase):
    def test_1_single_dead_label_does_not_force_dead(self):
        m = build_market_commander_matrix({"market_regime": {"regime_label": "low_volatility",
                                                             "confidence": 84}})
        self.assertNotEqual(m["environment"]["family"], FAM_INERT)
        self.assertNotEqual(m["participation"]["decision"], "STAND_DOWN")
        self.assertEqual(m["environment"]["dead_market_status"], "SUSPECTED")

    def test_2_dead_label_plus_no_expansion_confirms_dead(self):
        m = build_market_commander_matrix({
            "market_regime": {"regime_label": "low_volatility", "confidence": 84,
                              "volatility_state": "low_volatility", "expansion_state": "compression"}})
        self.assertEqual(m["environment"]["family"], FAM_INERT)
        self.assertEqual(m["environment"]["type"], "DEAD_MARKET")
        self.assertEqual(m["environment"]["dead_market_status"], "CONFIRMED")
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")

    def test_3_dead_label_plus_strong_expansion_does_not_force_dead(self):
        m = build_market_commander_matrix(rich_directional(
            regime="low_volatility",
            market_regime={"regime_label": "low_volatility", "confidence": 84,
                           "volatility_state": "low_volatility", "expansion_state": "healthy_expansion"}))
        self.assertNotEqual(m["environment"]["family"], FAM_INERT)
        self.assertNotEqual(m["environment"]["type"], "DEAD_MARKET")
        self.assertEqual(m["environment"]["dead_market_status"], "SUSPECTED")

    def test_4_confirmed_dead_cannot_be_outvoted(self):
        # two supports (dead volatility + inactive session) confirm DEAD even with a
        # full directional expansion stack present in the scorecard.
        m = build_market_commander_matrix(rich_directional(
            market_regime={"regime_label": "low_volatility", "confidence": 84,
                           "volatility_state": "low_volatility", "expansion_state": "healthy_expansion"},
            session="lunch"))
        e = m["environment"]
        self.assertEqual(e["family"], FAM_INERT)
        self.assertEqual(e["type"], "DEAD_MARKET")
        self.assertGreater(e["family_scorecard"].get(FAM_DIRECTIONAL, 0), 0)  # was present…
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")        # …but still vetoed

    def test_5_suspected_state_visible_in_telemetry(self):
        e = build_market_commander_matrix(rich_directional(
            market_regime={"regime_label": "low_volatility", "confidence": 84,
                           "volatility_state": "low_volatility", "expansion_state": "healthy_expansion"}))["environment"]
        self.assertEqual(e["dead_market_status"], "SUSPECTED")
        self.assertTrue(e["guardian_confirmations"])

    def test_6_confirmed_veto_explains_supporting_witnesses(self):
        e = build_market_commander_matrix({
            "market_regime": {"regime_label": "low_volatility", "confidence": 84,
                              "volatility_state": "low_volatility", "expansion_state": "compression"}})["environment"]
        self.assertEqual(e["dead_market_status"], "CONFIRMED")
        self.assertGreaterEqual(len(e["guardian_confirmations"]), 2)
        self.assertIn("guardian_supports", e["confidence_breakdown"])


# ── Domain isolation ───────────────────────────────────────────────────────────
class TestDomainIsolation(unittest.TestCase):
    def test_layer1_is_account_and_setup_blind(self):
        base = rich_directional("range_rotation")
        contaminated = copy.deepcopy(base)
        contaminated.update({
            "qualification": {"status": "elite", "opportunity_score": 100},
            "risk": {"trade_allowed": False}, "pnl": -9999,
            "execution_gate": {"allow_execution": True},
            "position": {"size": 50}, "playbook": "judas_swing",
        })
        a = build_market_commander_matrix(base)["environment"]
        b = build_market_commander_matrix(contaminated)["environment"]
        for k in ("family", "type", "confidence", "completeness", "conflict_index"):
            self.assertEqual(a[k], b[k], f"L1 leaked account/setup state via {k}")


# ── Layer 2: four-gate Participation Governor ──────────────────────────────────
class TestLayer2Governor(unittest.TestCase):
    def test_13_layer2_consumes_layer1_verdict_only(self):
        m = build_market_commander_matrix(rich_directional())
        e, p = m["environment"], m["participation"]
        self.assertEqual(p["consumed_environment_family"], e["family"])
        self.assertEqual(p["consumed_environment_type"], e["type"])
        self.assertEqual(p["consumed_environment_confidence"], e["confidence"])
        self.assertEqual(p["consumed_conflict_index"], e["conflict_index"])
        self.assertEqual(p["consumed_completeness"], e["completeness"])
        self.assertEqual(len(p["gates"]), 4)

    def test_directional_all_gates_pass_participates(self):
        m = build_market_commander_matrix(rich_directional())
        self.assertEqual(m["environment"]["family"], FAM_DIRECTIONAL)
        self.assertEqual(m["participation"]["decision"], "PARTICIPATE")
        self.assertEqual(m["final_state"], "COMMAND_PARTICIPATE")

    def test_14_cannot_participate_on_low_confidence(self):
        m = build_market_commander_matrix(conflicted())
        self.assertLess(m["environment"]["confidence"], CONF_PARTICIPATE)
        self.assertFalse(_gate(m["participation"], "confidence")["passed"])
        self.assertNotEqual(m["participation"]["decision"], "PARTICIPATE")

    def test_15_cannot_participate_on_high_conflict(self):
        m = build_market_commander_matrix(conflicted())
        self.assertGreater(m["environment"]["conflict_index"], CONFLICT_MAX)
        self.assertFalse(_gate(m["participation"], "conflict")["passed"])
        self.assertNotEqual(m["participation"]["decision"], "PARTICIPATE")

    def test_16_cannot_participate_on_low_completeness(self):
        # DIRECTIONAL but starved of evidence → completeness gate blocks.
        s = {"market_regime": {"regime_label": "trend_up", "confidence": 84,
                               "volatility_state": "stable", "expansion_state": "healthy_expansion"},
             "expansion": _expansion(), "qualification": {"status": "qualified"}}
        m = build_market_commander_matrix(s)
        self.assertEqual(m["environment"]["family"], FAM_DIRECTIONAL)
        self.assertLess(m["environment"]["completeness"], COMPLETENESS_PARTICIPATE)
        self.assertFalse(_gate(m["participation"], "completeness")["passed"])
        self.assertNotEqual(m["participation"]["decision"], "PARTICIPATE")

    def test_17_qualification_downgrades_but_never_upgrades(self):
        # downgrade: same DIRECTIONAL world, qualification not trade-ready → OBSERVE
        part = build_market_commander_matrix(rich_directional(qual="qualified"))["participation"]
        self.assertEqual(part["decision"], "PARTICIPATE")
        downgraded = build_market_commander_matrix(rich_directional(qual="no_trade"))["participation"]
        self.assertEqual(downgraded["decision"], "OBSERVE")
        self.assertIn("qualification_downgrade", downgraded["blockers"])
        # cannot upgrade: a ROTATIONAL world with elite qualification stays OBSERVE
        rot = build_market_commander_matrix(rich_rotational(
            qualification={"status": "elite", "opportunity_score": 100}))
        self.assertEqual(rot["environment"]["family"], FAM_ROTATIONAL)
        self.assertEqual(rot["participation"]["decision"], "OBSERVE")

    def test_unknown_low_completeness_stands_down(self):
        m = build_market_commander_matrix({})
        self.assertEqual(m["environment"]["family"], FAM_UNKNOWN)
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")

    def test_stand_down_flags_executable_thesis(self):
        m = build_market_commander_matrix(rich_directional(
            news_context={"risk_state": "high_risk"},
            thesis_state={"thesis_status": "EXECUTABLE"}))
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")
        self.assertFalse(m["consistency"]["logical_state_valid"])
        self.assertIn("STAND_DOWN_WITH_EXECUTABLE_THESIS", m["consistency"]["contradictions"])


# ── Observe-only / scope / no behaviour change ─────────────────────────────────
class TestScopeAndSafety(unittest.TestCase):
    def test_18_always_observe_only_and_valid(self):
        for s in (rich_directional(), rich_rotational(), conflicted(), {}):
            m = build_market_commander_matrix(s)
            self.assertEqual(m["authority_level"], "observe_only")
            ok, errs = validate_market_commander_matrix(m)
            self.assertTrue(ok, errs)
            self.assertIn(m["final_state"], FINAL_STATES)
            self.assertIn(m["environment"]["family"], FAMILIES)

    def test_19_no_snapshot_mutation(self):
        s = rich_directional()
        before = copy.deepcopy(s)
        build_market_commander_matrix(s)
        self.assertEqual(s, before)

    def test_no_layer3_or_layer4(self):
        m = build_market_commander_matrix(rich_directional())
        for k in ("layer3_opportunity", "layer4_execution", "opportunity", "execution"):
            self.assertNotIn(k, m)

    def test_formatter_lines(self):
        joined = "\n".join(format_market_commander_summary(
            build_market_commander_matrix(rich_rotational("trend_up"))))
        self.assertIn("MC Environment", joined)
        self.assertIn("MC Participation", joined)
        self.assertIn("MC L1/L2 State", joined)
        self.assertIn("OBSERVE_ONLY", joined)
        self.assertIn("gates[", joined)


# ── AI-authored L1 (gated); governor stays deterministic ───────────────────────
class TestAiAuthored(_McMode):
    def _ai(self, env_type, decision, conf=70, evidence=None):
        return {"environment": {"type": env_type, "confidence": conf,
                                "evidence": evidence or ["regime", "expansion", "delivery"]},
                "participation": {"decision": decision}}

    def test_valid_ai_environment_adopted(self):
        m = build_market_commander_matrix(rich_directional(
            ai_market_commander=self._ai("EXPANSION_TREND", "PARTICIPATE")))
        self.assertEqual(m["source"], SOURCE_AI)
        self.assertEqual(m["environment"]["type"], "EXPANSION_TREND")
        self.assertEqual(m["environment"]["family"], FAM_DIRECTIONAL)

    def test_ai_confidence_still_capped_by_completeness(self):
        m = build_market_commander_matrix({
            "market_regime": {"regime_label": "trend_up", "confidence": 80},
            "ai_market_commander": self._ai("EXPANSION_TREND", "PARTICIPATE", conf=99)})
        e = m["environment"]
        self.assertLessEqual(e["confidence"], e["completeness"])

    def test_ai_hostile_coerced_stand_down(self):
        m = build_market_commander_matrix(rich_directional(
            news_context={"risk_state": "high_risk"},
            ai_market_commander=self._ai("NEWS_CHAOS", "PARTICIPATE")))
        self.assertEqual(m["participation"]["decision"], "STAND_DOWN")
        self.assertIn("FORCED_STAND_DOWN_NEWS_CHAOS", m["consistency"]["contradictions"])

    def test_invalid_ai_falls_back(self):
        m = build_market_commander_matrix(rich_directional(
            ai_market_commander={"environment": {"type": "BOGUS"}}))
        self.assertEqual(m["source"], SOURCE_DETERMINISTIC)

    def test_default_off_ignores_ai(self):
        os.environ.pop("MARKET_COMMANDER_MODE", None)
        m = build_market_commander_matrix(rich_directional(
            ai_market_commander=self._ai("EXPANSION_TREND", "PARTICIPATE")))
        self.assertEqual(m["source"], SOURCE_DETERMINISTIC)


if __name__ == "__main__":
    unittest.main(verbosity=2)

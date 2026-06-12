"""
Phase NA-1 — Narrative Authority tests (the ten required June 11 replays).

T1  10:00 buy-side raid creates a protected high
T2  10:05-10:20 bearish response confirms bearish delivery -> bearish narrative
T3  10:20 retracement into the bearish OB is not bullish continuation
T4  AI bearish manipulation vs structure bullish -> conflicted/bearish, never bullish
T5  the June 11 long is blocked under narrative enforcement
T6  the ~11:00 strong low becomes a protected low
T7  the 13:17 short into the protected low is blocked/conflicted
T8  structure-only bias cannot override AI+Delivery agreement
T9  all narrative authority flags roll back to legacy behavior
T10 full regression (run the whole suite — this file only asserts its own)

June 11 values are taken from the archived snapshots, the governance ledger
context digests, and the narrative-transition audit (10:00:49 above_high@15m
sweep; bearish PO3 manipulation direction; AI 'bearish manipulation phase
despite bullish bias'; 11:04:54 below_low@15m sweep).
"""
import json
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from narrative_authority.protected_swings import ProtectedSwingTracker
from narrative_authority.narrative_engine import build_narrative, narrative_permits
from narrative_authority.liquidity_objectives import compute_liquidity_draw
from shared_context.council import run_council
from execution_gate.execution_gate import evaluate_gate

_REPO = os.path.join(os.path.dirname(__file__), "..")
_JUNE11_SNAPSHOT = os.path.join(_REPO, "data", "live_snapshots",
                                "20260611_102955_QQQ.json")

_NA_ENVS = ("NARRATIVE_AUTHORITY", "NARRATIVE_AI_MIN_CONF",
            "NARRATIVE_DELIVERY_MIN_CONF", "NARRATIVE_PROTECTED_ZONE_PCT",
            "NARRATIVE_PROTECTED_BUFFER_PCT")


def _clear():
    for k in _NA_ENVS + ("COUNCIL_AUTHORITY", "RULE_GOVERNANCE_MODE",
                         "EXECUTION_ENABLED"):
        os.environ.pop(k, None)


def _sweep_snapshot(direction="above_high", tf="15m", level=702.50,
                    price=701.40, ts="20260611T100049"):
    """June 11 10:00-style raid scan: sweep + reclaim on the 15m."""
    swing_key = "last_swing_high" if direction == "above_high" else "last_swing_low"
    return {
        "timestamp": ts,
        "liquidity": {
            tf: {"sweep_detected": True, "sweep_direction": direction,
                 "reclaim_detected": True,
                 "nearest_buy_side_liquidity": 703.10,
                 "nearest_sell_side_liquidity": 699.60},
        },
        "structure": {tf: {swing_key: level}},
        "timeframes": {"1m": {"last_candle": {"close": price}}},
    }


def _june11_1029_snapshot(swings):
    """
    The entry-scan evidence, as the live system saw it:
      AI bullish@65 (gpt-4o-mini flipped bullish on the entry scan),
      Delivery bearish (PO3 15m manipulation_direction=bearish, conf 25),
      Structure bias bullish (raid-made higher highs).
    """
    return {
        "timestamp": "20260611T102955",
        "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 65},
        "shared_context": {"delivery_state": "bearish_delivery",
                           "delivery_confidence": 25,
                           "exhaustion_present": True},
        "po3": {"15m": {"phase": "manipulation",
                        "manipulation_direction": "bearish"},
                "alignment": "mixed"},
        "ai_context": {"directional_bias": "bullish", "confidence_score": 65},
        "liquidity": {"15m": {"sweep_detected": True,
                              "sweep_direction": "above_high",
                              "reclaim_detected": True,
                              "nearest_sell_side_liquidity": 699.60}},
        "structure": {"15m": {"last_swing_high": 702.50}},
        "timeframes": {"1m": {"last_candle": {"close": 701.42}}},
        "protected_swings": swings,
    }


class T1_ProtectedHighFromBuySideRaid(unittest.TestCase):

    def test_raid_registers_protected_high(self):
        tracker = ProtectedSwingTracker()
        state = tracker.update(_sweep_snapshot())
        self.assertIsNotNone(state["protected_high"])
        self.assertEqual(state["protected_high"]["level"], 702.50)
        self.assertEqual(state["protected_high"]["basis"], "buy_side_raid_rejected")
        self.assertEqual(state["protected_high"]["timeframe"], "15m")

    def test_protected_high_persists_after_sweep_evidence_fades(self):
        """June 11 flaw: the liquidity engine forgot the sweep one scan
        later. The tracker must not."""
        tracker = ProtectedSwingTracker()
        tracker.update(_sweep_snapshot())
        state = tracker.update({   # next scan: no sweep visible
            "timestamp": "20260611T100149",
            "liquidity": {}, "structure": {},
            "timeframes": {"1m": {"last_candle": {"close": 701.10}}},
        })
        self.assertIsNotNone(state["protected_high"])

    def test_close_above_violates_protected_high(self):
        tracker = ProtectedSwingTracker()
        tracker.update(_sweep_snapshot())
        state = tracker.update({
            "timestamp": "20260611T110049",
            "liquidity": {}, "structure": {},
            "timeframes": {"1m": {"last_candle": {"close": 703.20}}},
        })
        self.assertIsNone(state["protected_high"])


class T2_BearishResponseConfirmsBearishDelivery(unittest.TestCase):
    """10:05-10:20: AI bearish + PO3 bearish manipulation -> bearish story."""

    def tearDown(self):
        _clear()

    def test_ai_plus_delivery_bearish_yields_bearish_narrative(self):
        snap = _june11_1029_snapshot({})
        snap["ai_discretionary"] = {"ai_direction": "bearish", "ai_confidence": 60}
        na = build_narrative(snap, {})
        self.assertEqual(na["narrative_direction"], "bearish")
        self.assertIn("structure_overruled", na["conflict_flags"])
        self.assertEqual(na["forbidden_trade_direction"], "bullish")
        self.assertEqual(na["narrative_phase"], "exhaustion")  # exhaustion_present


class T3_RetracementIntoBearishOBNotBullish(unittest.TestCase):
    """10:20: price inside the protected-high zone with bearish delivery —
    a long is not a continuation opportunity."""

    def tearDown(self):
        _clear()

    def test_long_inside_protected_zone_is_forbidden(self):
        tracker = ProtectedSwingTracker()
        swings = tracker.update(_sweep_snapshot())          # PH @ 702.50
        snap = _june11_1029_snapshot(swings)
        snap["timeframes"] = {"1m": {"last_candle": {"close": 701.40}}}
        # 702.50 - 701.40 = 1.10 -> within the 0.3% zone (~2.10)
        na = build_narrative(snap, swings)
        self.assertEqual(na["forbidden_trade_direction"], "bullish")
        warning_text = " ".join(na["warnings"])
        self.assertIn("protected-high zone", warning_text)


class T4_AIBearishVsStructureBullish(unittest.TestCase):
    """'Bearish manipulation phase despite bullish bias' must never
    resolve bullish."""

    def tearDown(self):
        _clear()

    def test_single_wide_lens_vs_structure_is_conflicted(self):
        snap = _june11_1029_snapshot({})
        snap["ai_discretionary"] = {"ai_direction": "bearish", "ai_confidence": 60}
        snap["po3"] = {}    # delivery silent -> AI alone vs structure
        snap["shared_context"] = {"delivery_state": "mixed",
                                  "delivery_confidence": 10}
        na = build_narrative(snap, {})
        self.assertIn(na["narrative_direction"], ("conflicted", "bearish"))
        self.assertNotEqual(na["narrative_direction"], "bullish")
        self.assertFalse(na["trade_allowed"])
        self.assertIn("wide_lens_vs_structure", na["conflict_flags"])


class T5_June11LongBlocked(unittest.TestCase):
    """The entry-scan evidence (AI bullish@65 vs Delivery bearish@25) is an
    AI/Delivery disagreement — conflicted, no trade. Structure may not
    break the tie. The real archived gate snapshot must block."""

    def setUp(self):
        os.environ["EXECUTION_ENABLED"] = "true"
        os.environ["NARRATIVE_AUTHORITY"] = "enforce"

    def tearDown(self):
        _clear()

    def test_narrative_is_conflicted_at_entry_scan(self):
        na = build_narrative(_june11_1029_snapshot({}), {})
        self.assertEqual(na["narrative_direction"], "conflicted")
        self.assertFalse(na["trade_allowed"])
        self.assertIn("ai_delivery_disagreement", na["conflict_flags"])

    def test_gate_blocks_the_june11_long(self):
        with open(_JUNE11_SNAPSHOT, encoding="utf-8") as fh:
            snapshot = json.load(fh)
        for cand in snapshot["toolbox"]["tool_candidates"]:
            if cand.get("tool") == snapshot["toolbox"]["preferred_tool"]:
                cand["trigger_prep"] = {"execution_ready": True,
                                        "raw_trigger_status": "confirmed"}
        snapshot["narrative_authority"] = build_narrative(
            _june11_1029_snapshot({}), {},
        )
        gate = evaluate_gate(snapshot)
        self.assertFalse(gate["allow_execution"])
        self.assertFalse(gate["authorization_checks"]["narrative_permits_trade"])
        self.assertIn("narrative authority", " | ".join(gate["blocking_factors"]))


class T6_ProtectedLowFromSellSideRaid(unittest.TestCase):
    """11:04:54: below_low@15m sweep + reclaim -> protected low."""

    def test_sell_side_raid_registers_protected_low(self):
        tracker = ProtectedSwingTracker()
        state = tracker.update(_sweep_snapshot(
            direction="below_low", level=699.60, price=700.20,
            ts="20260611T110454",
        ))
        self.assertIsNotNone(state["protected_low"])
        self.assertEqual(state["protected_low"]["level"], 699.60)
        self.assertEqual(state["protected_low"]["basis"], "sell_side_raid_rejected")


class T7_ShortIntoProtectedLowBlocked(unittest.TestCase):
    """13:17: short proposed with price sitting on the protected low —
    blocked or conflicted, not authorized."""

    def setUp(self):
        os.environ["NARRATIVE_AUTHORITY"] = "enforce"

    def tearDown(self):
        _clear()

    def test_short_into_protected_low_is_forbidden(self):
        tracker = ProtectedSwingTracker()
        swings = tracker.update(_sweep_snapshot(
            direction="below_low", level=698.50, price=699.20,
        ))
        # 13:17 state: AI bearish@74, delivery silent, structure bearish,
        # price 698.59 — 9 cents above the protected low.
        snap = {
            "timestamp": "20260611T131741",
            "ai_discretionary": {"ai_direction": "bearish", "ai_confidence": 74},
            "shared_context": {"delivery_state": "accumulation_building",
                               "delivery_confidence": 45},
            "po3": {"15m": {"phase": "accumulation"}, "alignment": "accumulation_building"},
            "ai_context": {"directional_bias": "bearish", "confidence_score": 73},
            "liquidity": {"3m": {"sweep_detected": True,
                                 "sweep_direction": "below_low",
                                 "reclaim_detected": True}},
            "structure": {},
            "timeframes": {"1m": {"last_candle": {"close": 698.59}}},
        }
        na = build_narrative(snap, swings)
        self.assertEqual(na["forbidden_trade_direction"], "bearish")
        if na["narrative_direction"] == "bearish":
            self.assertFalse(na["trade_allowed"])
            self.assertIn("short_into_protected_low", na["conflict_flags"])
        permits, reason = narrative_permits(na, "bearish")
        self.assertFalse(permits)


class T8_StructureCannotOverrideAgreement(unittest.TestCase):

    def tearDown(self):
        _clear()

    def test_bullish_structure_cannot_force_long_against_bear_agreement(self):
        snap = _june11_1029_snapshot({})
        snap["ai_discretionary"] = {"ai_direction": "bearish", "ai_confidence": 70}
        na = build_narrative(snap, {})    # delivery bearish@25 + AI bearish
        self.assertEqual(na["narrative_direction"], "bearish")
        permits, _ = narrative_permits(na, "bullish")
        os.environ["NARRATIVE_AUTHORITY"] = "enforce"
        permits, _ = narrative_permits(na, "bullish")
        self.assertFalse(permits)

    def test_bearish_structure_cannot_force_short_against_bull_agreement(self):
        snap = _june11_1029_snapshot({})
        snap["ai_discretionary"] = {"ai_direction": "bullish", "ai_confidence": 70}
        snap["po3"] = {"15m": {"phase": "manipulation",
                               "manipulation_direction": "bullish"}}
        snap["shared_context"] = {"delivery_state": "bullish_delivery",
                                  "delivery_confidence": 45}
        snap["ai_context"]["directional_bias"] = "bearish"
        na = build_narrative(snap, {})
        self.assertEqual(na["narrative_direction"], "bullish")
        self.assertIn("structure_overruled", na["conflict_flags"])
        os.environ["NARRATIVE_AUTHORITY"] = "enforce"
        permits, _ = narrative_permits(na, "bearish")
        self.assertFalse(permits)


class T9_Rollback(unittest.TestCase):

    def tearDown(self):
        _clear()

    def test_observe_only_never_blocks(self):
        """Default env: even a fully conflicted narrative permits trades —
        the legacy gate behavior is untouched."""
        _clear()
        na = build_narrative(_june11_1029_snapshot({}), {})
        self.assertEqual(na["authority_level"], "observe_only")
        permits, reason = narrative_permits(na, "bullish")
        self.assertTrue(permits)
        self.assertIn("observe_only", reason)

    def test_legacy_gate_replay_still_authorizes(self):
        """With all NA/FC flags at defaults the archived June 11 snapshot
        authorizes exactly as it did live — full rollback guarantee."""
        _clear()
        os.environ["EXECUTION_ENABLED"] = "true"
        with open(_JUNE11_SNAPSHOT, encoding="utf-8") as fh:
            snapshot = json.load(fh)
        for cand in snapshot["toolbox"]["tool_candidates"]:
            if cand.get("tool") == snapshot["toolbox"]["preferred_tool"]:
                cand["trigger_prep"] = {"execution_ready": True,
                                        "raw_trigger_status": "confirmed"}
        snapshot["narrative_authority"] = build_narrative(
            _june11_1029_snapshot({}), {},
        )   # conflicted — but observe_only must not block
        gate = evaluate_gate(snapshot)
        self.assertTrue(gate["allow_execution"])

    def test_engine_failure_fails_open_to_witness_mode(self):
        na = build_narrative(None, None)
        self.assertTrue(na["trade_allowed"])
        permits, _ = narrative_permits(na, "bullish")
        self.assertTrue(permits)


class T10_DrawOnLiquidity(unittest.TestCase):
    """Draw model: buy-side spent at protected high -> sell-side objective."""

    def test_bearish_narrative_draws_to_sell_side(self):
        snap = _june11_1029_snapshot({})
        draw = compute_liquidity_draw(snap, {}, "bearish")
        self.assertEqual(draw["side"], "sell_side")
        self.assertEqual(draw["level"], 699.60)

    def test_spent_buy_side_implies_sell_side_objective(self):
        tracker = ProtectedSwingTracker()
        swings = tracker.update(_sweep_snapshot())
        snap = _june11_1029_snapshot(swings)
        draw = compute_liquidity_draw(snap, swings, "conflicted")
        self.assertIsNotNone(draw)
        self.assertEqual(draw["side"], "sell_side")
        self.assertIn("opposite pool", draw["basis"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Phase 5F — Authority Enforcement test suite.

5F.1 — Risk multiplier enforcement in order_builder
5F.2 — Regime Permission Matrix
5F.3 — Trigger confirmation enforcement (gate + trigger prep)
5F.4 — Decision state rename (ready_for_execution, backward compatible)
5F.5 — Minimum setup age gate
Regression — today's losing QQQ trade (2026-06-10, scan #156) must be blocked.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from regime_authority.regime_permission_matrix import evaluate_regime_permissions
from decision_authority.decision_engine import make_decision, normalize_decision
from execution_gate.execution_gate import evaluate_gate
from toolbox.entry_trigger_prep import build_trigger_prep
import paper_execution.order_builder as ob_mod
from paper_execution.order_builder import build_order
from paper_execution.trade_journal import make_record

_SNAPSHOT_20260610 = os.path.join(
    os.path.dirname(__file__), "..", "data", "live_snapshots",
    "20260610_115839_QQQ.json",
)

_ACCOUNT_OK = {"buying_power": 1_000_000.0, "cash": 1_000_000.0}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sizing_snapshot(risk_multiplier=None, regime_cap=None):
    """Minimal snapshot for build_order: entry 100, stop 95 -> rps=5."""
    snap = {
        "trade_intent": {"intent_type": "long", "direction": "bullish"},
        "toolbox": {
            "preferred_tool": "bullish_fvg",
            "tool_candidates": [{
                "tool": "bullish_fvg",
                "price_level": {
                    "midpoint": 100.0,
                    "invalidation_level": 95.0,
                    "zone_low": 99.0,
                    "zone_high": 101.0,
                },
            }],
        },
        "risk": {},
        "regime_permissions": {},
    }
    if risk_multiplier is not None:
        snap["risk"]["risk_multiplier"] = risk_multiplier
    if regime_cap is not None:
        snap["regime_permissions"]["risk_multiplier_cap"] = regime_cap
    return snap


def _gate_snapshot(
    decision="ready_for_execution",
    required_trigger="confirmation_needed",
    actual_trigger="confirmation_needed",
    min_setup_age=1,
    setup_age=2,
    regime_allowed=True,
    rp_enabled=True,
    include_rp=True,
):
    """Snapshot where every legacy gate check passes; 5F knobs are parameters."""
    snap = {
        "decision_authority": {"decision": decision, "trade_authorized": False},
        "risk": {"trade_allowed": True},
        "state_transition": {"invalidated": False},
        "setup_lifecycle": {
            "active": True, "current_phase": "maturing", "age_scans": setup_age,
        },
        "ai_debate": {"final_verdict": {"recommended_stance": "prepare_long"}},
        "confidence_fusion": {"fusion_status": "agreement"},
        "toolbox": {
            "preferred_tool": "bullish_fvg",
            "tool_candidates": [{
                "tool": "bullish_fvg",
                "trigger_prep": {
                    "execution_ready": True,
                    "raw_trigger_status": actual_trigger,
                },
            }],
        },
    }
    if include_rp:
        snap["regime_permissions"] = {
            "enabled":                 rp_enabled,
            "allowed":                 regime_allowed,
            "permission_status":       "restricted",
            "risk_multiplier_cap":     0.5,
            "required_trigger_status": required_trigger,
            "min_setup_age_scans":     min_setup_age,
            "management_profile":      "range",
            "blocking_reasons":        [] if regime_allowed else ["playbook forbidden"],
        }
    return snap


def _regime_snapshot(label, vol="stable", exp="normal", playbook="liquidity_sweep_reversal"):
    return {
        "market_regime": {
            "regime_label": label,
            "volatility_state": vol,
            "expansion_state": exp,
        },
        "playbook": {"selected_playbook": playbook, "direction": "bullish"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5F.1 — Risk multiplier enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskMultiplierEnforcement(unittest.TestCase):

    def setUp(self):
        os.environ["RISK_PER_TRADE_DOLLARS"] = "500"
        patcher = patch.object(ob_mod, "_get_account", return_value=dict(_ACCOUNT_OK))
        self.mock_acct = patcher.start()
        self.addCleanup(patcher.stop)

    def test_multiplier_1_0_uses_full_risk(self):
        result = build_order(_sizing_snapshot(risk_multiplier=1.0), "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["qty"], 100)            # 500 / 5
        self.assertEqual(result["risk_multiplier_applied"], 1.0)
        self.assertEqual(result["base_risk_budget"], 500.0)
        self.assertEqual(result["effective_risk_budget"], 500.0)

    def test_multiplier_0_5_halves_risk(self):
        result = build_order(_sizing_snapshot(risk_multiplier=0.5), "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["qty"], 50)             # 250 / 5
        self.assertEqual(result["risk_multiplier_applied"], 0.5)
        self.assertEqual(result["effective_risk_budget"], 250.0)

    def test_multiplier_0_25_quarters_risk(self):
        result = build_order(_sizing_snapshot(risk_multiplier=0.25), "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["qty"], 25)             # 125 / 5
        self.assertEqual(result["effective_risk_budget"], 125.0)

    def test_missing_multiplier_defaults_to_1_0(self):
        result = build_order(_sizing_snapshot(), "QQQ")
        self.assertTrue(result["valid"])
        self.assertEqual(result["qty"], 100)
        self.assertEqual(result["risk_multiplier_applied"], 1.0)

    def test_buying_power_cap_still_applies_after_multiplier(self):
        self.mock_acct.return_value = {"buying_power": 1000.0}
        result = build_order(_sizing_snapshot(risk_multiplier=1.0), "QQQ")
        self.assertTrue(result["valid"])
        # risk_qty=100, affordable = floor(1000/100) = 10 -> capped at 10
        self.assertEqual(result["qty"], 10)
        self.assertEqual(result["affordable_qty"], 10)

    def test_invalid_multiplier_clamped_safely(self):
        # Non-numeric -> default 1.0
        r1 = build_order(_sizing_snapshot(risk_multiplier="garbage"), "QQQ")
        self.assertTrue(r1["valid"])
        self.assertEqual(r1["risk_multiplier_applied"], 1.0)
        # > 1.0 -> clamps to 1.0 (a multiplier can never raise risk)
        r2 = build_order(_sizing_snapshot(risk_multiplier=2.5), "QQQ")
        self.assertTrue(r2["valid"])
        self.assertEqual(r2["risk_multiplier_applied"], 1.0)
        # Negative -> clamps to 0.0 -> order rejected (no free-risk path)
        r3 = build_order(_sizing_snapshot(risk_multiplier=-1.0), "QQQ")
        self.assertFalse(r3["valid"])
        self.assertIn("effective risk budget is 0", r3["reject_reason"])

    def test_regime_cap_tighter_than_governor_wins(self):
        result = build_order(
            _sizing_snapshot(risk_multiplier=1.0, regime_cap=0.5), "QQQ"
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["qty"], 50)
        self.assertEqual(result["risk_multiplier_applied"], 0.5)
        self.assertEqual(result["regime_risk_cap"], 0.5)

    def test_journal_record_carries_multiplier_fields(self):
        rec = make_record(
            trade_id="T1", symbol="QQQ", intent_id=None, intent_type="long",
            side="buy", qty=50, entry_reference=100.0, stop_reference=95.0,
            risk_per_share=5.0, risk_dollars=250.0, order_status="submitted",
            alpaca_order_id="x", reason="test",
            risk_multiplier_applied=0.5, base_risk_budget=500.0,
            effective_risk_budget=250.0,
        )
        self.assertEqual(rec["risk_multiplier_applied"], 0.5)
        self.assertEqual(rec["base_risk_budget"], 500.0)
        self.assertEqual(rec["effective_risk_budget"], 250.0)


# ══════════════════════════════════════════════════════════════════════════════
# 5F.2 — Regime Permission Matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestRegimePermissionMatrix(unittest.TestCase):

    def setUp(self):
        os.environ["REGIME_AUTHORITY_ENABLED"] = "true"

    def test_range_rotation_forbids_trend_continuation(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("range_rotation", playbook="trend_continuation")
        )
        self.assertFalse(rp["allowed"])
        self.assertEqual(rp["permission_status"], "blocked")
        self.assertTrue(any("trend_continuation" in b for b in rp["blocking_reasons"]))

    def test_range_rotation_allows_sweep_reversal_restricted(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("range_rotation", playbook="liquidity_sweep_reversal")
        )
        self.assertTrue(rp["allowed"])
        self.assertEqual(rp["permission_status"], "restricted")
        self.assertEqual(rp["risk_multiplier_cap"], 0.5)
        self.assertEqual(rp["required_trigger_status"], "confirmed")
        self.assertEqual(rp["management_profile"], "range")
        self.assertEqual(rp["min_setup_age_scans"], 2)

    def test_exhaustion_risk_blocks_late_continuation(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("trend_up", exp="exhaustion_risk",
                             playbook="trend_continuation")
        )
        self.assertFalse(rp["allowed"])
        self.assertEqual(rp["permission_status"], "blocked")

    def test_exhaustion_risk_requires_confirmed_and_caps_risk(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("trend_up", exp="exhaustion_risk",
                             playbook="liquidity_sweep_reversal")
        )
        self.assertTrue(rp["allowed"])
        self.assertEqual(rp["required_trigger_status"], "confirmed")
        self.assertLessEqual(rp["risk_multiplier_cap"], 0.5)
        self.assertGreaterEqual(rp["min_setup_age_scans"], 2)

    def test_unstable_volatility_caps_risk_outside_trend(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("reversal_attempt", vol="unstable")
        )
        self.assertLessEqual(rp["risk_multiplier_cap"], 0.5)
        self.assertEqual(rp["required_trigger_status"], "confirmed")

    def test_unstable_volatility_in_trend_keeps_confirmation_needed(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("trend_up", vol="unstable", playbook="trend_continuation")
        )
        self.assertTrue(rp["allowed"])
        self.assertEqual(rp["risk_multiplier_cap"], 0.5)
        self.assertEqual(rp["required_trigger_status"], "confirmation_needed")

    def test_toxic_volatility_caps_at_0_25(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("range_rotation", vol="toxic")
        )
        self.assertLessEqual(rp["risk_multiplier_cap"], 0.25)

    def test_chop_blocks_non_reversal_playbooks(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("chop", playbook="opening_drive")
        )
        self.assertFalse(rp["allowed"])
        self.assertEqual(rp["permission_status"], "blocked")

    def test_chop_allows_sweep_reversal_at_quarter_risk(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("chop", playbook="liquidity_sweep_reversal")
        )
        self.assertTrue(rp["allowed"])
        self.assertEqual(rp["risk_multiplier_cap"], 0.25)
        self.assertEqual(rp["required_trigger_status"], "confirmed")
        self.assertEqual(rp["min_setup_age_scans"], 3)

    def test_strong_trend_full_permissions(self):
        rp = evaluate_regime_permissions(
            _regime_snapshot("trend_up", playbook="trend_continuation")
        )
        self.assertTrue(rp["allowed"])
        self.assertEqual(rp["permission_status"], "allowed")
        self.assertEqual(rp["risk_multiplier_cap"], 1.0)
        self.assertEqual(rp["required_trigger_status"], "confirmation_needed")
        self.assertEqual(rp["min_setup_age_scans"], 1)
        self.assertEqual(rp["management_profile"], "trend")

    def test_unknown_regime_is_restricted(self):
        rp = evaluate_regime_permissions(_regime_snapshot("unknown"))
        self.assertEqual(rp["permission_status"], "restricted")
        self.assertEqual(rp["required_trigger_status"], "confirmed")
        self.assertLessEqual(rp["risk_multiplier_cap"], 0.5)

    def test_disabled_env_returns_legacy_behavior(self):
        os.environ["REGIME_AUTHORITY_ENABLED"] = "false"
        try:
            rp = evaluate_regime_permissions(
                _regime_snapshot("chop", playbook="trend_continuation")
            )
            self.assertFalse(rp["enabled"])
            self.assertTrue(rp["allowed"])
            self.assertEqual(rp["risk_multiplier_cap"], 1.0)
        finally:
            os.environ["REGIME_AUTHORITY_ENABLED"] = "true"

    def test_never_raises_on_garbage_snapshot(self):
        rp = evaluate_regime_permissions({"market_regime": "not_a_dict"})
        self.assertIn(rp["permission_status"], ("restricted", "allowed", "blocked"))
        self.assertIn("required_trigger_status", rp)


# ══════════════════════════════════════════════════════════════════════════════
# 5F.3 — Trigger confirmation enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestTriggerConfirmationEnforcement(unittest.TestCase):

    def setUp(self):
        os.environ["EXECUTION_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

    def test_confirmed_required_confirmed_actual_passes(self):
        eg = evaluate_gate(_gate_snapshot(
            required_trigger="confirmed", actual_trigger="confirmed"))
        self.assertTrue(eg["trigger_requirement_met"])
        self.assertTrue(eg["allow_execution"])
        self.assertEqual(eg["gate_status"], "authorized")

    def test_confirmed_required_confirmation_needed_blocks(self):
        eg = evaluate_gate(_gate_snapshot(
            required_trigger="confirmed", actual_trigger="confirmation_needed"))
        self.assertFalse(eg["trigger_requirement_met"])
        self.assertFalse(eg["allow_execution"])
        self.assertFalse(eg["would_authorize_if_enabled"])
        self.assertEqual(eg["required_trigger_status"], "confirmed")
        self.assertEqual(eg["actual_trigger_status"], "confirmation_needed")
        self.assertTrue(
            any("trigger requirement not met" in b for b in eg["blocking_factors"])
        )

    def test_confirmation_needed_required_confirmation_needed_passes(self):
        eg = evaluate_gate(_gate_snapshot(
            required_trigger="confirmation_needed",
            actual_trigger="confirmation_needed"))
        self.assertTrue(eg["trigger_requirement_met"])
        self.assertTrue(eg["allow_execution"])

    def test_confirmation_needed_required_confirmed_passes(self):
        eg = evaluate_gate(_gate_snapshot(
            required_trigger="confirmation_needed", actual_trigger="confirmed"))
        self.assertTrue(eg["trigger_requirement_met"])
        self.assertTrue(eg["allow_execution"])

    def test_missing_matrix_defaults_safe_require_confirmed(self):
        eg = evaluate_gate(_gate_snapshot(
            actual_trigger="confirmation_needed", include_rp=False))
        self.assertFalse(eg["trigger_requirement_met"])
        self.assertFalse(eg["allow_execution"])
        self.assertEqual(eg["required_trigger_status"], "confirmed")
        self.assertEqual(eg["regime_constraint_source"], "missing_matrix_safe_default")

    def test_regime_blocked_locks_gate(self):
        eg = evaluate_gate(_gate_snapshot(regime_allowed=False,
                                          actual_trigger="confirmed",
                                          required_trigger="confirmed"))
        self.assertFalse(eg["allow_execution"])
        self.assertTrue(
            any("regime permission blocked" in b for b in eg["blocking_factors"])
        )

    def test_authority_disabled_skips_regime_gating(self):
        snap = _gate_snapshot(actual_trigger="confirmation_needed",
                              rp_enabled=False)
        eg = evaluate_gate(snap)
        self.assertTrue(eg["trigger_requirement_met"])
        self.assertTrue(eg["allow_execution"])
        self.assertEqual(eg["regime_constraint_source"], "regime_authority_disabled")


class TestTriggerConfirmedUpgrade(unittest.TestCase):
    """The trigger layer itself can now reach a real 'confirmed' state."""

    def _prep(self, direction, last_candle):
        tool = f"{direction}_fvg"
        snapshot = {
            "risk": {"trade_allowed": True},
            "timeframes": {"1m": {"last_candle": last_candle}},
        }
        price_level = {
            "level_type": "fvg",
            "midpoint": 100.0,
            "zone_low": 99.0,
            "zone_high": 101.0,
            "price_relation": "inside_zone",
            "invalidated": False,
        }
        return build_trigger_prep(
            tool, snapshot, price_level,
            readiness={"prerequisites_missing": []},
            raw_status="actionable", effective_status="actionable",
        )

    def test_bullish_confirmation_candle_upgrades_to_confirmed(self):
        tp = self._prep("bullish", {"open": 99.8, "close": 100.6})
        self.assertEqual(tp["raw_trigger_status"], "confirmed")

    def test_bearish_confirmation_candle_upgrades_to_confirmed(self):
        tp = self._prep("bearish", {"open": 100.2, "close": 99.4})
        self.assertEqual(tp["raw_trigger_status"], "confirmed")

    def test_no_candle_data_stays_confirmation_needed(self):
        tool = "bullish_fvg"
        snapshot = {"risk": {"trade_allowed": True}, "timeframes": {}}
        price_level = {
            "level_type": "fvg", "midpoint": 100.0,
            "zone_low": 99.0, "zone_high": 101.0,
            "price_relation": "inside_zone", "invalidated": False,
        }
        tp = build_trigger_prep(
            tool, snapshot, price_level,
            readiness={"prerequisites_missing": []},
            raw_status="actionable", effective_status="actionable",
        )
        self.assertEqual(tp["raw_trigger_status"], "confirmation_needed")

    def test_wrong_direction_candle_stays_confirmation_needed(self):
        tp = self._prep("bullish", {"open": 100.6, "close": 99.8})
        self.assertEqual(tp["raw_trigger_status"], "confirmation_needed")


# ══════════════════════════════════════════════════════════════════════════════
# 5F.4 — Decision state rename
# ══════════════════════════════════════════════════════════════════════════════

class TestDecisionStateRename(unittest.TestCase):

    def setUp(self):
        os.environ["EXECUTION_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

    def test_old_string_still_accepted_by_gate(self):
        eg = evaluate_gate(_gate_snapshot(
            decision="trade_authorized_false",
            required_trigger="confirmed", actual_trigger="confirmed"))
        self.assertTrue(eg["allow_execution"])

    def test_new_string_accepted_by_gate(self):
        eg = evaluate_gate(_gate_snapshot(
            decision="ready_for_execution",
            required_trigger="confirmed", actual_trigger="confirmed"))
        self.assertTrue(eg["allow_execution"])

    def test_normalize_decision_mapping(self):
        self.assertEqual(normalize_decision("trade_authorized_false"), "ready_for_execution")
        self.assertEqual(normalize_decision("TRADE_AUTHORIZED_FALSE"), "ready_for_execution")
        self.assertEqual(normalize_decision("ready_for_execution"), "ready_for_execution")
        self.assertEqual(normalize_decision("monitor"), "monitor")
        self.assertEqual(normalize_decision(None), "stand_down")

    def test_decision_engine_emits_new_state_not_old(self):
        snapshot = {
            "qualification": {"status": "qualified"},
            "playbook": {"selected_playbook": "liquidity_sweep_reversal",
                         "direction": "bullish", "playbook_confidence": 70},
            "risk": {"trade_allowed": True},
            "state_transition": {"invalidated": False},
            "setup_lifecycle": {"active": True, "current_phase": "maturing",
                                "direction": "bullish", "age_scans": 3},
            "ai_debate": {"final_verdict": {"recommended_stance": "prepare_long",
                                            "dominant_thesis": "bullish",
                                            "verdict_confidence": 70}},
            "confidence_fusion": {"combined_confidence": 75},
            "toolbox": {
                "preferred_tool": "bullish_fvg",
                "tool_candidates": [{
                    "tool": "bullish_fvg",
                    "raw_status": "actionable",
                    "trigger_prep": {"execution_ready": True,
                                     "raw_trigger_status": "confirmed"},
                }],
            },
        }
        da = make_decision(snapshot)
        self.assertEqual(da["decision"], "ready_for_execution")
        self.assertNotIn("trade_authorized_false", da["reason"])
        self.assertFalse(da["trade_authorized"])  # invariant unchanged pre-gate


# ══════════════════════════════════════════════════════════════════════════════
# 5F.5 — Minimum setup age gate
# ══════════════════════════════════════════════════════════════════════════════

class TestMinimumSetupAgeGate(unittest.TestCase):

    def setUp(self):
        os.environ["EXECUTION_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

    def _gate(self, min_age, age):
        return evaluate_gate(_gate_snapshot(
            required_trigger="confirmed", actual_trigger="confirmed",
            min_setup_age=min_age, setup_age=age,
        ))

    def test_trend_age_1_passes(self):
        eg = self._gate(min_age=1, age=1)
        self.assertTrue(eg["setup_age_requirement_met"])
        self.assertTrue(eg["allow_execution"])

    def test_range_age_1_blocks(self):
        eg = self._gate(min_age=2, age=1)
        self.assertFalse(eg["setup_age_requirement_met"])
        self.assertFalse(eg["allow_execution"])
        self.assertEqual(eg["setup_age_requirement"], 2)
        self.assertEqual(eg["setup_age_actual"], 1)
        self.assertTrue(
            any("setup age requirement not met" in b for b in eg["blocking_factors"])
        )

    def test_range_age_2_passes(self):
        eg = self._gate(min_age=2, age=2)
        self.assertTrue(eg["setup_age_requirement_met"])
        self.assertTrue(eg["allow_execution"])

    def test_chop_age_2_blocks(self):
        eg = self._gate(min_age=3, age=2)
        self.assertFalse(eg["setup_age_requirement_met"])
        self.assertFalse(eg["allow_execution"])

    def test_chop_age_3_passes(self):
        eg = self._gate(min_age=3, age=3)
        self.assertTrue(eg["setup_age_requirement_met"])
        self.assertTrue(eg["allow_execution"])


# ══════════════════════════════════════════════════════════════════════════════
# CRITICAL REGRESSION — today's losing trade must be blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase5FRegression(unittest.TestCase):

    def test_phase_5f_blocks_20260610_range_exhaustion_trade(self):
        """
        Scan #156 (2026-06-10 11:58 ET): long QQQ entered in
        range_rotation / exhaustion_risk / unstable with trigger
        CONFIRMATION_NEEDED at setup age 1 — lost $481.
        After Phase 5F this exact snapshot must be blocked.
        """
        os.environ["EXECUTION_ENABLED"] = "true"
        os.environ["REGIME_AUTHORITY_ENABLED"] = "true"
        os.environ["RISK_PER_TRADE_DOLLARS"] = "500"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

        with open(_SNAPSHOT_20260610, encoding="utf-8") as f:
            snapshot = json.load(f)

        # Sanity: this is the trade that lost money
        regime = snapshot["market_regime"]
        self.assertEqual(regime["regime_label"], "range_rotation")
        self.assertEqual(regime["volatility_state"], "unstable")
        self.assertEqual(regime["expansion_state"], "exhaustion_risk")
        self.assertEqual(snapshot["setup_lifecycle"]["age_scans"], 1)

        # The saved snapshot pre-dates 5F and strips candidate detail: restore
        # the live trigger_prep and price_level the log recorded at entry
        # (CONFIRMATION_NEEDED, execution_ready=true, zone 701.26-701.56,
        # invalidation 695.73 -> the actual order: buy 88 QQQ limit 701.41).
        for cand in snapshot["toolbox"]["tool_candidates"]:
            if cand["tool"] == snapshot["toolbox"]["preferred_tool"]:
                cand["trigger_prep"] = {
                    "execution_ready":    True,
                    "raw_trigger_status": "confirmation_needed",
                }
                cand["price_level"] = {
                    "level_type":         "rejection_block",
                    "direction":          "bullish",
                    "zone_low":           701.26,
                    "zone_high":          701.56,
                    "midpoint":           701.41,
                    "invalidation_level": 695.73,
                    "price_relation":     "touching_zone",
                    "invalidated":        False,
                }

        # ── 1. Regime permissions: restricted/blocked, confirmed, cap <= 0.5 ──
        rp = evaluate_regime_permissions(snapshot)
        snapshot["regime_permissions"] = rp
        self.assertIn(rp["permission_status"], ("restricted", "blocked"))
        self.assertEqual(rp["required_trigger_status"], "confirmed")
        self.assertLessEqual(rp["risk_multiplier_cap"], 0.5)
        self.assertGreaterEqual(rp["min_setup_age_scans"], 2)
        self.assertEqual(rp["management_profile"], "range")

        # ── 2. Execution gate: blocked on trigger AND setup age ───────────────
        eg = evaluate_gate(snapshot)
        snapshot["execution_gate"] = eg
        self.assertFalse(eg["allow_execution"])
        self.assertFalse(eg["would_authorize_if_enabled"])
        self.assertFalse(eg["trigger_requirement_met"])
        self.assertEqual(eg["required_trigger_status"], "confirmed")
        self.assertEqual(eg["actual_trigger_status"], "confirmation_needed")
        self.assertFalse(eg["setup_age_requirement_met"])
        self.assertEqual(eg["setup_age_actual"], 1)

        # Legacy decision string from the old snapshot is still understood
        self.assertEqual(
            snapshot["decision_authority"]["decision"], "trade_authorized_false"
        )

        # ── 3. Sizing: even if it had fired, risk is capped at 0.5x ───────────
        with patch.object(ob_mod, "_get_account", return_value=dict(_ACCOUNT_OK)):
            sizing = build_order(snapshot, "QQQ")
        self.assertTrue(sizing["valid"])
        self.assertEqual(sizing["risk_multiplier_applied"], 0.5)
        self.assertEqual(sizing["effective_risk_budget"], 250.0)
        # Original trade: 88 shares. Capped sizing must be ~half.
        self.assertLessEqual(sizing["qty"], 44)

        # ── 4. Execution engine: order is NOT submitted ────────────────────────
        import paper_execution.execution_engine as ee_mod
        os.environ["PAPER_TRADING_ONLY"] = "true"
        os.environ["ALLOW_PAPER_ORDERS"] = "true"
        with patch.object(ee_mod, "is_paper_account_safe", return_value=(True, "ok")):
            result = ee_mod.attempt_paper_execution(snapshot, "QQQ")
        self.assertEqual(result["status"], "skipped")
        self.assertNotIn("submitted", result["status"])
        self.assertIsNone(result.get("alpaca_order_id"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

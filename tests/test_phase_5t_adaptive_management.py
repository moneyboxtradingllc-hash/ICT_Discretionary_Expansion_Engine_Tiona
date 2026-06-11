"""
Phase 5T — Adaptive Trade Management test suite.

5T.1 — Policy Engine (profile consumption, zero behavior change at ship)
(5T.2/5T.3 classes appended in later sub-phases.)
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.management_policies as mp_mod
import paper_execution.trade_manager as tm_mod
from paper_execution.management_policies import get_policy, resolve_trade_profile
from paper_execution.trade_manager import manage_open_trade

_REAL_REGISTRY = os.path.join(
    os.path.dirname(__file__), "..", "data", "rule_governance", "registry.json",
)


def _trade_record(**overrides):
    rec = {
        "trade_id": "T1", "symbol": "QQQ", "side": "buy",
        "qty": 88, "order_status": "filled",
        "entry_reference": 700.0, "stop_reference": 695.0,
        "risk_per_share": 5.0,
        "breakeven_triggered": False, "take_profit_triggered": False,
        "management_profile": None,
    }
    rec.update(overrides)
    return rec


def _mgmt_snapshot(current_price, profile_in_matrix="defensive"):
    return {
        "position_monitor": {
            "has_open_position": True, "exit_already_submitted": False,
            "linked_trade_id": "T1", "current_price": current_price,
            "side": "long", "qty": 88, "avg_entry_price": 700.0,
        },
        "regime_permissions": {"enabled": True,
                               "management_profile": profile_in_matrix},
        "toolbox": {"tool_candidates": []},
    }


def _manage(snapshot, record):
    """Run manage_open_trade with journal + broker fully mocked."""
    with patch.object(tm_mod, "find_any_active_trade",
                      return_value=(record, "f.json")), \
         patch.object(tm_mod, "update_trade_management", return_value=True), \
         patch.object(mp_mod, "update_trade_management", return_value=True), \
         patch.object(tm_mod, "is_paper_account_safe",
                      return_value=(True, "ok")), \
         patch.object(tm_mod, "submit_paper_exit_order",
                      return_value={"alpaca_order_id": "X1"}), \
         patch.object(tm_mod, "mark_exit_submitted", return_value=True):
        return manage_open_trade(snapshot, "QQQ")


# ══════════════════════════════════════════════════════════════════════════════
# 5T.1 — Policy table + profile resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestPolicyTable(unittest.TestCase):

    def test_three_profiles_exist(self):
        for p in ("defensive", "range", "trend"):
            policy = get_policy(p)
            self.assertEqual(policy["profile"], p)

    def test_unknown_profile_falls_back_to_defensive(self):
        self.assertEqual(get_policy("aggressive")["profile"], "defensive")
        self.assertEqual(get_policy(None)["profile"], "defensive")

    def test_5t1_ships_all_none_zero_behavior_change(self):
        """Constitution: at 5T.1 ship, every numeric param is None (env default)."""
        for p in ("defensive", "range", "trend"):
            policy = get_policy(p)
            self.assertIsNone(policy["breakeven_trigger_r"], p)
            self.assertIsNone(policy["take_profit_r"], p)
            self.assertIsNone(policy["take_profit_fraction"], p)
            self.assertIsNone(policy["trail_after_breakeven"], p)

    def test_thesis_exit_is_shadow_everywhere(self):
        """Live thesis exits require promoted evidence — none exists yet."""
        for p in ("defensive", "range", "trend"):
            self.assertEqual(get_policy(p)["thesis_exit"], "shadow")


class TestProfileResolution(unittest.TestCase):

    def test_locked_profile_wins_over_snapshot(self):
        rec  = _trade_record(management_profile="trend")
        snap = _mgmt_snapshot(701.0, profile_in_matrix="range")
        with patch.object(mp_mod, "update_trade_management") as upd:
            profile = resolve_trade_profile(snap, rec, "QQQ")
        self.assertEqual(profile, "trend")
        upd.assert_not_called()          # locked — no journal write

    def test_first_touch_reads_matrix_and_persists(self):
        rec  = _trade_record()
        snap = _mgmt_snapshot(701.0, profile_in_matrix="range")
        with patch.object(mp_mod, "update_trade_management",
                          return_value=True) as upd:
            profile = resolve_trade_profile(snap, rec, "QQQ")
        self.assertEqual(profile, "range")
        upd.assert_called_once_with("T1", {"management_profile": "range"}, "QQQ")

    def test_missing_matrix_defaults_defensive(self):
        rec  = _trade_record()
        snap = {"position_monitor": {}}
        with patch.object(mp_mod, "update_trade_management", return_value=True):
            self.assertEqual(resolve_trade_profile(snap, rec, "QQQ"), "defensive")

    def test_invalid_profile_in_matrix_defaults_defensive(self):
        rec  = _trade_record()
        snap = _mgmt_snapshot(701.0, profile_in_matrix="yolo")
        with patch.object(mp_mod, "update_trade_management", return_value=True):
            self.assertEqual(resolve_trade_profile(snap, rec, "QQQ"), "defensive")

    def test_never_raises(self):
        self.assertEqual(resolve_trade_profile(None, {}, "QQQ"), "defensive")


class TestDefensiveReproducesCurrentBehavior(unittest.TestCase):
    """5E.8 behavior must be bit-identical under the policy engine."""

    def setUp(self):
        for var in ("BREAKEVEN_TRIGGER_R", "TAKE_PROFIT_R"):
            os.environ.pop(var, None)

    def test_take_profit_still_fires_at_2R(self):
        # entry 700, rps 5 -> +2R = 710
        result = _manage(_mgmt_snapshot(710.0), _trade_record())
        self.assertEqual(result["action"], "take_profit")
        self.assertAlmostEqual(result["unrealized_r"], 2.0)

    def test_breakeven_still_fires_at_1R(self):
        result = _manage(_mgmt_snapshot(705.0), _trade_record())
        self.assertEqual(result["action"], "breakeven")

    def test_hold_below_1R_with_profile_tag(self):
        result = _manage(_mgmt_snapshot(702.0), _trade_record())
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["management_profile"], "defensive")

    def test_range_profile_identical_at_5t1(self):
        """All-None RANGE row: same thresholds as defensive until 5T.3."""
        rec    = _trade_record(management_profile="range")
        result = _manage(_mgmt_snapshot(704.9), rec)   # +0.98R
        self.assertEqual(result["action"], "hold")     # not 0.75R yet
        result = _manage(_mgmt_snapshot(705.0), rec)   # +1.0R
        self.assertEqual(result["action"], "breakeven")

    def test_env_overrides_still_respected(self):
        os.environ["TAKE_PROFIT_R"] = "1.5"
        self.addCleanup(lambda: os.environ.pop("TAKE_PROFIT_R", None))
        result = _manage(_mgmt_snapshot(707.5), _trade_record())  # +1.5R
        self.assertEqual(result["action"], "take_profit")


class TestPolicyRegistryRecords(unittest.TestCase):

    def test_p001_p002_p003_load_clean(self):
        os.environ.pop("RULE_GOVERNANCE_DIR", None)
        from rule_governance.rule_registry import load_registry
        reg = load_registry()
        self.assertEqual(reg["quarantined"], [])
        by_id = {r["rule_id"]: r for r in reg["rules"]}
        self.assertEqual(by_id["P-001"]["status"], "grandfathered")
        self.assertEqual(by_id["P-002"]["status"], "shadow")
        self.assertEqual(by_id["P-003"]["status"], "shadow")
        for rid in ("P-002", "P-003"):
            self.assertTrue(by_id[rid].get("monitor_ref"))
            self.assertIn("5T0_mfe_mae_study", by_id[rid]["evidence_refs"][0])

    def test_shadow_management_policy_requires_monitor_ref(self):
        from rule_governance.rule_registry import validate_record
        rec = {
            "rule_id": "P-X", "name": "x", "sponsor": "REGIME",
            "rule_class": "management_policy", "status": "shadow",
            "created": "2026-06-11", "review_by": "2026-07-25",
            "scope": ["QQQ"],
        }
        ok, reason = validate_record(rec)
        self.assertFalse(ok)
        self.assertIn("monitor_ref", reason)
        rec["monitor_ref"] = "management ledger"
        ok, reason = validate_record(rec)
        self.assertTrue(ok, reason)


# ══════════════════════════════════════════════════════════════════════════════
# 5T.2 — Thesis-Failure Monitor (SHADOW ONLY)
# ══════════════════════════════════════════════════════════════════════════════

import paper_execution.thesis_monitor as th_mod
from paper_execution.thesis_monitor import monitor_thesis


def _thesis_snapshot(lifecycle_invalidated=False, st_invalidated=False,
                     current_price=698.0, delivery=None):
    snap = {
        "position_monitor": {
            "has_open_position": True, "exit_already_submitted": False,
            "linked_trade_id": "T1", "current_price": current_price,
            "side": "long", "qty": 88, "avg_entry_price": 700.0,
        },
        "setup_lifecycle": {
            "active": True,
            "current_phase": "invalidated" if lifecycle_invalidated else "maturing",
            "reason": "Entry trigger invalidated" if lifecycle_invalidated else None,
        },
        "state_transition": {"invalidated": st_invalidated},
        "shared_context": delivery or {},
    }
    return snap


def _run_thesis(snap, record):
    with patch.object(th_mod, "find_any_active_trade",
                      return_value=(record, "f.json")), \
         patch.object(th_mod, "update_trade_management",
                      return_value=True) as upd:
        result = monitor_thesis(snap, "QQQ")
    return result, upd


class TestThesisMonitor(unittest.TestCase):

    def setUp(self):
        os.environ.pop("THESIS_MONITOR_ENABLED", None)

    def test_intact_thesis_no_signal(self):
        result, _ = _run_thesis(_thesis_snapshot(), _trade_record())
        self.assertEqual(result["status"], "thesis_intact")
        self.assertFalse(result["would_exit"])
        self.assertEqual(result["events"], [])

    def test_lifecycle_invalidation_signals_would_exit(self):
        result, upd = _run_thesis(
            _thesis_snapshot(lifecycle_invalidated=True, current_price=698.0),
            _trade_record(),
        )
        self.assertTrue(result["would_exit"])
        self.assertEqual(result["reason"], "lifecycle_invalidated")
        # entry 700, rps 5, price 698 -> r = -0.4
        self.assertAlmostEqual(result["r_at_signal"], -0.4)
        # journal persistence of the one-shot signal
        upd.assert_called_once()
        fields = upd.call_args[0][1]
        self.assertTrue(fields["thesis_exit_signaled"])
        self.assertEqual(fields["thesis_exit_reason"], "lifecycle_invalidated")

    def test_state_transition_invalidation_signals(self):
        result, _ = _run_thesis(
            _thesis_snapshot(st_invalidated=True), _trade_record())
        self.assertTrue(result["would_exit"])
        self.assertEqual(result["reason"], "setup_invalidated")

    def test_event_shape_for_ledger(self):
        result, _ = _run_thesis(
            _thesis_snapshot(lifecycle_invalidated=True), _trade_record())
        ev = result["events"][0]
        self.assertEqual(ev["event_type"], "thesis_exit_shadow")
        self.assertEqual(ev["rule_id"], "TFX-001")
        self.assertTrue(ev["executed"])
        self.assertEqual(ev["trade_id"], "T1")
        self.assertEqual(ev["resolution"]["state"], "pending")
        self.assertIsNotNone(ev["r_at_signal"])

    def test_one_signal_per_trade(self):
        rec = _trade_record(thesis_exit_signaled=True,
                            thesis_exit_reason="lifecycle_invalidated")
        result, upd = _run_thesis(
            _thesis_snapshot(lifecycle_invalidated=True), rec)
        self.assertEqual(result["status"], "already_signaled")
        self.assertFalse(result["would_exit"])
        upd.assert_not_called()

    def test_delivery_collapse_only_on_trend_profile(self):
        collapse_ctx = {"delivery_state": "mixed", "continuation_intact": False,
                        "delivery_confidence": 20}
        # defensive profile: delivery collapse is NOT thesis death
        result, _ = _run_thesis(
            _thesis_snapshot(delivery=collapse_ctx),
            _trade_record(management_profile="defensive"))
        self.assertFalse(result["would_exit"])
        # trend profile: it is
        result, _ = _run_thesis(
            _thesis_snapshot(delivery=collapse_ctx),
            _trade_record(management_profile="trend"))
        self.assertTrue(result["would_exit"])
        self.assertEqual(result["reason"], "delivery_collapse")

    def test_delivery_missing_data_never_signals(self):
        unknown_ctx = {"delivery_state": "unknown", "continuation_intact": False,
                       "delivery_confidence": 0}
        result, _ = _run_thesis(
            _thesis_snapshot(delivery=unknown_ctx),
            _trade_record(management_profile="trend"))
        self.assertFalse(result["would_exit"])

    def test_no_position_no_signal(self):
        snap = _thesis_snapshot(lifecycle_invalidated=True)
        snap["position_monitor"]["has_open_position"] = False
        result = monitor_thesis(snap, "QQQ")
        self.assertEqual(result["status"], "no_position")

    def test_shadow_only_no_broker_calls_possible(self):
        """Constitutional: the module must not import any order-submitting API."""
        import inspect
        src = inspect.getsource(th_mod)
        for forbidden in ("submit_paper_exit_order", "submit_order",
                          "cancel_order", "submit_protective_stop",
                          "TradingClient"):
            self.assertNotIn(forbidden, src,
                             f"thesis_monitor references {forbidden} — shadow violation")

    def test_disabled_by_env(self):
        os.environ["THESIS_MONITOR_ENABLED"] = "false"
        self.addCleanup(lambda: os.environ.pop("THESIS_MONITOR_ENABLED", None))
        result = monitor_thesis(_thesis_snapshot(lifecycle_invalidated=True), "QQQ")
        self.assertEqual(result["status"], "disabled")

    def test_never_raises(self):
        self.assertIn("status", monitor_thesis(None, "QQQ"))
        self.assertIn("status", monitor_thesis({"position_monitor": "bad"}, "QQQ"))


class TestThesisCounterfactualScoring(unittest.TestCase):

    def setUp(self):
        from rule_governance.rule_scoring import score_thesis_events
        self.score = score_thesis_events

    @staticmethod
    def _thesis_event(r_at_signal, realized_r):
        return {
            "event_type": "thesis_exit_shadow", "rule_id": "TFX-001",
            "event_id": f"EV_{r_at_signal}_{realized_r}",
            "fire_reason": "lifecycle_invalidated: test",
            "r_at_signal": r_at_signal,
            "resolution": {"state": "resolved", "source": "fill",
                           "r": realized_r},
        }

    def test_exit_would_have_saved(self):
        # signaled at -0.3R, trade closed at -0.96R -> saved 0.66R
        card = self.score([self._thesis_event(-0.3, -0.96)])
        self.assertEqual(card["saved_R"], 0.66)
        self.assertEqual(card["cut_winners_R"], 0.0)
        self.assertEqual(card["net_saved_R"], 0.66)

    def test_exit_would_have_cut_a_winner(self):
        # signaled at -0.2R, trade recovered to +2.0R -> cut 2.2R
        card = self.score([self._thesis_event(-0.2, 2.0)])
        self.assertEqual(card["saved_R"], 0.0)
        self.assertEqual(card["cut_winners_R"], 2.2)
        self.assertEqual(card["net_saved_R"], -2.2)

    def test_mixed_record_nets_out(self):
        card = self.score([
            self._thesis_event(-0.3, -0.96),   # +0.66 saved
            self._thesis_event(-0.2, 2.0),     # -2.2
            self._thesis_event(-0.1, -1.0),    # +0.9 saved
        ])
        self.assertEqual(card["signals_resolved"], 3)
        self.assertEqual(card["saved_R"], 1.56)
        self.assertEqual(card["cut_winners_R"], 2.2)
        self.assertAlmostEqual(card["net_saved_R"], -0.64)

    def test_pending_events_excluded(self):
        ev = self._thesis_event(-0.3, -0.96)
        ev["resolution"] = {"state": "pending"}
        card = self.score([ev])
        self.assertEqual(card["signals_total"], 1)
        self.assertEqual(card["signals_resolved"], 0)

    def test_never_raises(self):
        self.assertIn("rule_id", self.score([{"bad": 1}, None]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

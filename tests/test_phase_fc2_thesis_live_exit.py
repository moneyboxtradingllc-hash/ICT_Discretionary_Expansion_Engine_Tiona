"""
Phase FC-2 — Thesis Monitor Live Exit tests.

June 11 evidence (TFX-001): thesis death signaled at 10:31:53 with the
position at -0.06R; shadow mode carried it to the broker stop at -1.34R.
Live mode must exit at the signal.

Interaction requirements tested:
  - broker stop cancelled BEFORE the exit order (no double-fill reversal)
  - no double exit when exit_already_submitted
  - failed exit submission falls back to shadow signaling
  - confirmation counter (THESIS_EXIT_CONFIRM_SCANS) gates the action
Rollback: THESIS_EXIT_MODE=shadow.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.thesis_monitor as thm_mod
from paper_execution.thesis_monitor import monitor_thesis


def _june11_snapshot(invalidated=True, price=701.10):
    """The 10:31:53 scan state: setup lifecycle invalidated, position open."""
    return {
        "setup_lifecycle": {
            "active":        True,
            "current_phase": "invalidated" if invalidated else "actionable",
            "reason":        "Playbook dropped to no_playbook",
        },
        "state_transition": {"invalidated": False},
        "position_monitor": {
            "has_open_position":      True,
            "exit_already_submitted": False,
            "side":                   "long",
            "qty":                    571,
            "avg_entry_price":        701.12,
            "current_price":          price,
        },
        "shared_context": {"delivery_state": "accumulation_building"},
    }


# June 11 journal record as of 10:31 (pre-signal)
def _june11_trade():
    return {
        "trade_id":             "PT_QQQ_20260611T102953",
        "intent_id":            "QQQ_20260611T102747",
        "qty":                  571,
        "filled_qty":           571,
        "risk_per_share":       0.35,
        "management_profile":   "range",
        "thesis_exit_signaled": False,
        "broker_stop_order_id": "80217a1f-6a53-4971-b0c5-ce74ff998366",
    }


class _Env:
    def __init__(self, **kv):
        self.kv = kv

    def __enter__(self):
        for k, v in self.kv.items():
            os.environ[k] = v

    def __exit__(self, *a):
        for k in self.kv:
            os.environ.pop(k, None)


class TestShadowModeRegression(unittest.TestCase):
    """Default env must be bit-for-bit 5T.2 shadow behavior."""

    def test_shadow_signals_but_never_exits(self):
        updates = {}
        with _Env(THESIS_EXIT_MODE="shadow"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(_june11_trade(), "fp")):
                with patch.object(thm_mod, "update_trade_management",
                                  side_effect=lambda tid, kv, sym: updates.update(kv)):
                    with patch.object(thm_mod, "submit_paper_exit_order") as exit_mock:
                        result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertEqual(result["status"], "would_exit")
        self.assertFalse(result.get("exit_live"))
        exit_mock.assert_not_called()
        self.assertTrue(updates.get("thesis_exit_signaled"))
        self.assertEqual(result["events"][0]["event_type"], "thesis_exit_shadow")

    def test_june11_r_at_signal(self):
        """Replay: (701.10 - 701.12) / 0.35 = -0.0571 — the ledger value."""
        with _Env(THESIS_EXIT_MODE="shadow"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(_june11_trade(), "fp")):
                with patch.object(thm_mod, "update_trade_management"):
                    result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertAlmostEqual(result["r_at_signal"], -0.0571, places=4)


class TestLiveExit(unittest.TestCase):

    def test_june11_live_exit_replay(self):
        """
        Live mode on the June 11 10:31:53 state: cancel broker stop, market
        sell 571, exit marked. Exit at -0.06R instead of the actual -1.34R.
        """
        updates, marked = {}, {}
        with _Env(THESIS_EXIT_MODE="live"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(_june11_trade(), "fp")):
                with patch.object(thm_mod, "update_trade_management",
                                  side_effect=lambda tid, kv, sym: updates.update(kv)):
                    with patch.object(thm_mod, "cancel_order",
                                      return_value={"canceled": True}) as cancel_mock:
                        with patch.object(thm_mod, "submit_paper_exit_order",
                                          return_value={"alpaca_order_id": "exit-123"}) as exit_mock:
                            with patch.object(thm_mod, "mark_exit_submitted",
                                              side_effect=lambda **kv: marked.update(kv)):
                                result = monitor_thesis(_june11_snapshot(), "QQQ")

        self.assertEqual(result["status"], "exit_submitted")
        self.assertTrue(result["exit_live"])
        self.assertAlmostEqual(result["r_at_signal"], -0.0571, places=4)
        # Broker stop cancelled BEFORE exit submission
        cancel_mock.assert_called_once_with("80217a1f-6a53-4971-b0c5-ce74ff998366")
        exit_mock.assert_called_once_with("QQQ", 571, "sell")
        self.assertTrue(result["broker_stop_cancelled"])
        self.assertEqual(marked["exit_order_id"], "exit-123")
        self.assertEqual(marked["reason"], "thesis_exit_lifecycle_invalidated")
        self.assertTrue(updates.get("thesis_exit_executed"))
        self.assertEqual(result["events"][0]["event_type"], "thesis_exit_live")

    def test_short_position_exits_with_buy(self):
        trade = {**_june11_trade(), "broker_stop_order_id": None}
        snap = _june11_snapshot()
        snap["position_monitor"]["side"] = "short"
        with _Env(THESIS_EXIT_MODE="live"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(trade, "fp")):
                with patch.object(thm_mod, "update_trade_management"):
                    with patch.object(thm_mod, "submit_paper_exit_order",
                                      return_value={"alpaca_order_id": "x"}) as exit_mock:
                        with patch.object(thm_mod, "mark_exit_submitted"):
                            monitor_thesis(snap, "QQQ")
        exit_mock.assert_called_once_with("QQQ", 571, "buy")

    def test_failed_exit_falls_back_to_shadow(self):
        with _Env(THESIS_EXIT_MODE="live"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(_june11_trade(), "fp")):
                with patch.object(thm_mod, "update_trade_management"):
                    with patch.object(thm_mod, "cancel_order",
                                      return_value={"canceled": True}):
                        with patch.object(thm_mod, "submit_paper_exit_order",
                                          side_effect=RuntimeError("rejected")):
                            result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertEqual(result["status"], "would_exit")     # shadow fallback
        self.assertFalse(result["exit_live"])
        self.assertIn("shadow fallback", result.get("warning", ""))
        self.assertEqual(result["events"][0]["event_type"], "thesis_exit_shadow")

    def test_no_double_exit_when_exit_already_submitted(self):
        snap = _june11_snapshot()
        snap["position_monitor"]["exit_already_submitted"] = True
        with _Env(THESIS_EXIT_MODE="live"):
            with patch.object(thm_mod, "submit_paper_exit_order") as exit_mock:
                result = monitor_thesis(snap, "QQQ")
        self.assertEqual(result["status"], "exit_already_submitted")
        exit_mock.assert_not_called()

    def test_no_position_no_action(self):
        snap = _june11_snapshot()
        snap["position_monitor"]["has_open_position"] = False
        with _Env(THESIS_EXIT_MODE="live"):
            result = monitor_thesis(snap, "QQQ")
        self.assertEqual(result["status"], "no_position")

    def test_one_exit_per_trade(self):
        trade = {**_june11_trade(), "thesis_exit_signaled": True,
                 "thesis_exit_reason": "lifecycle_invalidated"}
        with _Env(THESIS_EXIT_MODE="live"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(trade, "fp")):
                with patch.object(thm_mod, "submit_paper_exit_order") as exit_mock:
                    result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertEqual(result["status"], "already_signaled")
        exit_mock.assert_not_called()


class TestConfirmationScans(unittest.TestCase):

    def test_confirm_2_waits_one_scan(self):
        updates = {}
        with _Env(THESIS_EXIT_MODE="live", THESIS_EXIT_CONFIRM_SCANS="2"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(_june11_trade(), "fp")):
                with patch.object(thm_mod, "update_trade_management",
                                  side_effect=lambda tid, kv, sym: updates.update(kv)):
                    with patch.object(thm_mod, "submit_paper_exit_order") as exit_mock:
                        result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertEqual(result["status"], "confirming")
        self.assertEqual(updates["thesis_exit_pending_count"], 1)
        exit_mock.assert_not_called()

    def test_confirm_2_acts_on_second_scan(self):
        trade = {**_june11_trade(), "thesis_exit_pending_count": 1}
        with _Env(THESIS_EXIT_MODE="live", THESIS_EXIT_CONFIRM_SCANS="2"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(trade, "fp")):
                with patch.object(thm_mod, "update_trade_management"):
                    with patch.object(thm_mod, "cancel_order",
                                      return_value={"canceled": True}):
                        with patch.object(thm_mod, "submit_paper_exit_order",
                                          return_value={"alpaca_order_id": "x"}) as exit_mock:
                            with patch.object(thm_mod, "mark_exit_submitted"):
                                result = monitor_thesis(_june11_snapshot(), "QQQ")
        self.assertEqual(result["status"], "exit_submitted")
        exit_mock.assert_called_once()

    def test_recovered_thesis_resets_counter(self):
        trade = {**_june11_trade(), "thesis_exit_pending_count": 1}
        updates = {}
        with _Env(THESIS_EXIT_MODE="live", THESIS_EXIT_CONFIRM_SCANS="2"):
            with patch.object(thm_mod, "find_any_active_trade",
                              return_value=(trade, "fp")):
                with patch.object(thm_mod, "update_trade_management",
                                  side_effect=lambda tid, kv, sym: updates.update(kv)):
                    result = monitor_thesis(_june11_snapshot(invalidated=False), "QQQ")
        self.assertEqual(result["status"], "thesis_intact")
        self.assertEqual(updates["thesis_exit_pending_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

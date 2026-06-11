"""
Broker Position Supremacy test suite.

Exposure is truth. Journal is bookkeeping. When they disagree: BROKER WINS.
Includes the validation drill replicating the 2026-06-11 failure exactly.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import paper_execution.position_supremacy as ps_mod
from paper_execution.position_supremacy import (
    enforce_position_supremacy,
    ensure_protective_stop,
)


def _pos(side="long", qty=571, avg=701.12, current=702.5):
    return {"side": side, "qty": str(qty), "avg_entry_price": avg,
            "current_price": current, "symbol": "QQQ"}


def _trade(status="new", **over):
    t = {"trade_id": "PT_QQQ_X", "symbol": "QQQ", "side": "buy",
         "qty": 571, "order_status": status,
         "entry_reference": 701.14, "stop_reference": 700.79,
         "current_stop_reference": None,
         "risk_per_share": 0.35, "exit_submitted": False,
         "alpaca_order_id": "ALP1", "broker_stop_order_id": None}
    t.update(over)
    return t


def _stop_order(side="sell", qty=571, order_id="STOP1"):
    return {"order_id": order_id, "symbol": "QQQ", "side": side,
            "qty": str(qty), "order_type": "stop", "type": "stop",
            "stop_price": 700.79}


class _Base(unittest.TestCase):
    """Patches the broker/journal surface of position_supremacy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["OPS_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("OPS_DIR", None))

        self.synced  = []   # update_trade_status calls
        self.stops   = []   # submit_protective_stop calls
        self.cancels = []
        self.adopted = []   # append_trade calls

        self.patches = [
            patch.object(ps_mod, "update_trade_status",
                         side_effect=lambda tid, st, extra, sym:
                         self.synced.append((tid, st, extra)) or True),
            patch.object(ps_mod, "submit_protective_stop",
                         side_effect=lambda tid, sym, side, qty, price:
                         self.stops.append((tid, side, qty, price)) or
                         {"stop_submitted": True, "enabled": True,
                          "stop_order_id": "NEWSTOP"}),
            patch.object(ps_mod, "cancel_order",
                         side_effect=lambda oid:
                         self.cancels.append(oid) or {"canceled": True}),
            patch.object(ps_mod, "append_trade",
                         side_effect=lambda rec, sym:
                         self.adopted.append(rec) or True),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_supremacy(self, pos, trade, open_orders=None, order_info=None):
        with patch.object(ps_mod, "get_position", return_value=pos), \
             patch.object(ps_mod, "find_any_active_trade",
                          return_value=(trade, "f.json" if trade else None)), \
             patch.object(ps_mod, "get_open_orders",
                          return_value=open_orders or []), \
             patch.object(ps_mod, "get_order",
                          return_value=order_info):
            return enforce_position_supremacy("QQQ")


# ══════════════════════════════════════════════════════════════════════════════
# Cases 1/2 — broker position + non-filled journal
# ══════════════════════════════════════════════════════════════════════════════

class TestForcedSync(_Base):

    def test_case1_broker_long_journal_new_forced_sync(self):
        result = self.run_supremacy(_pos("long"), _trade("new"))
        self.assertEqual(result["status"], "POSITION_STATE_MISMATCH")
        self.assertTrue(result["mismatch"])
        self.assertTrue(result["forced_sync"])
        self.assertTrue(result["block_entries"])
        # Journal synced to filled with BROKER facts
        tid, status, extra = self.synced[0]
        self.assertEqual(status, "filled")
        self.assertEqual(extra["avg_fill_price"], 701.12)
        self.assertEqual(extra["filled_qty"], 571)
        # Protective stop submitted at journal reference
        self.assertEqual(self.stops[0], ("PT_QQQ_X", "long", 571, 700.79))
        self.assertTrue(result["protected"])

    def test_case2_broker_short_journal_new_forced_sync(self):
        result = self.run_supremacy(
            _pos("short", avg=700.0), _trade("new", side="sell",
                                             stop_reference=701.0))
        self.assertTrue(result["forced_sync"])
        tid, side, qty, price = self.stops[0]
        self.assertEqual(side, "short")     # stop side derives from position
        self.assertEqual(price, 701.0)

    def test_every_nonfilled_status_triggers(self):
        for status in ("new", "pending_new", "accepted", "submitted"):
            self.synced.clear()
            result = self.run_supremacy(_pos(), _trade(status))
            self.assertTrue(result["forced_sync"], status)
            self.assertEqual(self.synced[0][1], "filled", status)

    def test_no_false_positive_when_agreeing(self):
        result = self.run_supremacy(_pos(), _trade("filled"),
                                    open_orders=[_stop_order()])
        self.assertFalse(result["mismatch"])
        self.assertFalse(result["block_entries"])
        self.assertEqual(self.synced, [])
        self.assertEqual(result["case"], "agree")


# ══════════════════════════════════════════════════════════════════════════════
# Case 3 — orphan position
# ══════════════════════════════════════════════════════════════════════════════

class TestOrphanAdoption(_Base):

    def test_orphan_position_adopted_and_protected(self):
        result = self.run_supremacy(_pos("long"), None)
        self.assertEqual(result["case"], "orphan_position")
        self.assertTrue(result["block_entries"])
        self.assertEqual(len(self.adopted), 1)
        rec = self.adopted[0]
        self.assertTrue(rec["trade_id"].startswith("EMERG_QQQ_"))
        self.assertEqual(rec["order_status"], "filled")
        self.assertEqual(rec["qty"], 571)
        # Emergency 1% stop from current price (no journal reference)
        tid, side, qty, price = self.stops[0]
        self.assertAlmostEqual(price, round(702.5 * 0.99, 2))
        # Incident written
        import glob, json
        inc_files = glob.glob(os.path.join(self.tmp.name, "incidents_*.json"))
        self.assertTrue(inc_files)
        with open(inc_files[0], encoding="utf-8") as f:
            incidents = json.load(f)["incidents"]
        self.assertEqual(incidents[0]["type"], "ORPHAN_POSITION_ADOPTED")


# ══════════════════════════════════════════════════════════════════════════════
# Cases 4/5 — broker flat
# ══════════════════════════════════════════════════════════════════════════════

class TestBrokerFlat(_Base):

    def test_case4_journal_filled_broker_flat_reconciles(self):
        with patch("paper_execution.trade_reconciliation.reconcile_trade",
                   return_value={"status": "closed"}) as recon:
            result = self.run_supremacy(None, _trade("filled"))
        self.assertEqual(result["case"], "externally_closed")
        self.assertTrue(result["mismatch"])
        recon.assert_called_once_with("QQQ")

    def test_case5_pending_with_matching_broker_order_ok(self):
        result = self.run_supremacy(
            None, _trade("new"),
            open_orders=[{"order_id": "ALP1", "order_type": "limit"}])
        self.assertEqual(result["case"], "pending")
        self.assertFalse(result["mismatch"])
        self.assertFalse(result["block_entries"])

    def test_case5_stale_pending_marked_terminal(self):
        result = self.run_supremacy(
            None, _trade("new"), open_orders=[],
            order_info={"status": "canceled"})
        self.assertEqual(result["case"], "stale_pending")
        self.assertEqual(self.synced[0][1], "canceled")

    def test_case5_no_order_info_marks_expired(self):
        result = self.run_supremacy(None, _trade("submitted"),
                                    open_orders=[], order_info=None)
        self.assertEqual(self.synced[0][1], "expired")

    def test_flat_and_no_trade_all_clear(self):
        result = self.run_supremacy(None, None)
        self.assertEqual(result["case"], "flat")
        self.assertFalse(result["mismatch"])


# ══════════════════════════════════════════════════════════════════════════════
# Broker stop assurance
# ══════════════════════════════════════════════════════════════════════════════

class TestStopAssurance(_Base):

    def _ensure(self, pos, trade, open_orders):
        with patch.object(ps_mod, "get_open_orders", return_value=open_orders):
            return ensure_protective_stop("QQQ", pos, trade)

    def test_missing_stop_submitted(self):
        result = self._ensure(_pos(), _trade("filled"), [])
        self.assertTrue(result["protected"])
        self.assertEqual(result["action"], "submitted")
        self.assertEqual(self.stops[0][2], 571)

    def test_wrong_qty_corrected_new_stop_before_cancel(self):
        result = self._ensure(_pos(qty=571), _trade("filled"),
                              [_stop_order(qty=400)])
        self.assertTrue(result["protected"])
        self.assertEqual(result["action"], "corrected")
        self.assertEqual(self.stops[0][2], 571)      # correct qty submitted
        self.assertEqual(self.cancels, ["STOP1"])    # bad stop cancelled AFTER

    def test_wrong_side_corrected(self):
        result = self._ensure(_pos("long"), _trade("filled"),
                              [_stop_order(side="buy")])
        self.assertEqual(result["action"], "corrected")
        self.assertEqual(self.stops[0][1], "long")   # position side passed

    def test_correct_stop_verified_untouched(self):
        result = self._ensure(_pos(), _trade("filled"), [_stop_order()])
        self.assertEqual(result["action"], "verified")
        self.assertEqual(self.stops, [])
        self.assertEqual(self.cancels, [])

    def test_submission_failure_enters_emergency_management(self):
        for p in self.patches:
            p.stop()
        with patch.object(ps_mod, "submit_protective_stop",
                          return_value={"stop_submitted": False,
                                        "enabled": True,
                                        "reason": "rejected"}), \
             patch.object(ps_mod, "get_open_orders", return_value=[]):
            result = ensure_protective_stop("QQQ", _pos(), _trade("filled"))
        self.assertFalse(result["protected"])
        self.assertEqual(result["action"], "emergency_management")
        for p in self.patches:
            p.start()


# ══════════════════════════════════════════════════════════════════════════════
# Trade manager invariant
# ══════════════════════════════════════════════════════════════════════════════

class TestTradeManagerInvariant(unittest.TestCase):

    def test_manage_does_not_return_not_filled_when_position_exists(self):
        """2026-06-11 invariant: broker exposure must be managed even if the
        journal status is stale."""
        import paper_execution.trade_manager as tm_mod
        import paper_execution.management_policies as mp_mod
        from paper_execution.trade_manager import manage_open_trade

        record = {"trade_id": "T1", "order_status": "new",   # stale!
                  "risk_per_share": 0.35, "breakeven_triggered": False,
                  "take_profit_triggered": False,
                  "management_profile": "defensive"}
        snap = {
            "position_monitor": {
                "has_open_position": True, "exit_already_submitted": False,
                "linked_trade_id": "T1", "current_price": 701.3,
                "side": "long", "qty": 571, "avg_entry_price": 701.12,
            },
            "regime_permissions": {"management_profile": "defensive"},
            "toolbox": {"tool_candidates": []},
        }
        with patch.object(tm_mod, "find_any_active_trade",
                          return_value=(record, "f.json")), \
             patch.object(tm_mod, "update_trade_management", return_value=True), \
             patch.object(mp_mod, "update_trade_management", return_value=True), \
             patch.object(tm_mod, "is_paper_account_safe",
                          return_value=(True, "ok")):
            result = manage_open_trade(snap, "QQQ")

        self.assertNotIn("not_filled", result.get("reason", ""))
        self.assertIn("INVARIANT VIOLATION", result.get("invariant_violation", ""))
        self.assertEqual(result["action"], "hold")   # it MANAGES (r=+0.51)
        self.assertAlmostEqual(result["unrealized_r"], 0.5143, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION DRILL — replicate the 2026-06-11 failure exactly
# ══════════════════════════════════════════════════════════════════════════════

class TestJune11ValidationDrill(_Base):
    """order status 'new' + broker position exists + journal not filled."""

    def test_todays_failure_is_now_impossible(self):
        # Exact incident state: filled 571 @ 701.12, journal stuck at "new"
        result = self.run_supremacy(
            _pos("long", qty=571, avg=701.12, current=703.49),  # at the +6.77R peak
            _trade("new"),
        )
        # 1. POSITION_STATE_MISMATCH logged
        self.assertEqual(result["status"], "POSITION_STATE_MISMATCH")
        # 2. journal force-synced from broker facts
        self.assertTrue(result["forced_sync"])
        self.assertEqual(self.synced[0][1], "filled")
        self.assertEqual(self.synced[0][2]["avg_fill_price"], 701.12)
        # 3. broker stop submitted
        self.assertEqual(self.stops[0], ("PT_QQQ_X", "long", 571, 700.79))
        self.assertTrue(result["protected"])
        # 4. trade_manager allowed to run (invariant tested above; here the
        #    journal is already healed within the same scan)
        # 5. new entries blocked until reconciled
        self.assertTrue(result["block_entries"])
        # incident record written
        import glob
        self.assertTrue(glob.glob(os.path.join(self.tmp.name, "incidents_*.json")))

    def test_supremacy_error_blocks_entries_fail_closed(self):
        with patch.object(ps_mod, "get_position",
                          side_effect=RuntimeError("api down")):
            result = enforce_position_supremacy("QQQ")
        self.assertTrue(result["block_entries"])   # cannot prove flat -> no entries
        self.assertTrue(result["mismatch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

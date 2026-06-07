"""
Phase 1X — Intent Archive + Outcome Tracker unit tests.
Tests outcome_tracker and intent_archive logic.
No execution. No orders. No broker actions.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intent_archive.outcome_tracker import calculate_outcome, should_expire
import intent_archive.intent_archive as ia_mod
from intent_archive.intent_archive import (
    update_archive, _should_archive, _make_archive_key,
)
from ai_layer.ai_snapshot_formatter import format_archive_line


# ── Snapshot fixtures ─────────────────────────────────────────────────────────

def _snap_with_zone(direction="bullish", current_price=480.0, intent_created=True, raw_score=77):
    """Snapshot with a preferred tool that has a price_level and trade_intent entry_zone."""
    return {
        "playbook": {
            "selected_playbook": "liquidity_sweep_reversal",
            "direction": direction,
            "status": "active",
        },
        "toolbox": {
            "preferred_tool": f"{direction}_ifvg",
            "tool_candidates": [
                {
                    "tool": f"{direction}_ifvg",
                    "score": 80,
                    "raw_status": "actionable",
                    "effective_status": "actionable",
                    "price_level": {
                        "level_type": "ifvg_zone",
                        "zone_low": 478.0,
                        "zone_high": 480.0,
                        "midpoint": 479.0,
                        "current_price": current_price,
                        "price_relation": "above_zone",
                        "distance_to_zone": abs(current_price - 480.0),
                    },
                    "trigger_prep": {
                        "raw_trigger_status": "confirmed",
                        "effective_trigger_status": "confirmed",
                        "execution_ready": True,
                    },
                }
            ],
        },
        "trade_intent": {
            "intent_created": intent_created,
            "intent_type": "long" if direction == "bullish" else "short",
            "direction": direction,
            "preferred_tool": f"{direction}_ifvg",
            "entry_zone": {
                "zone_low": 478.0,
                "zone_high": 480.0,
                "midpoint": 479.0,
                "current_price": current_price,
                "price_relation": "above_zone",
            },
            "trigger_status": "confirmed",
            "reason": "All checks passed.",
        },
        "intent_score": {
            "scored": True,
            "raw_score": raw_score,
            "gated_score": raw_score,
            "gated_quality": "strong_watch",
            "gating_applied": False,
        },
        "setup_lifecycle": {
            "active": True,
            "invalidated": False,
            "setup_id": f"QQQ_20260605_liquidity_sweep_reversal_{direction}_{direction}_ifvg_47800_48000",
            "current_phase": "maturing",
        },
        "risk": {"trade_allowed": True, "risk_tier": "normal"},
        "qualification": {"status": "qualified"},
        "ai_context": {"summary": ""},
    }


def _snap_no_intent():
    return {
        "playbook": {"selected_playbook": "no_playbook", "direction": "neutral"},
        "toolbox": {"preferred_tool": None, "tool_candidates": []},
        "trade_intent": {"intent_created": False, "intent_type": "none", "reason": "No setup."},
        "intent_score": {"scored": False, "raw_score": 0, "gated_score": 0, "gated_quality": "no_intent"},
        "setup_lifecycle": {"active": False, "invalidated": False, "setup_id": None},
        "risk": {"trade_allowed": False, "risk_tier": "blocked"},
        "ai_context": {"summary": ""},
    }


def _record_base(direction="bullish", bars=1, mfe=0.0, mae=0.0):
    return {
        "intent_id": "QQQ_20260605T092300",
        "archive_key": "QQQ_20260605_liquidity_sweep_reversal_bullish_bullish_ifvg",
        "setup_id": "QQQ_20260605_liquidity_sweep_reversal_bullish_bullish_ifvg_47800_48000",
        "intent_type": "long",
        "direction": direction,
        "playbook": "liquidity_sweep_reversal",
        "preferred_tool": f"{direction}_ifvg",
        "entry_zone": {
            "zone_low": 478.0,
            "zone_high": 480.0,
            "midpoint": 479.0,
            "current_price": 479.5,
            "price_relation": "inside_zone",
        },
        "raw_score_at_creation": 77,
        "gated_score_at_creation": 77,
        "quality_at_creation": "strong_watch",
        "status": "open",
        "created_at": "20260605T092300",
        "last_updated": "20260605T092300",
        "bars_since_creation": bars,
        "mfe": mfe,
        "mae": mae,
        "zone_was_touched": False,
        "trigger_became_ready": False,
        "expiration_reason": None,
        "scan_updates": [],
    }


# ── calculate_outcome tests ───────────────────────────────────────────────────

class TestCalculateOutcome(unittest.TestCase):

    def test_01_long_mfe_above_midpoint(self):
        """Long trade: price above midpoint => MFE positive, MAE zero."""
        snap   = _snap_with_zone(direction="bullish", current_price=481.0)
        record = _record_base(direction="bullish")
        result = calculate_outcome(snap, record)
        # midpoint=479.0, current=481.0 → mfe=2.0, mae=0
        self.assertAlmostEqual(result["mfe_candidate"], 2.0, places=3)
        self.assertEqual(result["mae_candidate"], 0.0)
        self.assertFalse(result["zone_touched_this_scan"])
        self.assertTrue(result["trigger_ready_this_scan"])

    def test_02_long_mae_below_midpoint(self):
        """Long trade: price below midpoint => MAE positive, MFE zero."""
        snap   = _snap_with_zone(direction="bullish", current_price=477.0)
        record = _record_base(direction="bullish")
        result = calculate_outcome(snap, record)
        # midpoint=479.0, current=477.0 → mfe=0, mae=2.0
        self.assertEqual(result["mfe_candidate"], 0.0)
        self.assertAlmostEqual(result["mae_candidate"], 2.0, places=3)

    def test_03_short_mfe_below_midpoint(self):
        """Short trade: price below midpoint => MFE positive."""
        snap   = _snap_with_zone(direction="bearish", current_price=477.0)
        record = _record_base(direction="bearish")
        result = calculate_outcome(snap, record)
        self.assertGreater(result["mfe_candidate"], 0.0)
        self.assertEqual(result["mae_candidate"], 0.0)

    def test_04_zone_touched_when_inside(self):
        """zone_was_touched=True when price_relation is inside_zone."""
        snap = _snap_with_zone(direction="bullish", current_price=479.5)
        # Override price_relation to inside_zone
        snap["toolbox"]["tool_candidates"][0]["price_level"]["price_relation"] = "inside_zone"
        record = _record_base(direction="bullish")
        result = calculate_outcome(snap, record)
        self.assertTrue(result["zone_touched_this_scan"])

    def test_05_no_price_level_returns_zeros(self):
        """Missing price_level returns zero candidates."""
        snap = _snap_no_intent()
        record = _record_base(direction="bullish")
        result = calculate_outcome(snap, record)
        self.assertEqual(result["mfe_candidate"], 0.0)
        self.assertEqual(result["mae_candidate"], 0.0)
        self.assertIsNone(result["current_price"])


# ── should_expire tests ───────────────────────────────────────────────────────

class TestShouldExpire(unittest.TestCase):

    def _outcome_above_zone(self):
        return {
            "mfe_candidate": 2.0,
            "mae_candidate": 0.0,
            "zone_touched_this_scan": False,
            "trigger_ready_this_scan": False,
            "current_price": 481.0,
            "distance_from_midpoint": 2.0,
        }

    def test_06_age_exceeded(self):
        record = _record_base(bars=31)
        snap   = _snap_with_zone()
        expire, reason = should_expire(record, snap, self._outcome_above_zone())
        self.assertTrue(expire)
        self.assertEqual(reason, "age_exceeded_30_bars")

    def test_07_setup_invalidated(self):
        record = _record_base(bars=5)
        snap   = _snap_with_zone()
        snap["setup_lifecycle"]["invalidated"] = True
        expire, reason = should_expire(record, snap, self._outcome_above_zone())
        self.assertTrue(expire)
        self.assertEqual(reason, "setup_invalidated")

    def test_08_trigger_invalidated(self):
        record = _record_base(bars=3)
        snap   = _snap_with_zone()
        snap["toolbox"]["tool_candidates"][0]["trigger_prep"]["raw_trigger_status"] = "invalidated"
        expire, reason = should_expire(record, snap, self._outcome_above_zone())
        self.assertTrue(expire)
        self.assertEqual(reason, "trigger_invalidated")

    def test_09_setup_gone_after_5_bars(self):
        record = _record_base(bars=5)
        snap   = _snap_with_zone()
        snap["setup_lifecycle"]["active"] = False
        expire, reason = should_expire(record, snap, self._outcome_above_zone())
        self.assertTrue(expire)
        self.assertEqual(reason, "setup_gone")

    def test_10_price_too_far_adverse_long(self):
        record = _record_base(bars=10, direction="bullish")
        snap   = _snap_with_zone()
        # zone_low=478, zone_high=480, zone_width=2, 3x=6 → below 472
        outcome = {
            "mfe_candidate": 0.0,
            "mae_candidate": 12.0,
            "zone_touched_this_scan": False,
            "trigger_ready_this_scan": False,
            "current_price": 465.0,  # far below zone
            "distance_from_midpoint": 14.0,  # > 3*2=6
        }
        expire, reason = should_expire(record, snap, outcome)
        self.assertTrue(expire)
        self.assertEqual(reason, "price_too_far_adverse")

    def test_11_no_expiry_for_healthy_record(self):
        record = _record_base(bars=3)
        snap   = _snap_with_zone()
        expire, _ = should_expire(record, snap, self._outcome_above_zone())
        self.assertFalse(expire)


# ── update_archive tests ──────────────────────────────────────────────────────

class TestUpdateArchive(unittest.TestCase):

    def _run_archive(self, snapshot, symbol="QQQ"):
        """Run update_archive with a temp file, return (result, intents_on_disk)."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            with patch.object(ia_mod, "_archive_filepath", return_value=tmp_path):
                result = update_archive(snapshot, symbol)

            if os.path.exists(tmp_path):
                with open(tmp_path, encoding="utf-8") as f:
                    data = json.load(f)
                intents = data.get("intents", [])
            else:
                intents = []
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return result, intents

    def test_12_no_archive_when_no_intent(self):
        """No record created when intent_created=False and raw_score < 55."""
        result, intents = self._run_archive(_snap_no_intent())
        self.assertIsNone(result["active_intent_id"])
        self.assertEqual(len(intents), 0)
        self.assertFalse(result["new_record_created"])

    def test_13_creates_record_on_intent_created(self):
        """A new record is created when intent_created=True."""
        result, intents = self._run_archive(_snap_with_zone())
        self.assertTrue(result["new_record_created"])
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0]["status"], "open")
        self.assertIsNotNone(result["active_intent_id"])

    def test_14_creates_record_on_high_score(self):
        """A new record is created when raw_score >= 55, even if intent_created=False."""
        snap = _snap_with_zone(intent_created=False, raw_score=60)
        result, intents = self._run_archive(snap)
        self.assertTrue(result["new_record_created"])
        self.assertEqual(len(intents), 1)

    def test_15_no_duplicate_on_same_setup_key(self):
        """Second scan with same setup_id does not create a second record."""
        snap = _snap_with_zone()
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            with patch.object(ia_mod, "_archive_filepath", return_value=tmp_path):
                r1 = update_archive(snap, "QQQ")
                r2 = update_archive(snap, "QQQ")

            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            intents = data.get("intents", [])
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        self.assertTrue(r1["new_record_created"])
        self.assertFalse(r2["new_record_created"])
        self.assertEqual(len(intents), 1)

    def test_16_bars_increment_on_second_scan(self):
        """bars_since_creation increments from 1 to 2 on the second scan."""
        snap = _snap_with_zone()
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            with patch.object(ia_mod, "_archive_filepath", return_value=tmp_path):
                update_archive(snap, "QQQ")
                r2 = update_archive(snap, "QQQ")

            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            record = data["intents"][0]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        self.assertEqual(record["bars_since_creation"], 2)
        self.assertEqual(r2["bars_active"], 2)

    def test_17_mfe_accumulates(self):
        """MFE grows when price moves favorably."""
        snap1 = _snap_with_zone(current_price=481.0)
        snap2 = _snap_with_zone(current_price=483.0)
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            with patch.object(ia_mod, "_archive_filepath", return_value=tmp_path):
                update_archive(snap1, "QQQ")
                r2 = update_archive(snap2, "QQQ")

            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            record = data["intents"][0]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        # midpoint=479 → price 483 → mfe=4.0
        self.assertAlmostEqual(record["mfe"], 4.0, places=3)
        self.assertGreater(r2["mfe"], 0.0)

    def test_18_expired_record_count(self):
        """A record is expired when setup_lifecycle.invalidated=True."""
        snap_init = _snap_with_zone()
        snap_inv  = _snap_with_zone()
        snap_inv["setup_lifecycle"]["invalidated"] = True

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            with patch.object(ia_mod, "_archive_filepath", return_value=tmp_path):
                update_archive(snap_init, "QQQ")
                r2 = update_archive(snap_inv, "QQQ")

            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            record = data["intents"][0]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        self.assertEqual(record["status"], "expired")
        self.assertEqual(r2["expired_this_scan"], 1)
        self.assertEqual(r2["open_count"], 0)
        self.assertIsNone(r2["active_intent_id"])


# ── format_archive_line tests ─────────────────────────────────────────────────

class TestFormatArchiveLine(unittest.TestCase):

    def test_19_empty_when_no_active_id(self):
        self.assertEqual(format_archive_line({}), "")
        self.assertEqual(format_archive_line({"active_intent_id": None}), "")

    def test_20_formats_open_record(self):
        ia = {
            "active_intent_id": "QQQ_20260605T092315",
            "active_status": "open",
            "mfe": 1.25,
            "mae": 0.42,
            "zone_touched": False,
            "bars_active": 6,
        }
        line = format_archive_line(ia)
        self.assertIn("OPEN", line)
        self.assertIn("mfe=1.25", line)
        self.assertIn("mae=0.42", line)
        self.assertIn("zone_touched=false", line)
        self.assertIn("bars=6", line)

    def test_21_short_id_used(self):
        """Long intent_id is truncated to last 15 chars in the line."""
        ia = {
            "active_intent_id": "QQQ_20260605T092315_extra_long_suffix",
            "active_status": "open",
            "mfe": 0.0, "mae": 0.0, "zone_touched": False, "bars_active": 1,
        }
        line = format_archive_line(ia)
        self.assertIn("...", line)


# ── _should_archive helper tests ──────────────────────────────────────────────

class TestShouldArchive(unittest.TestCase):

    def test_22_false_when_no_intent_and_low_score(self):
        self.assertFalse(_should_archive(_snap_no_intent()))

    def test_23_true_when_intent_created(self):
        self.assertTrue(_should_archive(_snap_with_zone()))

    def test_24_true_when_score_above_55(self):
        snap = _snap_with_zone(intent_created=False, raw_score=60)
        self.assertTrue(_should_archive(snap))

    def test_25_false_when_score_below_55(self):
        snap = _snap_with_zone(intent_created=False, raw_score=54)
        snap["trade_intent"]["intent_created"] = False
        self.assertFalse(_should_archive(snap))


if __name__ == "__main__":
    unittest.main()

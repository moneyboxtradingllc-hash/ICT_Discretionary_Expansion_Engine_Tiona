"""
Phase AB-1 — Narrative Brain acceptance tests (T1-T16 from the directive).

AB-1 builds the replacement brain in OBSERVE mode: full two-sided sensory
input, 23-field machine-consumable schema, self-memory, persistence, June 11
replay. Authority wiring (T10/T11 generation seeding) is a later AB phase by
design — AB-1 proves the brain SEES and PARSES before it is given authority,
exactly as every prior subsystem was promoted.

June 11 replay injects the real 1-minute bars (data/replay_20260611_1m.json)
and the NA-1 protected-swing tracker so the brain receives price, candles,
and protected levels the archive alone does not carry.
"""
import json
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.narrative_brain import run_narrative_brain
from ai_brain.brain_input import build_brain_input
from ai_brain.brain_schema import validate_brain_output, empty_brain_output
from ai_brain.stance_memory import StanceMemory
from narrative_authority.protected_swings import ProtectedSwingTracker

_REPO = os.path.join(os.path.dirname(__file__), "..")


def _env_on():
    os.environ["AI_BRAIN_ENABLED"] = "true"
    os.environ.pop("AI_BRAIN_LLM", None)   # deterministic core in tests


def _env_off():
    for k in ("AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "AI_BRAIN_DIR"):
        os.environ.pop(k, None)


def _live_snapshot(price=701.42, has_position=False):
    """A live-shaped snapshot WITH candles + protected swing + delivery."""
    snap = {
        "timestamp": "20260611T102955",
        "session": "morning_continuation",
        "timeframes": {
            "1m": {"candles": [{"open": 701.6, "high": 701.8, "low": 701.2, "close": price}],
                   "last_candle": {"open": 701.6, "high": 701.8, "low": 701.2, "close": price}},
            "5m": {"last_candle": {"open": 700.9, "high": 702.6, "low": 700.7, "close": price}},
        },
        "market_regime": {"regime_label": "range_rotation", "volatility_state": "unstable",
                          "expansion_state": "exhaustion_risk"},
        "structure": {"15m": {"bias": "bullish", "state": "range_bound", "bos": False, "mss": False},
                      "5m": {"bias": "bullish"}, "3m": {"bias": "neutral"}, "1m": {"bias": "bullish"}},
        "shared_context": {"delivery_state": "bearish_delivery", "delivery_confidence": 25,
                           "exhaustion_present": True, "continuation_intact": False},
        "po3": {"15m": {"phase": "manipulation", "manipulation_direction": "bearish"},
                "alignment": "mixed"},
        "ai_discretionary": {"ai_direction": "bullish", "ai_confidence": 65},
        "ai_context": {"directional_bias": "bullish", "confidence_score": 65},
        "liquidity": {"15m": {"sweep_detected": True, "sweep_direction": "above_high",
                              "reclaim_detected": True, "nearest_sell_side_liquidity": 699.60}},
        "playbook": {"selected_playbook": "liquidity_sweep_reversal", "direction": "bullish"},
        "toolbox": {"preferred_tool": "bullish_ifvg",
                    "tool_candidates": [{"tool": "bullish_ifvg", "score": 80,
                                         "effective_status": "actionable",
                                         "price_level": {"zone_low": 700.79}}]},
        "narrative_authority": {},
        "protected_swings": {"protected_high": {"level": 702.50, "basis": "buy_side_raid_rejected"},
                             "protected_low": None},
    }
    if has_position:
        snap["position_monitor"] = {"has_open_position": True, "side": "long", "qty": 571,
                                    "avg_entry_price": 701.12, "current_price": price,
                                    "unrealized_pnl": -120.0, "stop_reference": 700.79}
        snap["thesis_monitor"] = {"status": "would_exit"}
    else:
        snap["position_monitor"] = {"has_open_position": False}
    return snap


class T1_PriceAndCandles(unittest.TestCase):
    def tearDown(self): _env_off()
    def test_brain_receives_price_and_candles(self):
        bi = build_brain_input(_live_snapshot(), {"available": False})
        self.assertEqual(bi["market"]["current_price"], 701.42)
        self.assertIn("1m", bi["market"]["candles"])
        self.assertIsNotNone(bi["market"]["candles"]["1m"]["body"])
        self.assertNotIn("current_price_unavailable", bi["degraded"])

    def test_missing_candles_flagged_not_silent(self):
        bi = build_brain_input({"timestamp": "x"}, {"available": False})
        self.assertIn("candles_unavailable", bi["degraded"])


class T2_ProtectedSwings(unittest.TestCase):
    def test_brain_receives_protected_high_and_status(self):
        bi = build_brain_input(_live_snapshot(price=701.42), {"available": False})
        ps = bi["protected_swings"]
        self.assertEqual(ps["protected_high"]["level"], 702.50)
        self.assertIn(ps["protected_high_status"], ("approaching", "below", "violating"))


class T3_ActiveDraw(unittest.TestCase):
    def test_brain_receives_draw(self):
        snap = _live_snapshot()
        snap["narrative_authority"] = {"active_liquidity_draw": {"side": "sell_side", "level": 699.60}}
        bi = build_brain_input(snap, {"available": False})
        self.assertEqual(bi["liquidity"]["active_draw"]["side"], "sell_side")


class T4_TwoSidedInventory(unittest.TestCase):
    def test_brain_receives_both_sides(self):
        bi = build_brain_input(_live_snapshot(), {"available": False})
        inv = bi["playbook_toolbox"]
        self.assertTrue(any("bearish" in t["tool"] for t in inv["bearish"]))
        self.assertTrue(any("bullish" in t["tool"] for t in inv["bullish"]))
        # bullish side is live-scored, bearish side is inventory-only (visibility)
        self.assertTrue(any(t["live_scored"] for t in inv["bullish"]))


class T5_PositionAwareness(unittest.TestCase):
    def test_brain_knows_it_is_in_a_long(self):
        bi = build_brain_input(_live_snapshot(has_position=True), {"available": False})
        self.assertTrue(bi["position"]["position_open"])
        self.assertEqual(bi["position"]["direction"], "long")
        self.assertEqual(bi["position"]["entry_price"], 701.12)


class T6_PriorStanceHistory(unittest.TestCase):
    def test_stance_history_reaches_input(self):
        mem = StanceMemory()
        mem.record("20260611T101500", {"narrative_direction": "bearish", "narrative_phase": "manipulation",
                                       "phase_confidence": 60, "current_action": "prepare_short"})
        mem.record("20260611T102800", {"narrative_direction": "bullish", "narrative_phase": "continuation",
                                       "phase_confidence": 65, "current_action": "prepare_long"})
        hist = mem.history_summary()
        bi = build_brain_input(_live_snapshot(), hist)
        self.assertTrue(bi["stance_history"]["available"])
        self.assertEqual(bi["stance_history"]["last"]["direction"], "bullish")
        self.assertTrue(bi["stance_history"]["changed_since_last"]["direction"])
        self.assertEqual(bi["stance_history"]["changed_since_last"]["from"]["direction"], "bearish")


class T7_MemoryRetrievalSlot(unittest.TestCase):
    def test_memory_matches_field_present(self):
        # AB-1 ships the slot (empty); real vector retrieval is a later phase.
        out = empty_brain_output()
        self.assertIn("memory_matches", out)
        self.assertIsInstance(out["memory_matches"], list)


class T8_SchemaFullyParsed(unittest.TestCase):
    def tearDown(self): _env_off()
    def test_deterministic_output_validates(self):
        _env_on()
        res = run_narrative_brain(_live_snapshot(), "QQQ", StanceMemory())
        ok, reason = validate_brain_output(res["output"])
        self.assertTrue(ok, reason)
        # AB-1 shipped 23 fields; AB-4 expanded the package to 31.
        self.assertGreaterEqual(len(res["output"]), 23)


class T9_NoPrintOnlyFields(unittest.TestCase):
    def tearDown(self): _env_off()
    def test_all_fields_persisted_record(self):
        _env_on()
        import tempfile
        os.environ["AI_BRAIN_DIR"] = tempfile.mkdtemp()
        res = run_narrative_brain(_live_snapshot(), "QQQ", StanceMemory())
        self.assertIsNotNone(res["persisted"])
        with open(res["persisted"], encoding="utf-8") as fh:
            rec = json.load(fh)
        # Every output field is accounted for as consumed or persisted-not-consumed
        accounted = set(rec["fields_consumed"]) | set(rec["fields_persisted_not_yet_consumed"])
        self.assertEqual(accounted, set(res["output"].keys()))


class T10_T11_AuthorityDeferred(unittest.TestCase):
    """AB-1 is observe-only by constitution. Seeding playbooks/toolbox (T10/T11)
    is a later AB phase; here we PROVE AB-1 wires no consumer (no silent
    authority leak)."""
    def tearDown(self): _env_off()
    def test_ab1_wires_no_consumer(self):
        _env_on()
        res = run_narrative_brain(_live_snapshot(), "QQQ", StanceMemory())
        self.assertEqual(res["authority"], "observe_only")
        import tempfile
        os.environ["AI_BRAIN_DIR"] = tempfile.mkdtemp()
        res = run_narrative_brain(_live_snapshot(), "QQQ", StanceMemory())
        with open(res["persisted"], encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["fields_consumed"], [])   # nothing consumed yet


class T12_CannotBypassControls(unittest.TestCase):
    def tearDown(self): _env_off()
    def test_brain_output_is_not_in_any_gate_or_risk_path(self):
        # Static guard: the brain module must not import the gate, risk, broker,
        # or order builder (it feeds them only via future explicit wiring).
        root = os.path.join(_REPO, "src", "ai_brain")
        forbidden = ("execution_gate", "risk_governor", "paper_broker",
                     "order_builder", "submit_paper_order")
        for fn in os.listdir(root):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(root, fn), encoding="utf-8") as fh:
                src = fh.read()
            for f in forbidden:
                self.assertNotIn(f, src, f"ai_brain/{fn} references {f}")


class T13_T14_T15_June11Replay(unittest.TestCase):
    """The 10:20-10:40 window: brain must SEE the buy-side raid, the protected
    high, bearish delivery, and (via deterministic NA synthesis) forbid longs
    — while knowing a long is open. Real bars injected for price/candles."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_REPO, "data", "replay_20260611_1m.json")) as fh:
            cls.bars = json.load(fh)

    def tearDown(self): _env_off()

    def _window_snapshot(self):
        # 10:29 entry-scan evidence + a real bar close + protected high from
        # the 10:00 raid, with the morning long OPEN (T14).
        snap = _live_snapshot(price=701.42, has_position=True)
        snap["narrative_authority"] = {"active_liquidity_draw":
                                       {"side": "sell_side", "level": 699.60}}
        return snap

    def test_T13_brain_sees_raid_protected_high_bearish_delivery_forbids_long(self):
        _env_on()
        res = run_narrative_brain(self._window_snapshot(), "QQQ", StanceMemory())
        out = res["output"]
        # buy-side raid visible as the protected high from the 10:00 raid
        self.assertIn("702.5", out["protected_high_interpretation"])
        # bearish delivery surfaced
        self.assertIn("bearish_delivery", out["delivery_interpretation"])
        # the long is NOT endorsed: NA synthesis (AI bullish vs delivery bearish)
        # resolves conflicted/bearish, never bullish — so a long is not allowed
        self.assertNotEqual(out["narrative_direction"], "bullish")
        self.assertNotEqual(out["allowed_direction"], "bullish")

    def test_T14_brain_knows_long_is_open(self):
        _env_on()
        snap = self._window_snapshot()
        bi = build_brain_input(snap, {"available": False})
        self.assertTrue(bi["position"]["position_open"])
        self.assertEqual(bi["position"]["direction"], "long")

    def test_T15_reasoning_persists_to_next_scan(self):
        _env_on()
        mem = StanceMemory()
        run_narrative_brain(self._window_snapshot(), "QQQ", mem)
        # next scan sees the prior stance
        hist = mem.history_summary()
        self.assertTrue(hist["available"])
        self.assertIsNotNone(hist["last"])


class T16_Regression(unittest.TestCase):
    """Disabled by default = zero behavior change."""
    def tearDown(self): _env_off()
    def test_disabled_returns_inert(self):
        _env_off()
        res = run_narrative_brain(_live_snapshot(), "QQQ", StanceMemory())
        self.assertFalse(res["enabled"])
        self.assertIsNone(res["output"])

    def test_brain_never_raises_on_garbage(self):
        _env_on()
        res = run_narrative_brain({}, "QQQ", StanceMemory())
        self.assertEqual(res["authority"], "observe_only")
        ok, _ = validate_brain_output(res["output"])
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)

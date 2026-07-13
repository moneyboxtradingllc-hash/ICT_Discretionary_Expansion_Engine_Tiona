"""
ENTRY-INVARIANT-HARDENING (2026-07-13) — fail-closed + provable-side locks.

Two audited defects in the shipped invariant (c96ea2b):
  1. the exception arm returned eligible=True (fail-OPEN) — an entry
     authority inferring permission from its own failure;
  2. unknown current price accepted a numeric invalidation (the repair-
     adoption helper's unknown-px semantics leaking into an entry authority).
Also found during audit: float('inf') passed the side check; booleans
masqueraded as numbers.

Hardened doctrine: the system must PROVE (a) numeric finite invalidation,
(b) known finite numeric price, (c) strict correct side (equality invalid) —
or FRESH exposure is denied with a machine-readable failure code. This is
fail-closed for NEW ENTRY ONLY: never a bot halt, never position management.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.ecu as ecu                                       # noqa: E402
from ai_brain.ecu import thesis_entry_eligible                   # noqa: E402
from execution_gate.execution_gate import evaluate_gate          # noqa: E402

_ON = {"BRAIN_INVALIDATION_ENTRY_INVARIANT": "on"}


def _snap(direction="bullish", source="llm", inv=None, px=500.0):
    return {
        "brain_thesis": {"owner": "ai_brain", "source": source,
                         "direction": direction, "invalidation_level": inv},
        "trade_intent": {"entry_zone": {"current_price": px}},
    }


def _rec(**kw):
    with patch.dict(os.environ, _ON):
        return thesis_entry_eligible(_snap(**kw))


class TestSideMatrix(unittest.TestCase):
    """Mission Phase 2 items 4-7 + strict equality."""

    def test_bullish_below_passes(self):
        self.assertTrue(_rec(inv=495.0, px=500.0)["eligible"])

    def test_bullish_above_fails(self):
        r = _rec(inv=505.0, px=500.0)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "wrong_side_invalidation")

    def test_bullish_equal_fails(self):
        self.assertFalse(_rec(inv=500.0, px=500.0)["eligible"])

    def test_bearish_above_passes(self):
        self.assertTrue(_rec(direction="bearish", inv=505.0, px=500.0)["eligible"])

    def test_bearish_below_fails(self):
        self.assertFalse(_rec(direction="bearish", inv=495.0, px=500.0)["eligible"])

    def test_bearish_equal_fails(self):
        r = _rec(direction="bearish", inv=500.0, px=500.0)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "wrong_side_invalidation")


class TestUnprovableData(unittest.TestCase):
    """Mission Phase 2 items 8-9 + Phase 7 failure modes."""

    def test_missing_invalidation(self):
        self.assertEqual(_rec(inv=None)["code"], "missing_invalidation")

    def test_boolean_invalidation(self):
        self.assertEqual(_rec(inv=True)["code"], "non_numeric_invalidation")

    def test_string_invalidation(self):
        # no silent float() conversion — normalization upstream owns coercion
        self.assertEqual(_rec(inv="495.0")["code"], "non_numeric_invalidation")

    def test_nan_and_inf_invalidation(self):
        self.assertEqual(_rec(inv=float("nan"))["code"], "non_numeric_invalidation")
        # pre-hardening, inf PASSED the bearish side check (inf > px)
        r = _rec(direction="bearish", inv=float("inf"))
        self.assertEqual(r["code"], "non_numeric_invalidation")

    def test_missing_price_all_sources_absent(self):
        snap = _snap(inv=495.0)
        snap["trade_intent"] = {}
        with patch.dict(os.environ, _ON):
            r = thesis_entry_eligible(snap)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "missing_current_price")
        self.assertIn("current price unavailable", r["reason"])

    def test_missing_timeframes_and_candle_fallbacks(self):
        for snap in (
            {"brain_thesis": _snap(inv=495.0)["brain_thesis"]},            # no ti, no tf
            {**_snap(inv=495.0, px=None), "timeframes": {}},               # empty tf
            {**_snap(inv=495.0, px=None), "timeframes": {"1m": {}}},       # no candle
        ):
            with patch.dict(os.environ, _ON):
                r = thesis_entry_eligible(snap)
            self.assertEqual(r["code"], "missing_current_price")

    def test_non_numeric_price(self):
        for px, in (("500.0",), (True,), (float("nan"),), (float("inf"),)):
            r = _rec(inv=495.0, px=px)
            self.assertFalse(r["eligible"], repr(px))
            self.assertEqual(r["code"], "non_numeric_current_price", repr(px))

    def test_casing_normalization(self):
        r = _rec(direction="BULLISH", source="LLM", inv=495.0, px=500.0)
        self.assertTrue(r["eligible"])


class TestFailClosed(unittest.TestCase):
    """Mission Phase 2 item 10: internal error denies fresh exposure."""

    def test_internal_exception_denies(self):
        with patch.dict(os.environ, _ON), \
             patch.object(ecu, "_gate_price", side_effect=RuntimeError("boom")):
            r = thesis_entry_eligible(_snap(inv=495.0))
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "invariant_evaluation_error")
        self.assertIn("fail-closed", r["reason"])

    def test_malformed_snapshot_denies_without_raising(self):
        class Hostile:
            def get(self, *_a, **_k):
                raise ValueError("hostile snapshot")
        with patch.dict(os.environ, _ON):
            r = thesis_entry_eligible(Hostile())
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "invariant_evaluation_error")

    def test_flag_off_exception_arm_never_reached(self):
        # flag off returns BEFORE any evaluation — legacy pass-through even
        # against a hostile snapshot
        class Hostile:
            def get(self, *_a, **_k):
                raise ValueError("hostile snapshot")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_INVALIDATION_ENTRY_INVARIANT", None)
            r = thesis_entry_eligible(Hostile())
        self.assertTrue(r["eligible"])
        self.assertEqual(r["code"], "off")

    def test_gate_survives_check_raising_and_denies(self):
        # even the check ITSELF exploding may not crash the loop or authorize
        with patch.dict(os.environ, _ON), \
             patch("ai_brain.ecu.thesis_entry_eligible",
                   side_effect=RuntimeError("check exploded")):
            gate = evaluate_gate(_snap(inv=495.0))
        self.assertFalse(gate["authorization_checks"]["thesis_invalidation_ok"])
        self.assertFalse(gate["would_authorize_if_enabled"])
        self.assertTrue(any("invariant_evaluation_error" in b
                            for b in gate["blocking_factors"]))

    def test_gate_survives_check_raising_flag_off_legacy(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_INVALIDATION_ENTRY_INVARIANT", None)
            with patch("ai_brain.ecu.thesis_entry_eligible",
                       side_effect=RuntimeError("check exploded")):
                gate = evaluate_gate(_snap(inv=495.0))
        self.assertTrue(gate["authorization_checks"]["thesis_invalidation_ok"])


class TestTelemetry(unittest.TestCase):
    def test_gate_carries_structured_record(self):
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(_snap(direction="bearish", inv=495.0, px=500.0))
        rec = gate["entry_invariant"]
        self.assertFalse(rec["eligible"])
        self.assertEqual(rec["code"], "wrong_side_invalidation")
        self.assertEqual(rec["direction"], "bearish")
        self.assertEqual(rec["source"], "llm")
        self.assertEqual(rec["invalidation_level"], 495.0)
        self.assertEqual(rec["current_price"], 500.0)
        # blocker carries the machine-readable code inline
        self.assertTrue(any("[wrong_side_invalidation]" in b
                            for b in gate["blocking_factors"]))

    def test_record_is_json_serializable(self):
        import json
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(_snap(inv=None))
        json.dumps(gate["entry_invariant"])   # must not raise

    def test_all_codes_declared(self):
        from ai_brain.ecu import ENTRY_INVARIANT_CODES
        for code in ("missing_invalidation", "non_numeric_invalidation",
                     "missing_current_price", "non_numeric_current_price",
                     "wrong_side_invalidation", "invariant_evaluation_error"):
            self.assertIn(code, ENTRY_INVARIANT_CODES)


class TestConstitutionalBoundaries(unittest.TestCase):
    def test_thesis_never_mutated(self):
        snap = _snap(direction="bearish", inv=495.0, px=500.0)
        import copy
        before = copy.deepcopy(snap["brain_thesis"])
        with patch.dict(os.environ, _ON):
            r = thesis_entry_eligible(snap)
        self.assertFalse(r["eligible"])
        self.assertEqual(snap["brain_thesis"], before)   # direction, level intact

    def test_no_model_call(self):
        # the eligibility check must be pure — no LLM, no network
        import ai_brain.narrative_brain as nb
        with patch.dict(os.environ, _ON), \
             patch.object(nb, "_call_llm",
                          side_effect=AssertionError("LLM called")) :
            thesis_entry_eligible(_snap(inv=495.0, px=500.0))

    def test_position_coexistence_denied_entry_gate_only(self):
        # a position exists; the invariant fails for the current thesis:
        # NEW entry is denied while the position-safety surface is untouched
        snap = _snap(inv=None)
        snap["position_monitor"] = {"has_open_position": True, "side": "long",
                                    "qty": 1, "current_price": 500.0}
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(snap)
        self.assertFalse(gate["would_authorize_if_enabled"])
        self.assertEqual(snap["position_monitor"]["has_open_position"], True)
        # position supremacy still evaluates independently of the gate
        from paper_execution.position_supremacy import enforce_position_supremacy
        with patch.dict(os.environ, _ON):
            enforce_position_supremacy(snap)   # must not raise

    def test_helper_absent_from_position_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for parts in (("paper_execution", "position_monitor.py"),
                      ("paper_execution", "stop_enforcer.py"),
                      ("paper_execution", "trade_manager.py"),
                      ("paper_execution", "order_builder.py"),
                      ("paper_execution", "paper_broker.py"),
                      ("paper_execution", "position_supremacy.py"),
                      ("paper_execution", "trade_reconciliation.py"),
                      ("risk", "risk_governor.py"),
                      ("operational_readiness", "eod_authority.py")):
            with open(os.path.join(src, *parts), encoding="utf-8") as fh:
                txt = fh.read()
            for needle in ("thesis_entry_eligible",
                           "BRAIN_INVALIDATION_ENTRY_INVARIANT"):
                self.assertNotIn(needle, txt, "/".join(parts))


if __name__ == "__main__":
    unittest.main()

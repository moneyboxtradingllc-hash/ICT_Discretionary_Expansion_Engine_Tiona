"""DEALING-RANGE-PAYLOAD-1 — the engine knew where price was. It said nothing.

`market_context.dealing_range` is computed on EVERY scan and written into memory
records for later retrieval. It was never shown to the Brain at decision time.

2026-08-20, 11:03:34 ET, the exact scan where Luna was reasoning about selling
the top of a range:

    high 29470.25   low 29240.25   midpoint 29355.25
    position 0.823  zone "premium"

Read those boundaries against her own thesis. The range HIGH is the protected
level she was rejecting from. The range LOW is her sell-side objective. Price sat
82.3% through the auction between them -- and the payload dropped all of it.

    THE SAME DEFECT AS THE TOOL LOCATIONS, ONE LAYER UP.
    THE FACT EXISTED, IT WAS CORRECT, AND THE BOUNDARY DISCARDED IT.

PASS-THROUGH ONLY. `structure/market_context._dealing_range` remains the sole
author. Nothing is recomputed in the payload, prompt or catalog layer, and an
absent range stays absent rather than being reconstructed downstream.

CONTEXT, NEVER DIRECTION. The obvious temptation is `premium -> short`, which
would be a mechanical directional gate of exactly the kind this system has spent
its life removing. The range says WHERE price is. It says nothing about what to
do there. It also does not justify moving a stop: where price sits in the range
is not a reason to advance protection -- evolving market structure would be, if
anything is.

WHAT THIS UNIT DELIBERATELY DOES NOT ADD. The forensic that found this leak also
found four concepts Luna correctly never receives: `directional_authority` (a
mechanical directional opinion), `capital_intelligence` (risk is not hers to
author), and `setup_lifecycle` / `state_transition` (both carry scan-count
semantics the repo eliminated on purpose). Restraint is the finding too.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import build_brain_input                  # noqa: E402
from ai_brain.brain_prompt import (BRAIN_SYSTEM_PROMPT,             # noqa: E402
                                   DEALING_RANGE_ADDENDUM)
from ai_brain.narrative_brain import _carries_dealing_range         # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260820_110334_MNQ.json")
TEXT = re.sub(r"\s+", " ", DEALING_RANGE_ADDENDUM)

RANGE_HIGH = 29470.25       # the protected high of her bearish thesis
RANGE_LOW = 29240.25        # her own sell-side objective
MIDPOINT = 29355.25
POSITION = 0.823


def snapshot():
    with open(ARCHIVE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh).get("raw_snapshot") or {})


def payload(snap=None):
    return build_brain_input(snap if snap is not None else snapshot(),
                             {"available": False})


def rng(snap=None):
    return (payload(snap).get("market") or {}).get("dealing_range") or {}


# ══════════════════════════════════════════════════════════════════════════════
class TestTheAugustTwentyLeak:
    def test_the_range_now_reaches_the_brain(self):
        assert rng()["high"] == RANGE_HIGH
        assert rng()["low"] == RANGE_LOW

    def test_every_canonical_field_travels(self):
        r = rng()
        assert r["midpoint"] == MIDPOINT
        assert r["position"] == POSITION
        assert r["zone"] == "premium"
        assert r["source_tf"] == "15m"

    def test_both_sides_of_liquidity_travel(self):
        r = rng()
        assert r["buy_side_liquidity"] == RANGE_HIGH
        assert r["sell_side_liquidity"] == RANGE_LOW

    def test_the_boundaries_ARE_her_thesis(self):
        """Why this leak mattered: the range high is the level she was
        rejecting from, and the range low is her own objective."""
        r = rng()
        assert r["high"] == 29470.25       # the protected high
        assert r["low"] == 29240.25        # OBJ_LIQ_SSL_2
        assert 0.8 < r["position"] < 0.85  # deep premium

    def test_before_this_unit_none_of_it_shipped(self):
        """The archived payload is the control."""
        with open(ARCHIVE, encoding="utf-8") as fh:
            shipped = json.dumps(json.load(fh)["input_payload"]).lower()
        for absent in ("dealing_range", "premium", "discount", "0.823", "29355.25"):
            assert absent not in shipped, absent


class TestPassThroughOnly:
    def test_the_payload_layer_computes_nothing(self):
        """AST: no arithmetic may touch the range on its way through."""
        import ast
        import inspect
        import textwrap
        from ai_brain import brain_input as BI
        tree = ast.parse(textwrap.dedent(inspect.getsource(BI.build_brain_input)))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and "dealing_range" in ast.unparse(node):
                pytest.fail(ast.unparse(node))

    def test_values_are_identical_to_the_upstream_author(self):
        snap = snapshot()
        upstream = (snap.get("market_context") or {}).get("dealing_range") or {}
        assert rng(snap) == upstream

    def test_an_absent_range_is_declared_not_reconstructed(self):
        snap = snapshot()
        snap["market_context"] = {}
        bi = payload(snap)
        assert (bi["market"].get("dealing_range") or {}) == {}
        assert "dealing_range_unavailable" in bi["degraded"]

    def test_it_is_not_rebuilt_from_structure_swings(self):
        """`structure` still holds swings that COULD form a range. They must
        not be used to manufacture one when the real range is absent."""
        snap = snapshot()
        snap["market_context"] = {}
        assert (payload(snap)["market"].get("dealing_range") or {}).get("high") is None

    def test_a_healthy_range_produces_no_degradation(self):
        assert "dealing_range_unavailable" not in payload()["degraded"]


class TestTheAddendumIsGuarded:
    def test_it_attaches_when_a_range_exists(self):
        assert _carries_dealing_range(payload()) is True

    @pytest.mark.parametrize("bad", [
        None, {}, {"market": {}}, {"market": {"dealing_range": {}}},
        {"market": {"dealing_range": {"low": 1.0}}},     # no high
        {"market": {"dealing_range": "nope"}},
    ])
    def test_it_does_not_attach_without_one(self, bad):
        assert _carries_dealing_range(bad) is False


class TestContextNeverDirection:
    def test_premium_is_explicitly_not_a_short_signal(self):
        assert "premium     does NOT mean short" in TEXT.replace("  ", " ") or \
               "premium does NOT mean short" in TEXT

    def test_discount_is_explicitly_not_a_long_signal(self):
        assert "discount does NOT mean long" in TEXT or \
               "discount    does NOT mean long" in TEXT.replace("  ", " ")

    def test_equilibrium_is_not_a_stand_down_signal(self):
        assert "equilibrium does NOT mean stand down" in TEXT

    def test_it_states_the_thesis_is_neither_strengthened_nor_weakened(self):
        assert "A thesis is not stronger because price is in premium, and not " \
               "weaker because it is in discount" in TEXT

    def test_movement_against_the_thesis_may_be_delivery_of_location(self):
        """The same lesson the rejection block taught, at range scale."""
        assert "can be the retracement that delivers your location" in TEXT
        assert "Movement toward premium is not automatically bullish evidence" in TEXT

    def test_it_authors_nothing(self):
        assert "It does not author a direction, select a tool, qualify a " \
               "candidate, set a stop, or justify moving one" in TEXT

    def test_it_does_NOT_justify_advancing_protection(self):
        """Operator ruling: the range says where you are; evolving structure is
        what would justify moving a stop. Otherwise 'crossed equilibrium ->
        move stop' is mechanical trailing in disguise."""
        assert "not, by itself, a reason to advance protection" in TEXT
        assert "evolving market structure is what would justify that" in TEXT

    def test_no_directional_or_scoring_language(self):
        t = TEXT.lower()
        for banned in ("prefer short", "prefer long", "bias toward",
                       "confluence score", "you should sell", "you should buy"):
            assert banned not in t

    def test_absence_must_not_be_papered_over(self):
        assert "Do not construct a range from other fields to replace it" in TEXT


class TestSovereigntyInvariantsHold:
    """The forensic's restraint, pinned. These stay OUT."""

    @staticmethod
    def blob():
        return json.dumps(payload()).lower()

    def test_directional_authority_is_still_excluded(self):
        """A MECHANICAL directional opinion must not reach a sovereign Brain."""
        assert "directional_authority" not in self.blob()

    def test_capital_intelligence_is_still_excluded(self):
        """Risk posture is not Luna's to author."""
        b = self.blob()
        assert "capital_authority" not in b
        assert "defensive_only" not in b

    def test_no_scan_count_semantics_were_introduced(self):
        """`age_scans` would revive 'observation count = market truth'."""
        b = self.blob()
        for banned in ("age_scans", "bars_in_state", "upgrade_detected"):
            assert banned not in b, banned

    def test_the_range_cannot_author_exposure(self):
        """It reaches the Brain payload only — never the candidate producer."""
        import inspect
        from broker import luna_candidate_producer as P
        assert "dealing_range" not in inspect.getsource(P)

    def test_no_risk_doctrine_moved(self):
        from broker import topstepx_combine_risk as R
        assert (R.PREFERRED_MAX_STOP_POINTS, R.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)
        assert R.PRODUCTION_MAX_RISK_USD == 350.00

    def test_the_base_prompt_is_unedited(self):
        assert "DEALING RANGE" not in BRAIN_SYSTEM_PROMPT


class TestTheAssembledPrompt:
    @staticmethod
    def call_without_network(brain_input):
        import ai_brain.narrative_brain as NB
        import ai_layer.ai_api_adapter as AD
        available = AD._OPENAI_AVAILABLE
        AD._OPENAI_AVAILABLE = False
        try:
            record = NB._call_llm(brain_input)
        finally:
            AD._OPENAI_AVAILABLE = available
        assert record["fallback_reason"] == "openai_package_unavailable", record
        assert record["raw_response"] is None, "a network call escaped this test"
        return record

    def test_the_live_prompt_carries_it(self):
        rec = self.call_without_network(payload())
        assert "DEALING RANGE — WHERE PRICE SITS IN THE BROADER AUCTION" in rec["prompt"]

    def test_a_payload_without_a_range_gets_the_base_prompt(self):
        snap = snapshot()
        snap["market_context"] = {}
        rec = self.call_without_network(payload(snap))
        assert "DEALING RANGE — WHERE PRICE SITS" not in rec["prompt"]

    def test_the_numbers_actually_reach_her(self):
        rec = self.call_without_network(payload())
        sent = json.loads(rec["user_content"])["market"]["dealing_range"]
        assert sent["position"] == POSITION and sent["zone"] == "premium"

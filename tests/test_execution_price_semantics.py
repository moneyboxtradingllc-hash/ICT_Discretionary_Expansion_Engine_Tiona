"""EXEC-PRICE-FRESHNESS-2 — the Brain is told which price means "now".

EXEC-PRICE-FRESHNESS-1 gave the producer a fresh sided quote and left
`market.current_price` as what it always was: the newest SETTLED candle close.
It did not tell the Brain. `_call_llm` json.dumps the whole payload, so Luna SAW
`execution_price` — with nothing in the prompt saying which of the two fields
governs live entry location, while the one named `current_price` held a stale
number.

    THE ENGINE STOPPED LYING TO THE RISK GATE.
    IT HAD NOT STOPPED LYING TO THE BRAIN.

2026-08-20, 11:02:10 ET: the payload said `current_price: 29404.25` while that
minute traded 29423.25-29457.25. The stated price sat 19 points BELOW the
candle's own low.

There is a second, quieter ambiguity this closes. The base prompt tells the
Brain an invalidation sits "ABOVE price for bearish, BELOW for bullish". With
two price fields in the payload that instruction no longer names a number — and
`luna_candidate_producer._invalidation` validates the side against the EXECUTION
price. A Brain measuring against the settled close and mechanics measuring
against the bid is the same class of disagreement as a duplicated constant.

This unit adds NO trading rule. It does not change direction, thresholds,
playbooks, confirmation standards, tool eligibility or frequency. It defines a
field that already exists.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_prompt import (BRAIN_SYSTEM_PROMPT,          # noqa: E402
                                   EXECUTION_PRICE_ADDENDUM)
from ai_brain.narrative_brain import _carries_execution_price     # noqa: E402


def block(available=True, fresh=True, bid=29440.75, ask=29441.00):
    return {"schema": "execution_price.v1", "available": available, "fresh": fresh,
            "source": "topstepx_realtime_quote", "best_bid": bid, "best_ask": ask,
            "last_trade": bid, "captured_at": "2026-08-20T15:02:10+00:00",
            "age_seconds": 0.4, "max_age_seconds": 5.0,
            "bullish_executable": ask, "bearish_executable": bid,
            "unavailable_reason": None}


def payload(execution=None):
    return {"timestamp": "2026-08-20T15:02:10+00:00",
            "market": {"current_price": 29404.25,
                       "settled_price_basis": "settled_close:1m",
                       "execution_price": block() if execution is None else execution}}


def flat(text):
    return re.sub(r"\s+", " ", text)


# ══════════════════════════════════════════════════════════════════════════════
class TestAttachedOnlyWhenTheFieldExists:
    """A clause describing a field the payload lacks teaches hallucination.
    Same guard the candle-temporal addendum already carries."""

    def test_a_payload_with_the_block_attaches_it(self):
        assert _carries_execution_price(payload()) is True

    def test_a_pre_freshness_archive_does_not(self):
        assert _carries_execution_price({"market": {"current_price": 29404.25}}) is False

    def test_absent_market_is_safe(self):
        for bad in ({}, None, {"market": None}, {"market": {"execution_price": None}}):
            assert _carries_execution_price(bad) is False

    def test_a_block_without_a_schema_is_not_trusted(self):
        assert _carries_execution_price(
            {"market": {"execution_price": {"best_bid": 1.0}}}) is False

    def test_an_unavailable_block_STILL_attaches_it(self):
        """Attached when the block EXISTS, not when it is healthy. 'No live
        price' is precisely the state the Brain must learn to describe."""
        assert _carries_execution_price(payload(block(available=False, fresh=False))) is True
        assert _carries_execution_price(payload(block(fresh=False))) is True


class TestTheTwoFieldsAreDistinguished:
    TEXT = flat(EXECUTION_PRICE_ADDENDUM)

    def test_the_settled_field_is_named_as_settled(self):
        assert "market.current_price the newest SETTLED candle close" in self.TEXT
        assert "market.settled_price_basis naming which timeframe it came from" in self.TEXT

    def test_the_settled_field_is_denied_executable_authority(self):
        assert "It is STRUCTURAL CONTEXT" in self.TEXT
        assert "it is NOT where you can trade right now" in self.TEXT

    def test_the_execution_field_is_named_as_live(self):
        assert "the live venue quote" in self.TEXT
        assert 'It answers "where is the market RIGHT NOW"' in self.TEXT

    def test_the_two_questions_are_stated_as_different(self):
        assert 'It answers "what has the market DONE"' in self.TEXT
        assert "they are frequently NOT the same number" in self.TEXT

    def test_the_settled_close_is_never_called_the_live_price(self):
        """The exact inversion this unit exists to prevent."""
        t = self.TEXT.lower()
        for lie in ("current_price is the live", "current_price is the current market",
                    "current_price is the executable", "settled close is the live"):
            assert lie not in t


class TestTheSidesAreCorrect:
    TEXT = flat(EXECUTION_PRICE_ADDENDUM)

    def test_a_short_reads_the_bid(self):
        assert "`bearish_executable` (the bid) for a short" in self.TEXT

    def test_a_long_reads_the_ask(self):
        assert "`bullish_executable` (the ask) for a long" in self.TEXT

    def test_the_sides_are_not_transposed(self):
        assert "bearish_executable` (the ask)" not in self.TEXT
        assert "bullish_executable` (the bid)" not in self.TEXT

    def test_the_side_names_match_what_the_payload_actually_carries(self):
        """Prose and contract must agree, or this clause is fiction."""
        b = block()
        assert b["bearish_executable"] == b["best_bid"]
        assert b["bullish_executable"] == b["best_ask"]


class TestTheAmbiguityInTheBaseRuleIsResolved:
    """The base prompt says 'ABOVE price for bearish, BELOW for bullish'."""

    def test_the_base_prompt_still_uses_the_bare_word_price(self):
        assert "ABOVE price for bearish" in BRAIN_SYSTEM_PROMPT

    def test_the_addendum_names_which_price_that_rule_means(self):
        t = flat(EXECUTION_PRICE_ADDENDUM)
        assert 'the "above price / below price" side rule is measured against the ' \
               "EXECUTION price" in t

    def test_it_says_mechanics_validates_against_the_same_number(self):
        assert "Mechanics validates the side against exactly that number" \
            in flat(EXECUTION_PRICE_ADDENDUM)

    def test_that_claim_is_true_of_the_producer(self):
        """AST, not trust: `_invalidation`'s side check must take the value
        `_reference_price` returned, which reads the execution block."""
        import ast
        import inspect
        import textwrap
        from broker.luna_candidate_producer import CandidateProducer
        ded = lambda f: textwrap.dedent(inspect.getsource(f))
        ref = ast.parse(ded(CandidateProducer._reference_price))
        assert "execution_price" in ast.unparse(ref)
        inv = ast.parse(ded(CandidateProducer._invalidation))
        src = ast.unparse(inv)
        assert "reference_price" in src
        assert "current_price" not in src, "the side check must not re-read settled price"


class TestAbsenceIsDescribedNotRepaired:
    TEXT = flat(EXECUTION_PRICE_ADDENDUM)

    def test_an_unavailable_or_stale_price_means_location_unknown(self):
        assert "treat current location as UNKNOWN" in self.TEXT

    def test_it_forbids_estimating_a_live_price_from_candles(self):
        assert "Do NOT estimate a live price from settled candles" in self.TEXT

    def test_it_forbids_inventing_a_quote(self):
        assert "do NOT invent a bid or ask" in self.TEXT

    def test_it_names_the_degraded_markers_the_payload_actually_emits(self):
        assert "execution_price_unavailable" in self.TEXT
        assert "execution_price_stale" in self.TEXT

    def test_those_markers_are_the_real_ones(self):
        """The clause must not describe telemetry that does not exist."""
        import inspect
        from ai_brain import brain_input as BI
        src = inspect.getsource(BI.build_brain_input)
        assert '"execution_price_unavailable:"' in src
        assert '"execution_price_stale"' in src

    def test_the_brain_is_not_asked_to_repair_it(self):
        assert "your job is to describe the absence, not repair it" in self.TEXT

    def test_mechanics_still_fails_closed_regardless(self):
        from broker import topstepx_execution_price as EP
        assert EP.executable_price(EP.unavailable(EP.NO_QUOTE_PROVIDER), "bearish") is None
        assert EP.executable_price(
            {"schema": EP.SCHEMA, "available": True, "fresh": False,
             "best_bid": 1.0, "best_ask": 2.0}, "bearish") is None


class TestStructureIsUntouched:
    TEXT = flat(EXECUTION_PRICE_ADDENDUM)

    def test_settled_candles_remain_structurally_authoritative(self):
        assert "Settled candles remain authoritative for STRUCTURE" in self.TEXT

    def test_the_quote_may_not_rewrite_history(self):
        assert "does not rewrite candle history" in self.TEXT
        assert "does not move a protected swing" in self.TEXT

    def test_a_gap_between_the_two_is_declared_ordinary(self):
        """Otherwise the Brain reports a normal quote/close gap as an anomaly."""
        assert "ORDINARY, not a contradiction to resolve" in self.TEXT


class TestNoDoctrineMoved:
    """This unit defines a field. It authorizes nothing."""

    TEXT = flat(EXECUTION_PRICE_ADDENDUM).lower()

    def test_it_grants_no_direction_and_no_setup(self):
        for banned in ("you should trade", "you must trade", "take the trade",
                       "be more aggressive", "lower your confidence",
                       "increase confidence", "prefer bearish", "prefer bullish"):
            assert banned not in self.TEXT

    def test_it_names_no_risk_number(self):
        for n in ("35", "40", "50", "350", "250", "725"):
            assert n not in self.TEXT

    def test_it_does_not_touch_confirmation_standards(self):
        for banned in ("confirmation", "retest", "playbook", "tool_family",
                       "phase_confidence"):
            assert banned not in self.TEXT

    def test_the_base_prompt_is_unchanged_by_this_unit(self):
        """The addendum is APPENDED; the base contract is not edited."""
        assert "WHICH PRICE IS" not in BRAIN_SYSTEM_PROMPT
        assert "execution_price" not in BRAIN_SYSTEM_PROMPT


class TestTheAssembledPromptAtTheRealCallSite:
    """Hermetic: `_call_llm` builds `prompt` before any network guard, so
    disabling the adapter returns it fully assembled with nothing sent.

    Popping OPENAI_API_KEY is NOT sufficient — `_call_llm` imports the adapter
    afterwards and the import reloads .env. The fallback_reason / raw_response
    assertions are what prove no request left."""

    @staticmethod
    def call_without_network(brain_input: dict) -> dict:
        import ai_brain.narrative_brain as NB
        import ai_layer.ai_api_adapter as AD
        available = AD._OPENAI_AVAILABLE
        AD._OPENAI_AVAILABLE = False
        try:
            record = NB._call_llm(brain_input)
        finally:
            AD._OPENAI_AVAILABLE = available
        assert record["fallback_reason"] == "openai_package_unavailable", record
        assert record["raw_response"] is None and record["parsed"] is None, \
            "a network call escaped this test"
        return record

    def test_the_live_prompt_carries_it_when_the_block_is_present(self):
        record = self.call_without_network(payload())
        assert 'WHICH PRICE IS "NOW"' in record["prompt"]
        assert "It is STRUCTURAL CONTEXT" in record["prompt"]
        # flattened: the clause wraps across lines in the assembled prompt
        assert "`bearish_executable` (the bid) for a short" in flat(record["prompt"])

    def test_a_pre_freshness_archive_gets_the_base_prompt(self):
        record = self.call_without_network({"market": {"current_price": 29404.25}})
        assert 'WHICH PRICE IS "NOW"' not in record["prompt"]

    def test_the_stale_case_still_carries_the_clause(self):
        record = self.call_without_network(payload(block(available=False, fresh=False)))
        assert "treat current location as UNKNOWN" in record["prompt"]

    def test_the_payload_the_brain_receives_contains_both_fields(self):
        """json.dumps of the payload — she sees the numbers, now with meaning."""
        import json
        record = self.call_without_network(payload())
        sent = json.loads(record["user_content"])
        assert sent["market"]["current_price"] == 29404.25
        assert sent["market"]["execution_price"]["best_bid"] == 29440.75

    def test_the_eleven_oh_two_gap_is_what_this_teaches(self):
        """29404.25 settled vs 29440.75 executable — the defect, in one payload."""
        import json
        sent = json.loads(self.call_without_network(payload())["user_content"])
        settled = sent["market"]["current_price"]
        executable = sent["market"]["execution_price"]["bearish_executable"]
        assert executable - settled == 36.50
        assert 29470.25 - settled == 66.00        # what mechanics used to measure
        assert 29470.25 - executable == 29.50     # what it measures now

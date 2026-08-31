"""REJECTION-ENTRY-MODE-SEPARATION-1 — proof is not required twice.

2026-08-20, in-zone counterfactual. Luna was placed INSIDE her own bearish
rejection block at 29455.00 holding fresh price, the block (29448.50-29470.25),
its mean threshold, the 5m active_leg anchor, the 3m geometry, her bearish
thesis, the 29240.25 draw and 15.25 points of structural risk. She recognised
exactly where she was --

    "price is currently inside the rejection zone"

-- and declined:

    "lacks a fresh rejection trigger from the live quote. Wait for rejection and
     bearish delivery confirmation rather than CHASING A SHORT."

By that point three engineering defects had already been removed from underneath
that refusal: the stale execution price, the tool catalog that published
eligibility without location, and a rejection block anchored to nothing. The
refusal survived all three, which is what makes this a decision-contract fault
rather than another infrastructure hypothesis.

    SHE DEMANDED A SECOND REJECTION TO VALIDATE A STRUCTURE
    WHOSE ENTIRE EXISTENCE IS THE RECORD OF THE FIRST.

The cost is not stylistic. By the time a confirming rejection has printed, price
has normally left the block, and the structural stop has widened from the
block's own depth to however far price has travelled. On this tape that is the
difference between roughly 15 points of risk and roughly 40.

Note also that "chasing" appears NOWHERE in the production prompt -- Luna
inferred it. Leaving the concept undefined let her invert it: entering at a
pre-established location became "chasing", while waiting for delivery AWAY from
that location became "confirmation".

THIS CLAUSE PERMITS; IT DOES NOT OBLIGE. A hard "inside the block -> trade" rule
would replace one bad absolute with another, and the whole point of the Brain is
that it decides.

NO NEW SCHEMA FIELD, and the reason matters. It is NOT that mode is mechanically
derivable from where the entry price lands -- it is not. A confirmation entry can
perfectly well occur INSIDE the block, after a new lower-timeframe rejection has
printed there. What separates the modes is whether Luna REQUIRED new confirmation
evidence, which is a discretionary choice, not a coordinate.

The existing contract already carries everything needed to express and audit
both paths: the tool and its zone, current location, whatever trigger evidence
exists, and Luna's own reasoning. Mechanics does not need to author an
`entry_mode` state on top of that, and giving it one would make mechanics the
author of a distinction that belongs to the Brain.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_prompt import (BRAIN_SYSTEM_PROMPT,             # noqa: E402
                                   REJECTION_ENTRY_MODE_ADDENDUM)
from ai_brain.narrative_brain import (                              # noqa: E402
    _carries_anchored_rejection_block)

TEXT = re.sub(r"\s+", " ", REJECTION_ENTRY_MODE_ADDENDUM)


def catalog(level_type="protected_level_rejection_block"):
    return {"authorized_tool_catalog": [{"tool": "bearish_rejection_block",
                                         "level_type": level_type}]}


# ══════════════════════════════════════════════════════════════════════════════
class TestAttachedOnlyWithAnAnchoredBlock:
    def test_an_anchored_block_attaches_it(self):
        assert _carries_anchored_rejection_block(catalog()) is True

    def test_a_generic_rejection_block_does_not(self):
        """The generic zone is not the settled record of a rejection AT a level."""
        assert _carries_anchored_rejection_block(catalog("rejection_block_zone")) is False

    def test_absent_or_malformed_payloads_are_safe(self):
        for bad in ({}, None, {"authorized_tool_catalog": None},
                    {"authorized_tool_catalog": "nope"},
                    {"authorized_tool_catalog": [None, 5]}):
            assert _carries_anchored_rejection_block(bad) is False


class TestTheBlockIsAlreadyTheRejection:
    def test_it_states_the_block_records_a_completed_event(self):
        assert "IS settled evidence of a rejection ALREADY ESTABLISHED" in TEXT

    def test_it_covers_BOTH_exact_print_and_proximity_blocks(self):
        """Commit 3 admits an exact print AND a lawful near miss. A clause
        saying every block literally reached its level would be FALSE for the
        second kind — and `distance_to_anchor` is what distinguishes them."""
        assert "at, or within the canonical permitted proximity of, the " \
               "protected anchor" in TEXT
        assert "`distance_to_anchor` states which" in TEXT
        assert "0 means the creating candle printed the anchor's exact extreme" in TEXT

    def test_it_requires_no_acceptance_through_the_anchor(self):
        assert "no authoritative acceptance through that anchor" in TEXT

    def test_it_says_the_block_predates_the_current_price(self):
        assert "normally well BEFORE the price you are looking at now" in TEXT

    def test_a_second_rejection_is_explicitly_not_required(self):
        assert "You do NOT need a second rejection, displacement or trigger to " \
               "re-prove the block you are standing in" in TEXT

    def test_it_names_the_cost_of_asking_twice(self):
        assert "asking for the same proof twice" in TEXT
        assert "the structural stop has widened" in TEXT


class TestBothModesSurvive:
    def test_aggressive_is_described(self):
        assert "AGGRESSIVE — price RETURNS into the established block" in TEXT

    def test_confirmation_is_preserved_as_legitimate(self):
        assert "CONFIRMATION — price returns, and a NEW rejection or failure then prints" in TEXT
        assert "A valid choice when the context genuinely warrants waiting" in TEXT

    def test_neither_mode_is_mandatory(self):
        assert "Both are legitimate. Neither is mandatory" in TEXT

    def test_confirmation_is_not_deleted_merely_demoted_from_prerequisite(self):
        t = TEXT.lower()
        assert "confirmation" in t
        for banned in ("never wait for confirmation", "confirmation is wrong",
                       "do not use confirmation"):
            assert banned not in t


class TestItPermitsRatherThanObliges:
    def test_standing_down_remains_available(self):
        assert "You remain free to stand down" in TEXT

    def test_it_says_available_not_obligatory(self):
        assert "makes the aggressive entry AVAILABLE; it never makes it obligatory" in TEXT

    def test_it_grants_no_direction(self):
        assert "grants no direction" in TEXT

    def test_no_hard_trade_rule_is_introduced(self):
        t = TEXT.lower()
        for absolute in ("you must enter", "must take", "always enter",
                         "you must trade", "required to enter"):
            assert absolute not in t

    def test_it_names_no_risk_number(self):
        for n in ("35", "40", "50", "250", "350", "725"):
            assert n not in TEXT


class TestChasingIsDefined:
    def test_the_base_prompt_never_used_the_word(self):
        """She inferred it. Leaving it undefined let her invert the concept."""
        assert "chas" not in BRAIN_SYSTEM_PROMPT.lower()

    def test_chasing_is_defined_as_entering_after_delivery(self):
        assert "Chasing is entering AFTER price has already delivered materially " \
               "away from the setup" in TEXT

    def test_being_inside_an_active_block_is_declared_not_chasing(self):
        assert "ENTERING AT LOCATION IS NOT CHASING" in TEXT
        assert "Do not describe a favourable return into a pre-established zone " \
               "as chasing" in TEXT

    def test_it_gives_concrete_examples_of_both_sides(self):
        assert "selling well below a rejection that has finished" in TEXT
        assert "buying well above a reclaim that has finished" in TEXT


class TestCounterevidenceIsPreserved:
    def test_acceptance_through_invalidation_still_kills_the_thesis(self):
        assert "Authoritative ACCEPTANCE through the invalidation" in TEXT
        assert "the block is finished and so is the thesis" in TEXT

    def test_opposing_ltf_delivery_is_distinguished_from_acceptance(self):
        """The 2026-08-20 inversion, named directly."""
        assert "Opposing lower-timeframe delivery INSIDE the block is not " \
               "acceptance through it" in TEXT
        assert "the mechanism by which price is delivered back to your location" in TEXT

    def test_the_registry_really_does_drop_a_violated_anchor(self):
        """The clause claims the block stops being offered. Prove it."""
        import inspect
        from narrative_authority import protected_swings as PS
        src = inspect.getsource(PS.ProtectedSwingTracker)
        assert "self.protected_highs.pop(tf, None)" in src


class TestTheMeanThresholdIsNotAGate:
    def test_it_is_declared_geometry_not_a_trigger(self):
        assert "It is NOT a required trigger and NOT an entry gate" in TEXT

    def test_mechanics_does_not_gate_on_it(self):
        """The producer must not consult mean_threshold to permit or refuse."""
        import inspect
        from broker import luna_candidate_producer as P
        src = inspect.getsource(P.CandidateProducer)
        assert "mean_threshold" not in src


class TestNoSchemaFieldWasAdded:
    """Both paths are expressible through the existing contract."""

    def test_the_schema_gained_no_entry_mode_field(self):
        from ai_brain import brain_schema as S
        assert "entry_mode" not in inspect_source(S)

    def test_mode_is_NOT_merely_where_the_entry_price_lands(self):
        """The tempting shortcut, and why it is wrong: a CONFIRMATION entry can
        occur inside the block too, once a new rejection has printed there. The
        modes differ by whether new confirmation evidence was REQUIRED — a
        discretionary choice, not a coordinate."""
        zone_low, zone_high = 29448.50, 29470.25
        confirmation_inside_the_block = 29452.00
        assert zone_low <= confirmation_inside_the_block <= zone_high

    def test_the_contract_already_carries_what_both_paths_need(self):
        from broker.luna_candidate_producer import TOOL_LOCATION_FIELDS
        for fact in ("zone_low", "zone_high", "price_relation", "current_price"):
            assert fact in TOOL_LOCATION_FIELDS, fact

    def test_mechanics_does_not_author_the_distinction(self):
        """Naming which mode was taken belongs to the Brain's reasoning, not to
        a mechanical state machine."""
        import inspect
        from broker import luna_candidate_producer as P
        src = inspect.getsource(P)
        for authored in ("entry_mode", "aggressive_entry", "confirmation_entry"):
            assert authored not in src, authored


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
        record = self.call_without_network(catalog())
        assert "THE BLOCK IS ALREADY THE REJECTION" in record["prompt"]
        assert "ENTERING AT LOCATION IS NOT CHASING" in record["prompt"]

    def test_a_payload_without_an_anchored_block_gets_the_base_prompt(self):
        record = self.call_without_network(catalog("rejection_block_zone"))
        assert "THE BLOCK IS ALREADY THE REJECTION" not in record["prompt"]

    def test_the_base_contract_is_unedited(self):
        assert "THE BLOCK IS ALREADY THE REJECTION" not in BRAIN_SYSTEM_PROMPT


def inspect_source(mod):
    import inspect
    return inspect.getsource(mod)

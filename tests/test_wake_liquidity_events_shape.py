"""WAKE-EVIDENCE-SHAPE-1 — the liquidity_events block/list contract.

PROD-20260921 ran 541 scans in ENFORCE and suppressed nothing. The wake
ledger was unambiguous about why: `mode=ENFORCE` and `changed_dimensions`
empty on all 541 rows, every wake `wake_kind=safety`, and the reason
`malformed_required_evidence:brain_input.liquidity_events` on every single
one.

The controller asked for a list:

    rows(brain_input, "liquidity_events", "brain_input.liquidity_events",
         required=True)

`brain_input._liquidity_events_block` publishes a block:

    {"available": False, "events": []}

A dict is not a list, so required evidence read as malformed on every scan
of every session, independent of market or state -- and malformed required
evidence must fail open to a safety WAKE. ENFORCE was therefore structurally
incapable of ever suppressing a call.

The unit test fixtures published a bare list too, so the suite agreed with
the validator instead of with the producer. That is why 7464 green tests
coexisted with a gate that could not gate. The fixtures are corrected in
`test_brain_wake_controller`, `test_brain_wake_integration` and
`test_pre_brain_wake_shadow`; this file locks the contract itself.

NOTHING HERE RELAXES EVIDENCE LAW. A wrong type at either level is still
malformed, absence is still malformed, and both still buy a WAKE.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain import wake_controller as W                          # noqa: E402

from test_brain_wake_controller import (                           # noqa: E402
    NOW, establish, observe, valid_evidence,
)

FLAG = "malformed_required_evidence:brain_input.liquidity_events"
NESTED_FLAG = "malformed_required_evidence:brain_input.liquidity_events.events"

SWEEP = {"occurrence_id": "SWEEP-9", "timeframe": "1m",
         "liquidity_side_taken": "sell_side", "swept_level": 99.5,
         "reclaimed": True, "detector_scope": "external",
         "po3_scope": "manipulation"}


def issues_for(liquidity_events, *, present=True):
    """The evidence issues a scan records for this liquidity_events value."""
    snapshot, brain_input = valid_evidence()
    if present:
        brain_input["liquidity_events"] = liquidity_events
    else:
        brain_input.pop("liquidity_events", None)
    return W._semantic_shape_issues(snapshot, brain_input)    # noqa: SLF001


def liquidity_flags(issues):
    return [i for i in issues if i.startswith(
        "malformed_required_evidence:brain_input.liquidity_events")]


class TestTheProducedShapeIsAccepted:
    """1 and 2. What `_liquidity_events_block` actually emits is legal."""

    def test_the_empty_block_production_publishes_is_not_malformed(self):
        """THE DEFECT. This exact value was flagged 541/541 on PROD-20260921."""
        assert liquidity_flags(issues_for({"available": False, "events": []})) == []

    def test_a_populated_block_of_row_dicts_is_not_malformed(self):
        block = {"available": True, "events": [SWEEP, dict(SWEEP,
                                                           occurrence_id="SWEEP-10")]}
        assert liquidity_flags(issues_for(block)) == []

    def test_extra_block_members_are_not_malformed(self):
        """The producer may add members; only `events` is asked for."""
        block = {"available": True, "events": [SWEEP], "scope_reason": "proven"}
        assert liquidity_flags(issues_for(block)) == []


class TestEvidenceLawIsNotRelaxed:
    """3, 4 and 5. Uncertainty is still uncertainty."""

    @pytest.mark.parametrize("wrong", [
        [],                      # the shape the validator used to demand
        [SWEEP],                 # a populated list is still not a block
        [("not", "a", "mapping")],
        "events",
        42,
        0,
        False,
    ])
    def test_a_wrong_top_level_type_is_still_malformed(self, wrong):
        assert FLAG in issues_for(wrong)

    @pytest.mark.parametrize("wrong", [
        {},                      # events missing entirely
        {"events": {}},          # a mapping where rows belong
        {"events": "none"},
        {"events": 0},
        {"events": None},
    ])
    def test_a_wrong_or_absent_nested_events_member_is_still_malformed(self, wrong):
        assert NESTED_FLAG in issues_for(dict({"available": False}, **wrong))

    def test_non_dict_rows_inside_events_are_still_malformed(self):
        block = {"available": True, "events": [SWEEP, ("not", "a", "mapping")]}
        assert NESTED_FLAG in issues_for(block)

    def test_an_absent_block_is_still_malformed(self):
        assert FLAG in issues_for(None, present=False)

    def test_a_null_block_is_still_malformed(self):
        assert FLAG in issues_for(None)

    def test_malformed_required_evidence_still_buys_a_safety_wake(self):
        """5. The fail-open behaviour fb1dcbb exists for is untouched."""
        controller = W.BrainWakeController(mode=W.ENFORCE)
        establish(controller)

        snapshot, brain_input = valid_evidence()
        brain_input["liquidity_events"] = ["wrong shape"]
        woken = observe(controller, 2, NOW + timedelta(seconds=60),
                        snapshot=snapshot, brain_input=brain_input)

        assert woken["decision"] == W.WAKE
        assert woken["wake_kind"] == "safety"
        assert woken["evidence_integrity"]["ok"] is False
        assert FLAG in woken["evidence_integrity"]["issues"]


class TestEnforceCanNowActuallySuppress:
    """6, 7 and 8. The behaviour PROD-20260921 could not reach."""

    def test_unchanged_state_with_valid_evidence_holds_under_enforce(self):
        """6. THE REGRESSION THIS FILE EXISTS FOR. 541 scans could not do this."""
        controller = W.BrainWakeController(mode=W.ENFORCE)
        establish(controller)

        held = observe(controller, 2, NOW + timedelta(seconds=60))

        assert held["decision"] == W.HOLD
        assert held["would_suppress"] is True
        assert held["actually_suppressed"] is True
        assert held["evidence_integrity"]["ok"] is True
        assert held["changed_dimensions"] == []

    def test_a_real_liquidity_event_still_wakes(self):
        """7. Proves the projection reads the block's rows.

        `_liquidity_view` ran the produced block through `_list()`, which
        answers [] for a dict, so `event_identities` was ALWAYS empty and a new
        sweep shown to the Brain moved nothing. Suppressing on a dead evidence
        path is how a gate sleeps through a real event.
        """
        controller = W.BrainWakeController(mode=W.ENFORCE)
        establish(controller)

        snapshot, brain_input = valid_evidence()
        brain_input["liquidity_events"]["events"].append(SWEEP)
        brain_input["liquidity_events"]["available"] = True
        woken = observe(controller, 2, NOW + timedelta(seconds=60),
                        snapshot=snapshot, brain_input=brain_input)

        assert woken["decision"] == W.WAKE
        assert woken["evidence_integrity"]["ok"] is True
        assert "liquidity" in woken["changed_dimensions"]

    def test_the_max_silence_backstop_still_wakes(self):
        """8. The independent safety clock is not a casualty of suppression."""
        controller = W.BrainWakeController(mode=W.ENFORCE)
        establish(controller)

        held = observe(controller, 2, NOW + timedelta(seconds=60))
        assert held["decision"] == W.HOLD

        woken = observe(controller, 3,
                        NOW + timedelta(seconds=W.DEFAULT_MAX_SILENCE_SECONDS + 1))
        assert woken["decision"] == W.WAKE
        assert woken["changed_dimensions"] == [], (
            "the backstop must fire on elapsed silence, not on a state change")


class TestUnrelatedAuthorityIsUntouched:
    """9. The quota circuit is a different mechanism and stays put."""

    def test_the_hard_quota_circuit_still_does_not_create_a_wake_loop(self):
        controller = W.BrainWakeController(mode=W.ENFORCE)
        first = observe(controller)
        controller.note_provider_result(
            first, request_attempted=True, sovereign=False,
            hard_quota_circuit_open=True)

        second = observe(controller, 2, NOW + timedelta(seconds=60))

        assert second["decision"] == W.HOLD
        assert "previous_brain_not_sovereign" not in second["reasons"]

    def test_a_skipped_provider_request_still_forces_the_next_wake(self):
        """The circuit's exemption is narrow: only an INTENTIONAL skip."""
        controller = W.BrainWakeController(mode=W.ENFORCE)
        first = observe(controller)
        controller.note_provider_result(first, request_attempted=False,
                                        sovereign=False)

        second = observe(controller, 2, NOW + timedelta(seconds=60))

        assert second["decision"] == W.WAKE
        assert "previous_provider_request_not_attempted" in second["reasons"]

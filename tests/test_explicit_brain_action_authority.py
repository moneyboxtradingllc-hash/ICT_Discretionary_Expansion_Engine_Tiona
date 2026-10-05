"""The Brain action token is an exposure authority, not free-form prose."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from ai_brain.brain_schema import (
    ACTION_PROPOSE_ENTRY, ACTION_STAND_DOWN, ACTION_WATCHING,
    canonical_action, empty_brain_output, validate_brain_output,
    validate_llm_core,
)
from ai_brain.brain_validation import normalize_output


@pytest.mark.parametrize("action", [
    ACTION_PROPOSE_ENTRY, ACTION_WATCHING, ACTION_STAND_DOWN,
])
def test_only_the_three_exact_tokens_pass_both_real_brain_validators(action):
    output = empty_brain_output()
    output["current_action"] = action
    assert canonical_action(action) == action
    assert validate_llm_core(output) == (True, None)
    assert validate_brain_output(output) == (True, None)


@pytest.mark.parametrize("action", [
    "pending confirmation", "unknown", "", "   ", None, 0, True, [], {},
    "await_retest", "waiting for confirmation", "WATCHING",
    "watching: enter on touch", "propose_entry after confirmation",
    "propose_entryXYZ", "I want to buy if the zone holds",
])
def test_unrecognized_action_is_rejected_by_both_validators(action):
    output = empty_brain_output()
    output["current_action"] = action
    assert validate_llm_core(output)[0] is False
    assert validate_brain_output(output)[0] is False
    normalized, _notes = normalize_output(deepcopy(output), [])
    assert normalized["current_action"] == action
    assert validate_brain_output(normalized)[0] is False


@pytest.mark.parametrize("validator", [validate_llm_core, validate_brain_output])
def test_missing_current_action_is_rejected(validator):
    output = empty_brain_output()
    del output["current_action"]
    assert validator(output)[0] is False


def test_prompt_documents_the_three_distinct_action_authorities():
    from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT

    assert '"current_action": "propose_entry|watching|stand_down"' in BRAIN_SYSTEM_PROMPT
    assert "immediate entry now" in BRAIN_SYSTEM_PROMPT
    assert "never authorizes immediate exposure" in BRAIN_SYSTEM_PROMPT
    assert "authorize no new exposure and no conditional plan" in BRAIN_SYSTEM_PROMPT


def test_real_campaign_authorities_do_not_turn_unknown_action_into_permission(
        monkeypatch):
    from broker.luna_candidate_producer import NoCandidate
    from test_conditional_plan_authority import context

    (fixtures, snapshot, draw, _authored, brain_result, brain_input, auth,
     producer, _plan_authority) = context(monkeypatch)
    bad_result = deepcopy(brain_result)
    bad_result["parsed"]["current_action"] = "pending confirmation"
    assert bad_result["ok"] is True
    assert bad_result["source"] == "llm"
    assert snapshot["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    assert validate_llm_core(bad_result["parsed"])[0] is False
    with pytest.raises(NoCandidate, match="brain_action_invalid"):
        fixtures.produce(
            p=producer, res=bad_result, bi=brain_input,
            qual={"qualified": True}, snapshot=snapshot,
            snapshot_id="unknown-action-with-valid-campaign",
            now=fixtures.NOW + timedelta(seconds=1),
            require_campaign_lifecycle=True, campaign_draw=draw,
            campaign_session_id=auth.session_id)


def test_real_propose_entry_candidate_reaches_only_mocked_mint_boundary(
        monkeypatch, tmp_path):
    from test_conditional_plan_authority import context
    from test_latency1_final_quote_zone import (
        MintBoundaryReached, _runner_and_market, _submit_to_mint_boundary)

    (fixtures, snapshot, draw, _authored, brain_result, brain_input, auth,
     producer, _plan_authority) = context(monkeypatch)
    immediate_result = deepcopy(brain_result)
    immediate_result["parsed"]["current_action"] = ACTION_PROPOSE_ENTRY
    candidate = fixtures.produce(
        p=producer, res=immediate_result, bi=brain_input,
        qual={"qualified": True}, snapshot=snapshot,
        snapshot_id="explicit-propose-entry-current",
        now=fixtures.NOW + timedelta(seconds=1),
        require_campaign_lifecycle=True, campaign_draw=draw,
        campaign_session_id=auth.session_id)
    assert candidate.direction == "bullish"
    assert candidate.extras.get("conditional_plan") is not True

    now = fixtures.NOW + timedelta(seconds=1)
    runner, market, quote, venue, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority=None, producer=None, now=now,
        final_bid=candidate.entry_price - fixtures.MNQ.tick_size,
        final_ask=candidate.entry_price)
    mint_boundary = []
    with pytest.raises(MintBoundaryReached):
        _submit_to_mint_boundary(
            runner, candidate, market, quote, ledger, mint_boundary)
    assert mint_boundary == [True]
    assert venue.place_calls == 0

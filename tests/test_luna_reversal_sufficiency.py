"""LUNA-REVERSAL-SUFFICIENCY-1 — the cognition contract, pinned.

2026-08-24 live evidence. Across 308 production scans, 36 distinct scans carried
a bullish tool that was execution-eligible, not invalidated, AT location, with a
lawful protected-low invalidation inside the 50-point cap and a lawful bullish
objective clearing the 1.0R floor. Luna's `narrative_direction` was `conflicted`
or `bearish` on every one of them and never once `bullish`. On the two scans
where she WAS bullish, price had already left every bullish zone by 71 and 108
points. Her direction and mechanics' location were anti-correlated all session.

The payload was not the carrier. Two prompt surfaces were:

R1  The only causal-implication sentence in the authority rules taught the
    bearish inference and nothing else -- a rejected buy-side raid implies
    bearish delivery. No mirrored sentence existed for the sell-side raid, so
    the bullish inference had to be re-derived from scratch on every scan.

R2  `conflicted/neutral` was written as a HARD TOOL VETO: the prompt required
    `recommended_tool_family` to be one of four neutral tokens. Uncertainty was
    therefore a prohibition, which contradicts DISCRETIONARY SUFFICIENCY. She
    was conflicted on 94 of the 193 complete-opportunity scans.

This file pins BOTH directions of both repairs. It must fail if the mirrored
bullish rule is deleted, AND if the original bearish rule is weakened to make
room for it; if the sufficiency law is removed, AND if it is ever turned into an
obligation to trade.

No network. No model. No order. Text-contract and gate-behaviour only.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT                # noqa: E402
from ai_brain.brain_validation import (NEUTRAL_TOOL_FAMILIES,        # noqa: E402
                                       normalize_output)
from broker.luna_candidate_producer import (CandidateProducer,       # noqa: E402
                                            NoCandidate)

P = BRAIN_SYSTEM_PROMPT


def _norm(text: str) -> str:
    """Whitespace-insensitive so a re-wrap of the paragraph cannot fail a test
    that is asserting about DOCTRINE, not line breaks."""
    return re.sub(r"\s+", " ", text).strip().lower()


FLAT = _norm(P)


# ══════════════════════════════════════════════════════════════════════════════
class TestR1DirectionalCausalSymmetry:
    """Rejected raids are symmetric evidence, but cannot independently transfer campaigns."""

    def test_the_buy_side_rule_is_still_there(self):
        """The repair ADDS a mirror. Deleting the original would 'fix' the
        asymmetry by removing the half that was already right."""
        assert _norm("a buy-side raid rejected and reclaimed establishes a "
                     "protected high and is causal evidence for bearish "
                     "delivery toward sell-side liquidity") in FLAT

    def test_the_mirrored_sell_side_rule_exists(self):
        assert _norm("a sell-side raid rejected and reclaimed establishes a "
                     "protected low and is causal evidence for bullish "
                     "delivery toward buy-side liquidity") in FLAT

    def test_both_carry_the_same_structure_qualifier(self):
        """Neither side's local raid may be promoted to a standalone reversal."""
        assert _norm("a local raid alone does not transfer an established "
                     "campaign or authorize an entry") in FLAT

    def test_neither_is_declared_the_stronger_reading(self):
        assert _norm("these implications carry equal weight") in FLAT

    def test_neither_raid_is_an_automatic_trade(self):
        """A protected low must not become an automatic long -- that would swap
        one directional reflex for another."""
        assert _norm("a local raid alone does not transfer an established "
                     "campaign or authorize an entry") in FLAT

    def test_the_two_rules_are_lexically_symmetric(self):
        """Mechanical guard against a mirror that drifts. Swapping every
        directional token in the bearish sentence must literally produce the
        bullish one."""
        bear = ("a buy-side raid rejected and reclaimed establishes a protected "
                "high and is causal evidence for bearish delivery toward "
                "sell-side liquidity")
        swap = {"buy-side": "sell-side", "sell-side": "buy-side",
                "high": "low", "bearish": "bullish"}
        bull = re.sub("|".join(map(re.escape, swap)),
                      lambda m: swap[m.group(0)], bear)
        assert _norm(bear) in FLAT
        assert _norm(bull) in FLAT


# ══════════════════════════════════════════════════════════════════════════════
class TestR2ConflictedIsNotAVeto:

    def test_the_hard_restriction_is_gone(self):
        """The exact production sentence that made uncertainty a prohibition."""
        assert _norm('if conflicted/neutral, recommended_tool_family must be one '
                     'of ["none"], ["wait"], ["two_sided_watch"], '
                     '["confirmation_required"]') not in FLAT

    def test_conflicted_is_named_a_descriptive_state(self):
        assert _norm("use conflicted only when material bullish and bearish "
                     "evidence are genuinely opposed and neither dominates") in FLAT

    def test_the_neutral_tokens_are_still_offered_not_mandated(self):
        """Removing the veto must not remove the option. A neutral answer stays
        available and stays correct for a directional stand_down."""
        assert '"none"' in P
        assert _norm('for a directional stand_down, ["none"], ["wait"], '
                     '["two_sided_watch"] and ["confirmation_required"] are all correct') in FLAT

    def test_conflicted_does_not_become_an_obligation_to_trade(self):
        """The inverse defect. Permission must never read as pressure."""
        assert _norm("stand down from new entries while control is unresolved") in FLAT
        assert _norm("no opposing-direction entry is allowed") in FLAT

    def test_standing_down_on_a_fact_remains_complete(self):
        assert _norm("a directional story may remain in the packet without a trade") in FLAT


# ══════════════════════════════════════════════════════════════════════════════
class TestSufficiencyLaw:
    """Mechanics still requires real evidence; geometry cannot author direction."""

    def test_the_six_conditions_are_all_named(self):
        assert _norm("a mechanically eligible object proves its own identity/lifecycle/geometry") in FLAT
        assert _norm("it does not prove that it belongs to the current campaign or phase") in FLAT

    def test_proof_of_future_continuation_is_not_required(self):
        assert _norm("it may later provide a location for continuation with "
                     "the incumbent direction") in FLAT

    def test_the_exact_10_10_57_failure_mode_is_named(self):
        """A local reversal tool cannot itself promote a new campaign."""
        assert _norm("tools, geometry, a local raid, displacement, or one local "
                     "structure event never create or transfer campaign direction") in FLAT

    def test_uncertainty_is_not_a_veto(self):
        assert _norm("treat missing or unresolved continuity as unknown, never "
                     "as permission to flip") in FLAT
        assert _norm("if control is contested or unavailable, describe the "
                     "evidence and stand down") in FLAT

    def test_only_facts_may_stop_her(self):
        assert _norm("if the campaign is unestablished, transfer is developing, "
                     "or continuity is unavailable, stand down") in FLAT

    def test_no_todays_prices_or_outcome_were_encoded(self):
        """The repair is doctrine, not a memorial to one session. A price, a
        date or a session id in the prompt would make it one."""
        for leak in ("28979", "28962", "29242", "28947", "29283", "2026-08-24",
                     "20260824", "maurice", "ote_after_reclaim at 28966"):
            assert leak.lower() not in FLAT, leak
        assert not re.search(r"\b2[89]\d{3}(\.\d+)?\b", P), "a raw MNQ price leaked"


# ══════════════════════════════════════════════════════════════════════════════
class TestCampaignVersusCounterflow:
    """One campaign direction persists; local counter-flow is not trade authority."""

    def test_dominant_direction_is_distinct_from_local_retracement(self):
        assert _norm("`narrative_direction` means the dominant current market "
                     "delivery / campaign direction") in FLAT
        assert _norm("it never means the direction of a local retracement") in FLAT

    def test_opposed_theses_are_declared_ordinary(self):
        assert _norm("retracement is counter-flow, not an opposing trade") in FLAT

    def test_a_counter_directional_path_cannot_authorize_entry(self):
        assert _norm("does not authorize the opposing directional trade") in FLAT

    def test_the_broader_thesis_need_not_be_invalidated_first(self):
        assert _norm("then, and only then, `narrative_direction` may change to "
                     "that new owner") in FLAT

    def test_a_protected_level_is_not_a_directional_prison(self):
        """2026-08-24: she held bearish under an intact protected high for two
        hours. The level records the broader thesis; it does not own the tape."""
        assert _norm("its failure alone begins a developing transfer but does "
                     "not establish the new campaign") in FLAT

    def test_narrative_direction_is_defined_as_dominant_delivery(self):
        assert _norm('narrative_direction answers only "what is the dominant '
                     'current market delivery?"') in FLAT

    def test_campaign_cause_and_draw_remain_represented(self):
        """The dominant story and active draw remain explicit packet evidence."""
        for field in ("market_story", "thesis_health", "active_draw",
                      "contradiction_flags"):
            assert field in P, field
        assert _norm("prior campaign direction and its causal explanation, "
                     "the active-leg evidence") in FLAT

    def test_naming_a_path_is_not_a_claim_the_conflict_resolved(self):
        assert _norm("first establish the narrative, then select geometry") in FLAT


class TestNeitherTimeframeLayerHoldsAVeto:
    """Coarse context establishes the campaign; local evidence explains phase/location."""

    def test_htf_informs_the_four_things_it_legitimately_informs(self):
        assert _norm("use session and 15m delivery") in FLAT

    def test_htf_bias_alone_is_not_an_automatic_veto(self):
        assert _norm("lower-timeframe evidence can contribute to a causal "
                     "transfer only through the complete active-path sequence") in FLAT

    def test_htf_is_still_real_evidence_she_must_weigh(self):
        assert _norm("coarse delivery sets the campaign; lower timeframes "
                     "locate it") in FLAT

    def test_local_geometry_does_not_automatically_outrank_htf(self):
        """THE CONVERSE PRISON. This is the assertion that fails if the doctrine
        ever drifts back toward 'a location always wins'."""
        assert _norm("those facts do not make it an authorized opportunity") in FLAT
        assert _norm("tool availability, one-sided catalog asymmetry, reward-to-risk, "
                     "or a destination beyond price to choose or change") in FLAT

    def test_materially_adverse_coarse_facts_are_a_real_reason_to_refuse(self):
        assert _norm("stand down whenever the campaign or transfer state is "
                     "unresolved") in FLAT

    def test_neither_layer_holds_a_standing_veto(self):
        assert _norm("that destination does not create a second independently "
                     "tradable path thesis") in FLAT

    def test_a_coarse_zone_beyond_price_is_a_draw_first(self):
        assert _norm("an untouched objective is evidence of a possible draw") in FLAT

    def test_a_destination_alone_never_creates_a_trade(self):
        """Second operator correction: 'destination above price MAKES the path
        bullish' is the mirror-image of 'HTF bearish means short'."""
        assert _norm("that destination does not create a second independently "
                     "tradable path thesis") in FLAT


class TestDefendedLevelDoctrineMatchesThePayload:
    """Third operator correction. The first draft told her to read
    created -> TESTED -> STRENGTHENED. Proven against the archived payloads:
    `protected_swings` publishes level/timeframe/role/registered_at/swing_id/
    basis, and `protected_low_status` is a STATELESS current-price relation
    recomputed every scan (`brain_input._protected`). Nothing carries revisit
    count, status history, or a failed re-attack. Instructing her to read a
    lifecycle she cannot observe would license invention.

    So the clause was reduced to exactly the two facts the payload proves."""

    def test_the_level_is_not_a_static_boolean(self):
        assert _norm("a protected high or low is not a single boolean that is "
                     "true once and then static") in FLAT

    def test_only_the_two_observable_carriers_are_named(self):
        assert _norm("`basis` + `registered_at`") in FLAT
        assert _norm("its continued presence") in FLAT

    def test_presence_is_liveness_is_stated_correctly(self):
        assert _norm("the registry drops a level the moment price accepts "
                     "through it") in FLAT

    def test_she_is_forbidden_from_narrating_an_unobservable_retest(self):
        """The guard that keeps this clause honest."""
        assert _norm("you are not told how many times price returned to the "
                     "level, whether any particular return failed") in FLAT
        assert _norm("do not narrate a re-test you cannot see") in FLAT

    def test_the_unobservable_lifecycle_words_are_absent(self):
        """Mechanical guard against the reduced clause drifting back."""
        for banned in ("it is tested when price returns",
                       "re-attacked and held",
                       "strengthened when that return fails"):
            assert _norm(banned) not in FLAT, banned

    def test_the_payload_really_lacks_a_revisit_carrier(self):
        """The clause's premise, pinned against the producer. If a revisit
        history is ever published, this test fails and the doctrine may be
        widened deliberately rather than by drift."""
        import inspect
        from ai_brain import brain_input
        src = inspect.getsource(brain_input._protected)
        for absent in ("revisit", "retest", "touch_count", "tested", "history"):
            assert absent not in src.lower(), absent
        assert "registered_at" not in src   # passed through, never recomputed


class TestEquilibriumIsADecisionPoint:

    def test_the_midpoint_does_not_end_the_path(self):
        assert _norm("equilibrium is a decision point, not a destiny") in FLAT
        assert _norm("never treat reaching a midpoint as proof that the path is "
                     "finished") in FLAT

    def test_both_reactions_are_described(self):
        assert _norm("price rejecting there resumes the prior delivery") in FLAT
        assert _norm("price accepting through it says the changed delivery "
                     "continues") in FLAT

    def test_no_new_threshold_was_invented(self):
        """This unit adds cognition doctrine only. A numeric band here would be
        a new indicator smuggled into a prompt."""
        assert not re.search(r"0\.\d{2}\s*(retracement|band|threshold)", FLAT)


class TestSufficiencyDoesNotLicenseChasing:
    """The 10:42:57 negative control, written into the contract. She turned
    bullish only once price was 71 points above the order block and 108 above
    the OTE zone; that stand_down was CORRECT and must stay correct."""

    def test_sufficiency_is_scoped_to_the_location(self):
        assert _norm("reserve this for the location itself") in FLAT

    def test_leaving_the_location_spends_the_argument(self):
        assert _norm("once price has left that structure, the argument is "
                     "spent") in FLAT

    def test_missing_it_is_a_complete_answer(self):
        assert _norm('"i missed it" is a complete and correct answer') in FLAT

    def test_early_and_late_are_named_opposite(self):
        assert _norm("entering early at a location and entering late after the "
                     "move are opposite behaviours, and only the first is what "
                     "this section permits") in FLAT

    def test_the_extended_move_action_fact_still_stands(self):
        assert _norm("an extended move") in FLAT


class TestProposalCoherence:
    """A proposal's side must be the established campaign side."""

    def test_a_proposal_must_carry_its_own_direction(self):
        assert _norm("if `current_action` proposes an entry, `narrative_direction` "
                     "remains the dominant campaign direction") in FLAT

    def test_the_mechanical_consequence_is_stated_not_implied(self):
        assert _norm("the selected playbook/tool must agree with it") in FLAT

    def test_refusing_to_name_a_path_still_means_stand_down(self):
        """The clause must not push her to invent a direction to keep a trade."""
        assert _norm("stand down whenever the campaign or transfer state is "
                     "unresolved") in FLAT

    def test_the_producer_really_does_refuse_conflicted(self):
        """The clause claims a mechanical fact. Pin the fact, not the claim --
        if `_direction` ever starts accepting conflicted, this prompt text
        becomes a lie and must be revisited."""
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._direction(
                {"narrative_direction": "conflicted"}, {})
        assert exc.value.reason == "stand_down"

    def test_a_named_direction_passes_that_same_gate(self):
        assert CandidateProducer._direction(
            {"narrative_direction": "bullish"}, {}) == "bullish"


# ══════════════════════════════════════════════════════════════════════════════
class TestNothingWasWidenedBeyondCognition:

    def test_no_sizing_or_risk_authority_was_granted(self):
        """Position sizing is deterministic risk authority and is not Luna's.
        `reduce size because you are conflicted` would be the classic leak."""
        for phrase in ("reduce size", "smaller size", "half size", "size down",
                       "position size", "contracts", "reduce risk",
                       "increase size", "scale in"):
            assert phrase not in FLAT, phrase

    def test_the_existing_risk_prohibition_survives(self):
        assert _norm("never widen risk, size, or reward-to-risk") in FLAT

    def test_action_facts_still_may_not_change_direction(self):
        """The paragraph the sufficiency law was appended to must be intact."""
        assert _norm("a missing playbook, poor reward-to-risk, an extended move, "
                     "waiting for confirmation, or absent execution geometry are "
                     "action facts — they must never change your direction") in FLAT

    def test_structure_is_still_witness_only(self):
        assert _norm("structure is witness only. it cannot define direction") in FLAT

    def test_the_authorized_object_contract_is_untouched(self):
        assert _norm("nothing outside those lists can be traded against") in FLAT
        assert _norm("never invent an id") in FLAT


# ══════════════════════════════════════════════════════════════════════════════
class TestARecommendationStillRequiresARealTool:
    """The repair removes a REFUSAL. It grants no new execution authority."""

    def test_a_tool_the_market_never_produced_is_still_refused(self):
        """Step 7, untouched: a family the deterministic toolbox did not detect
        cannot be executed however confidently she names it."""
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(
                ["order_block"], "bullish", {"toolbox": {}}, trace={})
        assert exc.value.reason == "tool_not_detected"

    def test_a_stand_down_never_becomes_a_candidate(self):
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_action_permits_entry(
                {"current_action": "stand_down",
                 "recommended_tool_family": ["ote_after_reclaim"]})
        assert exc.value.reason == "action_declines_entry"

    def test_the_validator_never_invents_a_family_under_conflicted(self):
        """Removing the prompt veto must not push the NORMALIZER into supplying
        a directional family for her."""
        out, _ = normalize_output({"narrative_direction": "conflicted",
                                   "narrative_phase": "transition",
                                   "recommended_tool_family": None,
                                   "dominant_reasoning": "x" * 80})
        assert out["recommended_tool_family"] == ["none"]

    def test_the_validator_still_passes_a_family_she_did_name(self):
        """Normalization remains descriptive; the narrative authority gate is
        downstream and decides whether a candidate side is authorized."""
        out, _ = normalize_output({"narrative_direction": "conflicted",
                                   "narrative_phase": "transition",
                                   "recommended_tool_family": ["ote_after_reclaim"],
                                   "dominant_reasoning": "x" * 80})
        assert out["recommended_tool_family"] == ["ote_after_reclaim"]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheContractFingerprintMoved:

    def test_brain_prompt_is_inside_the_contract_closure(self):
        from ai_brain.production_model import (_CONTRACT_SOURCES,
                                               _CONTRACT_SOURCES_REPO)
        rels = [rel for _label, rel in _CONTRACT_SOURCES + _CONTRACT_SOURCES_REPO]
        assert "ai_brain/brain_prompt.py" in rels

    def test_the_pre_repair_fingerprint_can_no_longer_be_produced(self):
        """`brain:064298a1cf9a85df` is the 2026-08-24 production contract. An
        authorization minted against it must fail closed after this unit."""
        from ai_brain.production_model import brain_contract_fingerprint
        assert brain_contract_fingerprint() != "brain:064298a1cf9a85df"

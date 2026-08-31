"""Luna -> CandidateSnapshot producer locks. No network, no orders."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402

from broker.luna_candidate_producer import (                      # noqa: E402
    CandidateProducer, NoCandidate, classify_draw, enumerate_objectives,
    resolve_objective,
)
from broker.topstepx_candidate_freshness import CandidateSnapshot  # noqa: E402
from broker.topstepx_client import TopstepXContract                # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)


def execution_block(bid, ask, *, fresh=True, available=True, reason=None,
                    age=0.4):
    """The executable block a live scan now attaches. EXEC-PRICE-FRESHNESS-1.

    Defaults to a zero-width spread so a fixture's `price` is what a candidate
    is priced from on BOTH sides; tests that care about sidedness pass a real
    bid and ask.
    """
    if not available:
        return {"schema": "execution_price.v1", "available": False, "fresh": False,
                "source": None, "unavailable_reason": reason or "NO_QUOTE_PROVIDER",
                "best_bid": None, "best_ask": None, "last_trade": None,
                "captured_at": None, "age_seconds": None, "max_age_seconds": 5.0}
    return {"schema": "execution_price.v1", "available": True, "fresh": fresh,
            "source": "topstepx_realtime_quote",
            "unavailable_reason": None if fresh else "UNRELIABLE_STALE_QUOTE",
            "best_bid": bid, "best_ask": ask, "last_trade": bid,
            "captured_at": "2026-08-05T15:29:59+00:00", "age_seconds": age,
            "max_age_seconds": 5.0,
            "bullish_executable": ask, "bearish_executable": bid}


def brain_input(price=29880.0, buy_side=29910.25, sell_side=29840.0,
                prot_low=29875.0, prot_high=29915.0, execution=None):
    return {
        "timestamp": "2026-08-05T15:29:00+00:00",
        "market": {"current_price": price,
                   "settled_price_basis": "settled_close:1m",
                   "execution_price": (execution if execution is not None
                                       else execution_block(price, price))},
        "liquidity": {"nearest_buy_side": buy_side, "nearest_sell_side": sell_side},
        "protected_swings": {
            "protected_low": {"level": prot_low, "timestamp": "2026-08-05T15:00:00+00:00"},
            "protected_high": {"level": prot_high, "timestamp": "2026-08-05T15:05:00+00:00"},
        },
    }


def parsed(**over):
    p = {"narrative_direction": "bullish", "narrative_phase": "continuation",
         "invalidation_level": 29875.0, "active_draw": "buy side liquidity above",
         "recommended_playbook_family": "continuation",
         "recommended_tool_family": ["fvg"], "market_story": "bullish continuation",
         "current_action": "await_retest"}
    p.update(over)
    return p


def result(**over):
    r = {"ok": True, "parsed": parsed(), "fallback_reason": None,
         "model": PRODUCTION_MODEL}
    r.update(over)
    return r


def producer():
    return CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint=FP, contract=MNQ)


def produce(p=None, *, res=None, bi=None, qual=None, **over):
    kw = dict(brain_result=res or result(), brain_input=bi or brain_input(),
              snapshot=_detected("ifvg", "fvg"),
              qualification=qual if qual is not None else {"qualified": True},
              engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
              snapshot_id="snap-1", market_data_timestamp="2026-08-05T15:29:30+00:00",
              latest_closed_bar_timestamp="2026-08-05T15:29:00+00:00", now=NOW)
    kw.update(over)
    return (p or producer()).produce(**kw)


# ══════════════════════════════════════════════════════════════════════════════
class TestValidCandidates:

    def test_a_bullish_candidate_is_produced(self):
        c = produce()
        assert isinstance(c, CandidateSnapshot)
        assert c.direction == "bullish"
        assert c.invalidation_price == 29875.0
        assert c.objective.price == 29910.25
        assert c.objective.kind == "opposing_external_liquidity"
        assert c.extras["playbook"] == "continuation"
        assert c.extras["tool_family"] == ["fvg"]
        assert c.extras["sovereign_conversion"] is True
        assert c.extras["model"] == PRODUCTION_MODEL

    def test_a_bearish_candidate_is_produced(self):
        # stop 29885 (5.00 risk), target 29840 (40.00 reward) -> 8.0R
        c = produce(bi=brain_input(prot_high=29885.0),
                    res=result(parsed=parsed(
                        narrative_direction="bearish", invalidation_level=29885.0,
                        active_draw="sell side liquidity below")))
        assert c.direction == "bearish"
        assert c.objective.price == 29840.0
        assert c.invalidation_price == 29885.0
        assert c.extras["expected_reward_to_risk"] == pytest.approx(8.0, abs=0.01)

    def test_the_expected_r_is_recorded_as_evidence(self):
        c = produce()
        # entry 29880, stop 29875 (5.00), target 29910.25 (30.25) -> 6.05R
        assert c.extras["expected_reward_to_risk"] == pytest.approx(6.05, abs=0.01)

    def test_the_objective_carries_a_named_identity(self):
        c = produce()
        assert c.objective.identity.startswith("opposing_external_liquidity:")
        for generic in ("target", "tp", "objective_1"):
            assert c.objective.identity != generic

    def test_digests_are_recorded(self):
        c = produce()
        for k in ("engine_inventory_digest", "mechanical_evidence_digest",
                  "brain_response_digest"):
            assert c.extras[k] and len(c.extras[k]) == 16


class TestStandDownAndRejection:

    @pytest.mark.parametrize("direction", ["neutral", "conflicted", ""])
    def test_a_non_directional_thesis_is_a_stand_down(self, direction):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(narrative_direction=direction)))
        assert exc.value.stand_down is True
        assert exc.value.reason == "stand_down"

    def test_a_fallback_thesis_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(fallback_reason="llm_error:Timeout"))
        assert exc.value.reason == "fallback_not_authoritative"

    def test_a_timeout_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as exc:
            produce(ai_state="AI_TIMEOUT")
        assert exc.value.reason == "brain_timeout"

    def test_a_superseded_response_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as exc:
            produce(ai_state="AI_SUPERSEDED")
        assert exc.value.reason == "brain_superseded"

    def test_another_model_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(model="gpt-5.6-sol"))
        assert exc.value.reason == "wrong_model"

    def test_a_missing_invalidation_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(invalidation_level=None)))
        assert exc.value.reason == "invalidation_missing"

    def test_a_wrong_side_invalidation_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(invalidation_level=29890.0)))
        assert exc.value.reason == "invalidation_wrong_side"

    def test_an_off_tick_invalidation_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(invalidation_level=29875.13)))
        assert exc.value.reason == "invalidation_off_tick"

    def test_an_unresolvable_draw_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(active_draw="somewhere higher probably")))
        assert exc.value.reason == "objective_unresolved"

    def test_a_missing_objective_catalog_rejects(self):
        # The payload is priceable; what is absent is the objective catalog.
        # Without the execution block this would refuse one stage earlier and
        # stop proving anything about objectives.
        with pytest.raises(NoCandidate) as exc:
            produce(bi={"timestamp": "t",
                        "market": {"current_price": 29880.0,
                                   "execution_price": execution_block(29880.0, 29880.0)}})
        assert exc.value.reason == "objective_missing"

    def test_a_wrong_side_objective_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(bi=brain_input(buy_side=29800.0),
                    res=result(parsed=parsed(active_draw="buy side liquidity")))
        assert exc.value.reason == "objective_wrong_side"

    def test_direction_disagreement_is_RECORDED_not_refused(self):
        """PHASE 3 AUTHORITY DEMOTION (2026-08-12).

        This used to raise `direction_disagreement`: the deterministic qualifier
        preferred the other side, so Terra's thesis died. That is an OPINION
        holding a permission, and it is the same authority inversion the Toolbox
        cage was. Measured on PROD-20260812-PM the mechanical direction
        disagreed with Terra on 60 of 81 scans.

        Terra owns direction. Step 7 still proves her selected tool physically
        exists on her side, which is the fact-based check that survives.
        """
        c = produce(qual={"qualified": True, "direction": "bearish"})
        assert isinstance(c, CandidateSnapshot)

    def test_an_unqualified_candidate_is_RECORDED_not_refused(self):
        """`qualified: False` is a mechanical observation, not a veto over the
        discretionary lane. It is surfaced in the trace instead."""
        c = produce(qual={"qualified": False, "reason": "funnel refused"})
        assert isinstance(c, CandidateSnapshot)

    def test_an_unauthorized_playbook_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(recommended_playbook_family="none")))
        assert exc.value.reason == "playbook_unauthorized"

    def test_a_playbook_outside_the_RECOMMENDED_set_is_still_allowed(self):
        """`authorized_playbooks` narrowed Terra's selectable set to whatever the
        deterministic classifier had already chosen -- a recommendation enforced
        as a permission. Terra may name a different playbook; its factual
        prerequisites are proven downstream by Step 7, not by the classifier's
        preference."""
        c = produce(qual={"qualified": True, "authorized_playbooks": ["reversal"]})
        assert isinstance(c, CandidateSnapshot)

    def test_an_unauthorized_tool_family_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(res=result(parsed=parsed(recommended_tool_family=[])))
        assert exc.value.reason == "tool_family_unauthorized"

    def test_a_contract_mismatch_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(snapshot={**_detected("ifvg", "fvg"), "contract_id": "CON.F.US.MNQ.Z26"})
        assert exc.value.reason == "contract_mismatch"

    def test_a_closed_window_rejects(self):
        with pytest.raises(NoCandidate) as exc:
            produce(in_window=False)
        assert exc.value.reason == "window_closed"

    def test_reward_below_the_floor_rejects_without_moving_boundaries(self):
        """Sub-floor geometry must be refused, not improved.

        RR-FLOOR-1.0 (2026-08-08): 1.0R now QUALIFIES, so the fixture moved to a
        genuinely sub-floor target. The law is unchanged -- neither boundary may
        be moved to manufacture the ratio.
        """
        bi = brain_input(buy_side=29884.0)          # 4 up vs 5 down = 0.80R
        with pytest.raises(NoCandidate) as exc:
            produce(bi=bi)
        assert exc.value.reason == "reward_below_qualification"
        assert "may be moved" in str(exc.value)


class TestObjectiveResolution:

    def test_ambiguous_objectives_are_refused_not_optimised(self):
        """Two matching objectives must never be resolved by best R."""
        cands = [
            {"kind": "equal_highs", "price": 29900.0, "identity": "equal_highs:a",
             "source": "s", "source_timestamp": "t", "supporting_evidence": {}},
            {"kind": "equal_highs", "price": 29950.0, "identity": "equal_highs:b",
             "source": "s", "source_timestamp": "t", "supporting_evidence": {}},
        ]
        with pytest.raises(NoCandidate) as exc:
            resolve_objective("equal highs above", cands,
                              direction="bullish", reference_price=29880.0)
        assert exc.value.reason == "objective_ambiguous"
        assert "flatters reward-to-risk" in str(exc.value)

    @pytest.mark.parametrize("text,kind", [
        ("previous day high", "previous_day_high"),
        ("PDL", "previous_day_low"),
        ("overnight low", "overnight_low"),
        ("equal lows", "equal_lows"),
        ("the imbalance above", "imbalance_completion"),
    ])
    def test_known_draw_phrases_classify(self, text, kind):
        assert classify_draw(text) == kind

    def test_vague_language_does_not_classify(self):
        for text in ("higher", "up there", "the next level", ""):
            assert classify_draw(text) is None

    def test_the_catalog_only_contains_snapshot_levels(self):
        cat = enumerate_objectives({}, brain_input())
        prices = {c["price"] for c in cat}
        assert prices == {29910.25, 29840.0, 29875.0, 29915.0}


class TestFingerprintDeterminism:

    def test_identical_inputs_produce_the_same_fingerprint(self):
        assert produce().fingerprint() == produce().fingerprint()

    def test_a_one_tick_stop_change_changes_the_fingerprint(self):
        a = produce().fingerprint()
        b = produce(res=result(parsed=parsed(invalidation_level=29874.75))).fingerprint()
        assert a != b

    def test_a_one_tick_target_change_changes_the_fingerprint(self):
        a = produce().fingerprint()
        b = produce(bi=brain_input(buy_side=29910.0)).fingerprint()
        assert a != b

    def test_same_price_different_objective_identity_changes_the_fingerprint(self):
        a = produce()
        b = produce(bi=brain_input(buy_side=29999.0, prot_high=29910.25),
                    res=result(parsed=parsed(active_draw="protected swing high")))
        assert a.objective.price != b.objective.price or a.fingerprint() != b.fingerprint()
        c = produce(bi=brain_input(prot_high=29910.25),
                    res=result(parsed=parsed(active_draw="protected swing high")))
        assert c.objective.price == 29910.25
        assert c.fingerprint() != a.fingerprint()      # same price, different identity

    def test_dict_order_does_not_affect_the_fingerprint(self):
        bi1 = brain_input()
        bi2 = {k: bi1[k] for k in reversed(list(bi1))}
        assert produce(bi=bi1).fingerprint() == produce(bi=bi2).fingerprint()


class TestLifecycle:

    def test_a_candidate_carries_an_expiry(self):
        c = produce()
        assert c.extras["candidate_expires_at"] > c.created_at.isoformat()

    def test_an_expired_candidate_is_detected(self):
        p = producer()
        c = produce(p)
        assert p.is_expired(c, now=NOW + timedelta(seconds=1)) is False
        assert p.is_expired(c, now=NOW + timedelta(seconds=300)) is True

    def test_a_newer_candidate_supersedes_the_old_one(self):
        p = producer()
        first = produce(p)
        second = produce(p, bi=brain_input(buy_side=29920.0))
        assert p.active_candidate is second
        assert first.fingerprint() in p._superseded

    def test_the_producer_builds_no_bracket(self):
        """Bracket construction belongs at submit time, on the current price."""
        import inspect
        import broker.luna_candidate_producer as m
        src = inspect.getsource(m)
        assert "build_bracket" not in src
        assert "as_order_payload" not in src
        assert "stopLossBracket" not in src

    def test_the_producer_has_no_execution_methods(self):
        for name in ("place_order", "submit", "gated_submit", "cancel_order",
                     "close_position", "flatten", "authorize_submission"):
            assert not hasattr(CandidateProducer, name)

    def test_the_producer_never_mints_a_token(self):
        import inspect
        import broker.luna_candidate_producer as m
        assert "smoke_auth" not in inspect.getsource(m)


class TestRunnerBoundary:

    def test_the_produced_candidate_satisfies_the_runner_freshness_gate(self):
        """The whole point: the producer's output is what the gate expects."""
        from broker.topstepx_candidate_freshness import assess
        c = produce()
        verdict = assess(c, current_price=29882.0, high_since=29884.0,
                         low_since=29878.0, tick_size=0.25, snapshot_id="snap-1",
                         contract_id=CID, account_fingerprint=FP,
                         account_state_digest="", data_age_seconds=2.0,
                         in_window=True, manual_activity=False, now=NOW)
        assert verdict["fresh"] is True
        assert verdict["objective_validation"]["valid"] is True

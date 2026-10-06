from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_brain.narrative_continuity import build_narrative_continuity
from market_data.campaign_draw_truth import (
    CampaignDrawTruth, PROVEN_DELIVERED, PROVEN_NOT_DELIVERED)
from market_data.campaign_lifecycle import evaluate_campaign_lifecycle
from market_data.trade_horizon import (
    AUTHORITY_UNKNOWN, CAMPAIGN_HOLD, LOCAL_PARTICIPATION,
    project_trade_horizon)
from market_state.active_path import production_session_key


CONTRACT = "CON.F.US.MNQ.U26"
SESSION = "TRADE-HORIZON-SESSION"
START = datetime(2026, 8, 5, 15, 29, tzinfo=timezone.utc)
REVISION = 9


def stamp(offset=0):
    return (START + timedelta(minutes=offset)).isoformat()


def authorities(*, direction="bullish", campaign_price=29950,
                campaign_identity=None, phase="continuation"):
    sign = 1 if direction == "bullish" else -1
    campaign_identity = campaign_identity or (
        f"opposing_external_liquidity:{'buyside' if sign == 1 else 'sellside'}@{campaign_price:g}")
    objective = {"identity": campaign_identity,
                 "kind": "opposing_external_liquidity",
                 "price": campaign_price}
    side = "low" if direction == "bullish" else "high"
    path = {
        "contract_id": CONTRACT,
        "state_available": True, "owner": direction, "status": "active",
        "session": production_session_key(stamp(2)),
        "origin": {"direction": direction, "at": stamp(0),
                   "proof_family": "rejected_raid_reclaim",
                   "occurrence_id": f"origin:{direction}"},
        "load_bearing_structure": {"side": side, "level": 29875 if sign == 1 else 29885,
                                   "intact": True},
        "progression": {"supporting_timeframes": ["1m"]},
        "transfer_evidence": {
            "opposing_structure_break": False,
            "load_bearing_failure": False,
            "load_bearing_replaced_against_path": False,
            "ambiguous_load_bearing_invalidation": False,
            "opposing_raid_rejected": False,
        },
        "last_invalidated": None,
    }
    snapshot = {
        "timestamp": stamp(2), "contract_id": CONTRACT,
        "derived_state": {"current": True, "history_revision": REVISION,
                          "derived_revision": REVISION},
        "active_path_state": path,
    }
    rows = [{"timestamp": stamp(i), "open": 29880, "high": 29880.5,
             "low": 29879.5, "close": 29880, "volume": 10,
             "contract": CONTRACT, "members": 1, "expected_members": 1,
             "complete": True} for i in range(3)]
    accepted = {"direction_authorized": True, "direction": direction,
                "objective": objective,
                "brain_lineage": {"source": "llm", "snapshot_id": "scan-3"}}
    draw_tracker = CampaignDrawTruth(contract_id=CONTRACT, session_id=SESSION,
                                     instrument="MNQ")
    def observe(bars):
        return draw_tracker.observe(
            settled_bars=bars,
            settled_source={"source_bar_time": bars[-1]["timestamp"],
                            "temporal_status": "settled",
                            "settled_edge_basis": "no_member_list_published"},
            contract_id=CONTRACT, session_id=SESSION,
            history_revision=REVISION, derived_state_current=True,
            accepted_view=accepted, ownership_state=path)
    observe(rows[:1])
    campaign_draw = observe(rows)
    continuity = build_narrative_continuity(snapshot, {"available": False})
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot,
        brain_output={"narrative_direction": direction,
                      "narrative_phase": phase},
        narrative_continuity=continuity,
        campaign_draw=campaign_draw, session_id=SESSION,
        contract_id=CONTRACT, brain_authority_available=True)
    assert campaign_draw["authority_status"] == PROVEN_NOT_DELIVERED
    assert lifecycle["state"] == "ACTIVE_DELIVERY"
    return snapshot, campaign_draw, lifecycle


def registry(*rows):
    return {"by_timeframe": {
        "highs": {row["timeframe"]: row for row in rows
                  if row["side"] == "high"},
        "lows": {row["timeframe"]: row for row in rows
                 if row["side"] == "low"},
    }}


def swing(side, level, *, tf="1m", swing_id="swing-1", registered=None):
    return {"side": side, "level": level, "timeframe": tf,
            "swing_id": swing_id, "registered_at": registered or stamp(0),
            "basis": f"{side}_raid_rejected", "role": f"protected_{side}"}


def project(*, draw_price=29950, draw_identity=None, direction="bullish",
            target=29910.25, target_identity="opposing_external_liquidity:buyside@29910.25",
            entry=29880, stop=29875, rows=(), draw_mutation=None,
            protected_override=None):
    snapshot, draw, lifecycle = authorities(
        direction=direction, campaign_price=draw_price,
        campaign_identity=draw_identity)
    if draw_mutation:
        draw.update(draw_mutation)
    bi = {"market": {"current_price": 29880,
                      "settled_price_basis": "settled_close:1m",
                      "execution_price": {"source": "topstepx_realtime_quote",
                                           "captured_at": stamp(2),
                                           "bullish_executable": entry,
                                           "bearish_executable": entry}},
          "protected_swings": (protected_override if protected_override is not None
                               else registry(*rows))}
    return project_trade_horizon(
        snapshot=snapshot, brain_input=bi, campaign_draw=draw,
        campaign_lifecycle=lifecycle, direction=direction,
        entry_price=entry, stop_price=stop,
        objective_identity=target_identity,
        objective_kind="opposing_external_liquidity",
        objective_price=target, snapshot_id="scan-3", session_id=SESSION,
        contract_id=CONTRACT, narrative_phase="continuation")


def test_real_public_draw_classifies_local_and_exact_campaign_target():
    local = project(rows=(swing("high", 29882.5),))
    assert local["classification"] == LOCAL_PARTICIPATION
    assert local["selected_target_reward_to_risk"] == pytest.approx(6.05)
    assert local["protected_structure"]["nearest"][0]["reward_to_risk"] == pytest.approx(.5)
    assert local["campaign"]["episode_id"]

    hold = project(draw_price=29910.25,
                   draw_identity="opposing_external_liquidity:buyside@29910.25",
                   target=29910.25,
                   target_identity="opposing_external_liquidity:buyside@29910.25")
    assert hold["classification"] == CAMPAIGN_HOLD


@pytest.mark.parametrize("target,identity", [
    (29950, "different_identity_same_price"),
    (29960, "opposing_external_liquidity:buyside@29960"),
    (29910.25, "opposing_external_liquidity:buyside@29950"),
])
def test_same_price_mismatch_and_farther_than_campaign_are_unknown(target, identity):
    result = project(target=target, target_identity=identity)
    assert result["classification"] == AUTHORITY_UNKNOWN


def test_bearish_mirror_uses_directional_distances():
    result = project(direction="bearish", draw_price=29800,
                     target=29845, target_identity="local:target@29845",
                     entry=29880, stop=29885,
                     rows=(swing("low", 29877.5),))
    assert result["classification"] == LOCAL_PARTICIPATION
    assert result["selected_target_distance"] == 35
    assert result["protected_structure"]["nearest"][0]["reward_to_risk"] == pytest.approx(.5)


def test_executable_entry_not_settled_close_is_the_payoff_reference():
    result = project(entry=29881, rows=(swing("high", 29883),))
    assert result["entry_price"] == 29881
    assert result["settled_price_at_authorship"] == 29880
    assert result["protected_structure"]["nearest"][0]["distance_from_entry"] == 2


def test_available_empty_registry_is_distinct_from_unavailable_registry():
    empty = project()
    assert empty["protected_structure"]["status"] == \
        "NO_PUBLISHED_INTERVENING_PROTECTED_LEVEL"
    missing = project(protected_override={})
    assert missing["protected_structure"]["status"] == "UNKNOWN"


def test_malformed_registry_cannot_be_reported_as_empty_or_nearest():
    result = project(protected_override={"by_timeframe": {
        "highs": {"1m": {"level": 29882}}, "lows": {}}})
    assert result["protected_structure"]["status"] == "UNKNOWN"
    assert result["protected_structure"]["nearest"] is None


def test_nearest_is_order_independent_and_retains_tied_witness_lives():
    a = swing("high", 29882.5, tf="1m", swing_id="repeat", registered=stamp(0))
    b = swing("low", 29882.5, tf="5m", swing_id="repeat", registered=stamp(1))
    farther = swing("high", 29885, tf="15m", swing_id="farther")
    first = project(rows=(farther, a, b))
    second = project(rows=(b, farther, a))
    assert first["protected_structure"] == second["protected_structure"]
    nearest = first["protected_structure"]["nearest"]
    assert len(nearest) == 2
    assert {row["side"] for row in nearest} == {"high", "low"}
    assert {row["registered_at"] for row in nearest} == {stamp(0), stamp(1)}


@pytest.mark.parametrize("level,relation", [
    (29879, "BEHIND_ENTRY"),
    (29880, "AT_ENTRY"),
    (29910.25, "AT_SELECTED_TARGET"),
])
def test_entry_target_and_behind_relations(level, relation):
    result = project(rows=(swing("high", level),))
    assert result["protected_structure"]["witnesses"][0]["relation"] == relation


@pytest.mark.parametrize("mutation", [
    {"superseded": True},
    {"authority_status": "UNKNOWN"},
    {"authority_status": PROVEN_DELIVERED},
    {"history_revision": REVISION + 1},
    {"campaign_episode_id": "prior-episode"},
    {"objective_identity": "another-campaign"},
    {"campaign_direction": "bearish"},
    {"session_id": "prior-session"},
    {"process_authority": "AUDIT_ONLY"},
])
def test_stale_or_mismatched_public_campaign_authority_is_unknown(mutation):
    result = project(draw_mutation=mutation)
    assert result["classification"] == AUTHORITY_UNKNOWN


def test_current_episode_change_is_not_reused_from_a_prior_projection():
    old = project()
    new_snapshot, new_draw, new_lifecycle = authorities()
    new_draw["campaign_episode_id"] = "fresh-episode"
    new_lifecycle["campaign_episode_id"] = "fresh-episode"
    result = project_trade_horizon(
        snapshot=new_snapshot,
        brain_input={"market": {}, "protected_swings": {"by_timeframe": {
            "highs": {}, "lows": {}}}},
        campaign_draw=new_draw, campaign_lifecycle=new_lifecycle,
        direction="bullish", entry_price=29880, stop_price=29875,
        objective_identity="opposing_external_liquidity:buyside@29910.25",
        objective_kind="opposing_external_liquidity", objective_price=29910.25,
        snapshot_id="scan-4", session_id=SESSION, contract_id=CONTRACT,
        narrative_phase="continuation")
    assert old["campaign"]["episode_id"] != result["campaign"]["episode_id"]


def test_projection_is_stateless_and_does_not_provide_an_entry_permission():
    result = project(rows=(swing("high", 29882.5),))
    assert "participation_permitted" not in result
    assert "authorized_direction" not in result
    assert result["classification"] == LOCAL_PARTICIPATION


def test_real_candidate_producer_keeps_target_and_allows_low_obstacle_payoff():
    import copy
    from test_luna_candidate_producer import (
        _detected, _established_narrative, brain_input as make_brain_input,
        producer as make_producer, result as make_result, CID as fixture_contract,
        NOW)
    from broker.luna_candidate_producer import NoCandidate
    from broker.luna_candidate_producer import authorized_objective_catalog
    from market_data.campaign_lifecycle import TRANSFER_UNRESOLVED

    path, _ = _established_narrative("bullish")
    path["session"] = production_session_key(stamp(2))
    snapshot = _detected("ifvg", "fvg")
    snapshot.update({"contract_id": fixture_contract, "timestamp": stamp(2),
                     "derived_state": {"current": True,
                                       "history_revision": REVISION,
                                       "derived_revision": REVISION},
                     "active_path_state": path})
    continuity = build_narrative_continuity(snapshot, {"available": False})
    rows = [{"timestamp": stamp(i), "open": 29880, "high": 29880.5,
             "low": 29879.5, "close": 29880, "volume": 10,
             "contract": fixture_contract, "members": 1,
             "expected_members": 1, "complete": True} for i in range(3)]
    campaign_objective = {
        "identity": "opposing_external_liquidity:buyside@29950",
        "kind": "opposing_external_liquidity", "price": 29950.0}
    accepted = {"direction_authorized": True, "direction": "bullish",
                "objective": campaign_objective}
    tracker = CampaignDrawTruth(contract_id=fixture_contract,
                                session_id="TH-TEST", instrument="MNQ")

    def observe(bars):
        return tracker.observe(
            settled_bars=bars,
            settled_source={"source_bar_time": bars[-1]["timestamp"],
                            "temporal_status": "settled",
                            "settled_edge_basis": "no_member_list_published"},
            contract_id=fixture_contract, session_id="TH-TEST",
            history_revision=REVISION, derived_state_current=True,
            accepted_view=accepted, ownership_state=path)

    observe(rows[:1])
    public_draw = observe(rows)
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot,
        brain_output={"narrative_direction": "bullish",
                      "narrative_phase": "continuation"},
        narrative_continuity=continuity, campaign_draw=public_draw,
        session_id="TH-TEST", contract_id=fixture_contract,
        brain_authority_available=True)
    assert public_draw["authority_status"] == PROVEN_NOT_DELIVERED
    assert lifecycle["state"] == "ACTIVE_DELIVERY"
    snapshot["campaign_lifecycle"] = lifecycle

    bi = make_brain_input(price=29880, buy_side=29910.25,
                          prot_low=29875, prot_high=29915)
    bi["narrative_continuity"] = continuity
    bi["protected_swings"]["by_timeframe"] = {
        "highs": {"1m": swing("high", 29882.5)}, "lows": {}}
    parsed = make_result().get("parsed")
    parsed["objective_id"] = next(
        row["objective_id"] for row in authorized_objective_catalog(
            snapshot, bi, 29880)
        if row["identity"] == "opposing_external_liquidity:buyside@29910.25")
    brain_result = make_result(parsed=parsed, source="llm",
                               narrative_continuity=continuity)
    producer = make_producer()
    before_snapshot, before_input = copy.deepcopy(snapshot), copy.deepcopy(bi)
    candidate = __import__("test_luna_candidate_producer").produce(
        producer, res=brain_result, bi=bi, snapshot=snapshot,
        campaign_draw=public_draw, campaign_session_id="TH-TEST",
        require_campaign_lifecycle=True)

    assert candidate.objective.price == 29910.25
    assert candidate.entry_price == 29880
    assert candidate.invalidation_price == 29875
    assert candidate.extras["expected_reward_to_risk"] == pytest.approx(6.05)
    horizon = candidate.extras["trade_horizon"]
    assert horizon["classification"] == LOCAL_PARTICIPATION
    assert horizon["candidate_id"] == candidate.candidate_id
    assert horizon["selected_target_reward_to_risk"] == pytest.approx(6.05)
    assert horizon["protected_structure"]["nearest"][0]["reward_to_risk"] == pytest.approx(.5)
    assert producer.last_decision_trace["reward_risk_floor"] == producer.min_r
    assert snapshot == before_snapshot
    assert bi == before_input

    # The projection itself is non-authoritative: withholding it cannot change
    # an already permitted candidate or silently become a new refusal.
    no_draw = __import__("test_luna_candidate_producer").produce(
        producer, res=brain_result, bi=bi, snapshot=snapshot,
        campaign_draw=None, campaign_session_id="TH-TEST",
        require_campaign_lifecycle=True)
    assert no_draw.direction == candidate.direction
    assert no_draw.objective == candidate.objective
    assert no_draw.invalidation_price == candidate.invalidation_price
    assert no_draw.extras["trade_horizon"]["classification"] == AUTHORITY_UNKNOWN

    snapshot["campaign_lifecycle"] = {
        "state": TRANSFER_UNRESOLVED, "participation_permitted": False,
        "authorized_direction": None}
    with pytest.raises(NoCandidate, match="campaign_lifecycle_refused"):
        __import__("test_luna_candidate_producer").produce(
            producer, res=brain_result, bi=bi, snapshot=snapshot,
            campaign_draw=public_draw, campaign_session_id="TH-TEST",
            require_campaign_lifecycle=True)

    snapshot["campaign_lifecycle"] = lifecycle
    producer.min_r = 7.0
    with pytest.raises(NoCandidate) as refusal:
        __import__("test_luna_candidate_producer").produce(
            producer, res=brain_result, bi=bi, snapshot=snapshot,
            campaign_draw=public_draw, campaign_session_id="TH-TEST",
            require_campaign_lifecycle=True)
    assert refusal.value.reason == "reward_below_qualification"


def test_production_calls_pass_current_draw_and_projection_is_fingerprinted():
    import ast
    import inspect
    from pathlib import Path
    from ai_brain.production_model import _CONTRACT_SOURCES
    from broker.topstepx_production_loop import ProductionLoop

    source = inspect.getsource(ProductionLoop)
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "produce"
             and isinstance(node.func.value, ast.Attribute)
             and node.func.value.attr == "producer"]
    assert len(calls) == 2
    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "campaign_draw" in keywords
        assert ast.unparse(keywords["campaign_draw"]) == \
            "scan.get('campaign_draw_truth')"
        assert "session_id" in ast.unparse(keywords["campaign_session_id"])
    assert ("trade_horizon", "market_data/trade_horizon.py") in _CONTRACT_SOURCES
    assert ("candidate_producer", "broker/luna_candidate_producer.py") in _CONTRACT_SOURCES
    assert ("campaign_lifecycle_gate", "broker/topstepx_production_loop.py") in _CONTRACT_SOURCES


def test_projection_source_has_no_private_draw_or_settled_source_dependency():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "src/market_data/trade_horizon.py").read_text()
    assert "CampaignDrawTruth._active" not in source
    assert "anchor_bar_digest" not in source
    assert "evidence_bars" not in source
    assert "settled_source" not in source
    assert "raw_trade" not in source.lower()
    assert "observed_progress_fraction" not in source

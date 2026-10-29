"""Existing plan conditions must survive the actual final order boundary."""
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_luna_candidate_producer as T
from _restoration_quote_fixture import trajectory, MintBoundary
from broker.topstepx_production_loop import ProductionLoop
from broker import topstepx_execution_runner as R


def attach_guard(runner, candidate):
    original = copy.deepcopy(candidate)
    original.extras['activation_zone'] = dict(
        original.extras['selected_tool_zone'],
        occurrence_id=original.extras['selected_tool_occurrence_id'],
        direction=original.direction)
    original.extras['plan_expires_at'] = (T.NOW+timedelta(seconds=1)).isoformat()
    runner.conditional_order_guard = ProductionLoop._freeze_conditional_order_guard(
        original,'parent-plan',candidate.contract_id)
    return original


@pytest.mark.parametrize('quote',[29860.0,29865.0,29866.0])
def test_healthy_final_quote_reaches_real_mint_boundary(tmp_path,quote):
    status,runner,candidate=trajectory(tmp_path,quote,attach=attach_guard)
    assert status=='MINT_BOUNDARY'
    assert runner.final_quote_economics['decision']=='EXECUTE_AS_AUTHORIZED'


@pytest.mark.parametrize('quote,expired,reason',[
    (29866.25,False,'conditional_order_outside_zone'),
    (29859.75,False,'conditional_order_outside_zone'),
    (29865.0,True,'conditional_order_expired')])
def test_final_quote_cannot_outlive_or_escape_authored_plan(tmp_path,quote,expired,reason):
    status,runner,_=trajectory(tmp_path,quote,expired,attach_guard)
    assert status==R.STALE_CANDIDATE
    assert runner.final_quote_economics['refusal_reason']==reason
    assert runner._entry_attempted is False


def test_missing_guard_refuses_conditional_candidate(tmp_path):
    status,runner,_=trajectory(tmp_path,29865)
    assert status==R.STALE_CANDIDATE
    assert runner.final_quote_economics['refusal_reason']=='conditional_order_guard_missing'


@pytest.mark.parametrize('mutate',[
    lambda c: c.extras.update(conditional_plan_id='another-plan'),
    lambda c: c.extras.update(selected_tool_zone={'low':1,'high':99999}),
    lambda c: c.extras.update(selected_tool_occurrence_id='another-occurrence'),
    lambda c: setattr(c,'contract_id','another-contract'),
    lambda c: setattr(c,'invalidation_price',29854),
    lambda c: c.extras.pop('conditional_plan_id')])
def test_frozen_identity_cannot_be_replaced_or_removed(tmp_path,mutate):
    def attach(r,c):
        attach_guard(r,c)
        mutate(c)
    status,runner,_=trajectory(tmp_path,29865,attach=attach)
    assert status!='MINT_BOUNDARY'
    assert runner._entry_attempted is False


def test_callback_failure_refuses_before_mint(tmp_path):
    def attach(r,c):
        def broken(*_): raise ValueError('broken')
        r.conditional_order_guard=broken
    status,runner,_=trajectory(tmp_path,29865,attach=attach)
    assert status==R.STALE_CANDIDATE
    assert runner.final_quote_economics['refusal_reason']=='conditional_order_guard_invalid'


def test_activated_removed_zone_check_reproduces_parent_leak(tmp_path):
    def broken(r,c):
        r.conditional_order_guard=lambda *_:None
    status,_,_=trajectory(tmp_path,29866.25,attach=broken)
    assert status=='MINT_BOUNDARY'
    with pytest.raises(AssertionError):
        assert status==R.STALE_CANDIDATE


def test_freezing_copies_authorized_conditions_not_mutable_original():
    holder={}
    def attach(r,c):
        old=attach_guard(r,c)
        old.extras['activation_zone']['high']=99999
        old.extras['plan_expires_at']=(T.NOW+timedelta(days=1)).isoformat()
        holder['guard']=r.conditional_order_guard
        holder['candidate']=c
    # Guard has no dependence on the mutable original after construction.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        status,runner,_=trajectory(Path(tmp),29866.25,attach=attach)
    assert status==R.STALE_CANDIDATE
    assert holder['guard'](holder['candidate'],29865,T.NOW+timedelta(seconds=2))=='conditional_order_expired'


@pytest.mark.parametrize('consumed',[False,True])
def test_final_quote_refusal_terminalizes_only_proven_unused_mission(consumed):
    transitions=[]
    mission=SimpleNamespace(attempt_count=int(consumed),order_id=None,token_spent=False,
                            transition=lambda *args:transitions.append(args))
    runner=SimpleNamespace(_entry_attempted=consumed,final_quote_economics={
        'refusal_reason':'conditional_order_outside_zone'})
    closed=ProductionLoop._terminalize_unused_freshness_mission(
        mission,R.RunnerHalt(R.STALE_CANDIDATE,'conditional_order_outside_zone'),runner)
    assert closed is (not consumed)
    assert bool(transitions) is (not consumed)

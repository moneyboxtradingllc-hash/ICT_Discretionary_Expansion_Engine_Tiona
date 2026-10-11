"""Stage 4 first checkpoint: actual retained PO3 plans and exact-object custody.

Fixed synthetic producer tape, real scans and consumers, mocked model transport.
No detector or catalog injection in the production composition cases.
"""
import copy
import json
from datetime import datetime,timedelta,timezone
import pytest
import test_reversal_foundation_proof_closure as RF
import test_campaign_draw_temporal_authority as T
from broker.conditional_plan_authority import validate_final_quote,_current_po3_binding
from market_data.reversal_formation import current_block,is_producer_owned_view

def _plan(tmp_path,monkeypatch,ecu):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    def watching(output,ordinal,payload):
        row=next(r for r in payload['authorized_tool_catalog']
                 if r['tool_family']=='po3_reversal_order_block' and r['direction']=='bullish')
        return {**output,'current_action':'watching',
                'recommended_tool_occurrence_id':row['occurrence_id'],
                'plan_expires_at':(now+timedelta(minutes=30)).isoformat()}
    cycle,calls=T._cycle_with_brain(tmp_path,monkeypatch,ecu=ecu,mutator=watching)
    first=T._scan(cycle,RF.TAPE_1M)
    planning=T._scan(cycle,T.LATER)
    producer=RF.CandidateProducer(account_fingerprint='acct:po3-participation',contract=RF.MNQ)
    candidate=T._plan_candidate(producer,planning,now)
    auth=T._authorization(candidate,now)
    authority=producer.capture_conditional_plan_authority(
        candidate=candidate,scan=planning,authorization=auth,
        process_session_id=RF.SESSION_ID,now=now)
    return cycle,calls,planning,producer,candidate,auth,authority,now

@T.ECU_MODES
def test_real_po3_plan_capture_brainless_trigger_and_final_quote(tmp_path,monkeypatch,ecu):
    cycle,calls,planning,producer,plan,auth,authority,now=_plan(tmp_path,monkeypatch,ecu)
    bound=authority.payload()
    row=bound['participation_object']
    assert row['occurrence_id']==row['formation_authority']['occurrence_id']
    assert bound['occurrence_id']==row['occurrence_id']==plan.extras['activation_zone']['occurrence_id']
    assert plan.objective.price==29500 and plan.invalidation_price==29429.75
    assert row['sweep_occurrence_id'] and row['protected_swing_occurrence_id']
    assert row['creating_run_start'] and row['validation_timestamp']
    assert len(calls)==2
    trigger=T._scan(cycle,T.NEXT_MINUTE,brain=False)
    fresh=T._trigger(producer,trigger,plan_candidate=plan,authority=authority,auth=auth,now=now)
    assert len(calls)==2
    assert fresh.extras['selected_tool_occurrence_id']==bound['occurrence_id']
    assert _current_po3_binding(trigger['snapshot'],'bullish',bound['occurrence_id'])==row
    fresh.extras['conditional_plan_id']=plan.candidate_id
    zone=bound['activation_zone'];price=(zone['low']+zone['high'])/2
    assert validate_final_quote(authority=authority,scope=producer._conditional_plan_scope,
        candidate=fresh,contract_id=RF.CONTRACT,executable_price=price,now=now)==(True,None)

@T.ECU_MODES
def test_po3_lost_formation_after_successful_trigger_refuses_final_quote(tmp_path,monkeypatch,ecu):
    cycle,calls,planning,producer,plan,auth,authority,now=_plan(tmp_path,monkeypatch,ecu)
    trigger=T._scan(cycle,T.NEXT_MINUTE,brain=False)
    fresh=T._trigger(producer,trigger,plan_candidate=plan,authority=authority,auth=auth,now=now)
    fresh.extras['conditional_plan_id']=plan.candidate_id
    zone=authority.payload()['activation_zone'];price=(zone['low']+zone['high'])/2
    args=dict(authority=authority,scope=producer._conditional_plan_scope,candidate=fresh,
              contract_id=RF.CONTRACT,executable_price=price,now=now)
    assert validate_final_quote(**args)==(True,None)
    trigger['snapshot'].pop('reversal_formation_view')
    # Campaign scope remains authentic: this isolates formation loss rather
    # than already failing at the existing campaign-scope guard.
    from market_data.campaign_scope import read_current_campaign_scope
    assert read_current_campaign_scope(trigger['snapshot'])['status']=='AVAILABLE'
    assert validate_final_quote(**args)==(False,'conditional_plan_participation_object_changed')
    assert len(calls)==2

@pytest.mark.parametrize('defect',['occurrence','zone','sweep','scope'])
def test_mutated_current_producer_view_cannot_relabel_a_formation(tmp_path,monkeypatch,defect):
    cycle,scan,calls=RF._incumbent_return_scan(tmp_path,monkeypatch)
    view=scan['snapshot']['reversal_formation_view']
    assert is_producer_owned_view(view) and current_block(scan['snapshot'],'bullish')
    record=view['bullish']['5m']
    if defect=='occurrence':record['occurrence_id']='PO3:unrelated-same-price'
    elif defect=='zone':record['block']['zone_low']+=.25
    elif defect=='sweep':record['sweep_evidence']['occurrence_id']='RAID:unrelated'
    else:view._scope['history_revision']+=1
    assert not is_producer_owned_view(view)
    assert current_block(scan['snapshot'],'bullish') is None

@pytest.mark.parametrize('copy_kind',['deepcopy','json'])
def test_copied_or_restored_formation_view_is_not_live_custody(tmp_path,monkeypatch,copy_kind):
    cycle,scan,calls=RF._incumbent_return_scan(tmp_path,monkeypatch)
    original=scan['snapshot']['reversal_formation_view']
    restored=copy.deepcopy(original) if copy_kind=='deepcopy' else json.loads(json.dumps(original))
    scan['snapshot']['reversal_formation_view']=restored
    assert current_block(scan['snapshot'],'bullish') is None

@pytest.mark.parametrize('wrong',['PO3:foreign-same-price','None','RAID:unrelated'])
def test_po3_named_occurrence_never_substitutes_the_available_object(tmp_path,monkeypatch,wrong):
    cycle,scan,calls=RF._incumbent_return_scan(tmp_path,monkeypatch)
    row=next(r for r in RF.authorized_tool_catalog(scan['snapshot'])
             if r['tool_family']=='po3_reversal_order_block' and r['direction']=='bullish')
    args=(['po3_reversal_order_block'],'bullish',scan['snapshot'])
    assert RF.CandidateProducer._assert_tool_detected(*args,occurrence_id=row['occurrence_id'])==row
    with pytest.raises(RF.NoCandidate) as error:
        RF.CandidateProducer._assert_tool_detected(*args,occurrence_id=wrong)
    assert error.value.reason=='tool_occurrence_unknown'

@T.ECU_MODES
def test_po3_capture_refuses_changed_object_identity_without_changing_scope(tmp_path,monkeypatch,ecu):
    cycle,calls,planning,producer,plan,auth,authority,now=_plan(tmp_path,monkeypatch,ecu)
    plan.extras['activation_zone']['occurrence_id']='PO3:foreign-same-price'
    plan.extras['selected_tool_occurrence_id']='PO3:foreign-same-price'
    with pytest.raises(ValueError,match='conditional_plan_participation_object_unavailable'):
        producer.capture_conditional_plan_authority(candidate=plan,scan=planning,authorization=auth,
            process_session_id=RF.SESSION_ID,now=now)

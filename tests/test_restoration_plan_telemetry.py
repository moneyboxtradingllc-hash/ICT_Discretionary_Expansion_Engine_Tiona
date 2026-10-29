"""Truthful plan telemetry without participation or order policy changes."""
import sys
import json
from types import SimpleNamespace
import pytest
import test_pre_authorized_conditional_plan as T
from broker.topstepx_production_loop import ProductionLoop


def test_real_conditional_consumer_reports_no_phantom_submission(monkeypatch):
    events=[]
    def capture(frame,event,arg):
        if event=='return' and frame.f_code is T.test_trigger_uses_stored_brain_plan_and_current_mechanics_without_recalling_brain.__code__:
            events.extend(frame.f_locals.get('plan_events',[]))
    previous=sys.getprofile()
    try:
        sys.setprofile(capture)
        T.test_trigger_uses_stored_brain_plan_and_current_mechanics_without_recalling_brain(monkeypatch)
    finally:
        sys.setprofile(previous)
    assert any(e['event']=='execution_result' for e in events)
    assert not any(e['event'] in {'final_quote_captured','economics_completed','submission_started'} for e in events)


def test_reported_submission_has_this_execution_evidence():
    events=ProductionLoop._conditional_execution_events({'outcome':'SUBMITTED',
        'sizing':{'final_quote_economics':{
            'final_quote_timestamp':'quote-time','final_entry_reference':100.0,
            'final_economics_completed_timestamp':'economics-time',
            'venue_submit_timestamp':'submit-time'}}})
    assert [e['event'] for e in events]==[
        'final_quote_captured','economics_completed','submission_started','execution_result']
    assert events[2]['timestamp']=='submit-time'


def test_refused_execution_reports_refusal_without_submission():
    events=ProductionLoop._conditional_execution_events({'outcome':'SUBMIT_FAILED',
        'final_quote_economics':{'refusal_reason':'conditional_order_expired',
                                'final_quote_timestamp':'quote-time'}})
    assert [e['event'] for e in events]==['final_quote_captured','economics_refused']
    assert events[-1]['reason']=='conditional_order_expired'


def test_journal_uses_actual_producer_and_ignores_decoy_cycle_owner(monkeypatch,tmp_path):
    import test_luna_candidate_producer as C
    import ai_retrieval.retrieval_telemetry as RT
    monkeypatch.setattr(RT,'session_root',lambda _:str(tmp_path))
    producer=C.producer()
    C.produce(producer,res=C.result(parsed=C.parsed(current_action='propose_entry')))
    loop=ProductionLoop.__new__(ProductionLoop)
    loop.producer=producer
    loop.cycle=SimpleNamespace(contract_id=C.CID,producer=SimpleNamespace(
        last_decision_trace={'geometry_valid':False}))
    scan={'snapshot_id':'producer-probe','brain_block':{'output':C.parsed(current_action='propose_entry')}}
    loop._record_decision(scan,'CANDIDATE',None,'probe')
    record=json.loads((tmp_path/'candidate_decisions.jsonl').read_text().splitlines()[-1])
    assert record['geometry_valid'] is producer.last_decision_trace['geometry_valid'] is True
    # Activated wrong-owner control: the previous implementation reads this decoy.
    loop.producer=loop.cycle.producer
    loop._record_decision(scan,'CANDIDATE',None,'activated wrong-owner control')
    broken=json.loads((tmp_path/'candidate_decisions.jsonl').read_text().splitlines()[-1])
    with pytest.raises(AssertionError):
        assert broken['geometry_valid'] is True


def test_invalid_action_has_its_own_truthful_brain_unusable_disposition():
    from broker.candidate_decision_record import terminal_disposition,BRAIN_UNUSABLE
    assert terminal_disposition('brain_action_invalid')==BRAIN_UNUSABLE

"""Priority M3 independent-review follow-up: VOID resulting consumer states.

Replay real fixed W5 producer facts through the real custody publisher. Source
facts are deliberately altered at the next cutoff to exercise negative guards.
Lineage/not_unbound use explicit private-state fault fixtures for defensive
branches, not claimed natural single-thread production transitions.
"""
import copy
import pytest
from market_data import campaign_scope as CS,campaign_premise as CP
from ai_brain.narrative_continuity import build_narrative_continuity,candidate_direction_authorized
from broker.conditional_plan_authority import _current_scope_binding
from test_campaign_scope import natural,owner,_Owner,_publish,_qualify

SURFACES=('derived_state','campaign_scope_custody','campaign_scope_custody_shadow',
          'campaign_premise_catalog','campaign_premise_shadow')

REASONS=('life_not_current_or_k_not_met','lineage_changed','not_unbound',
         'producer_facts_unavailable','d3_death_time_unestablished',
         'd3_raid_not_after_death','lt_context_unavailable','lt_origin_unavailable')

@pytest.mark.parametrize('reason',REASONS)
def test_missing_void_reason_has_exact_projection_continuity_and_plan_binding(owner,natural,reason):
    proposed=_publish(owner,natural,'14:36')
    assert _qualify(owner,proposed)['status']=='PENDING'
    custody=owner.campaign_scope_custody
    args=copy.deepcopy(natural['14:37']);snap=args['snapshot']
    path=snap['active_path_state'];incumbent=None
    if reason=='producer_facts_unavailable':snap['campaign_premise_shadow']['status']='UNAVAILABLE'
    elif reason=='life_not_current_or_k_not_met':
        snap['campaign_premise_shadow']['lives']=[x for x in snap['campaign_premise_shadow']['lives'] if x['side']!='high']
    elif reason=='lt_context_unavailable':path['session']='19990101'
    elif reason=='lt_origin_unavailable':path['origin']['occurrence_id']=None
    elif reason=='d3_death_time_unestablished':
        path['last_invalidated']['settled_edge_time']=None
        path['last_invalidated']['source_tf']='5m'
    elif reason=='d3_raid_not_after_death':
        path['last_invalidated']['settled_edge_time']='2026-08-19T14:26:00+00:00'
    elif reason=='lineage_changed':
        # A context boundary normally clears pending before activation. This
        # explicit fault tests the secondary defensive activation guard.
        custody._pending['context']['custody_lineage']='unit-stale-lineage'
        custody._pending['seal']=CS._pending_seal(custody._pending)
    elif reason=='not_unbound':
        # Ordinary S1-S7 never establishes twice concurrently. Preserve a real
        # independently activated incumbent in this private-state fault case.
        other=_Owner();p=_publish(other,natural,'14:36')
        assert _qualify(other,p)['status']=='PENDING'
        active=_publish(other,natural,'14:37')
        incumbent=CS.read_current_campaign_scope(active)['campaign']
        custody._campaign=copy.deepcopy(other.campaign_scope_custody._campaign)
    args.update(owner=owner,history_revision=0,contract_id=owner.contract_id,
                market_session=CP._session_of(snap['timestamp']))
    custody.advance(**args)
    scope=CS.read_current_campaign_scope(snap)
    assert scope['pending'] is None
    assert scope['pending_disposition']['kind']=='void'
    assert scope['pending_disposition']['reason']==reason
    assert scope['pending_disposition']['cutoff']==scope['context']['cutoff']
    current=build_narrative_continuity(snap,{'available':False})
    assert 'campaign_scope' not in current
    if reason=='producer_facts_unavailable':
        assert scope['status']=='UNAVAILABLE' and scope['authority']=='none'
        assert scope['state']=='UNBOUND' and scope['campaign'] is None
        assert current['control_state']=='unresolved' and current['dominant_direction'] is None
        assert current['campaign_premise']['status']=='UNKNOWN'
        assert not any(candidate_direction_authorized(d,snap,current)[0] for d in ('bullish','bearish'))
        with pytest.raises(ValueError,match='campaign_scope_changed'):_current_scope_binding(snap)
    elif reason=='not_unbound':
        assert scope['status']=='AVAILABLE' and scope['state']=='ACTIVE'
        assert scope['campaign']['campaign_id']==incumbent['campaign_id']
        assert current['campaign_premise']['status']=='INTACT'
        assert current['control_state']=='incumbent_intact' and current['dominant_direction']=='bearish'
        assert _current_scope_binding(snap)=={'campaign_id':incumbent['campaign_id'],
            'scope_proof_id':incumbent['scope_proof']['proof_id']}
        assert candidate_direction_authorized('bearish',snap,current)[0]
        assert not candidate_direction_authorized('bullish',snap,current)[0]
    else:
        assert scope['status']=='AVAILABLE' and scope['authority']=='scope'
        assert scope['state']=='UNBOUND' and scope['campaign'] is None
        detached={k:copy.deepcopy(v) for k,v in snap.items() if k not in SURFACES}
        legacy=build_narrative_continuity(detached,{'available':False})
        assert current==legacy
        assert _current_scope_binding(snap) is None
        for d in ('bullish','bearish'):
            assert candidate_direction_authorized(d,snap,current)==candidate_direction_authorized(d,detached,legacy)
    if reason!='not_unbound':
        next_snap=_publish(owner,natural,'14:38')
        next_scope=CS.read_current_campaign_scope(next_snap)
        assert next_scope['status']=='AVAILABLE' and next_scope['state']=='UNBOUND'
        assert _current_scope_binding(next_snap) is None
        assert CS.read_current_campaign_scope(snap)['status']=='UNAVAILABLE'

def test_unbound_model_continuity_is_legacy_without_raw_custody(owner,natural,monkeypatch):
    from ai_brain.brain_input import build_brain_input
    import ai_brain.narrative_continuity as N
    snap=_publish(owner,natural,'14:36')
    payload=build_brain_input(snap,{})
    assert 'campaign_scope' not in payload['narrative_continuity']
    # Reference the unchanged local table on identical snapshot/model facts.
    # This is an audit comparison only, not a replacement production publisher.
    monkeypatch.setattr(N,'_apply_campaign_scope',lambda snapshot,local:local)
    reference=build_brain_input(snap,{})
    assert payload==reference
    assert CS.read_current_campaign_scope(snap)['authority']=='scope'

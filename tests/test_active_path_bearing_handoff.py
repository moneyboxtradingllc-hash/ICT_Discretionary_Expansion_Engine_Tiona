"""Current protected-life producer -> actual scan-cycle ActivePath consumer.

The three captured market snapshots are not a full session replay or Brain
ground truth. They isolate a real current-registry/consumer handoff failure.
"""
import copy
import json
from pathlib import Path

import pytest

from live_scan.production_scan_cycle import ProductionScanCycle
from market_state.active_path import (ActivePath, extract_occurrences,
                                      PROTECTED_SWING_VIOLATED)


def _frames():
    data=json.loads((Path(__file__).parent/'fixtures/session_20261023_bearing_handoff.json').read_text())
    return copy.deepcopy([x['snapshot'] for x in data['frames']])


def _cycle(tmp_path,monkeypatch):
    for key in ['OCCURRENCE_LEDGER_DIR','AI_BRAIN_DIR','AI_RETRIEVAL_DIR','REPLAY_SESSIONS_DIR']:
        monkeypatch.setenv(key,str(tmp_path/key))
    monkeypatch.setenv('AI_BRAIN_ENABLED','false');monkeypatch.setenv('AI_BRAIN_LLM','false')
    return ProductionScanCycle(symbol='MNQ',contract_id='CON.F.US.MNQ.Z26',session_id='CAPTURED-HANDOFF')


def test_captured_current_protected_life_reaches_new_active_owner(tmp_path,monkeypatch):
    cycle=_cycle(tmp_path,monkeypatch)
    fixture=json.loads((Path(__file__).parent/'fixtures/session_20261023_bearing_handoff.json').read_text())
    # Existing receipt history, produced by the unchanged production detector
    # replay. The actual restart caller consumes it; no derived owner is set.
    for event in fixture['retained_occurrences']:
        cycle.occurrence_ledger.record(event)
    frames=_frames()
    for snapshot in frames:
        path=cycle._update_active_path(snapshot)
        assert path['state_available'] is True,path
    assert path['owner']=='bearish' and path['status']=='active',path
    current=frames[-1]['protected_swings']['by_timeframe']['highs']['1m']
    assert current['level']==29263.0
    assert path['load_bearing_structure'] is not None,(
        'Actual current high remained in the producer registry, but its registration '
        'was consumed before the bearish leg existed and was never handed to the new owner')
    bearing=path['load_bearing_structure']
    assert (bearing['level'],bearing['timeframe'],bearing['swing_id'],bearing['registered_at'])==(
        current['level'],'1m',current['swing_id'],current['registered_at'])


def test_registration_first_observed_after_origin_is_healthy_control(tmp_path,monkeypatch):
    # Explicit controlled variant, not claimed to be the observed tape: the
    # same current birth is first transported after the origin is forming.
    cycle=_cycle(tmp_path,monkeypatch);frames=_frames()
    frames[0]['protected_swings']['by_timeframe']['highs']={}
    for snapshot in frames:path=cycle._update_active_path(snapshot)
    assert path['owner']=='bearish' and path['load_bearing_structure'] is not None


def test_missing_current_support_does_not_invent_bearing(tmp_path,monkeypatch):
    cycle=_cycle(tmp_path,monkeypatch);frames=_frames()
    for snapshot in frames:
        snapshot['protected_swings']['by_timeframe']['highs']={}
        path=cycle._update_active_path(snapshot)
    assert path['owner']=='bearish' and path['load_bearing_structure'] is None


def _retained_life_case(change=None):
    fixture=json.loads((Path(__file__).parent/'fixtures/session_20261023_bearing_handoff.json').read_text())
    frames=_frames()
    receipt=next(copy.deepcopy(e) for e in fixture['retained_occurrences']
                 if e.get('source_tf')=='1m' and e.get('swing_id')=='1m:swing_high:29263'
                 and e.get('registered_at')=='2026-10-23T16:48:00+00:00'
                 and e.get('event_type') in ('PROTECTED_SWING_REGISTERED','PROTECTED_SWING_REPLACED'))
    current=copy.deepcopy(frames[-1]['protected_swings']['by_timeframe'])
    ap=ActivePath();ap.enforce_lifecycle(frames[0]['timestamp'],frames[0]['contract_id'])
    if change=='foreign':receipt['contract']='OTHER-CONTRACT'
    if change=='future':
        receipt['registered_at']=receipt['event_time']='2026-10-23T17:16:00+00:00'
        current['highs']['1m']['registered_at']=receipt['registered_at']
    if change in ('future_source','future_edge','future_observed'):
        field={'future_source':'source_bar_time','future_edge':'settled_edge_time',
               'future_observed':'observed_at'}[change]
        receipt[field]='2026-10-23T17:16:00+00:00'
    if change=='missing_source':receipt.pop('source_bar_time',None)
    if change!='no_receipt':ap.ingest([receipt])
    if change=='retired':
        dead={**receipt,'event_type':PROTECTED_SWING_VIOLATED,
              'event_time':'2026-10-23T17:08:00+00:00','occurrence_id':'CONTROL-RETIRED-LIFE'}
        ap.ingest([dead])
    prior=frames[0]['protected_swings']['by_timeframe']
    for frame in frames[1:]:
        ap.ingest(extract_occurrences(frame,prior,frame['contract_id']))
        prior=frame['protected_swings']['by_timeframe']
    assert ap.owner=='bearish' and ap.load_bearing is None
    if change=='new_birth_same_price':current['highs']['1m']['registered_at']='2026-10-23T17:14:00+00:00'
    if change=='wrong_timeframe':current['highs']['1m']['timeframe']='5m'
    if change=='missing_registry':current={}
    return ap,current,frames[-1]['timestamp']


def test_retained_matching_life_is_not_a_new_event_or_progression():
    ap,current,cutoff=_retained_life_case()
    before=copy.deepcopy(ap.events);progress=copy.deepcopy(ap.latest_progression)
    ap.reconcile_current_structure(current,cutoff)
    assert ap.load_bearing['level']==29263.0
    assert ap.events==before and ap.latest_progression==progress
    assert ap.origin['event_time']=='2026-10-23T17:09:00+00:00'
    assert ap.load_bearing['registered_at']=='2026-10-23T16:48:00+00:00'


@pytest.mark.parametrize('change',['no_receipt','foreign','future','retired',
                                 'new_birth_same_price','wrong_timeframe','missing_registry',
                                 'future_source','future_edge','future_observed','missing_source'])
def test_unowned_or_noncurrent_life_never_repairs_missing_bearing(change):
    ap,current,cutoff=_retained_life_case(change)
    ap.reconcile_current_structure(current,cutoff)
    assert ap.load_bearing is None


@pytest.mark.parametrize('direction,side,sweep',[('bullish','low','below_low'),
                                               ('bearish','high','above_high')])
def test_same_binding_law_for_both_directions(direction,side,sweep):
    # Explicit fictional symmetry control. The captured-session witness above
    # remains unchanged; these rows are not claimed as historical market data.
    born='2026-10-23T17:00:00+00:00';origin='2026-10-23T17:01:00+00:00'
    confirmed='2026-10-23T17:02:00+00:00'
    basis='sell_side_raid_rejected' if side=='low' else 'buy_side_raid_rejected'
    registration={'event_type':'PROTECTED_SWING_REGISTERED','occurrence_id':'FICTIONAL-BIRTH',
                  'contract':'CONTROL','source_tf':'1m','side':side,'level':100.0,
                  'swing_id':'FICTIONAL-LIFE','registered_at':born,'basis':basis,
                  'source_bar_time':born,'event_time':born,'observed_at':born}
    events=[registration,{'event_type':'LIQUIDITY_SWEEP','occurrence_id':'FICTIONAL-RAID',
                         'contract':'CONTROL','source_tf':'1m','event_time':origin,
                         'source_bar_time':origin,'sweep_direction':sweep,'reclaimed':True},
            {'event_type':'STRUCTURE_BREAK','occurrence_id':'FICTIONAL-BREAK',
             'contract':'CONTROL','source_tf':'1m','event_time':confirmed,
             'source_bar_time':confirmed,'direction':direction}]
    ap=ActivePath();ap.enforce_lifecycle(confirmed,'CONTROL');ap.ingest(events)
    assert ap.owner==direction and ap.load_bearing is None
    registry={side+'s':{'1m':{'level':100.0,'timeframe':'1m','swing_id':'FICTIONAL-LIFE',
                             'registered_at':born,'basis':basis}}}
    ap.reconcile_current_structure(registry,confirmed)
    assert ap.load_bearing['side']==side and ap.load_bearing['level']==100.0


@pytest.mark.parametrize('bad',[True,float('nan'),float('inf'),10**500])
def test_malformed_current_price_fails_closed(bad):
    ap,current,cutoff=_retained_life_case()
    current['highs']['1m']['level']=bad
    ap.reconcile_current_structure(current,cutoff)
    assert ap.load_bearing is None

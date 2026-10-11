"""Stage 4 episode retirement: real producer replay, mocked model transport.

W4 minute data from Claude's checksum-verified causal audit. No catalog,
detector, formation or ActivePath injection in the composed replay cases.
"""
from datetime import datetime,timedelta,timezone
import copy
import pytest
import test_reversal_foundation_proof_closure as RF
import test_campaign_draw_temporal_authority as T
from broker.conditional_plan_authority import _current_po3_binding
from market_data.reversal_formation import current_block,ReversalFormationCustody
from market_data.campaign_scope import read_current_campaign_scope

W4 = [('m03:00', 29459.0, 29463, 29458, 29462),
 ('m03:01', 29462, 29466, 29461, 29465),
 ('m03:02', 29465, 29468, 29463, 29467),
 ('m03:03', 29467, 29470, 29464, 29469),
 ('m03:04', 29469, 29472, 29466, 29470),
 ('m03:05', 29470, 29471, 29462, 29464),
 ('m03:06', 29464, 29465, 29458, 29460),
 ('m03:07', 29460, 29462, 29457, 29459),
 ('m03:08', 29459, 29461, 29456, 29458),
 ('m03:09', 29458, 29459, 29454, 29455),
 ('m03:10', 29455, 29457, 29452, 29456),
 ('m03:11', 29456, 29460, 29455, 29459),
 ('m03:12', 29459, 29464, 29458, 29463),
 ('m03:13', 29463, 29468, 29462, 29467),
 ('m03:14', 29467, 29470, 29465, 29469),
 ('m03:15', 29469, 29473, 29467, 29472),
 ('m03:16', 29472, 29476, 29470, 29475),
 ('m03:17', 29475, 29478, 29472, 29476),
 ('m03:18', 29476, 29477, 29470, 29471),
 ('m03:19', 29471, 29472, 29466, 29467),
 ('m03:20', 29467, 29468, 29462, 29463),
 ('m03:21', 29463, 29464, 29450, 29455),
 ('m03:22', 29455, 29458, 29453, 29457),
 ('m03:23', 29457, 29461, 29456, 29460),
 ('m03:24', 29460, 29462, 29458, 29461),
 ('m03:25', 29461, 29463, 29459, 29462),
 ('m03:26', 29462, 29462, 29457, 29458),
 ('m03:27', 29458, 29459, 29452, 29453),
 ('m03:28', 29453, 29454, 29448, 29449),
 ('m03:29', 29449, 29450, 29446, 29447),
 ('m03:30', 29447, 29448, 29445, 29446),
 ('m03:31', 29446, 29447, 29444, 29445),
 ('m03:32', 29445, 29446, 29443, 29444),
 ('m03:33', 29444, 29445, 29442, 29443),
 ('m03:34', 29443, 29444, 29442, 29443),
 ('m03:35', 29443, 29443.5, 29441, 29442),
 ('m03:36', 29442, 29443.25, 29442, 29443),
 ('m03:37', 29443, 29443.5, 29443, 29443.25),
 ('m03:38', 29443.25, 29443.75, 29443.25, 29443.5),
 ('m03:39', 29443.5, 29444, 29439, 29443.75),
 ('m03:40', 29443.75, 29447, 29443.5, 29446),
 ('m03:41', 29446, 29452, 29445, 29451),
 ('m03:42', 29451, 29458, 29450, 29457),
 ('m03:43', 29457, 29463, 29456, 29462),
 ('m03:44', 29462, 29468, 29462, 29467),
 ('m03:45', 29467, 29470, 29464, 29469),
 ('m03:46', 29469, 29470, 29463.5, 29465),
 ('m03:47', 29465, 29466, 29461, 29464),
 ('m03:48', 29464, 29467, 29463, 29466),
 ('m03:49', 29466, 29469, 29464, 29468),
 ('m03:50', 29468, 29469, 29464.5, 29466),
 ('m03:51', 29466, 29467, 29459.5, 29465),
 ('m03:52', 29465, 29471, 29464, 29470),
 ('m03:53', 29470, 29476, 29469, 29475),
 ('m03:54', 29475, 29480, 29474, 29479),
 ('m03:55', 29479, 29482, 29477, 29481),
 ('m03:56', 29481, 29483, 29478, 29482),
 ('m03:57', 29482, 29484, 29479, 29482),
 ('m03:58', 29482, 29483, 29478, 29481)]
EXT = [dict(timestamp=f'2026-08-19T{r[0][1:]}:00+00:00',open=r[1],high=r[2],low=r[3],close=r[4],volume=10,contract=RF.CONTRACT) for r in W4]

@pytest.mark.parametrize('mode',['propose','watching'])
@T.ECU_MODES
def test_released_leg_object_cannot_serve_later_same_direction_generation(tmp_path,monkeypatch,ecu,mode):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    selected={}
    def choose(output,ordinal,payload):
        if output.get('current_action')!='propose_entry' or output.get('narrative_direction')!='bullish':
            return output
        po3=next((r for r in payload.get('authorized_tool_catalog',[]) if r['tool_family']=='po3_reversal_order_block' and r['direction']=='bullish'),None)
        if po3:selected['id']=po3['occurrence_id']
        inv=next((r for r in payload.get('authorized_invalidations',[]) if r.get('type')=='protected_low' and r.get('timeframe')=='5m'),None)
        if not inv:return output
        out={**output,'recommended_tool_family':['po3_reversal_order_block'],
             'recommended_tool_occurrence_id':selected.get('id'),
             'invalidation_id':inv['invalidation_id'],'invalidation_level':inv['price']}
        if mode=='watching':out.update(current_action='watching',plan_expires_at=(now+timedelta(minutes=30)).isoformat())
        return out
    cycle,calls=T._cycle_with_brain(tmp_path,monkeypatch,ecu=ecu,mutator=choose)
    original=T._scan(cycle,RF.TAPE_1M)
    initial=current_block(original['snapshot'],'bullish')
    assert initial and initial['validation_timestamp']=='2026-08-19T02:20:00+00:00'
    anchor=initial['formation_authority']['anchor_identity']
    old_id=initial['formation_authority']['occurrence_id']
    tape=RF.TAPE_1M+EXT
    released=False;later=None
    for end in range(len(RF.TAPE_1M)+1,len(tape)+1):
        minute=tape[end-1]['timestamp'][11:16]
        scan=T._scan(cycle,tape[:end],brain=minute>='03:50')
        if minute=='03:29':
            released=True
            snap=scan['snapshot'];path=snap['active_path_state']
            assert path['owner']=='none' and path['last_invalidated']['owner']=='bullish'
            assert path['last_invalidated']['source_bar_time']=='2026-08-19T03:27:00+00:00'
            live=snap['protected_swings']['by_timeframe']['lows']['5m']
            assert (live['swing_id'],live['registered_at'],live['level'])==(anchor['swing_id'],anchor['registered_at'],anchor['level'])
        if released:
            assert current_block(scan['snapshot'],'bullish') is None
            assert _current_po3_binding(scan['snapshot'],'bullish',old_id) is None
            # An older producer-published snapshot cannot regain live custody.
            assert current_block(original['snapshot'],'bullish') is None
        if minute>='03:50' and scan['campaign_lifecycle']['state']=='ACTIVE_DELIVERY':
            later=scan;break
    assert released and later
    assert later['snapshot']['timestamp'][11:16]=='03:52'
    path=later['snapshot']['active_path_state']
    assert path['owner']=='bullish' and path['origin']['source_bar_time']=='2026-08-19T03:39:00+00:00'
    scope=read_current_campaign_scope(later['snapshot'])
    assert (scope['status'],scope['state'])==('AVAILABLE','UNBOUND')
    producer=RF.CandidateProducer(account_fingerprint='acct:episode-retirement',contract=RF.MNQ)
    with pytest.raises(RF.NoCandidate) as error:
        if mode=='propose':RF._produce_candidate(later,now=now)
        else:T._plan_candidate(producer,later,now)
    assert error.value.reason=='tool_not_detected'
    assert len(calls)==4

@T.ECU_MODES
def test_cold_canonical_replay_does_not_restore_retired_episode(tmp_path,monkeypatch,ecu):
    # _cycle_with_brain prewarms state and therefore is not a cold replay.
    cycle=RF._cycle(tmp_path,monkeypatch)
    calls=[]
    RF._mock_current_brain(monkeypatch,calls)
    monkeypatch.setenv('BRAIN_ECU_MODE','true' if ecu else 'false')
    rebuilt=cycle._rebuild_derived_state(RF.TAPE_1M+EXT,cycle._history.revision)
    assert rebuilt['ok'] is True
    scan=T._scan(cycle,RF.TAPE_1M+EXT,brain=False)
    assert scan['snapshot']['derived_state']['current'] is True
    assert current_block(scan['snapshot'],'bullish') is None
    assert not [r for r in RF.authorized_tool_catalog(scan['snapshot']) if r['tool_family']=='po3_reversal_order_block' and r['direction']=='bullish']
    assert len(calls)==0

@T.ECU_MODES
def test_history_rebuild_revokes_previously_published_formation(tmp_path,monkeypatch,ecu):
    cycle,calls=T._cycle_with_brain(tmp_path,monkeypatch,ecu=ecu)
    original=T._scan(cycle,RF.TAPE_1M)
    assert current_block(original['snapshot'],'bullish')
    revision=original['snapshot']['derived_state']['history_revision']
    revised=copy.deepcopy(RF.TAPE_1M)
    revised[-1]['high']+=.25
    scan=T._scan(cycle,revised,brain=False)
    assert scan['snapshot']['derived_state']['history_revision']==revision+1
    assert current_block(original['snapshot'],'bullish') is None
    assert scan['snapshot']['derived_state']['current'] is True
    assert len(calls)==1

def _release(owner,source,*,at=None):
    # Predicate unit inputs only; not minted production authority.
    return dict(owner=owner,source_bar_time=source,at=at or source,
                source_tf='3m',swing_id='unit-life',registered_at='2026-08-19T01:39:00+00:00',occurrence_id='unit-release')

@pytest.mark.parametrize('direction,history,expected',[
    ('bullish',[_release('bullish','2026-08-19T02:19:00+00:00')],True),
    ('bullish',[_release('bullish','2026-08-19T02:20:00+00:00')],False),
    ('bullish',[_release('bullish','2026-08-19T03:27:00+00:00')],False),
    ('bullish',[_release('bearish','2026-08-19T03:27:00+00:00')],True),
    ('bearish',[_release('bullish','2026-08-19T03:27:00+00:00')],True),
    ('bearish',[_release('bearish','2026-08-19T03:27:00+00:00')],False),
    ('bullish',[_release('bullish','2026-08-19T03:27:00+00:00'),_release('bearish','2026-08-19T03:40:00+00:00')],False),
    ('bullish',[_release('bullish','2026-08-19T03:55:00+00:00')],True),
    ('bullish',None,False),
    ('bullish',[dict(owner='bullish')],False),
])
def test_release_chronology_and_direction_are_distinct_from_anchor_geometry(direction,history,expected):
    record=dict(direction=direction,validation_timestamp='2026-08-19T02:20:00+00:00')
    assert ReversalFormationCustody._current_generation(record,history,'2026-08-19T03:52:00+00:00') is expected

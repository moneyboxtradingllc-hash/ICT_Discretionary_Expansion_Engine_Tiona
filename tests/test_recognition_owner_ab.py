"""Bounded owner audit: CONSTRUCTED evidence only, never owner/model truth."""
import copy
import json
import sys
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import test_recognition_owner_audit as OA
import test_recognition_layer_projection as LP
from recognition_validation import child as CH, contracts as C, __main__ as CLI
from recognition_validation import layers as LY, scoring as SC, report as RP


def child_evidence(root):
    """Small schema-valid fixture; real returned producer traces are also audited separately."""
    rec, annotation, manifest=OA.world(root)
    receipt={'kind':'FRESH_CHILD','pid':202,'ppid':101,'request_sha256':'a'*64}
    manifest['process_isolation']=receipt
    manifest['seal']={'sha256':C.seal_digest(manifest),'sealed_at':'2030-01-02T15:00:00Z','sealer_ref':'CONSTRUCTED'}
    (root/RP.MANIFEST).write_text(json.dumps(manifest))
    exit_record=dict(schema='trajectory_child_exit/v1',request_sha256='a'*64,status='RUN_COMPLETE',exit_code=0)
    status=dict(schema='trajectory_child_status/v1',state='EXITED',exit_code=0,complete=True,
                request_sha256='a'*64,parent_pid=101,child_exit=copy.deepcopy(exit_record),
                manifest_sha256=C.sha256_hex((root/RP.MANIFEST).read_bytes()))
    (root/CH.EXIT_FILE).write_text(json.dumps(exit_record))
    (root/CH.STATUS_FILE).write_text(json.dumps(status))
    return manifest,status,exit_record


def report(root,out):
    code=CLI.main(['report','--run',str(root),'--out',str(out)])
    path=out/'result.json'
    return code,json.loads(path.read_text()) if path.exists() else None


def test_untouched_child_evidence_reaches_actual_cli_complete(tmp_path):
    root=tmp_path/'e';root.mkdir()
    manifest,_,_=child_evidence(root)
    assert CH.verify_child_status(root,manifest)==[]
    code,result=report(root,tmp_path/'report')
    assert code==CLI.EXIT_MISSING  # annotations missing, not a failed engineering run
    assert (result['engineering_status'],result['final_status'])==('COMPLETE','READY_FOR_OWNER_REVIEW')
    assert result['current_brain_recognition']=='UNPROVEN'


@pytest.mark.parametrize('attack',['missing_exit','replaced_exit','exit_request','exit_completion',
                                  'exit_schema','malformed_exit','exit_list','manifest_resealed',
                                  'status_request','same_pid','ppid','exit_snapshot'])
def test_child_tampering_cannot_retain_cli_complete(tmp_path,attack):
    root=tmp_path/'e';root.mkdir()
    manifest,status,exit_record=child_evidence(root)
    if attack=='missing_exit':(root/CH.EXIT_FILE).unlink()
    elif attack=='replaced_exit':(root/CH.EXIT_FILE).write_text('{}')
    elif attack=='malformed_exit':(root/CH.EXIT_FILE).write_text('{broken')
    elif attack=='exit_list':(root/CH.EXIT_FILE).write_text('[]')
    elif attack.startswith('exit_') and attack!='exit_snapshot':
        field,value={'exit_request':('request_sha256','b'*64),'exit_completion':('status','RUN_INCOMPLETE'),
                     'exit_schema':('schema','WRONG')}[attack]
        exit_record[field]=value;(root/CH.EXIT_FILE).write_text(json.dumps(exit_record))
    elif attack=='manifest_resealed':
        manifest['CONSTRUCTED_tamper']=True;manifest['seal']['sha256']=C.seal_digest(manifest)
        (root/RP.MANIFEST).write_text(json.dumps(manifest))
    elif attack in ('status_request','same_pid','exit_snapshot'):
        if attack=='status_request':status['request_sha256']='b'*64
        elif attack=='same_pid':status['parent_pid']=202
        else:status['child_exit']={}
        (root/CH.STATUS_FILE).write_text(json.dumps(status))
    elif attack=='ppid':
        manifest['process_isolation']['ppid']=999
        manifest['seal']['sha256']=C.seal_digest(manifest)
        (root/RP.MANIFEST).write_text(json.dumps(manifest))
        status['manifest_sha256']=C.sha256_hex((root/RP.MANIFEST).read_bytes())
        (root/CH.STATUS_FILE).write_text(json.dumps(status))
    code,result=report(root,tmp_path/'report')
    assert code==CLI.EXIT_INFRA
    assert result is None or (result['engineering_status']=='INCOMPLETE' and result['final_status']=='ENGINEERING_INCOMPLETE')


def test_existing_manifest_self_seal_defense_remains_active(tmp_path):
    root=tmp_path/'e';root.mkdir();manifest,_,_=child_evidence(root)
    manifest['CONSTRUCTED_tamper']=True
    (root/RP.MANIFEST).write_text(json.dumps(manifest))
    code,result=report(root,tmp_path/'report')
    assert code==CLI.EXIT_INFRA and result is None


def test_changed_manifest_argument_cannot_bypass_on_disk_binding(tmp_path):
    root=tmp_path/'e';root.mkdir();manifest,_,_=child_evidence(root)
    assert CH.verify_child_status(root,{**manifest,'CONSTRUCTED_tamper':True})


def test_exit_receipt_json_formatting_preserves_healthy_content(tmp_path):
    root=tmp_path/'e';root.mkdir();manifest,_,exit_record=child_evidence(root)
    (root/CH.EXIT_FILE).write_text(json.dumps(exit_record,indent=4))
    assert CH.verify_child_status(root,manifest)==[]


@pytest.mark.parametrize('completion',['RUN_COMPLETE','RUN_INCOMPLETE'])
def test_parent_completion_consumes_actual_child_exit_status(tmp_path,monkeypatch,completion):
    """Controlled transport only; exercise the real parent writer and completion predicate."""
    out=tmp_path/'run'
    def completed(command,**kwargs):
        request_path=Path(command[-1])
        evidence=out/'evidence';evidence.mkdir()
        (evidence/RP.MANIFEST).write_text('{}')
        (evidence/CH.EXIT_FILE).write_text(json.dumps(dict(schema='trajectory_child_exit/v1',
            request_sha256=C.sha256_hex(request_path.read_bytes()),status=completion,exit_code=0)))
        return subprocess.CompletedProcess(command,0,stdout=b'{}\n',stderr=b'')
    monkeypatch.setattr(CH.subprocess,'run',completed)
    status=CH.run_in_child({'schema':CH.REQUEST_SCHEMA,'ecu':False},out_root=out)
    assert status['complete'] is (completion=='RUN_COMPLETE')


def test_report_defense_is_activated_not_a_permanently_refusing_fixture(tmp_path,monkeypatch):
    root=tmp_path/'e';root.mkdir();child_evidence(root)
    (root/CH.EXIT_FILE).unlink()
    assert report(root,tmp_path/'blocked')[0]==CLI.EXIT_INFRA
    monkeypatch.setattr(CH,'verify_child_status',lambda *a:[])
    _,mutant=report(root,tmp_path/'mutant')
    assert mutant['engineering_status']=='COMPLETE'  # bypass mutant demonstrates the decisive consumer boundary


def projection(*,brain='bearish',tool='correct',at='16:01',primary=1):
    stamp='2030-01-02T'+at+':00Z'
    return dict(schema=LY.SCHEMA,tick=dict(ordinal=0,kind='SCAN',decision_time=stamp),history_revision=0,
        process_lineage_id='CONSTRUCTED',layers={
        'MARKET_FACTS':{'state':'ABSENT','reason':'CONSTRUCTED','source':'CONSTRUCTED'},
        'CAMPAIGN':dict(state='PROJECTED',direction='bearish',brain_direction=brain,history_start=None,
                        history_complete=True,authority_status='CURRENT',objective={'identity':None,'price':None},origin=None),
        'DELIVERY':{'state':'ABSENT','reason':'CONSTRUCTED','source':'CONSTRUCTED'},
        'TOOL':dict(state='PROJECTED',playbook='family',tool_family=['tool'],occurrence_id=tool,direction='bearish')
               if tool else {'state':'ABSENT','reason':'CONSTRUCTED','source':'CONSTRUCTED'},
        'COMPOSITION':dict(state='PROJECTED',outcome='NO_CANDIDATE',brain_primary_calls=primary),
        'TIMING':dict(state='PROJECTED',settled_cutoff=None,decision_time=stamp,plan_capture_at=None,trigger_at=None,final_quote_at=None)})


@pytest.mark.parametrize('case',['correct_draw_no_recognition','correct_brain_draw','wrong_opportunity',
                                  'missing_opportunity','missing_brain','early_recognition','healthy'])
def test_direction_timing_is_explicitly_diagnostic_and_separate_from_recognition(case):
    p=projection();label=LP._label(start='16:00',end='16:05',campaign_origin=[],campaign_objective=[])
    # LP fixture uses a different date; make this entire synthetic example unambiguous.
    for field in ('window','recognition_target'):
        label[field]={k:v.replace('2026-08-19','2030-01-02') for k,v in label[field].items()}
    label.update(earliest_available_utc='2030-01-02T16:00:00Z',occurrence_id='correct',
                 playbook_family='family',tool_family='tool',expected_action='ENTRY',opportunity='eligible')
    directions=[(C.instant(p['tick']['decision_time']),'bearish','MOCK')]
    if case=='correct_draw_no_recognition':p['layers']['CAMPAIGN']['brain_direction']='bullish';directions=[(directions[0][0],'bullish','MOCK')]
    if case=='wrong_opportunity':p['layers']['TOOL']['occurrence_id']='wrong'
    if case=='missing_opportunity':p['layers']['TOOL']={'state':'ABSENT','reason':'CONSTRUCTED','source':'CONSTRUCTED'}
    if case=='missing_brain':p['layers']['CAMPAIGN']['brain_direction']=None;directions=[]
    if case=='early_recognition':label['earliest_available_utc']='2030-01-02T16:02:00Z'
    findings=dict(duplicate_cognition_cutoffs=[],missed_scans=[],revisions=[],restarts=[])
    cells={c['layer']:c for c in LY.score_label(label,[p],findings)}
    timing=cells['TIMING']
    assert 'CAMPAIGN_DIRECTION_ONLY' in timing['source_binding']
    assert 'not Brain or opportunity recognition' in timing['source_binding']
    event=dict(observed_at=p['tick']['decision_time'],settled_cutoff=p['tick']['decision_time'],event_kind='SCAN:NO_CANDIDATE',
               outcome='NO_CANDIDATE',tool_occurrence_id=None,first_refusal_code=None,candidate_id=None)
    episode=SC.classify_episode(label,[event],directions)
    rec=next(c for c in episode['cells'] if c['layer']=='RECOGNITION')
    if case=='early_recognition':assert timing['observed']=='EARLY_BEFORE_AVAILABILITY' and timing['agreement'] is False
    else:assert timing['observed']=='ON_TIME' and timing['agreement'] is True
    if case=='missing_brain':assert rec['assessment']=='UNPROVEN' and not episode['first_recognition_utc']
    elif case=='correct_draw_no_recognition':assert rec['observed']=='OBSERVED_bullish'
    elif case!='early_recognition':assert rec['observed']=='HIT'
    if case=='wrong_opportunity':assert cells['TOOL']['agreement'] is False
    if case=='missing_opportunity':assert cells['TOOL']['state']=='UNPROVEN'


def test_actual_cli_json_and_markdown_disclose_timing_scope(tmp_path):
    root=tmp_path/'e';root.mkdir();child_evidence(root)
    _,result=report(root,tmp_path/'report')
    assert any('CAMPAIGN_DIRECTION_ONLY' in s for s in result['session_summaries'][0]['limitations'])
    assert 'not Brain or opportunity recognition' in (tmp_path/'report/report.md').read_text()

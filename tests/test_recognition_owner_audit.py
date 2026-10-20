"""Owner-side adversarial audit. All examples here are FICTIONAL engineering data."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
from recognition_validation import contracts as C, recorder as REC, scoring as SC, report as RP
import verify_engineering_ledger as L


def example(name):
    return json.loads((ROOT / "src/recognition_validation/examples" / name).read_text())


def world(root):
    event = example("fictional_event.json")
    rec = REC.Recorder(root, run_digest=event["run_digest"], trajectory_id=event["trajectory_id"],
                       classification="FICTIONAL")
    for key in ("schema_version", "document_id", "provenance", "run_digest", "trajectory_id", "sequence",
                "previous_event_digest", "event_payload_digest"):
        event.pop(key)
    event.update(event_kind="SCAN:NO_CANDIDATE", outcome="NO_CANDIDATE", primary_call_count=1,
                 first_refusal_code=None, missing_evidence=[])
    rec.event(**event)
    call = example("fictional_brain_call.json")
    call.update(record_status="COMPLETE", input_ref=rec.json_artifact({}, kind="input", origin="CONSTRUCTED"),
                prompt_ref=rec.artifact(b"FICTIONAL prompt", kind="prompt", origin="CONSTRUCTED"),
                post_guard_output_ref=rec.json_artifact({"narrative_direction":"bearish"}, kind="parsed", origin="CONSTRUCTED"))
    rec.brain_call(call)
    annotation = example("fictional_annotation.json")
    annotation.update(session_id="FICTIONAL-SESSION")
    label=annotation["labels"][0]
    label.update(window={"start_utc":"2030-01-02T14:00:00Z","end_utc":"2030-01-02T14:05:00Z"},
                 recognition_target={"start_utc":"2030-01-02T14:00:00Z","end_utc":"2030-01-02T14:05:00Z"},
                 earliest_available_utc="2030-01-02T14:00:00Z", dominant_campaign_direction="bearish",
                 expected_action="STAND_DOWN", opportunity="forbidden", confidence="CLEAR", ambiguous=False,
                 occurrence_id=None, source_evidence=[])
    manifest=dict(schema="run_manifest/v1",trajectory_id=rec.trajectory_id,session_id="FICTIONAL-SESSION",
                  corpus_digest=rec.run_digest,evaluation_origin="MOCK",tick_count=1,ticks=1,events=1,
                  primary_calls=1,repair_calls=0,infrastructure_error=None,network_attempts=[],venue_writes=[])
    (root/RP.MANIFEST).write_text(json.dumps(manifest))
    return rec, annotation, manifest


def score(root, annotation, **over):
    args=dict(mode="B",session_id="FICTIONAL-SESSION",trajectory_id="FICTIONAL-B-1",annotation=annotation)
    args.update(over)
    return SC.score_trace(root,**args)


def test_crlf_committed_ledger_keeps_the_same_receipt():
    entry={"schema":"TEST_ONLY","mission_id":"TEST_ONLY"}
    entry["receipt_digest"]=L.receipt_digest(entry)
    text="```json ledger-entry\n"+json.dumps(entry)+"\n```\n"
    assert L.parse_entries(text.replace("\n","\r\n")) == L.parse_entries(text)


def test_missing_call_file_cannot_be_reported_complete(tmp_path):
    _, annotation, _=world(tmp_path)
    (tmp_path/REC.CALLS).unlink()
    with pytest.raises(C.ContractError,match="BRAIN_CALL_COUNT_MISMATCH"):
        score(tmp_path,annotation)


def test_missing_prompt_bytes_refuse_scoring(tmp_path):
    rec, annotation, _=world(tmp_path)
    (tmp_path/rec.calls[0]["prompt_ref"]["path"]).unlink()
    with pytest.raises(C.ContractError,match="ARTIFACT_MISSING"):
        score(tmp_path,annotation)


def test_mock_calls_cannot_enter_mode_c_recognition(tmp_path):
    _, annotation, _=world(tmp_path)
    with pytest.raises(C.ContractError,match="MODE_EVIDENCE_MISMATCH"):
        score(tmp_path,annotation,mode="C")


def test_foreign_annotation_session_refuses(tmp_path):
    _, annotation, _=world(tmp_path)
    annotation["session_id"]="OTHER-SESSION"
    with pytest.raises(C.ContractError,match="ANNOTATION_SESSION_MISMATCH"):
        score(tmp_path,annotation)


def test_unoffered_or_unrecorded_ticks_are_incomplete(tmp_path):
    _, annotation, manifest=world(tmp_path)
    scored=score(tmp_path,annotation)
    manifest["tick_count"]=2
    result=RP.build_result(document_id="FICTIONAL-REPORT",run_digest="0"*64,mode="B",scored=[scored],
                           manifest=manifest,artifact_refs=[],missing_prerequisites=[])
    assert result["engineering_status"] == "INCOMPLETE"


def test_unknown_ratified_metric_is_never_silently_ignored(tmp_path):
    _, annotation, _=world(tmp_path)
    scoring={"state":"OWNER_RATIFIED","thresholds":[{"metric":"not_implemented", "operator":">=",
               "value":0,"decision_ref":"FICTIONAL test only"}]}
    with pytest.raises(C.ContractError,match="UNKNOWN_SCORING_METRIC"):
        score(tmp_path,annotation,scoring=scoring)


def test_missing_cognition_is_not_a_demonstrated_entry_miss(tmp_path):
    rec, annotation, _=world(tmp_path)
    label=annotation["labels"][0]
    label.update(expected_action="ENTRY",opportunity="eligible")
    episode=SC.classify_episode(label,rec.events,[])
    cell=next(c for c in episode["cells"] if c["layer"]=="REFUSAL")
    assert cell["assessment"] == "UNPROVEN"


def test_healthy_control_has_a_complete_trace_and_correct_refusal(tmp_path):
    _, annotation, manifest=world(tmp_path)
    scored=score(tmp_path,annotation)
    assert any(c["observed"]=="CORRECT_REFUSAL" for c in scored["summary"]["confusion_cells"])
    result=RP.build_result(document_id="FICTIONAL-REPORT",run_digest="0"*64,mode="B",scored=[scored],
                           manifest=manifest,artifact_refs=[],missing_prerequisites=[])
    assert result["engineering_status"]=="COMPLETE"
    assert result["current_brain_recognition"]=="UNPROVEN"


def cli_world(tmp_path, monkeypatch):
    from recognition_validation import corpus as K, driver as DR, __main__ as CLI
    import test_po3_distinct_anchor_premise as W
    tape=W._tape(W._HEALTHY)
    corpus_path=K.build_constructed_corpus(tmp_path/"corpus",session_id="TEST-SESSION",contract_id="CON.F.US.MNQ.Z26",
                    market_date="2026-08-19",tape=tape,warmup_end="2026-08-19T15:30:00Z",
                    notes="CONSTRUCTED owner audit only",sealed_at="2026-10-17T00:00:00Z")
    corpus=K.load_corpus(corpus_path)
    repository=L.Repo(ROOT)
    source=example("current_brain_disabled.json")
    diff=repository.git("diff","--binary","HEAD").encode()
    source.update(mode="B",dry_run=False,trajectory_count=1,corpus_digest=corpus.digest,
                  source_sha=repository.git("rev-parse","HEAD").strip(),
                  source_tree=repository.git("rev-parse","HEAD^{tree}").strip(),
                  dirty_tree_digest=C.sha256_hex(diff) if diff else None,
                  closure_digest=L.sha256(L.canonical(L.closure_at(repository,"HEAD"))))
    schedule=example("fictional_schedule.json")
    schedule.update(corpus_digest=corpus.digest,ticks=[dict(session_id="TEST-SESSION",ordinal=0,
                  decision_time_utc="2026-08-19T15:31:00Z",kind="SCAN",source_ref=None)],seal=None)
    schedule["seal"]={"sha256":C.seal_digest(schedule),"sealed_at":"2026-10-17T00:00:00Z","sealer_ref":"TEST_ONLY"}
    raw=C.canonical(schedule)
    (tmp_path/"schedule.json").write_bytes(raw)
    source["schedule_ref"]=dict(path="schedule.json",sha256=C.sha256_hex(raw),bytes=len(raw),origin="CONSTRUCTED")
    script=tmp_path/"script.py"
    script.write_text("def script(request): return None\n")
    captured=[]
    # The CLI hands each trajectory to a fresh child (gap mission 2); capture the sealed request it would send.
    from recognition_validation import child as CH
    def stub(request,**kwargs):
        captured.append(request)
        return dict(state="EXITED",exit_code=0,complete=True,summary=dict(status="RUN_COMPLETE",ticks=1,events=1,
                    primary_calls=0,repair_calls=0,infrastructure_error=None,evidence_root="TEST_ONLY"))
    monkeypatch.setattr(CH,"run_in_child",stub)
    def invoke(**over):
        doc={**source,**over}
        config=tmp_path/"run.json"
        config.write_text(json.dumps(doc))
        return CLI.main(["run","--mode","B","--run",str(config),"--corpus",str(corpus_path),
                         "--script",str(script),"--out",str(tmp_path/"out")])
    return invoke,captured


def test_declared_source_must_match_actual_loaded_source(tmp_path,monkeypatch):
    invoke,captured=cli_world(tmp_path,monkeypatch)
    assert invoke(source_sha="1"*40)==2
    assert captured==[]


def test_schedule_artifact_must_be_verified_before_running(tmp_path,monkeypatch):
    invoke,captured=cli_world(tmp_path,monkeypatch)
    (tmp_path/"schedule.json").unlink()
    assert invoke()==5
    assert captured==[]


def test_declared_missing_quotes_never_become_constructed_quotes(tmp_path,monkeypatch):
    invoke,captured=cli_world(tmp_path,monkeypatch)
    assert invoke(quote_policy="MISSING")==0
    assert captured[0].get("quote_policy")=="MISSING"
    assert len(captured[0].get("ticks",[]))==1


def test_unimplemented_memory_seed_is_refused_not_ignored(tmp_path,monkeypatch):
    invoke,captured=cli_world(tmp_path,monkeypatch)
    assert invoke(memory_policy="SEALED_APPROVED_SEED")==2
    assert captured==[]


def test_fake_current_transport_never_claims_current_cognition():
    from recognition_validation import brain_gateway as G
    assert G.CurrentModelResponder.origin == "MOCK"


def test_scoring_uses_decision_time_not_the_source_bar_open(tmp_path):
    rec, annotation, _ = world(tmp_path)
    label = annotation["labels"][0]
    label.update(expected_action="ENTRY",opportunity="eligible",earliest_available_utc="2030-01-02T14:01:00Z")
    event = dict(rec.events[0], outcome="QUALIFIED_CANDIDATE_OBSERVED")
    episode = SC.classify_episode(label,[event],[])
    assert not episode["violations"]
    assert episode["first_candidate_utc"] == "2030-01-02T14:01:00+00:00"


def test_canonical_window_keeps_the_strict_close_and_dated_override():
    from recognition_validation import ports as P
    assert P.production_window_open(C.instant("2026-08-19T13:30:00Z"))
    assert not P.production_window_open(C.instant("2026-08-19T18:00:00Z"))
    assert P.production_window_open(C.instant("2026-08-12T19:54:59Z"))
    assert not P.production_window_open(C.instant("2026-08-12T19:55:00Z"))


def test_forming_or_unproven_release_is_never_a_settled_candle():
    from recognition_validation import corpus as K, ports as P
    release = example("fictional_release.json")
    original = copy.deepcopy(release)
    release.update(settlement_proven=False,settled_at_utc=None,available_at_utc="2030-01-02T14:00:30Z")
    unknown = K.ReleaseStream.from_documents([release],session_id=release["session_id"],contract_id=release["contract_id"])
    clock = P.DecisionClock(C.instant("2030-01-02T14:00:30Z"))
    port = P.LocalCandlePort(unknown,clock,symbol="TEST_ONLY")
    assert port.fetch_1m_candles("TEST_ONLY") == []
    clock.set(C.instant("2030-01-02T14:05:00Z"))
    assert port.fetch_1m_candles("TEST_ONLY") == []  # elapsed time cannot invent a settlement witness
    proven = K.ReleaseStream.from_documents([original],session_id=original["session_id"],contract_id=original["contract_id"])
    assert P.LocalCandlePort(proven,clock,symbol="TEST_ONLY").fetch_1m_candles("TEST_ONLY") == [proven.releases[0].candle()]


def test_explicit_unknown_judgment_stays_unproven_not_a_directional_miss(tmp_path):
    rec, annotation, _ = world(tmp_path)
    label=annotation["labels"][0]
    label.update(expected_action="ENTRY",opportunity="eligible")
    directions=[(C.instant("2030-01-02T14:01:00Z"),"UNKNOWN","MOCK")]
    result=SC.classify_episode(label,rec.events,directions)
    assert all(c["assessment"]=="UNPROVEN" for c in result["cells"] if c["layer"] in ("RECOGNITION","REFUSAL"))

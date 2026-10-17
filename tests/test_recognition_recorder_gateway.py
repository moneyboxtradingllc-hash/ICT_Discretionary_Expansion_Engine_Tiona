"""Stage 5 M03: recorder durability and the provider-seam gateway contract."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import ports as P  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402

RUN = "a" * 64
T0 = datetime(2026, 8, 19, 16, 39, tzinfo=timezone.utc)


def _event_fields(**over):
    fields = dict(scan_key="T/2026-08-19T16:38:00+00:00/0", settled_cutoff="2026-08-19T16:38:00+00:00",
                  observed_at="2026-08-19T16:39:00+00:00", event_kind="SCAN:NO_CANDIDATE", source_event_refs=[],
                  history_revision=0, derived_revision=0, process_lineage_id="process:test", scope_id=None,
                  scope_proof_id=None, draw_record_id=None, formation_id=None, tool_occurrence_id=None,
                  candidate_id=None, plan_id=None, boundary="CANDIDATE", outcome="NO_CANDIDATE",
                  first_refusal_code="tool_not_detected", primary_call_count=1, repair_call_count=0,
                  evidence_refs=[], missing_evidence=[])
    fields.update(over)
    return fields


def test_events_chain_durably_and_reread_strictly(tmp_path):
    rec = REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED")
    first = rec.event(**_event_fields())
    second = rec.event(**_event_fields(outcome="QUALIFIED_CANDIDATE_OBSERVED", first_refusal_code=None,
                                       event_kind="SCAN:QUALIFIED_CANDIDATE_OBSERVED", boundary="MISSION"))
    events = REC.read_events(tmp_path / "r")
    assert events == [first, second]
    assert second["previous_event_digest"] == C.event_digest(first)
    lines = (tmp_path / "r" / REC.EVENTS).read_text().splitlines()
    lines[0] = lines[0].replace("tool_not_detected", "laundered")
    (tmp_path / "r" / REC.EVENTS).write_text("\n".join(lines) + "\n")
    with pytest.raises(C.ContractError) as exc:
        REC.read_events(tmp_path / "r")
    assert exc.value.code == "EVENT_DIGEST_MISMATCH"


def test_output_root_reuse_refuses(tmp_path):
    REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED").event(**_event_fields())
    with pytest.raises(C.ContractError) as exc:
        REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED")
    assert exc.value.code == "OUTPUT_ROOT_REUSE"


def test_recording_failure_is_infrastructure_error_not_a_pass(tmp_path, monkeypatch):
    rec = REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED")

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(REC.os, "fsync", full_disk)
    with pytest.raises(REC.RecorderError):
        rec.event(**_event_fields())
    assert rec.failed and "No space left" in rec.failed
    assert rec.sequence == 0 and rec.events == []


def test_invalid_event_is_refused_before_it_is_written(tmp_path):
    rec = REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED")
    with pytest.raises(C.ContractError):
        rec.event(**_event_fields(boundary="NOT_A_BOUNDARY"))
    assert not (tmp_path / "r" / REC.EVENTS).exists()


def test_content_addressed_artifacts_never_silently_collide(tmp_path):
    rec = REC.Recorder(tmp_path / "r", run_digest=RUN, trajectory_id="T", classification="CONSTRUCTED")
    ref = rec.artifact(b"payload", kind="input", origin="CONSTRUCTED")
    assert ref == rec.artifact(b"payload", kind="input", origin="CONSTRUCTED")
    (tmp_path / "r" / ref["path"]).write_bytes(b"tampered")
    with pytest.raises(REC.RecorderError):
        rec.artifact(b"payload", kind="input", origin="CONSTRUCTED")


def _request(**over):
    request = {"scan_key": "T/c/1", "requested_model": "gpt-6-luna", "request_digest": "d" * 64,
               "settled_cutoff": "2026-08-19T16:38:00+00:00", "cutoff_ordinal": 0, "purpose": "PRIMARY",
               "input_digest": "e" * 64}
    request.update(over)
    return request


def test_scripted_responder_declines_explicitly_and_echoes_the_requested_model():
    responder = G.ScriptedResponder(lambda r: None, fixture_digest="f" * 64)
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond(_request())
    assert exc.value.code == "MOCK_SCRIPT_DECLINED"
    reply = G.ScriptedResponder(lambda r: {"current_action": "stand_down"}, fixture_digest="f" * 64).respond(_request())
    assert reply.served_model == "gpt-6-luna" and json.loads(reply.content) == {"current_action": "stand_down"}


def test_disabled_current_model_refuses_every_request():
    with pytest.raises(G.ProviderRefusal) as exc:
        G.DisabledCurrentModel().respond(_request())
    assert exc.value.code == "CURRENT_MODEL_CALLS_DISABLED"


def test_gateway_seam_restores_production_and_refuses_foreign_credentials(monkeypatch):
    from ai_brain import narrative_brain
    from ai_layer import ai_api_adapter
    before = (ai_api_adapter._openai, ai_api_adapter._OPENAI_AVAILABLE, narrative_brain._call_llm,
              os.environ.get("OPENAI_API_KEY"), narrative_brain.time, narrative_brain.datetime)
    clock = P.DecisionClock(T0)
    gateway = G.BrainGateway(G.DisabledCurrentModel(), trajectory_id="T", clock=clock)
    with gateway.installed():
        assert isinstance(ai_api_adapter._openai, G._FakeProviderModule)
        assert narrative_brain.time.time() == T0.timestamp()
        assert narrative_brain.datetime.now(timezone.utc) == T0
        with pytest.raises(C.ContractError) as exc:
            ai_api_adapter._openai.OpenAI(api_key="sk-real-looking").chat.completions.create(messages=[])
        assert exc.value.code == "UNEXPECTED_PROVIDER_CREDENTIAL"
    assert (ai_api_adapter._openai, ai_api_adapter._OPENAI_AVAILABLE, narrative_brain._call_llm,
            os.environ.get("OPENAI_API_KEY"), narrative_brain.time, narrative_brain.datetime) == before

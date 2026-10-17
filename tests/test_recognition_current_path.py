"""Stage 5 M03: the offline driver reaches the ACTUAL production graph.

The CONSTRUCTED distinct-anchor tape is ingested as a sealed corpus and
offered minute by minute to the real ProductionLoop (disarmed) through the
local candle port and decision clock. Cognition crosses the provider-client
seam inside production's own `_call_llm`, answered by a Mode B script that
may only name rows the current transported payload publishes. Assertions read
the recorded event chain and the gateway's transported requests -- never a
mirrored consumer.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_reversal_foundation_proof_closure as RF  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import ports as P  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402

CONTRACT = "CON.F.US.MNQ.Z26"
SESSION = "DAW-CONSTRUCTED-20260819"


def _script():
    """MOCK: the distinct-anchor test's adversarial Brain, keyed by the
    transported payload of each request (current catalogs only)."""
    state = {}

    def script(request):
        payload = request["payload"]
        market = payload.get("market") or {}
        entry = (market.get("execution_price") or {}).get("best_bid") or market.get("current_price")
        output = RF._valid_model_reply(payload, action="propose_entry", direction="bearish")
        return W._reply(output, request["scan"], payload, entry, state)
    return script, state


def _trajectory(root, monkeypatch, *, ecu, install_on_wrong_target=False, ticks_until=None):
    corpus_root = root / "corpus"
    path = K.build_constructed_corpus(corpus_root, session_id=SESSION, contract_id=CONTRACT, market_date="2026-08-19",
                                      tape=W._tape(W._HEALTHY), warmup_end="2026-08-19T15:30:00+00:00",
                                      notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                      sealed_at="2026-10-17T00:00:00Z")
    corpus = K.load_corpus(path)
    stream = corpus.sessions[SESSION].stream
    ticks = DR.minute_schedule(stream, prewarm_until=DR.utc("2026-08-19T15:30:00Z"))
    if ticks_until:
        ticks = [t for t in ticks if t.decision_time <= DR.utc(ticks_until)]
    run_root = root / "run"
    with DR.isolation(run_root, ecu=ecu):
        clock = P.DecisionClock(ticks[0].decision_time)
        organism = DR.build_organism(stream=stream, clock=clock, store_dir=run_root / "store", session_id="S5-B",
                                     contract_id=CONTRACT, session_date="20260819",
                                     issued_at="2026-08-19T13:00:00+00:00")
        recorder = REC.Recorder(run_root / "evidence", run_digest=corpus.digest, trajectory_id="S5-B-1",
                                classification="CONSTRUCTED")
        script, state = _script()
        gateway = G.BrainGateway(G.ScriptedResponder(script, fixture_digest=C.digest("daw-script-v1")),
                                 trajectory_id="S5-B-1", clock=clock, recorder=recorder,
                                 fingerprints={"brain": "brain:3d9878ad3ff57f1f", "retrieval": "retr:0c241bdb8234d1ba"})
        if install_on_wrong_target:
            # WRONG PATCH TARGET control: the fake provider is attached to a
            # module production never reads; the gateway's own seam is a no-op.
            import types
            decoy = types.SimpleNamespace(_openai=None, _OPENAI_AVAILABLE=False)
            original = gateway.installed

            def wrong_installed():
                import contextlib

                @contextlib.contextmanager
                def cm():
                    decoy._openai = G._FakeProviderModule(gateway)
                    decoy._OPENAI_AVAILABLE = True
                    yield gateway
                return cm()
            gateway.installed = wrong_installed
            assert original is not None
        summary = DR.run_trajectory(organism=organism, stream=stream, ticks=ticks, gateway=gateway, recorder=recorder)
    events = REC.read_events(run_root / "evidence")
    calls = REC.read_calls(run_root / "evidence")
    return summary, events, calls, gateway, ticks


def _by_minute(events):
    return {event["settled_cutoff"][11:16]: event for event in events}


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_driver_reaches_actual_loop_consumers_disarmed_with_complete_trace(tmp_path, monkeypatch, ecu):
    summary, events, calls, gateway, ticks = _trajectory(tmp_path, monkeypatch, ecu=ecu)
    # One recorded event per offered tick, chained, nothing skipped.
    assert summary["infrastructure_error"] is None
    assert len(events) == len(ticks) == summary["ticks"]
    assert [e["sequence"] for e in events] == list(range(len(ticks)))
    # The real loop produced the distinct-anchor candidate and stopped at the
    # arm switch: no mission token, attempt, venue write or network attempt.
    minutes = _by_minute(events)
    for hm in W.WINDOW:
        event = minutes[hm]
        assert event["outcome"] == "QUALIFIED_CANDIDATE_OBSERVED", (hm, event["outcome"], event["first_refusal_code"])
        assert event["tool_occurrence_id"] == W.FORMATION_ID, hm
        assert event["formation_id"] == W.FORMATION_ID and event["scope_id"], hm
    assert summary["venue_writes"] == [] and summary["network_attempts"] == []
    assert summary["mission_tokens"] == 0 and summary["mission_attempts"] == 0
    # Cognition crossed the real provider seam: one primary per cognition tick
    # at most, none on declared prewarm ticks, each with its transported bytes.
    prewarm = {t.ordinal for t in ticks if t.kind == "PREWARM"}
    assert all(e["primary_call_count"] == 0 for e in events if e["sequence"] in prewarm)
    assert all(e["primary_call_count"] <= 1 for e in events)
    assert summary["primary_calls"] == len([c for c in calls if c["purpose"] == "PRIMARY"]) > 0
    for call, request in zip(calls, gateway.requests):
        assert call["evaluation_origin"] == "MOCK" and call["request_attempted"] is False
        assert call["input_ref"]["sha256"] == request["input_digest"]
        assert call["prompt_ref"]["sha256"] == request["prompt_digest"]
        assert call["requested_model"] == call["served_model"] == request["requested_model"]
        assert C.instant(request["settled_cutoff"]) <= C.instant(request["decision_time"])
    # The transported payload is the real producer catalog: the named formation
    # in the window was published to the model in that very request.
    named = [r for r in gateway.requests if r["settled_cutoff"][11:16] in W.WINDOW]
    assert named and all(W.FORMATION_ID in r["user_contents"][0] for r in named)


def test_wrong_patch_target_fails_the_reachability_assertion(tmp_path, monkeypatch):
    summary, events, calls, gateway, ticks = _trajectory(tmp_path, monkeypatch, ecu=False, install_on_wrong_target=True,
                                                         ticks_until="2026-08-19T15:50:00Z")
    # Production never reached the decoy: no transported request, and the
    # scans that asked for cognition took production's degraded path.
    assert gateway.requests == [] and calls == []
    assert any(e["outcome"] == "BRAIN_DEGRADED" for e in events)
    with pytest.raises(AssertionError):
        assert summary["primary_calls"] > 0

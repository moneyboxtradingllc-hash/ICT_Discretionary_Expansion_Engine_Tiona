"""Current-Brain evaluation PREPARATION: the disabled real-provider path, offline only.

Codex contract 2026-10-25/1 (PREPARE ONLY). Nothing here can reach a provider:
every SDK client either carries an httpx MockTransport (so it is never
genuine and can never be labelled CURRENT_EXTERNAL) or is constructed and
then refused before it could send. No credential exists; the strings below
are test sentinels. Authorizations and approved prices here are CONSTRUCTED
test documents, never an owner approval.
"""
from __future__ import annotations

import copy
import json
import socket
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import openai
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
import test_recognition_model_authority as TMA  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import child as CH  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import eval_plan as EP  # noqa: E402
from recognition_validation import model_authority as MA  # noqa: E402
from recognition_validation import ports as P  # noqa: E402
from recognition_validation import provider_transport as PT  # noqa: E402

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
SENTINEL = "sk-TEST-SENTINEL-not-a-credential-000000"
PROFILE = MA.EvaluationParameters(EP.BUDGET["max_completion_tokens"])
PAYLOAD = {"model": EP.MODEL, "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "{}"}],
           "timeout": 25.0, "prompt_cache_key": "k", "response_format": {"type": "json_object"},
           "max_completion_tokens": 8192, "extra_headers": {"X-Client-Request-Id": "cid-1"}}
COMPLETION = {"id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "gpt-6-luna-2026-09-22",
              "service_tier": "default",
              "choices": [{"index": 0, "finish_reason": "stop",
                           "message": {"role": "assistant", "content": "{\"ok\": true}"}}],
              "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
                        "prompt_tokens_details": {"cached_tokens": 0},
                        "completion_tokens_details": {"reasoning_tokens": 120}}}


# -- transport: genuine SDK, pinned endpoint, retries off, exact payload -----------

def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_genuine_sdk_over_a_mock_http_client_sends_production_payload_once_and_is_never_genuine():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=COMPLETION, headers={"x-request-id": "req-test"})
    transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, http_client=_mock_client(handler),
                                       environ={})
    assert PT.genuine_sdk(openai) and transport.genuine is False
    reply = transport.send(copy.deepcopy(PAYLOAD))
    assert len(seen) == 1 and str(seen[0].url) == PT.ENDPOINT + "/chat/completions"
    body = json.loads(seen[0].content)
    assert body["max_completion_tokens"] == 8192 and body["model"] == EP.MODEL
    assert body["response_format"] == {"type": "json_object"} and body["prompt_cache_key"] == "k"
    assert seen[0].headers["X-Client-Request-Id"] == "cid-1"
    assert reply.served_model == "gpt-6-luna-2026-09-22" and reply.request_id == "req-test"
    assert reply.finish_reason == "stop" and reply.service_tier == "default"
    assert reply.usage == {"prompt_tokens": 1200, "completion_tokens": 300, "cached_tokens": 0,
                           "reasoning_tokens": 120}
    with pytest.raises(C.ContractError) as exc:
        PT.CurrentExternalResponder(None, None, transport, trajectory_id="T")
    assert exc.value.code == "WRONG_TRANSPORT_SEAM"


@pytest.mark.parametrize("status", [500, 429, 408])
def test_sdk_retries_are_off_one_http_request_per_send_and_errors_are_transport_errors(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": {"message": "test"}})
    transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, http_client=_mock_client(handler),
                                       environ={})
    assert transport.client.max_retries == 0
    with pytest.raises(G.TransportError):
        transport.send(copy.deepcopy(PAYLOAD))
    assert len(seen) == 1, "an SDK retry would be an uncounted request"


def test_timeout_is_a_transport_error_with_unknown_usage():
    def handler(request):
        raise httpx.ReadTimeout("test timeout", request=request)
    transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, http_client=_mock_client(handler),
                                       environ={})
    with pytest.raises(G.TransportError):
        transport.send(copy.deepcopy(PAYLOAD))


def test_internally_built_client_is_genuine_pinned_and_ignores_environment_proxy():
    with P.NetworkGuard().deny() as guard:
        transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, environ={})
    assert guard.attempts == [], "constructing the client must not touch the network"
    assert transport.genuine is True and transport.client.max_retries == 0
    assert str(transport.client.base_url).rstrip("/") == PT.ENDPOINT
    assert transport.client._client.trust_env is False


@pytest.mark.parametrize("name", ["OPENAI_BASE_URL", "OPENAI_API_BASE"])
def test_endpoint_override_in_environment_refuses(name):
    with pytest.raises(C.ContractError) as exc:
        PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, environ={name: "https://proxy.example/v1"})
    assert exc.value.code == "ENDPOINT_OVERRIDE_REFUSED"


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.update(temperature=0), "PAYLOAD_PARAMETER_UNEXPECTED"),
    (lambda p: p.update(service_tier="flex"), "PAYLOAD_PARAMETER_UNEXPECTED"),
    (lambda p: p.pop("max_completion_tokens"), "OUTPUT_CAP_ABSENT"),
    (lambda p: p["extra_headers"].update({"OpenAI-Organization": "x"}), "PAYLOAD_HEADER_UNEXPECTED"),
])
def test_payload_beyond_production_plus_output_cap_is_refused_before_any_http(mutate, code):
    seen = []
    transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, environ={},
                                       http_client=_mock_client(lambda r: seen.append(r) or httpx.Response(200)))
    payload = copy.deepcopy(PAYLOAD)
    mutate(payload)
    with pytest.raises(C.ContractError) as exc:
        transport.send(payload)
    assert exc.value.code == code and seen == [] and transport.sent == 0


def test_a_stand_in_sdk_module_is_never_genuine():
    fake = types.ModuleType("openai")
    fake.__file__ = "/tmp/site-packages/openai/__init__.py"

    class Client:
        def __init__(self, **kwargs):
            self.max_retries = kwargs["max_retries"]
    fake.OpenAI = Client
    assert PT.genuine_sdk(fake) is False
    transport = PT.OpenAIChatTransport(fake, lambda: SENTINEL, timeout=5.0, environ={})
    assert transport.genuine is False
    with pytest.raises(C.ContractError) as exc:
        PT.CurrentExternalResponder(None, None, transport, trajectory_id="T")
    assert exc.value.code == "WRONG_TRANSPORT_SEAM"


@pytest.mark.parametrize("transport", [TMA.FakeTransport(), object()])
def test_only_the_genuine_transport_can_be_current_external(transport):
    with pytest.raises(C.ContractError) as exc:
        PT.CurrentExternalResponder(None, None, transport, trajectory_id="T")
    assert exc.value.code == "WRONG_TRANSPORT_SEAM"
    assert G.CurrentModelResponder.origin == "MOCK" and PT.CurrentExternalResponder.origin == "CURRENT_EXTERNAL"


def test_genuine_responder_under_the_disabled_template_refuses_before_transport(tmp_path):
    with P.NetworkGuard().deny() as guard:
        transport = PT.OpenAIChatTransport(openai, lambda: SENTINEL, timeout=5.0, environ={})
        disabled = json.loads((ROOT / "src/recognition_validation/examples/model_authorization_disabled.json")
                              .read_text())
        authority = MA.ModelAuthority(disabled, pricing=None, parameters=PROFILE, identity=TMA.IDENTITY,
                                      real_clock=lambda: NOW)
        ledger = MA.BudgetLedger(tmp_path / "ledger.jsonl", disabled, Decimal(0))
        responder = PT.CurrentExternalResponder(authority, ledger, transport, trajectory_id="T")
        with pytest.raises(G.ProviderRefusal) as exc:
            responder.respond(TMA._request())
    assert exc.value.code == "CURRENT_MODEL_CALLS_DISABLED"
    assert transport.sent == 0 and responder.transport_calls == 0 and ledger.requests == 0
    assert guard.attempts == []


# -- the provider-only guard -------------------------------------------------------

def test_provider_only_guard_admits_exactly_the_pinned_host_and_its_resolved_addresses(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", port))])
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: calls.append(("connect", address)))
    monkeypatch.setattr(socket, "create_connection", lambda address, *a, **k: calls.append(("create", address)))
    guard = PT.ProviderOnlyNetworkGuard("https://provider.invalid/v1")
    with guard.deny():
        assert socket.getaddrinfo("provider.invalid", 443)
        sock = socket.socket()
        try:
            sock.connect(("203.0.113.7", 443))
            for address in (("203.0.113.8", 443), ("203.0.113.7", 80)):
                with pytest.raises(P.NetworkRefused):
                    sock.connect(address)
        finally:
            sock.close()
        socket.create_connection(("provider.invalid", 443))
        for host, port in (("api.topstepx.com", 443), ("provider.invalid", 80), ("127.0.0.1", 9)):
            with pytest.raises(P.NetworkRefused):
                socket.getaddrinfo(host, port)
            with pytest.raises(P.NetworkRefused):
                socket.create_connection((host, port))
    assert calls == [("connect", ("203.0.113.7", 443)), ("create", ("provider.invalid", 443))]
    refused = [a for a in guard.attempts]
    assert len(refused) == 8 and all(kind in ("getaddrinfo", "connect", "create_connection") for kind, _ in refused)


# -- one durable ledger: lanes, cases, restarts and run ids share it ---------------

def _ledger(tmp_path, authorization, binding):
    pricing = TMA._pricing()
    authority = MA.ModelAuthority(authorization, pricing=pricing, parameters=TMA.PROFILE, identity=TMA.IDENTITY,
                                  receipt_root=tmp_path, real_clock=lambda: TMA.NOW)
    return authority, MA.BudgetLedger(tmp_path / "shared.jsonl", authorization, authority.per_request_bound,
                                      binding=binding)


def test_lanes_cases_restarts_and_new_run_ids_cannot_refill_the_budget(tmp_path):
    auth = TMA._authorization(tmp_path, max_external_requests=3, max_transport_retries=0)
    binding = auth["seal"]["sha256"]
    sent = 0
    for trajectory in ("CBE-A-ecu", "CBE-A-non_ecu", "CBE-B-ecu"):   # lanes, cases, a new run id
        authority, ledger = _ledger(tmp_path, auth, binding)          # every open is a restart
        responder = G.CurrentModelResponder(authority, ledger, TMA.FakeTransport(), trajectory_id=trajectory)
        responder.respond(TMA._request(sent))
        sent += 1
    authority, ledger = _ledger(tmp_path, auth, binding)
    responder = G.CurrentModelResponder(authority, ledger, TMA.FakeTransport(), trajectory_id="CBE-NEW-RUN")
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond(TMA._request(9))
    assert exc.value.code == "REQUEST_CAP_EXHAUSTED" and responder.transport.sent == []
    assert ledger.requests == 3


def test_a_ledger_is_bound_to_one_authorization(tmp_path):
    auth = TMA._authorization(tmp_path)
    _ledger(tmp_path, auth, auth["seal"]["sha256"])
    with pytest.raises(C.ContractError) as exc:
        _ledger(tmp_path, auth, "f" * 64)
    assert exc.value.code == "LEDGER_AUTHORIZATION_MISMATCH"


def test_unbound_history_cannot_be_adopted_by_a_bound_run(tmp_path):
    auth = TMA._authorization(tmp_path)
    authority, ledger = _ledger(tmp_path, auth, None)
    G.CurrentModelResponder(authority, ledger, TMA.FakeTransport(), trajectory_id="T").respond(TMA._request())
    with pytest.raises(C.ContractError) as exc:
        _ledger(tmp_path, auth, auth["seal"]["sha256"])
    assert exc.value.code == "LEDGER_UNBOUND_HISTORY"


@pytest.mark.parametrize("failure,reason", [
    (G.TransportError("timeout"), "TRANSPORT_ERROR_USAGE_UNKNOWN"),
    (G.ProviderReply(content="{}", served_model=EP.MODEL, usage={}), "USAGE_UNKNOWN"),
])
def test_unknown_usage_or_timeout_halts_every_later_lane_and_restart(tmp_path, failure, reason):
    auth = TMA._authorization(tmp_path, max_transport_retries=0)
    binding = auth["seal"]["sha256"]
    authority, ledger = _ledger(tmp_path, auth, binding)
    responder = G.CurrentModelResponder(authority, ledger, TMA.FakeTransport([failure]), trajectory_id="ecu")
    try:
        responder.respond(TMA._request())
    except G.ProviderRefusal:
        pass
    assert ledger.halted == reason
    authority, reopened = _ledger(tmp_path, auth, binding)
    assert reopened.halted == reason
    other = G.CurrentModelResponder(authority, reopened, TMA.FakeTransport(), trajectory_id="non_ecu")
    with pytest.raises(G.ProviderRefusal) as exc:
        other.respond(TMA._request(1))
    assert exc.value.code == "RUN_HALTED" and other.transport.sent == []


# -- the sealed plan and release admission -----------------------------------------

def _plan(tmp_path, **over):
    identity = C.source_identity()
    root = tmp_path / "plan"
    root.mkdir()
    (root / "artifact.json").write_text("{}\n")
    ref = {"path": "artifact.json", "sha256": C.sha256_hex(b"{}\n"), "bytes": 3, "origin": "CONSTRUCTED"}
    trajectories = [{"trajectory_id": f"T{i}-{lane}", "lane": lane, "ecu": ecu, "primary_decisions": n}
                    for i, n in enumerate((12, 3, 1, 1)) for lane, ecu in EP.LANES]
    plan = {"schema": EP.PLAN_SCHEMA, "production_source_sha": identity["source_sha"],
            "brain_fingerprint": identity["brain_fingerprint"],
            "retrieval_fingerprint": identity["retrieval_fingerprint"], "parameter_digest": PROFILE.digest,
            "corpus_set_digest": "c" * 64, "schedule_set_digest": "d" * 64, "artifacts": {"a": ref},
            "trajectories": trajectories, "max_input_tokens_per_request": 200000, "authority": "DISABLED",
            "owner_approval": None, "seal": None}
    plan.update(over)
    plan = EP.seal(plan, sealed_at="2026-10-25T00:00:00Z", sealer="test")
    (root / "plan.json").write_text(json.dumps(plan, sort_keys=True))
    return root / "plan.json", plan


def _pricing(approved: bool):
    source = {"path": "pricing_source.md", "sha256": "0" * 64, "bytes": 0, "origin": "REPOSITORY_RECORDED"}
    doc = EP.pricing_document(source_ref=source, accessed_at="2026-10-25T20:28:11Z")
    if approved:
        doc["owner_pricing_approval_ref"] = "TEST-ONLY constructed approval"
        doc = EP.seal(doc, sealed_at="2026-10-25T00:00:00Z", sealer="test")
    return doc


def _authorized(tmp_path, plan, pricing, **over):
    doc = EP.authorization_template(plan, sealed_at="2026-10-25T00:00:00Z")
    doc.update(state="OWNER_AUTHORIZED", owner_receipt_ref=TMA._receipt(tmp_path), model=EP.MODEL,
               endpoint_identity=PT.ENDPOINT_IDENTITY, trajectory_count=len(plan["trajectories"]),
               issued_at="2026-10-26T00:00:00Z", expires_at="2026-10-27T00:00:00Z", max_external_requests=40,
               max_input_tokens_per_request=200000, max_output_tokens_per_request=8192, max_repair_requests=6,
               max_transport_retries=0, max_cost_usd="15.00", pricing_digest=C.seal_digest(pricing))
    doc.update(over)
    return EP.seal(doc, sealed_at="2026-10-25T00:00:00Z", sealer="test")


def test_plan_seal_counts_lanes_and_disabled_authority_are_verified(tmp_path):
    path, plan = _plan(tmp_path)
    assert EP.load_plan(path)["seal"] == plan["seal"]
    tampered = dict(plan, max_input_tokens_per_request=900000)
    path.write_text(json.dumps(tampered))
    with pytest.raises(C.ContractError, match="PLAN_SEAL_INVALID"):
        EP.load_plan(path)
    for n, over in enumerate(({"authority": "OWNER_AUTHORIZED"},
                              {"trajectories": plan["trajectories"][:-1]},
                              {"trajectories": [dict(t, lane="ecu") for t in plan["trajectories"]]})):
        sub = tmp_path / f"case{n}"
        sub.mkdir()
        bad_path, _ = _plan(sub, **over)
        with pytest.raises(C.ContractError):
            EP.load_plan(bad_path)


def test_disabled_release_refuses_before_any_credential_child_or_ledger(tmp_path):
    path, plan = _plan(tmp_path)
    auth_path, pricing_path = tmp_path / "auth.json", tmp_path / "pricing.json"
    auth_path.write_text(json.dumps(EP.authorization_template(plan, sealed_at="2026-10-25T00:00:00Z")))
    pricing_path.write_text(json.dumps(_pricing(approved=False)))
    touched = []
    with P.NetworkGuard().deny() as guard, pytest.raises(C.ContractError) as exc:
        EP.run_released(path, auth_path, pricing_path, receipt_root=tmp_path, ledger_path=tmp_path / "ledger.jsonl",
                        out_root=tmp_path / "run", credential_reader=lambda: touched.append("credential"),
                        run_child=lambda *a, **k: touched.append("child"))
    assert exc.value.code == "CURRENT_MODEL_CALLS_DISABLED"
    assert touched == [] and guard.attempts == [] and not (tmp_path / "ledger.jsonl").exists()


@pytest.mark.parametrize("over,approved,code", [
    ({}, False, "PRICING_UNAPPROVED"),
    ({"expires_at": "2026-10-26T12:00:00Z"}, True, "AUTHORIZATION_EXPIRED"),
    ({"issued_at": "2026-10-26T16:00:00Z"}, True, "AUTHORIZATION_NOT_YET_VALID"),
    ({"source_sha": "0" * 40}, True, "AUTHORIZATION_IDENTITY_MISMATCH"),
    ({"model": "gpt-6-sol"}, True, "AUTHORIZATION_IDENTITY_MISMATCH"),
    ({"endpoint_identity": "openai:chat.completions:https://proxy.example/v1"}, True,
     "AUTHORIZATION_IDENTITY_MISMATCH"),
    ({"owner_receipt_ref": None}, True, "MODEL_AUTHORIZATION_INCOMPLETE"),   # schema: OWNER_AUTHORIZED needs a receipt
    ({"max_external_requests": 41}, True, "AUTHORIZATION_EXCEEDS_PLAN"),
    ({"max_transport_retries": 1}, True, "AUTHORIZATION_EXCEEDS_PLAN"),
    ({"max_cost_usd": "15.01"}, True, "AUTHORIZATION_EXCEEDS_PLAN"),
    ({"max_input_tokens_per_request": 200001}, True, "AUTHORIZATION_EXCEEDS_PLAN"),
    ({"trajectory_count": 7}, True, "AUTHORIZATION_IDENTITY_MISMATCH"),
])
def test_every_release_gate_refuses_before_transport(tmp_path, over, approved, code):
    _, plan = _plan(tmp_path)
    pricing = _pricing(approved)
    auth = _authorized(tmp_path, plan, pricing, **over)
    with pytest.raises(C.ContractError) as exc:
        EP.admit_release(plan, auth, pricing, receipt_root=tmp_path, real_clock=lambda: NOW)
    assert exc.value.code == code


def test_unsealed_authorization_refuses(tmp_path):
    _, plan = _plan(tmp_path)
    pricing = _pricing(True)
    auth = _authorized(tmp_path, plan, pricing)
    auth["max_cost_usd"] = "14.00"     # edited after the seal
    with pytest.raises(C.ContractError) as exc:
        EP.admit_release(plan, auth, pricing, receipt_root=tmp_path, real_clock=lambda: NOW)
    assert exc.value.code == "SEAL_MISMATCH"


def test_a_complete_constructed_authorization_admits_and_the_child_would_bind_its_ledger(tmp_path):
    _, plan = _plan(tmp_path)
    pricing = _pricing(True)
    auth = _authorized(tmp_path, plan, pricing)
    authority = EP.admit_release(plan, auth, pricing, receipt_root=tmp_path, real_clock=lambda: NOW)
    assert authority.per_request_bound == Decimal("0.108192")   # (200000*0.50 + 8192*1.00) / 1e6
    ledger = MA.BudgetLedger(tmp_path / "l.jsonl", auth, authority.per_request_bound, binding=auth["seal"]["sha256"])
    assert ledger.binding == auth["seal"]["sha256"] and ledger.requests == 0


def test_cost_plan_is_a_conservative_bound_below_the_proposed_cap():
    plan = EP.cost_plan(input_cap_tokens=200000, pricing=_pricing(False))
    assert plan["external_requests_made"] == 0 and plan["per_request_upper_bound_usd"] == "0.108192"
    assert plan["binding_limit"] == "REQUEST_CAP" and Decimal(plan["worst_case_total_usd"]) == Decimal("4.32768")
    with pytest.raises(C.ContractError, match="INPUT_CAP_ABOVE_LONG_CONTEXT"):
        EP.input_cap(190000)


# -- the child: secret channel, refusal before stdin --------------------------------

def test_secret_channel_exists_only_for_a_current_external_request(tmp_path):
    with pytest.raises(C.ContractError, match="CHILD_SECRET_CHANNEL"):
        CH.run_in_child({"schema": CH.REQUEST_SCHEMA, "ecu": False, "responder": {"kind": "SCRIPT"}},
                        out_root=tmp_path / "a", stdin_secret=SENTINEL)
    with pytest.raises(C.ContractError, match="CHILD_SECRET_CHANNEL"):
        CH.run_in_child({"schema": CH.REQUEST_SCHEMA, "ecu": False, "responder": {"kind": "CURRENT_EXTERNAL"}},
                        out_root=tmp_path / "b")


def test_released_child_refuses_disabled_authority_before_reading_its_stdin(tmp_path):
    path, plan = _plan(tmp_path)
    auth_path, pricing_path = tmp_path / "auth.json", tmp_path / "pricing.json"
    auth_path.write_text(json.dumps(EP.authorization_template(plan, sealed_at="2026-10-25T00:00:00Z")))
    pricing_path.write_text(json.dumps(_pricing(approved=False)))
    request = {"schema": CH.REQUEST_SCHEMA, "mode": "C", "ecu": False, "trajectory_id": "T0-non_ecu",
               "contract_id": EP.CONTRACT_ID, "memory_policy": "EMPTY",
               "expected_source_identity": C.source_identity(),
               "responder": {"kind": "CURRENT_EXTERNAL", "plan_path": str(path), "plan_seal": plan["seal"]["sha256"],
                             "authorization_path": str(auth_path), "pricing_path": str(pricing_path),
                             "receipt_root": str(tmp_path), "ledger_path": str(tmp_path / "ledger.jsonl"),
                             "client_timeout_seconds": 5.0}}
    # An EMPTY secret: had the child read stdin first it would refuse CREDENTIAL_MISSING instead.
    status = CH.run_in_child(request, out_root=tmp_path / "run", timeout_seconds=600.0, stdin_secret="")
    exit_record = status["child_exit"]
    assert status["complete"] is False and status["exit_code"] == 2
    assert exit_record["status"] == "REFUSED" and exit_record["code"] == "CURRENT_MODEL_CALLS_DISABLED"
    assert not (tmp_path / "ledger.jsonl").exists()
    status2 = CH.run_in_child(request, out_root=tmp_path / "run2", timeout_seconds=600.0, stdin_secret=SENTINEL)
    assert status2["child_exit"]["code"] == "CURRENT_MODEL_CALLS_DISABLED"
    written = b"".join(p.read_bytes() for p in (tmp_path / "run2").rglob("*") if p.is_file())
    assert SENTINEL.encode() not in written, "the secret never reaches disk"


# -- corpus, schedule and quotes -----------------------------------------------------

def test_sealed_schedule_shape_is_the_contract_schedule():
    import build_current_brain_eval_plan as B
    groups = B.sessions()
    specs = [s for group in groups.values() for s in group]
    assert sum(len(s["opens"]) for s in specs) * 2 == 34
    friday = groups["friday"][0]
    assert [o[11:16] for o in friday["opens"]] == list(EP.FRIDAY_CUTOFFS)
    w5 = next(s for s in specs if s["session_id"] == "W5-T2T3T4")
    assert [o[11:16] for o in w5["opens"]] == ["14:36", "14:37", "14:38"] and len(w5["tape"]) == 99
    import test_campaign_draw_temporal_authority as TA
    import test_campaign_leg_scope_labels as L
    for sid, name, last in (("C2-UNSUPPORTED-TRANSFER", "C2", "15:14"), ("C4-INTACT-RETRACE", "C4", "15:16")):
        spec = next(s for s in specs if s["session_id"] == sid)
        original = list(TA.LATER) + list(L.SCENARIOS[name])
        assert [o[11:16] for o in spec["opens"]] == [last]
        assert [{k: b[k] for k in ("open", "high", "low", "close")} for b in spec["tape"]] == \
               [{k: b[k] for k in ("open", "high", "low", "close")} for b in original]
        assert all(datetime.fromisoformat(a["timestamp"]) - datetime.fromisoformat(b["timestamp"])
                   == timedelta(hours=12) for a, b in zip(spec["tape"], original))
        decision = datetime.fromisoformat(spec["opens"][0]) + timedelta(minutes=1)
        assert P.production_window_open(decision)
        assert not P.production_window_open(decision - timedelta(hours=12))


def test_controlled_quotes_are_sealed_inputs_only_under_the_controlled_policy(tmp_path):
    import build_current_brain_eval_plan as B
    tape = B.w5_tape()
    quotes = EP.controlled_quotes(tape)
    assert all(q["origin"] == "CONTROLLED" and q["ask"] - q["bid"] == 0.25 for q in quotes)
    from recognition_validation import corpus as K
    from recognition_validation import driver as DR
    corpus = K.build_constructed_corpus(tmp_path / "corpus", session_id="W5", contract_id=EP.CONTRACT_ID,
                                        market_date="2026-08-19", tape=tape, warmup_end=tape[96]["timestamp"],
                                        notes="CONSTRUCTED", sealed_at="2026-10-25T00:00:00Z")
    for policy, supplied in (("CONTROLLED", None), ("CONSTRUCTED", quotes)):
        with pytest.raises(C.ContractError, match="CONTROLLED_QUOTES_POLICY"):
            DR.run_offline(corpus_path=corpus, session_id="W5", out_root=tmp_path / f"run-{policy}",
                           responder=TMA.FakeTransport(), ecu=False, trajectory_id="T", quote_policy=policy,
                           controlled_quotes=supplied)


# -- dual-standard report -------------------------------------------------------------

def _row(lane, case, *, raw_action="stand_down", outcome="NO_CANDIDATE", origin="CURRENT_EXTERNAL",
         status="COMPLETE", lifecycle="TRANSFER_UNRESOLVED", candidate=False, basis=None):
    from recognition_validation import eval_report as ER
    call = {"record_status": status, "evaluation_origin": origin, "fallback_reason": None}
    raw = {"current_action": raw_action, "narrative_direction": "bearish"}
    scan = {"outcome": outcome, "first_refusal_code": "campaign_lifecycle_refused", "lifecycle_state": lifecycle,
            "candidate_present": candidate}
    return dict(ER.classify(case=case, call=call, raw=raw, post=raw, scan=scan, negative_basis=basis), lane=lane)


def test_every_refusal_gets_exactly_one_class_or_is_left_for_audit():
    from recognition_validation import eval_report as ER
    basis = {"lifecycle_states": ["TRANSFER_UNRESOLVED"]}
    assert _row("ecu", "FRIDAY_SETTLED")["participation"]["refusal_class"] == "BRAIN_NO_ENTRY_INTENT"
    assert _row("ecu", "FRIDAY_SETTLED", status="INCOMPLETE")["participation"]["refusal_class"] == \
        "BUDGET_PROVIDER_OR_RUN_FAILURE"
    assert _row("ecu", "FRIDAY_SETTLED", origin="MOCK")["participation"]["refusal_class"] == \
        "BUDGET_PROVIDER_OR_RUN_FAILURE", "mock cognition can never be scored as fresh"
    neg = _row("ecu", "NEGATIVE_UNSUPPORTED_TRANSFER", raw_action="propose_entry", basis=basis)
    assert neg["participation"]["refusal_class"] == "CORRECT_RESTRAINT"
    assert neg["cognitive"]["cognitive_result"] == "ENTRY_INTENT_ON_NEGATIVE"
    open_case = _row("ecu", "FRIDAY_SETTLED", raw_action="propose_entry")["participation"]
    assert open_case["refusal_class"] == "UNCLASSIFIED" and open_case["audit_candidates"] == list(ER.AUDIT_CANDIDATES)
    assert set(ER.REFUSAL_CLASSES) == {"CORRECT_RESTRAINT", "BRAIN_NO_ENTRY_INTENT", "MISSING_OR_UNPROVEN_EVIDENCE",
                                       "PRODUCER_CONSUMER_DEFECT", "AUTHORITY_CONTRACT_MISMATCH_OR_GAP",
                                       "BUDGET_PROVIDER_OR_RUN_FAILURE"}


def test_an_all_refusal_result_cannot_pass_and_a_run_failure_is_incomplete():
    from recognition_validation import eval_report as ER
    basis = {"lifecycle_states": ["TRANSFER_UNRESOLVED"]}
    rows = [_row(lane, "NEGATIVE_INTACT_RETRACEMENT", basis=basis) for lane in ("ecu", "non_ecu") for _ in range(17)]
    result = ER.verdict(rows, expected_primaries=34)
    assert {v["participation_verdict"] for v in result.values()} == {"NOT_PASSED_ALL_REFUSAL"}
    rows[0] = _row("ecu", "FRIDAY_SETTLED", outcome="QUALIFIED_CANDIDATE_OBSERVED", candidate=True,
                   raw_action="propose_entry")
    assert ER.verdict(rows, expected_primaries=34)["ecu"]["participation_verdict"] == "ELIGIBLE_FOR_AUDIT_PASS"
    assert ER.verdict(rows, expected_primaries=34)["non_ecu"]["participation_verdict"] == "NOT_PASSED_ALL_REFUSAL"
    rows[1] = _row("ecu", "FRIDAY_SETTLED", status="INCOMPLETE")
    assert ER.verdict(rows, expected_primaries=34)["ecu"]["participation_verdict"] == "INCOMPLETE"
    assert ER.verdict(rows[:-1], expected_primaries=34)["non_ecu"]["participation_verdict"] == "INCOMPLETE"
    assert ER.report_schema()["pass_authority"].startswith("Codex audit")

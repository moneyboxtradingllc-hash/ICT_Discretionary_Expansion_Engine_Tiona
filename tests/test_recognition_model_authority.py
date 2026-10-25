"""Stage 5 M05: disabled Mode C, owner authority, hard budgets, counted transport.

Every external-mode path runs only against a fake transport. The authorization
and price table here are CONSTRUCTED test documents (a simulated receipt), not
an owner approval; the repository holds no key and makes no request.
"""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_recognition_current_path as CP  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import model_authority as MA  # noqa: E402
from recognition_validation import ports as P  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402

MODEL = "gpt-6-luna"
ENDPOINT = "fake-transport://stage5-tests"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
PROFILE = MA.EvaluationParameters(max_completion_tokens=4000)
IDENTITY = MA.RunIdentity(source_sha="a" * 40, brain_fingerprint="brain:62fe5ecf46d75dc4",
                          retrieval_fingerprint="retr:0c241bdb8234d1ba", corpus_digest="c" * 64,
                          schedule_digest="d" * 64, model=MODEL, endpoint_identity=ENDPOINT)
PROVENANCE = {"classification": "CONSTRUCTED", "author_role": "STAGE5_TEST",
              "source_refs": ["tests/test_recognition_model_authority.py"],
              "notes": "CONSTRUCTED test authority; not an owner approval."}


def _seal(doc):
    doc["seal"] = None
    doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": "2026-10-17T00:00:00Z", "sealer_ref": "test"}
    return doc


def _pricing(**over):
    doc = {"schema_version": "pricing/v1", "document_id": "TEST-PRICING", "provenance": PROVENANCE,
           "currency": "USD", "model": MODEL, "effective_at": "2026-10-01T00:00:00Z",
           "source_ref": {"path": "receipt.txt", "sha256": "0" * 64, "bytes": 0, "origin": "CONSTRUCTED"},
           "rate_unit_tokens": 1000000, "uncached_input_rate": "2.00", "output_rate": "8.00",
           "cache_discount_assumed": False, "owner_pricing_approval_ref": "TEST-ONLY constructed approval"}
    doc.update(over)
    return _seal(doc)


def _receipt(tmp_path):
    data = b"CONSTRUCTED owner receipt for tests only\n"
    (tmp_path / "receipt.txt").write_bytes(data)
    return {"path": "receipt.txt", "sha256": C.sha256_hex(data), "bytes": len(data), "origin": "CONSTRUCTED"}


def _authorization(tmp_path, pricing=None, **over):
    pricing = pricing or _pricing()
    doc = {"schema_version": "model_authorization/v1", "document_id": "TEST-AUTH", "provenance": PROVENANCE,
           "state": "OWNER_AUTHORIZED", "owner_receipt_ref": _receipt(tmp_path),
           "source_sha": IDENTITY.source_sha, "brain_fingerprint": IDENTITY.brain_fingerprint,
           "retrieval_fingerprint": IDENTITY.retrieval_fingerprint, "model": MODEL,
           "parameter_digest": PROFILE.digest, "endpoint_identity": ENDPOINT,
           "corpus_digest": IDENTITY.corpus_digest, "annotation_digests": [], "scoring_plan_digest": None,
           "schedule_digest": IDENTITY.schedule_digest, "trajectory_count": 1,
           "issued_at": "2026-10-17T00:00:00Z", "expires_at": "2026-10-18T00:00:00Z",
           "max_external_requests": 50, "max_input_tokens_per_request": 400000,
           "max_output_tokens_per_request": 4000, "max_repair_requests": 10, "max_transport_retries": 1,
           "max_cost_usd": "100", "pricing_digest": C.seal_digest(pricing), "stage4_owner_acceptance_ref": None}
    doc.update(over)
    return _seal(doc)


class FakeTransport:
    endpoint_identity = ENDPOINT

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.sent: list = []

    def send(self, payload):
        self.sent.append(payload)
        reply = self.replies.pop(0) if self.replies else None
        if isinstance(reply, Exception):
            raise reply
        return reply or G.ProviderReply(content="{}", served_model=MODEL,
                                        usage={"prompt_tokens": 1000, "completion_tokens": 100},
                                        request_id="fake-req", response_id="fake-resp")


def _responder(tmp_path, *, authorization=None, pricing="default", parameters=PROFILE, identity=IDENTITY,
               transport=None, clock=lambda: NOW, receipt_root="default"):
    pricing = _pricing() if pricing == "default" else pricing
    authorization = authorization or _authorization(tmp_path, pricing=pricing)
    authority = MA.ModelAuthority(authorization, pricing=pricing, parameters=parameters, identity=identity,
                                  receipt_root=tmp_path if receipt_root == "default" else receipt_root,
                                  real_clock=clock)
    ledger = MA.BudgetLedger(tmp_path / "budget.jsonl", authorization,
                             authority.per_request_bound if pricing and parameters else Decimal(0))
    return G.CurrentModelResponder(authority, ledger, transport or FakeTransport(), trajectory_id="T")


def _request(n=0, purpose="PRIMARY", **over):
    request = {"scan_key": f"T/2026-08-19T16:{n:02d}:00+00:00/{n}", "purpose": purpose, "cutoff_ordinal": 0,
               "attempt": 1, "requested_model": MODEL, "client_parameters": {"timeout": 25.0, "max_retries": 0},
               "system_prompt": "system", "user_contents": ['{"timestamp": "x"}'],
               "parameters": {"model": MODEL, "timeout": 25.0}}
    request.update(over)
    return request


def _refused(responder, request, code):
    before = len(responder.transport.sent)
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond(request)
    assert exc.value.code == code
    assert len(responder.transport.sent) == before, "refusal must precede the transport"


# -- defaults ---------------------------------------------------------------

def test_default_is_disabled_and_no_flag_or_environment_enables_it(tmp_path, monkeypatch):
    for name in ("MODEL_CALLS_AUTHORIZED", "STAGE5_MODE_C", "ALLOW_EXTERNAL_MODEL", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "true")
    disabled = json.loads((ROOT / "src/recognition_validation/examples/model_authorization_disabled.json")
                          .read_text())
    responder = _responder(tmp_path, authorization=disabled)
    _refused(responder, _request(), "CURRENT_MODEL_CALLS_DISABLED")
    with pytest.raises(G.ProviderRefusal) as exc:
        G.DisabledCurrentModel().respond(_request())
    assert exc.value.code == "CURRENT_MODEL_CALLS_DISABLED"
    # A disabled document cannot carry a budget, and a FICTIONAL one cannot enable.
    with pytest.raises(C.ContractError) as exc:
        C.validate({**disabled, "max_external_requests": 1})
    assert exc.value.code == "DISABLED_AUTHORIZATION_HAS_BUDGET"
    with pytest.raises(C.ContractError) as exc:
        C.validate(_authorization(tmp_path, provenance={**PROVENANCE, "classification": "FICTIONAL"}))
    assert exc.value.code == "MODEL_AUTHORIZATION_INCOMPLETE"


# -- authority preconditions, each refused before the transport ----------------

@pytest.mark.parametrize("case,code", [
    ("no_receipt_root", "OWNER_RECEIPT_MISSING"),
    ("wrong_receipt", "ARTIFACT_DIGEST_MISMATCH"),
    ("stale_source", "AUTHORIZATION_IDENTITY_MISMATCH"),
    ("stale_corpus", "AUTHORIZATION_IDENTITY_MISMATCH"),
    ("stale_annotation", "AUTHORIZATION_IDENTITY_MISMATCH"),
    ("stale_fingerprint", "AUTHORIZATION_IDENTITY_MISMATCH"),
    ("expired", "AUTHORIZATION_EXPIRED"),
    ("not_yet_valid", "AUTHORIZATION_NOT_YET_VALID"),
    ("unpriced", "PRICING_MISSING"),
    ("unapproved_price", "PRICING_UNAPPROVED"),
    ("tampered_price", "SEAL_MISMATCH"),
    ("tampered_authorization", "SEAL_MISMATCH"),
    ("no_output_cap", "PRODUCTION_OUTPUT_CAP_ABSENT"),
    ("other_profile", "PARAMETER_PROFILE_MISMATCH"),
    ("other_endpoint", "AUTHORIZATION_IDENTITY_MISMATCH"),
    ("sdk_retry", "SDK_RETRY_UNCOUNTED"),
    ("input_cap", "INPUT_TOKEN_CAP_EXCEEDED"),
])
def test_every_missing_or_stale_precondition_refuses_before_transport(tmp_path, case, code):
    kwargs, request = {}, _request()
    if case == "no_receipt_root":
        kwargs["receipt_root"] = None
    elif case == "wrong_receipt":
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "receipt.txt").write_bytes(b"FORGED".ljust(40, b"x") + b"\n")  # same length
        kwargs["receipt_root"] = tmp_path / "other"
    elif case == "stale_source":
        kwargs["identity"] = MA.RunIdentity(**{**IDENTITY.__dict__, "source_sha": "b" * 40})
    elif case == "stale_corpus":
        kwargs["identity"] = MA.RunIdentity(**{**IDENTITY.__dict__, "corpus_digest": "e" * 64})
    elif case == "stale_annotation":
        kwargs["identity"] = MA.RunIdentity(**{**IDENTITY.__dict__, "annotation_digests": ("f" * 64,)})
    elif case == "stale_fingerprint":
        kwargs["identity"] = MA.RunIdentity(**{**IDENTITY.__dict__, "brain_fingerprint": "brain:0000000000000000"})
    elif case == "expired":
        kwargs["clock"] = lambda: NOW + timedelta(days=2)
    elif case == "not_yet_valid":
        kwargs["clock"] = lambda: NOW - timedelta(days=2)
    elif case == "unpriced":
        kwargs["pricing"] = None
    elif case == "unapproved_price":
        pricing = _pricing(owner_pricing_approval_ref=None)
        kwargs.update(pricing=pricing, authorization=_authorization(tmp_path, pricing=pricing))
    elif case == "tampered_price":
        pricing = _pricing()
        kwargs["authorization"] = _authorization(tmp_path, pricing=pricing)
        kwargs["pricing"] = {**pricing, "output_rate": "0.01"}
    elif case == "tampered_authorization":
        kwargs["authorization"] = {**_authorization(tmp_path), "max_cost_usd": "100000"}
    elif case == "no_output_cap":
        kwargs["parameters"] = None
    elif case == "other_profile":
        kwargs["parameters"] = MA.EvaluationParameters(max_completion_tokens=3999)
    elif case == "other_endpoint":
        transport = FakeTransport()
        transport.endpoint_identity = "fake-transport://elsewhere"
        kwargs["transport"] = transport
    elif case == "sdk_retry":
        request["client_parameters"] = {"timeout": 25.0, "max_retries": 2}
    elif case == "input_cap":
        request["user_contents"] = ["x" * 400001]
    if case == "tampered_authorization":
        # Refused when the authority is built, long before any request exists.
        with pytest.raises(C.ContractError) as exc:
            _responder(tmp_path, **kwargs)
        assert exc.value.code == code
        return
    responder = _responder(tmp_path, **kwargs)
    _refused(responder, request, code)
    assert responder.ledger.requests == 0 and responder.ledger.exposure == 0


def test_authorization_time_is_real_utc_never_the_market_decision_clock(tmp_path):
    seen = []

    def real():
        seen.append(True)
        return NOW
    responder = _responder(tmp_path, clock=real)
    request = _request(decision_time="2026-08-19T16:39:00+00:00")
    responder.respond(request)
    assert seen and len(responder.transport.sent) == 1
    assert P.real_utc_now().year >= 2026


# -- budget state machine --------------------------------------------------------

def test_request_cap_counts_every_purpose_and_stops_before_transport(tmp_path):
    auth = _authorization(tmp_path, max_external_requests=3, max_repair_requests=2)
    responder = _responder(tmp_path, authorization=auth)
    responder.respond(_request(1))
    responder.respond(_request(1, purpose="REPAIR"))
    responder.respond(_request(1, purpose="INVALIDATION_REPAIR"))
    _refused(responder, _request(2), "REQUEST_CAP_EXHAUSTED")
    assert len(responder.transport.sent) == responder.ledger.requests == 3
    assert responder.ledger.repairs == 2


def test_repair_cap_and_cost_cap_refuse_before_transport(tmp_path):
    responder = _responder(tmp_path, authorization=_authorization(tmp_path, max_repair_requests=0))
    _refused(responder, _request(purpose="FAMILY_REPAIR"), "REPAIR_CAP_EXHAUSTED")
    bound = MA.request_upper_bound(400000, PROFILE.max_completion_tokens, _pricing())
    assert bound == Decimal("0.832")
    priced = tmp_path / "cost"
    priced.mkdir()
    unknown = FakeTransport([G.ProviderReply(content="{}", served_model=MODEL, usage={})])
    responder = _responder(priced, authorization=_authorization(priced, max_cost_usd="1.6"), transport=unknown)
    responder.respond(_request(1))
    _refused(responder, _request(2), "COST_CAP_EXHAUSTED")
    assert responder.ledger.exposure <= Decimal("1.6")


def test_transport_retry_is_reserved_counted_and_charged_in_full(tmp_path):
    transport = FakeTransport([G.TransportError("timeout"), None])
    responder = _responder(tmp_path, transport=transport)
    reply = responder.respond(_request())
    assert reply.served_model == MODEL and len(transport.sent) == 2
    assert responder.ledger.requests == 2 and responder.ledger.retries == 1
    first, second = responder.ledger.reservations.values()
    assert Decimal(first["charged"]) == responder.ledger.per_request_bound  # unknown usage: full charge
    assert Decimal(second["charged"]) == MA.request_upper_bound(1000, 100, _pricing())
    no_retry = tmp_path / "noretry"
    no_retry.mkdir()
    transport = FakeTransport([G.TransportError("timeout")])
    responder = _responder(no_retry, authorization=_authorization(no_retry, max_transport_retries=0),
                           transport=transport)
    with pytest.raises(G.ProviderRefusal) as exc:
        responder.respond(_request())
    assert exc.value.code == "TRANSPORT_FAILED" and len(transport.sent) == 1
    assert responder.ledger.exposure == responder.ledger.per_request_bound


def test_unknown_usage_charges_reservation_and_overrun_halts_the_run(tmp_path):
    transport = FakeTransport([G.ProviderReply(content="{}", served_model=MODEL, usage={}),
                               G.ProviderReply(content="{}", served_model=MODEL,
                                               usage={"prompt_tokens": 400000, "completion_tokens": 900000})])
    responder = _responder(tmp_path, transport=transport)
    responder.respond(_request(1))
    assert responder.ledger.exposure == responder.ledger.per_request_bound
    responder.respond(_request(2))
    assert responder.ledger.exposure == 2 * responder.ledger.per_request_bound  # never above reserved
    _refused(responder, _request(3), "USAGE_EXCEEDED_RESERVATION")


def test_ledger_persists_reservations_cancellation_and_restart(tmp_path):
    auth = _authorization(tmp_path, max_external_requests=3)
    bound = Decimal("0.5")
    ledger = MA.BudgetLedger(tmp_path / "l.jsonl", auth, bound)
    ledger.reserve(reservation_id="r1", purpose="PRIMARY", transport_attempt=0, scan_key="s1")
    ledger.settle("r1", {"input_tokens": 10, "output_tokens": 10}, _pricing())
    ledger.reserve(reservation_id="r2", purpose="PRIMARY", transport_attempt=0, scan_key="s2")
    ledger.cancel("r2", "proven never sent")
    ledger.reserve(reservation_id="r3", purpose="REPAIR", transport_attempt=0, scan_key="s3")
    # crash here: r3 reserved, never settled
    reopened = MA.BudgetLedger(tmp_path / "l.jsonl", auth, bound)
    assert reopened.orphans == ["r3"] and reopened.reservations["r3"]["state"] == "ORPHANED_CHARGED"
    assert reopened.requests == 2 and reopened.exposure == Decimal(ledger.reservations["r1"]["charged"]) + bound
    with pytest.raises(C.ContractError) as exc:
        reopened.reserve(reservation_id="r1", purpose="PRIMARY", transport_attempt=0, scan_key="s1")
    assert exc.value.code == "DUPLICATE_RESERVATION"
    reopened.reserve(reservation_id="r4", purpose="PRIMARY", transport_attempt=0, scan_key="s4")
    with pytest.raises(C.ContractError) as exc:
        reopened.reserve(reservation_id="r5", purpose="PRIMARY", transport_attempt=0, scan_key="s5")
    assert exc.value.code == "REQUEST_CAP_EXHAUSTED"
    with open(tmp_path / "l.jsonl", "a") as handle:
        handle.write(json.dumps({"kind": "settle", "reservation_id": "ghost", "charged_usd": "0"}) + "\n")
    with pytest.raises(C.ContractError) as exc:
        MA.BudgetLedger(tmp_path / "l.jsonl", auth, bound)
    assert exc.value.code == "LEDGER_STATE_INVALID"


def test_recorder_failure_stops_the_next_request_before_transport(tmp_path):
    from ai_layer import ai_api_adapter
    rec = REC.Recorder(tmp_path / "r", run_digest="a" * 64, trajectory_id="T", classification="CONSTRUCTED")
    rec.failed = "OSError: No space left on device"
    responder = _responder(tmp_path)
    gateway = G.BrainGateway(responder, trajectory_id="T", clock=P.DecisionClock(NOW), recorder=rec)
    with gateway.installed():
        client = ai_api_adapter._openai.OpenAI(api_key=G._SENTINEL_KEY, timeout=25.0, max_retries=0)
        with pytest.raises(G.ProviderRefusal) as exc:
            client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "{}"}])
    assert exc.value.code == "RECORDER_FAILED" and responder.transport.sent == []


# -- whole trajectory through production, both lanes ---------------------------

@pytest.fixture(scope="module")
def corpus_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus")
    return K.build_constructed_corpus(root, session_id=CP.SESSION, contract_id=CP.CONTRACT,
                                      market_date="2026-08-19", tape=W._tape(W._HEALTHY),
                                      warmup_end="2026-08-19T15:30:00+00:00",
                                      notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                      sealed_at="2026-10-17T00:00:00Z")


class ScriptTransport(FakeTransport):
    """Answers like the Mode B script; one reply carries a foreign served model."""

    def __init__(self, foreign_at):
        super().__init__()
        self.script, _ = CP._script()
        self.foreign_at = foreign_at

    def send(self, payload):
        self.sent.append(payload)
        users = [m["content"] for m in payload["messages"] if m["role"] == "user"]
        body = json.loads(users[0])
        reply = self.script({"payload": body, "scan": len(self.sent)})
        served = "gpt-4o-2024-08-06" if len(self.sent) == self.foreign_at else MODEL + "-2026-09-22"
        return G.ProviderReply(content=json.dumps(reply, sort_keys=True), served_model=served,
                               usage={"prompt_tokens": 30000, "completion_tokens": 700},
                               request_id=f"fake-req-{len(self.sent)}", response_id=f"fake-resp-{len(self.sent)}")


@pytest.mark.parametrize("ecu", [False, True])
def test_fake_provider_whole_trajectory_records_and_counts_every_attempt(corpus_path, tmp_path, ecu):
    transport = ScriptTransport(foreign_at=3)
    responder = _responder(tmp_path, transport=transport)
    summary = DR.run_offline(corpus_path=corpus_path, session_id=CP.SESSION, out_root=tmp_path / "run", ecu=ecu,
                             trajectory_id="S5-C", prewarm_until="2026-08-19T15:30:00Z",
                             ticks_until="2026-08-19T15:40:00Z", responder=responder)
    calls = REC.read_calls(summary["evidence_root"])
    assert calls and len(calls) == len(transport.sent) == responder.ledger.requests
    assert all(c["evaluation_origin"] == "MOCK" and not c["request_attempted"] for c in calls)
    assert len({c["budget_reservation_id"] for c in calls}) == len(calls)
    assert set(responder.ledger.reservations) == {c["budget_reservation_id"] for c in calls}
    assert all(p["max_completion_tokens"] == PROFILE.max_completion_tokens and p["model"] == MODEL
               for p in transport.sent)
    # The bytes sent are exactly production's transported request.
    first = calls[0]
    sent_user = [m["content"] for m in transport.sent[0]["messages"] if m["role"] == "user"][0]
    assert C.sha256_hex(sent_user.encode()) == first["input_ref"]["sha256"]
    served = [c["served_model"] for c in calls]
    assert served[0].startswith(MODEL) and served[2] is None
    assert calls[2]["fallback_reason"].startswith("provider_model_mismatch")
    assert all(c["usage"] == {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
               for c in calls)
    assert responder.ledger.exposure == len(calls) * MA.request_upper_bound(30000, 700, _pricing())


# -- dry run ---------------------------------------------------------------------

def test_dry_run_prints_a_finite_plan_and_conservative_maximum_without_requests(tmp_path):
    disabled = json.loads((ROOT / "src/recognition_validation/examples/model_authorization_disabled.json")
                          .read_text())
    plan = MA.dry_run_plan(tick_count=390, lanes=2, trajectory_count=0, authorization=disabled,
                           pricing=None, parameters=None)
    assert plan["external_requests_made"] == 0 and plan["planned_request_bound"] == 0
    assert plan["blockers"] == ["CURRENT_MODEL_CALLS_DISABLED", "PRICING_OR_OUTPUT_CAP_MISSING"]
    auth = _authorization(tmp_path, max_external_requests=10000, max_cost_usd="5000", trajectory_count=3)
    plan = MA.dry_run_plan(tick_count=390, lanes=2, trajectory_count=3, authorization=auth,
                           pricing=_pricing(), parameters=PROFILE)
    assert plan["structural_request_bound"] == 390 * 2 * 3 * 4 * 2
    assert plan["planned_request_bound"] == 10000
    assert Decimal(plan["max_cost_usd_bound"]) == min(Decimal("0.832") * 10000, Decimal("5000"))
    assert plan["blockers"] == [] and plan["network"] == "DENIED"

"""The one Brain request boundary every replay mode passes through.

Production builds its provider request inside `ai_brain.narrative_brain.
_call_llm`: system prompt with its conditional addenda, user payload, model
resolution, cache key, client request id, JSON mode. The gateway replaces
ONLY the provider client object (`ai_layer.ai_api_adapter._openai`) for the
duration of a run, so every byte of that request is built by production and
every response travels production's own served-model check, parse, schema,
repair and continuity path. Both the ECU and non-ECU lanes reach this seam.

A thin observer on `_call_llm` records which repair purpose a request served
and the call record production returned; it never substitutes an output.
Production stamps provider calls with the wall clock (narrative_brain.py
`time.time()` / `datetime.now`) and the stamp re-enters the next Brain input
(campaign_draw_context.brain_lineage); inside the seam those two names read
the decision clock, the only admissible clock offline.

Modes (out-of-band provenance, never inferred from `source='llm'`):
  * B / MOCK        a frozen script answers each causal request key;
  * A / HISTORICAL  exact one-to-one association with an archived record,
                    never nearest, future, foreign-contract or reused;
  * C / CURRENT     refuses before any transport unless a complete
                    authorization and budget admit the request (M05).
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from recognition_validation import compare as CMP
from recognition_validation import contracts as C

PURPOSES = {"primary": "PRIMARY", "json_repair": "REPAIR", "family_repair": "FAMILY_REPAIR",
            "invalidation_repair": "INVALIDATION_REPAIR"}
_SENTINEL_KEY = "offline-gateway-sentinel-no-network"


class ProviderRefusal(Exception):
    """The gateway declined to answer; production takes its fallback path."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class APITimeoutError(Exception):
    """Mirror of the provider SDK name production may catch."""


@dataclass
class ProviderReply:
    content: str
    served_model: str | None
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    request_id: str | None = None
    response_id: str | None = None


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, reply: ProviderReply):
        self.choices = [_Choice(reply.content)]
        self.model = reply.served_model or ""
        self.id = reply.response_id or ""
        self.usage = dict(reply.usage)


class _Raw:
    def __init__(self, reply: ProviderReply):
        self.headers = {"x-request-id": reply.request_id or ""}
        self._response = _Response(reply)

    def parse(self):
        return self._response


class _Completions:
    def __init__(self, gateway, client_kwargs):
        self._gateway, self._client_kwargs = gateway, client_kwargs
        self.with_raw_response = self

    def create(self, **kwargs):
        return _Raw(self._gateway._provider_request(kwargs, self._client_kwargs))


class _Chat:
    def __init__(self, gateway, client_kwargs):
        self.completions = _Completions(gateway, client_kwargs)


class _FakeClient:
    def __init__(self, gateway, **client_kwargs):
        self.chat = _Chat(gateway, client_kwargs)


class _FakeProviderModule:
    """Stands in for the SDK module object; constructs no network client."""

    APITimeoutError = APITimeoutError

    def __init__(self, gateway):
        self._gateway = gateway

    def OpenAI(self, **kwargs):  # noqa: N802 -- mirrors the SDK constructor name
        return _FakeClient(self._gateway, **kwargs)


class _ClockTime:
    """`time` for narrative_brain: `time()` is the decision clock, the rest is real."""

    def __init__(self, clock):
        self._clock = clock

    def time(self) -> float:
        return self._clock().timestamp()

    def __getattr__(self, name):
        return getattr(time, name)


def _clock_datetime(clock):
    class ClockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = clock()
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)
    return ClockDatetime


class ScriptedResponder:
    """Mode B. `script(request) -> dict | None`; None declines (MISSING)."""

    origin = "MOCK"

    def __init__(self, script, *, fixture_digest: str):
        self.script, self.fixture_digest = script, fixture_digest

    def respond(self, request: dict) -> ProviderReply:
        reply = self.script(request)
        if reply is None:
            raise ProviderRefusal("MOCK_SCRIPT_DECLINED", request["scan_key"])
        C.require(isinstance(reply, dict), "MOCK_REPLY_NOT_OBJECT", "/script")
        return ProviderReply(content=json.dumps(reply, sort_keys=True), served_model=request["requested_model"],
                             request_id=f"mock:{request['request_digest'][:16]}",
                             response_id=f"mock-response:{request['request_digest'][:16]}")


class HistoricalResponder:
    """Mode A. Exact association by (settled cutoff, same-cutoff ordinal, purpose)."""

    origin = "HISTORICAL"

    def __init__(self, records: list, *, contract_id: str):
        self.contract_id = contract_id
        self._records = {}
        for index, record in enumerate(records):
            key = (C.instant(record["settled_cutoff"]).isoformat(), int(record["cutoff_ordinal"]),
                   record["purpose"])
            C.require(record.get("contract_id") == contract_id, "HISTORICAL_FOREIGN_CONTRACT", f"/records/{index}")
            C.require(key not in self._records, "HISTORICAL_DUPLICATE_ASSOCIATION", f"/records/{index}")
            self._records[key] = dict(record)
        self.consumed: set = set()

    def respond(self, request: dict) -> ProviderReply:
        key = (C.instant(request["settled_cutoff"]).isoformat(), request["cutoff_ordinal"], request["purpose"])
        if key in self.consumed:
            raise ProviderRefusal("HISTORICAL_RECORD_ALREADY_CONSUMED", str(key))
        record = self._records.get(key)
        if record is None:
            raise ProviderRefusal("MISSING_COGNITION", str(key))
        self.consumed.add(key)
        content = record["raw_response"]
        mapping = None
        if record.get("input_text") is not None and request.get("user_contents"):
            mapping = CMP.rebinding(record["input_text"], request["user_contents"][0])
        semantic = mapping is not None or (record.get("semantic_input_digest") is not None and
                                           record["semantic_input_digest"] == request.get("semantic_input_digest"))
        rebound = {k: v for k, v in (mapping or {}).items() if k != v and k in content}
        if rebound:
            content = CMP._pattern(rebound).sub(lambda m: rebound[m.group(0)], content)
        request["historical"] = {
            "record_digest": C.digest(record),
            "input_matches_archive": record.get("input_digest") == request["input_digest"],
            "input_matches_semantic_v1": semantic,
            "archived_response_sha256": C.sha256_hex(record["raw_response"].encode("utf-8")),
            "rebound_identities": len(rebound),
            "historical_brain_fingerprint": record.get("brain_fingerprint"),
            "historical_unknown_reason": None if record.get("brain_fingerprint") else
            "archived record carries no per-call fingerprint",
        }
        return ProviderReply(content=content, served_model=record.get("served_model"),
                             request_id=record.get("provider_request_id"),
                             response_id=record.get("provider_response_id"))


class DisabledCurrentModel:
    """Mode C default: refuses before the transport boundary, always."""

    origin = "CURRENT_EXTERNAL"

    def respond(self, request: dict) -> ProviderReply:
        raise ProviderRefusal("CURRENT_MODEL_CALLS_DISABLED", "no owner model-call authorization")


class TransportError(Exception):
    """The external transport failed after it was reached (usage unknown)."""


class CurrentModelResponder:
    """Mode C under a validated authority; every attempt reserved before transport.

    `transport` exposes `endpoint_identity` and `send(payload) -> ProviderReply`.
    Only fake transports exist in this repository.
    """

    origin = "CURRENT_EXTERNAL"

    def __init__(self, authority, ledger, transport, *, trajectory_id: str):
        self.authority, self.ledger, self.transport = authority, ledger, transport
        self.trajectory_id = trajectory_id
        self.halted: str | None = None
        self.transport_calls = 0

    def _refuse(self, code: str, detail: str = ""):
        raise ProviderRefusal(code, detail)

    def respond(self, request: dict) -> ProviderReply:
        from recognition_validation import model_authority as MA
        if self.halted:
            self._refuse(self.halted)
        try:
            self.authority.admit()
        except C.ContractError as error:
            self._refuse(error.code, error.pointer)
        doc = self.authority.authorization
        if self.transport.endpoint_identity != doc["endpoint_identity"]:
            self._refuse("AUTHORIZATION_IDENTITY_MISMATCH", "/endpoint_identity")
        if request.get("requested_model") != doc["model"]:
            self._refuse("AUTHORIZATION_IDENTITY_MISMATCH", "/model")
        # An implicit SDK retry would be an uncounted request.
        if (request.get("client_parameters") or {}).get("max_retries") != 0:
            self._refuse("SDK_RETRY_UNCOUNTED", "/client_parameters/max_retries")
        messages = ([{"role": "system", "content": request.get("system_prompt") or ""}]
                    + [{"role": "user", "content": u} for u in request.get("user_contents") or []])
        bound = MA.input_token_bound(messages)
        if bound > doc["max_input_tokens_per_request"]:
            self._refuse("INPUT_TOKEN_CAP_EXCEEDED", f"{bound}>{doc['max_input_tokens_per_request']}")
        parameters = dict(request.get("parameters") or {})
        parameters["max_completion_tokens"] = self.authority.parameters.max_completion_tokens
        payload = {**parameters, "messages": messages}
        request["evaluation_parameter_digest"] = self.authority.parameters.digest
        last = None
        for transport_attempt in range(1 + doc["max_transport_retries"]):
            reservation_id = "rsv:" + C.digest([self.trajectory_id, request["scan_key"], request["purpose"],
                                                request["cutoff_ordinal"], request["attempt"],
                                                transport_attempt])[:32]
            try:
                self.ledger.reserve(reservation_id=reservation_id, purpose=request["purpose"],
                                    transport_attempt=transport_attempt, scan_key=request["scan_key"])
            except C.ContractError as error:
                self._refuse(error.code, error.detail)
            request["budget_reservation_id"] = reservation_id
            request["transport_reached"] = True
            self.transport_calls += 1
            try:
                reply = self.transport.send(copy.deepcopy(payload))
            except TransportError as error:
                self.ledger.settle(reservation_id, None, self.authority.pricing)
                last = error
                continue
            usage = reply.usage or {}
            settled = self.ledger.settle(
                reservation_id, {"input_tokens": usage.get("prompt_tokens"),
                                 "output_tokens": usage.get("completion_tokens")}, self.authority.pricing)
            if settled.get("exceeded"):
                self.halted = "USAGE_EXCEEDED_RESERVATION"
            request["usage_known"] = settled.get("usage_known")
            return reply
        self._refuse("TRANSPORT_FAILED", str(last))


class BrainGateway:
    def __init__(self, responder, *, trajectory_id: str, clock, recorder=None, fingerprints=None):
        self.responder, self.trajectory_id, self.clock = responder, trajectory_id, clock
        self.recorder = recorder
        self.fingerprints = fingerprints or {}
        self.requests: list = []
        self.calls: list = []
        self._pending = None
        self._cutoff_ordinals: dict = {}

    # -- seam installation -------------------------------------------------
    @contextlib.contextmanager
    def installed(self):
        from ai_brain import narrative_brain
        from ai_layer import ai_api_adapter
        saved = (ai_api_adapter._openai, ai_api_adapter._OPENAI_AVAILABLE, narrative_brain._call_llm,
                 os.environ.get("OPENAI_API_KEY"), narrative_brain.time, narrative_brain.datetime)
        original_call = narrative_brain._call_llm
        gateway = self

        def observed_call(brain_input, repair=None):
            gateway._pending = {"purpose": PURPOSES.get(narrative_brain._purpose_for(repair), "RETRY"),
                                "brain_input": brain_input, "request": None}
            try:
                out = original_call(brain_input, repair)
            finally:
                pending, gateway._pending = gateway._pending, None
            gateway._finish(pending, out)
            return out
        ai_api_adapter._openai = _FakeProviderModule(self)
        ai_api_adapter._OPENAI_AVAILABLE = True
        narrative_brain._call_llm = observed_call
        narrative_brain.time, narrative_brain.datetime = _ClockTime(self.clock), _clock_datetime(self.clock)
        os.environ["OPENAI_API_KEY"] = _SENTINEL_KEY
        try:
            yield self
        finally:
            ai_api_adapter._openai, ai_api_adapter._OPENAI_AVAILABLE, narrative_brain._call_llm = saved[:3]
            narrative_brain.time, narrative_brain.datetime = saved[4:]
            if saved[3] is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = saved[3]

    # -- the provider boundary ---------------------------------------------
    def _provider_request(self, kwargs: dict, client_kwargs: dict) -> ProviderReply:
        from ai_brain import narrative_brain
        C.require(client_kwargs.get("api_key") == _SENTINEL_KEY, "UNEXPECTED_PROVIDER_CREDENTIAL", "/api_key")
        messages = kwargs.get("messages") or []
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        users = [m["content"] for m in messages if m.get("role") == "user"]
        pending = self._pending or {"purpose": "RETRY", "brain_input": None}
        session_id, scan, attempt = narrative_brain._call_context()
        payload = json.loads(users[0]) if users else {}
        cutoff = str(payload.get("timestamp") or "")
        ordinal_key = (cutoff, pending["purpose"])
        ordinal = self._cutoff_ordinals.get(ordinal_key, 0)
        self._cutoff_ordinals[ordinal_key] = ordinal + 1
        request = {
            "trajectory_id": self.trajectory_id, "scan_key": f"{self.trajectory_id}/{cutoff}/{scan}",
            "scan": scan, "settled_cutoff": cutoff, "cutoff_ordinal": ordinal,
            "decision_time": self.clock().isoformat(), "purpose": pending["purpose"],
            "attempt": int(attempt or 1), "requested_model": kwargs.get("model"),
            "system_prompt": system, "user_contents": users, "payload": payload,
            "parameters": {k: v for k, v in kwargs.items() if k not in ("messages", "extra_headers")},
            "client_parameters": {k: v for k, v in client_kwargs.items() if k != "api_key"},
            "input_digest": C.sha256_hex(users[0].encode("utf-8")) if users else None,
            "semantic_input_digest": CMP.semantic_input_digest(users[0]) if users else None,
            "prompt_digest": C.sha256_hex(system.encode("utf-8")),
        }
        request["request_digest"] = C.digest({k: request[k] for k in
                                              ("scan_key", "purpose", "attempt", "input_digest", "prompt_digest")})
        if self._pending is not None:
            self._pending["request"] = request
        self.requests.append(request)
        if self.recorder is not None and self.recorder.failed:
            # Cognition without a durable record is UNPROVEN: stop before any transport.
            request["refusal"] = "RECORDER_FAILED"
            raise ProviderRefusal("RECORDER_FAILED", self.recorder.failed)
        try:
            reply = self.responder.respond(request)
        except ProviderRefusal as refusal:
            request["refusal"] = refusal.code
            raise
        request["reply"] = {"content": reply.content, "served_model": reply.served_model,
                            "request_id": reply.request_id, "response_id": reply.response_id,
                            "usage": dict(reply.usage)}
        return reply

    def _finish(self, pending: dict, out: dict) -> None:
        request = (pending or {}).get("request")
        record = {"purpose": (pending or {}).get("purpose"), "request": request,
                  "ok": bool((out or {}).get("ok")), "parsed": (out or {}).get("parsed"),
                  "fallback_reason": (out or {}).get("fallback_reason"),
                  "served_model": (out or {}).get("model"),
                  "provider_request_attempted": bool((out or {}).get("provider_request_attempted"))}
        self.calls.append(record)
        if self.recorder is not None:
            self.recorder.brain_call(self._brain_call_document(record))

    @staticmethod
    def _usage(origin, request, reply):
        if not reply:
            return None
        if origin != "CURRENT_EXTERNAL":
            return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
        if not request.get("usage_known"):
            return None
        usage = reply.get("usage") or {}
        return {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"],
                "cached_input_tokens": int(usage.get("cached_tokens") or 0)}

    def _brain_call_document(self, record: dict) -> dict:
        rec = self.recorder
        request = record["request"] or {}
        origin = getattr(self.responder, "origin", "MOCK")
        classification = rec.classification
        art = "CONSTRUCTED" if classification == "CONSTRUCTED" else "UNKNOWN"
        users = request.get("user_contents") or []
        input_ref = rec.artifact((users[0] if users else "").encode("utf-8"), kind="input", origin=art)
        prompt_ref = rec.artifact((request.get("system_prompt") or "").encode("utf-8"), kind="prompt", origin=art)
        reply = request.get("reply")
        raw_ref = rec.artifact(reply["content"].encode("utf-8"), kind="raw", origin=art) if reply else None
        parsed_ref = (rec.json_artifact(record["parsed"], kind="parsed", origin=art)
                      if record["parsed"] is not None else None)
        historical = request.get("historical") or {}
        status = ("COMPLETE" if reply and record["ok"] else
                  "REFUSED" if request.get("refusal") or not record["provider_request_attempted"] else "INCOMPLETE")
        evaluation_origin = origin
        if request.get("refusal") in ("MISSING_COGNITION", "MOCK_SCRIPT_DECLINED"):
            evaluation_origin = "MISSING"
        notes = f"Mode origin {origin}; recorded at the provider seam."
        if historical and not historical.get("input_matches_archive"):
            if historical.get("input_matches_semantic_v1"):
                notes += (" HISTORICAL_INPUT_SEMANTIC_V1_MATCH: archived and transported inputs differ only in"
                          f" process-random identities; {historical['rebound_identities']} rebound in the archived"
                          f" output (archived raw sha256 {historical['archived_response_sha256']}).")
            else:
                notes += " HISTORICAL_OUTPUT_ON_CURRENT_INPUTS: archived input differs from the transported input."
        return {
            "schema_version": "brain_call/v1",
            "document_id": f"{self.trajectory_id}:call:{len(self.calls) - 1}",
            "provenance": {"classification": classification, "author_role": "STAGE5_BRAIN_GATEWAY",
                           "source_refs": [], "notes": notes},
            "run_digest": rec.run_digest, "trajectory_id": self.trajectory_id,
            "scan_key": request.get("scan_key") or f"{self.trajectory_id}/unreached",
            "settled_cutoff": request.get("settled_cutoff") or self.clock().isoformat(),
            "decision_time": request.get("decision_time") or self.clock().isoformat(),
            "purpose": record["purpose"] or "RETRY", "attempt": request.get("attempt") or 1,
            "evaluation_origin": evaluation_origin, "input_ref": input_ref, "prompt_ref": prompt_ref,
            "raw_response_ref": raw_ref, "parsed_output_ref": parsed_ref,
            "post_guard_output_ref": parsed_ref if record["ok"] else None,
            "requested_model": request.get("requested_model"), "served_model": record["served_model"],
            "brain_fingerprint": self.fingerprints.get("brain", "UNKNOWN"),
            "retrieval_fingerprint": self.fingerprints.get("retrieval", "UNKNOWN"),
            "historical_brain_fingerprint": historical.get("historical_brain_fingerprint"),
            "historical_unknown_reason": historical.get("historical_unknown_reason"),
            "parameter_digest": C.digest(request.get("parameters") or {}),
            "provider_request_id": (reply or {}).get("request_id"),
            "provider_response_id": (reply or {}).get("response_id"),
            "started_at": request.get("decision_time") or self.clock().isoformat(),
            "completed_at": request.get("decision_time"),
            "request_attempted": bool(request.get("transport_reached")) and origin == "CURRENT_EXTERNAL",
            "usage": self._usage(origin, request, reply),
            "budget_reservation_id": request.get("budget_reservation_id"),
            "fallback_reason": record["fallback_reason"] or request.get("refusal"),
            "record_status": status, "request_ref": None,
        }

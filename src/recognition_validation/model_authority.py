"""Mode C: owner model-call authority, hard budgets and a counted transport.

Disabled by default and exercised here only with a fake transport. A future
external request needs ALL of: an OWNER_AUTHORIZED, sealed authorization
whose owner receipt, source SHA, Brain/retrieval fingerprints, corpus,
schedule, model, endpoint, parameter profile and pricing digest equal the
run's; a real-UTC time inside [issued_at, expires_at); a sealed USD price
table for that model; and remaining request/repair/retry/cost budget. No
CLI flag or environment variable can enable it, and no credential is stored.

Production's request (ai_brain/narrative_brain.py `_call_llm`) sets no output
token cap, so the worst-case cost of a request is unbounded. External mode
therefore also needs an evaluation-parameter profile that adds an explicit
`max_completion_tokens`; that profile is an evaluation contract with its own
digest, never a change to production generation parameters or fingerprints.

Every attempt -- primary, each repair purpose, each transport retry -- is
reserved at worst case in a durable ledger BEFORE the transport is reached,
settled once (unknown usage charges the full reservation), and a crash
between reserve and settle is charged in full on reopen.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from recognition_validation import contracts as C
from recognition_validation import ports as P

#: narrative_brain issues at most one primary plus the json/family/invalidation
#: repairs per scan (call sites at narrative_brain.py:1029/1046/1099/1148, no loop).
MAX_CALLS_PER_SCAN = 4
REPAIR_PURPOSES = frozenset({"REPAIR", "FAMILY_REPAIR", "INVALIDATION_REPAIR", "RETRY"})
#: Conservative per-message framing allowance on top of the byte bound.
MESSAGE_OVERHEAD_TOKENS = 16


def input_token_bound(messages: list) -> int:
    """Upper bound: a byte-level BPE token covers at least one UTF-8 byte."""
    return sum(len(str(m.get("content") or "").encode("utf-8")) + MESSAGE_OVERHEAD_TOKENS for m in messages)


def request_upper_bound(max_input_tokens: int, max_output_tokens: int, pricing: dict) -> Decimal:
    """(max_in * uncached_input_rate + max_out * output_rate) / rate_unit; no cache discount."""
    return ((Decimal(max_input_tokens) * Decimal(pricing["uncached_input_rate"])
             + Decimal(max_output_tokens) * Decimal(pricing["output_rate"]))
            / Decimal(pricing["rate_unit_tokens"]))


@dataclass(frozen=True)
class EvaluationParameters:
    """The only parameters an external evaluation adds to production's request."""

    max_completion_tokens: int

    def document(self) -> dict:
        return {"schema": "evaluation_parameters/v1", "max_completion_tokens": self.max_completion_tokens}

    @property
    def digest(self) -> str:
        return C.digest(self.document())


@dataclass(frozen=True)
class RunIdentity:
    """What the frozen run actually is; the authorization must name exactly this."""

    source_sha: str
    brain_fingerprint: str
    retrieval_fingerprint: str
    corpus_digest: str
    schedule_digest: str
    model: str
    endpoint_identity: str
    annotation_digests: tuple = ()


def _sealed(doc: dict, code: str, pointer: str) -> None:
    seal = doc.get("seal")
    C.require(bool(seal) and seal.get("sha256") == C.seal_digest(doc), code, pointer)


class ModelAuthority:
    """Validated authorization + pricing + parameter profile for one run."""

    def __init__(self, authorization: dict, *, pricing: dict | None, parameters: EvaluationParameters | None,
                 identity: RunIdentity, receipt_root=None, real_clock=P.real_utc_now):
        C.validate(authorization)
        self.authorization, self.pricing, self.parameters = authorization, pricing, parameters
        self.receipt_root = receipt_root
        self.identity, self.real_clock = identity, real_clock
        self.enabled = authorization["state"] == "OWNER_AUTHORIZED"

    def admit(self) -> None:
        """Every run-level precondition; raises the first unmet one."""
        doc = self.authorization
        C.require(self.enabled, "CURRENT_MODEL_CALLS_DISABLED", "/state")
        _sealed(doc, "AUTHORIZATION_SEAL_INVALID", "/seal")
        C.require(bool(doc["owner_receipt_ref"]) and self.receipt_root is not None, "OWNER_RECEIPT_MISSING",
                  "/owner_receipt_ref")
        C.verify_artifact(doc["owner_receipt_ref"], self.receipt_root, "/owner_receipt_ref")
        now = self.real_clock()
        C.require(isinstance(now, datetime) and now.tzinfo is not None, "TIMEZONE_REQUIRED", "/real_clock")
        C.require(C.instant(doc["issued_at"]) <= now, "AUTHORIZATION_NOT_YET_VALID", "/issued_at")
        C.require(now < C.instant(doc["expires_at"]), "AUTHORIZATION_EXPIRED", "/expires_at")
        ident = self.identity
        for field, value in (("source_sha", ident.source_sha), ("brain_fingerprint", ident.brain_fingerprint),
                             ("retrieval_fingerprint", ident.retrieval_fingerprint),
                             ("corpus_digest", ident.corpus_digest), ("schedule_digest", ident.schedule_digest),
                             ("model", ident.model), ("endpoint_identity", ident.endpoint_identity)):
            C.require(doc[field] == value, "AUTHORIZATION_IDENTITY_MISMATCH", "/" + field, f"{doc[field]!r}!={value!r}")
        C.require(sorted(doc["annotation_digests"]) == sorted(ident.annotation_digests),
                  "AUTHORIZATION_IDENTITY_MISMATCH", "/annotation_digests")
        C.require(self.pricing is not None and bool(doc["pricing_digest"]), "PRICING_MISSING", "/pricing_digest")
        C.validate(self.pricing)
        _sealed(self.pricing, "PRICING_SEAL_INVALID", "/pricing/seal")
        C.require(C.seal_digest(self.pricing) == doc["pricing_digest"], "PRICING_DIGEST_MISMATCH", "/pricing_digest")
        C.require(self.pricing["model"] == ident.model, "PRICING_MODEL_MISMATCH", "/pricing/model")
        C.require(bool(self.pricing["owner_pricing_approval_ref"]), "PRICING_UNAPPROVED",
                  "/pricing/owner_pricing_approval_ref")
        C.require(C.instant(self.pricing["effective_at"]) <= now, "PRICING_NOT_EFFECTIVE", "/pricing/effective_at")
        C.require(self.parameters is not None, "PRODUCTION_OUTPUT_CAP_ABSENT", "/parameter_digest",
                  "production sets no output token cap; an evaluation parameter profile is required")
        C.require(self.parameters.digest == doc["parameter_digest"], "PARAMETER_PROFILE_MISMATCH", "/parameter_digest")
        C.require(0 < self.parameters.max_completion_tokens <= doc["max_output_tokens_per_request"],
                  "OUTPUT_CAP_EXCEEDS_AUTHORIZATION", "/max_output_tokens_per_request")
        C.require(doc["max_input_tokens_per_request"] > 0, "INPUT_CAP_MISSING", "/max_input_tokens_per_request")

    @property
    def per_request_bound(self) -> Decimal:
        doc = self.authorization
        return request_upper_bound(doc["max_input_tokens_per_request"], self.parameters.max_completion_tokens,
                                   self.pricing)


class BudgetLedger:
    """Durable reservation ledger; append-only JSONL, fsynced per record."""

    def __init__(self, path, authorization: dict, per_request_bound: Decimal):
        self.path = Path(path)
        self.caps = {k: authorization[k] for k in ("max_external_requests", "max_repair_requests",
                                                   "max_transport_retries")}
        self.max_cost = Decimal(authorization["max_cost_usd"])
        self.per_request_bound = per_request_bound
        self.reservations: dict = {}
        self.orphans: list = []
        if self.path.exists():
            self._replay()

    # -- persistence -------------------------------------------------------
    def _append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _replay(self) -> None:
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            record = C.loads_strict(line, pointer=f"/{self.path.name}:{number}")
            rid = record["reservation_id"]
            if record["kind"] == "reserve":
                C.require(rid not in self.reservations, "DUPLICATE_RESERVATION", f"/{number}")
                self.reservations[rid] = dict(record, state="OPEN", charged=record["reserved_usd"])
            else:
                C.require(rid in self.reservations and self.reservations[rid]["state"] == "OPEN",
                          "LEDGER_STATE_INVALID", f"/{number}")
                state = {"settle": "SETTLE", "cancel": "CANCELLED"}.get(record["kind"])
                C.require(state is not None, "LEDGER_STATE_INVALID", f"/{number}")
                self.reservations[rid].update(state=state, charged=record["charged_usd"])
        # An attempt reserved but never settled may have reached the provider:
        # it stays charged at its full reservation.
        self.orphans = [rid for rid, r in self.reservations.items() if r["state"] == "OPEN"]
        for rid in self.orphans:
            self.reservations[rid]["state"] = "ORPHANED_CHARGED"

    # -- accounting --------------------------------------------------------
    def _count(self, predicate) -> int:
        return sum(1 for r in self.reservations.values() if r["state"] != "CANCELLED" and predicate(r))

    @property
    def requests(self) -> int:
        return self._count(lambda r: True)

    @property
    def repairs(self) -> int:
        return self._count(lambda r: r["purpose"] in REPAIR_PURPOSES)

    @property
    def retries(self) -> int:
        return self._count(lambda r: r["transport_attempt"] > 0)

    @property
    def exposure(self) -> Decimal:
        return sum((Decimal(r["charged"]) for r in self.reservations.values()), Decimal(0))

    def reserve(self, *, reservation_id: str, purpose: str, transport_attempt: int, scan_key: str) -> dict:
        C.require(reservation_id not in self.reservations, "DUPLICATE_RESERVATION", "/reservation_id")
        C.require(self.requests < self.caps["max_external_requests"], "REQUEST_CAP_EXHAUSTED",
                  "/max_external_requests")
        if purpose in REPAIR_PURPOSES:
            C.require(self.repairs < self.caps["max_repair_requests"], "REPAIR_CAP_EXHAUSTED", "/max_repair_requests")
        if transport_attempt > 0:
            C.require(self.retries < self.caps["max_transport_retries"], "RETRY_CAP_EXHAUSTED",
                      "/max_transport_retries")
        C.require(self.exposure + self.per_request_bound <= self.max_cost, "COST_CAP_EXHAUSTED", "/max_cost_usd",
                  f"{self.exposure}+{self.per_request_bound}>{self.max_cost}")
        record = {"kind": "reserve", "reservation_id": reservation_id, "purpose": purpose, "scan_key": scan_key,
                  "transport_attempt": transport_attempt, "reserved_usd": str(self.per_request_bound)}
        self._append(record)
        self.reservations[reservation_id] = dict(record, state="OPEN", charged=record["reserved_usd"])
        return self.reservations[reservation_id]

    def settle(self, reservation_id: str, usage: dict | None, pricing: dict) -> dict:
        reservation = self.reservations[reservation_id]
        C.require(reservation["state"] == "OPEN", "LEDGER_STATE_INVALID", "/reservation_id")
        reserved = Decimal(reservation["reserved_usd"])
        known = (isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int)
                 and isinstance(usage.get("output_tokens"), int))
        actual = request_upper_bound(usage["input_tokens"], usage["output_tokens"], pricing) if known else reserved
        exceeded = actual > reserved
        charged = reserved if (exceeded or not known) else actual
        self._append({"kind": "settle", "reservation_id": reservation_id, "charged_usd": str(charged),
                      "usage_known": known, "exceeded_reservation": exceeded})
        reservation.update(state="SETTLE", charged=str(charged), usage_known=known, exceeded=exceeded)
        return reservation

    def cancel(self, reservation_id: str, reason: str) -> None:
        """Only for an attempt proven never to have reached the transport."""
        reservation = self.reservations[reservation_id]
        C.require(reservation["state"] == "OPEN", "LEDGER_STATE_INVALID", "/reservation_id")
        self._append({"kind": "cancel", "reservation_id": reservation_id, "charged_usd": "0", "reason": reason})
        reservation.update(state="CANCELLED", charged="0")


def dry_run_plan(*, tick_count: int, lanes: int, trajectory_count: int, authorization: dict,
                 pricing: dict | None, parameters: EvaluationParameters | None) -> dict:
    """A complete finite future call plan with its conservative maximum; zero requests."""
    retries = authorization["max_transport_retries"]
    per_scan = MAX_CALLS_PER_SCAN * (1 + retries)
    structural = tick_count * lanes * trajectory_count * per_scan
    capped = min(structural, authorization["max_external_requests"])
    priced = pricing is not None and parameters is not None
    bound = (request_upper_bound(authorization["max_input_tokens_per_request"], parameters.max_completion_tokens,
                                 pricing) if priced else None)
    worst = (bound * capped) if priced else None
    blockers = []
    if authorization["state"] != "OWNER_AUTHORIZED":
        blockers.append("CURRENT_MODEL_CALLS_DISABLED")
    if not priced:
        blockers.append("PRICING_OR_OUTPUT_CAP_MISSING")
    return {
        "schema": "mode_c_dry_run/v1", "external_requests_made": 0, "network": "DENIED",
        "ticks_per_trajectory": tick_count, "lanes": lanes, "trajectory_count": trajectory_count,
        "max_calls_per_scan": MAX_CALLS_PER_SCAN, "max_transport_retries": retries,
        "structural_request_bound": structural, "request_cap": authorization["max_external_requests"],
        "planned_request_bound": capped,
        "per_request_formula": "(max_input_tokens * uncached_input_rate + max_output_tokens * output_rate)"
                               " / rate_unit_tokens; no cache discount",
        "per_request_bound_usd": None if bound is None else str(bound),
        "max_cost_formula": "min(ticks * lanes * trajectories * calls_per_scan * (1 + retries), request_cap)"
                            " * per_request_bound_usd, never above max_cost_usd",
        "max_cost_usd_bound": None if worst is None else str(min(worst, Decimal(authorization["max_cost_usd"]))),
        "authorized_max_cost_usd": authorization["max_cost_usd"],
        "blockers": blockers,
    }

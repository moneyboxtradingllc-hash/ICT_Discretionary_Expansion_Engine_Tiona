"""Current-Brain integrated evaluation: sealed plan, dry run, released runner.

PREPARED, DISABLED. Codex contract 2026-10-25/1 (PREPARE ONLY). This module
builds and verifies the sealed 34-primary evaluation plan, prices its
conservative worst case without any request, and contains the runner that a
later, separately sealed owner authorization could release. Nothing here can
reach a provider today:

  * the plan's authority is DISABLED and its pricing carries no owner
    approval, so `ModelAuthority.admit()` refuses before any transport or
    credential is touched (CURRENT_MODEL_CALLS_DISABLED / PRICING_UNAPPROVED);
  * each trajectory runs in a fresh allowlisted child (`child.py`), which reads
    a credential from its stdin only after admission, and in which every
    connection except the pinned provider host is refused;
  * one durable ledger, bound to the authorization seal, carries every
    primary, repair and error request of every lane and case; a halt or a
    restart never refills it.

Corpora: the Friday 2026-10-23 tape is REPOSITORY_RECORDED (committed fixture,
owner-archive provenance, not provider certification) and uses a sealed
CONTROLLED quote stream; W5, C2 and C4 are CONSTRUCTED. C2/C4 bars are the
pinned scenario shapes translated +12h into the production window (their
original 03:xx UTC stamps fall outside it, where `window_closed` would refuse
before any authority gate). Warmup is factual settled replay with no cognition.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from recognition_validation import contracts as C
from recognition_validation import corpus as K

PLAN_SCHEMA = "current_brain_eval_plan/v1"
MODEL = "gpt-6-luna"
LANES = (("ecu", True), ("non_ecu", False))
CONTRACT_ID = "CON.F.US.MNQ.Z26"
#: The Codex budget PROPOSAL (BUDGET_PROPOSAL_DISABLED.json), not an approval.
BUDGET = {"max_external_requests": 40, "max_primary_requests": 34, "max_repair_requests": 6,
          "max_transport_retries": 0, "max_cost_usd": "15.00", "max_completion_tokens": 8192}
FRIDAY_CUTOFFS = ("13:30", "14:00", "15:06", "15:30", "16:05", "16:14", "16:22", "16:24", "16:29", "16:45",
                  "17:15", "17:40")
#: Hard ceiling below the provider's long-context tier (>272K input tokens bills 2x / 1.5x).
LONG_CONTEXT_THRESHOLD = 272_000


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(root: Path, rel: str, value, origin: str) -> dict:
    data = (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")
    return K.write_artifact(root, rel, data, origin)


def _decisions_from_opens(tape: list, opens: list) -> list:
    """A settled 1m OPEN cutoff is decided when that candle settles, one minute later."""
    stamps = {datetime.fromisoformat(b["timestamp"]).astimezone(timezone.utc) for b in tape}
    out = []
    for value in opens:
        opened = datetime.fromisoformat(value).astimezone(timezone.utc)
        C.require(opened in stamps, "DECISION_BAR_MISSING", "/decisions", value)
        out.append(opened + timedelta(minutes=1))
    return out


def session_entry(*, session_id: str, tape: list, original: dict, releases: dict, warmup_end: str,
                  classification: str, notes: str, market_date: str) -> dict:
    entry = K.constructed_session_entry(session_id=session_id, contract_id=CONTRACT_ID, market_date=market_date,
                                        tape=tape, original=original, releases=releases, warmup_end=warmup_end,
                                        notes=notes)
    if classification == "REPOSITORY_RECORDED":
        entry.update(
            settlement={"status": "PROVEN", "policy_ref": "tests/fixtures/session_20261023_settled_tape.json",
                        "reason": "Committed settled 1m tape; every bar settles one minute after its open. "
                                  "Owner-archive provenance only, not provider certification."},
            history_track="FINAL_HISTORY_ONLY", partition="EVALUATION", eligibility="PARTIAL",
            fingerprint_unknown_reason="no recorded cognition is supplied to this evaluation",
            exclusion_reasons=["owner-archive tape provenance, not provider certification",
                               "no independent quote archive: a sealed CONTROLLED quote stream is used",
                               "empty memory counterfactual (no forged prior cognition)",
                               "no owner annotation: recognition reference truth UNPROVEN"])
    return entry


def build_corpus(root: Path, *, document_id: str, classification: str, sessions: list, sealed_at: str) -> dict:
    """sessions: [{session_id, tape, warmup_end, notes, market_date}]"""
    entries, refs = [], []
    for spec in sessions:
        sid, tape = spec["session_id"], spec["tape"]
        original = _write(root, f"tapes/{sid}.json", tape, classification)
        docs = K.release_documents_from_tape(tape, session_id=sid, contract_id=CONTRACT_ID,
                                             source_artifact=original, classification=classification)
        releases = _write(root, f"releases/{sid}.json", docs, classification)
        entries.append(session_entry(session_id=sid, tape=tape, original=original, releases=releases,
                                     warmup_end=spec["warmup_end"], classification=classification,
                                     notes=spec["notes"], market_date=spec["market_date"]))
        refs.append(original["path"])
    corpus = {"schema_version": "corpus/v1", "document_id": document_id,
              "provenance": {"classification": classification, "author_role": "EVALUATION_PREPARATION",
                             "source_refs": refs, "notes": "Current-Brain evaluation corpus; PREPARE ONLY."},
              "selection_state": "PROPOSED", "owner_decision_ref": None, "sessions": entries, "seal": None}
    corpus["seal"] = {"sha256": C.seal_digest(corpus), "sealed_at": sealed_at,
                      "sealer_ref": "EVALUATION-PREPARATION engineering seal (not an owner seal)"}
    C.validate(corpus)
    data = (json.dumps(corpus, sort_keys=True, indent=1) + "\n").encode("utf-8")
    (root / "corpus.json").write_bytes(data)
    return corpus


def build_schedule(corpus: dict, decisions: dict, *, document_id: str, classification: str, sealed_at: str,
                   source_refs: list) -> dict:
    """One schedule per corpus: every settled minute is PREWARM, sealed decisions are SCAN.

    Ticks stop at a session's last decision: nothing after the final scored
    cognition is replayed."""
    ticks = []
    for entry in corpus["sessions"]:
        sid = entry["session_id"]
        session_decisions = sorted(decisions[sid])
        release_doc = json.loads((Path(decisions["__root__"]) / entry["availability_events"]["path"]).read_text())
        ordinal = 0
        for release in release_doc:
            at = C.instant(release["available_at_utc"])
            if at > session_decisions[-1]:
                break
            ticks.append({"session_id": sid, "ordinal": ordinal, "decision_time_utc": _iso(at),
                          "kind": "SCAN" if at in session_decisions else "PREWARM",
                          "source_ref": release["document_id"]})
            ordinal += 1
        scans = [t for t in ticks if t["session_id"] == sid and t["kind"] == "SCAN"]
        C.require(len(scans) == len(session_decisions), "DECISION_NOT_SCHEDULED", f"/{sid}")
    schedule = {"schema_version": "schedule/v1", "document_id": document_id,
                "provenance": {"classification": classification, "author_role": "EVALUATION_PREPARATION",
                               "source_refs": source_refs,
                               "notes": "Sealed before any fresh response: PREWARM settled minutes, SCAN only at "
                                        "the sealed decisions; no warmup cognition."},
                "corpus_digest": C.seal_digest(corpus), "algorithm": "FIXED_MINUTE_GRID",
                "algorithm_version": "current-brain-eval/v1",
                "cognition_policy": "PRODUCTION_SCAN_ONCE_WITH_PLAN_WAKE_SEMANTICS", "ticks": ticks,
                "warmup_cognition": "NONE", "seal": None}
    schedule["seal"] = {"sha256": C.seal_digest(schedule), "sealed_at": sealed_at,
                        "sealer_ref": "EVALUATION-PREPARATION engineering seal (not an owner seal)"}
    C.validate(schedule)
    return schedule


def controlled_quotes(tape: list) -> list:
    """CONTROLLED: bid = settled close, ask = bid + 1 tick, captured when the candle settles."""
    out = []
    for bar in tape:
        settled = datetime.fromisoformat(bar["timestamp"]).astimezone(timezone.utc) + timedelta(minutes=1)
        close = float(bar["close"])
        out.append({"captured_at_utc": _iso(settled), "bid": close, "ask": close + 0.25, "last": close,
                    "contract_id": CONTRACT_ID, "origin": "CONTROLLED"})
    return out


def pricing_document(*, source_ref: dict, accessed_at: str) -> dict:
    """The worst case of every billed class the verified rate card lists, UNAPPROVED.

    Production sets no `service_tier`, so the project's configured tier is
    unknown: price every input token at the dearest short-context input class
    of the dearest tier (Fast 12h cache write 0.50/1M) and every output or
    reasoning token at Fast output (1.00/1M). No cache discount. The plan's
    input cap keeps every request below the long-context threshold."""
    doc = {"schema_version": "pricing/v1", "document_id": "GPT-6-LUNA-WORST-CASE-20261025",
           "provenance": {"classification": "REPOSITORY_RECORDED", "author_role": "EVALUATION_PREPARATION",
                          "source_refs": ["https://developers.openai.com/api/docs/pricing",
                                          "https://developers.openai.com/api/docs/models/gpt-6-luna",
                                          "https://developers.openai.com/api/docs/guides/reasoning"],
                          "notes": f"Public rate card read {accessed_at}; worst-case classes; NOT owner-approved."},
           "currency": "USD", "model": MODEL, "effective_at": accessed_at, "source_ref": source_ref,
           "rate_unit_tokens": 1000000, "uncached_input_rate": "0.50", "output_rate": "1.00",
           "cache_discount_assumed": False, "owner_pricing_approval_ref": None, "seal": None}
    doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": accessed_at,
                   "sealer_ref": "EVALUATION-PREPARATION engineering seal (pricing NOT approved)"}
    C.validate(doc)
    return doc


def input_cap(measured_max_bound: int) -> int:
    """Measured byte-bound plus 50% margin, rounded up to 1,000, below the long-context tier."""
    cap = int((Decimal(measured_max_bound) * Decimal("1.5") / 1000).to_integral_value(ROUND_CEILING)) * 1000
    C.require(cap < LONG_CONTEXT_THRESHOLD, "INPUT_CAP_ABOVE_LONG_CONTEXT", "/max_input_tokens_per_request",
              f"{cap}>={LONG_CONTEXT_THRESHOLD}")
    return cap


def cost_plan(*, input_cap_tokens: int, pricing: dict) -> dict:
    from recognition_validation import model_authority as MA
    bound = MA.request_upper_bound(input_cap_tokens, BUDGET["max_completion_tokens"], pricing)
    cap = Decimal(BUDGET["max_cost_usd"])
    affordable = int(cap // bound)
    return {"schema": "current_brain_eval_cost_plan/v1", "external_requests_made": 0,
            "per_request_upper_bound_usd": str(bound),
            "formula": "(max_input_tokens * 0.50 + 8192 * 1.00) / 1,000,000 USD; no cache discount",
            "max_input_tokens_per_request": input_cap_tokens,
            "max_completion_tokens": BUDGET["max_completion_tokens"],
            "request_cap": BUDGET["max_external_requests"],
            "requests_affordable_at_upper_bound": affordable,
            "binding_limit": "REQUEST_CAP" if affordable >= BUDGET["max_external_requests"] else "COST_CAP",
            "worst_case_total_usd": str(min(bound * BUDGET["max_external_requests"], cap)),
            "proposed_max_cost_usd": BUDGET["max_cost_usd"],
            "note": "A proposed ceiling and a conservative bound, not a cost estimate or an approval."}


def seal(doc: dict, *, sealed_at: str, sealer: str) -> dict:
    doc = copy.deepcopy(doc)
    doc["seal"] = None
    doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": sealed_at, "sealer_ref": sealer}
    return doc


def load_plan(path) -> dict:
    """Verify the sealed plan and every artifact it binds; return it with resolved roots."""
    path = Path(path)
    plan = C.loads_strict(path.read_text(encoding="utf-8"), pointer="/plan")
    C.require(plan.get("schema") == PLAN_SCHEMA, "PLAN_SCHEMA", "/schema")
    C.require(bool(plan.get("seal")) and plan["seal"]["sha256"] == C.seal_digest(plan), "PLAN_SEAL_INVALID", "/seal")
    root = path.parent
    for ref in plan["artifacts"].values():
        C.verify_artifact(ref, root, "/artifacts")
    trajectories = plan["trajectories"]
    C.require(sum(t["primary_decisions"] for t in trajectories) == BUDGET["max_primary_requests"],
              "PLAN_PRIMARY_COUNT", "/trajectories")
    ids = [t["trajectory_id"] for t in trajectories]
    C.require(len(ids) == len(set(ids)), "PLAN_TRAJECTORY_DUPLICATE", "/trajectories")
    for lane, _ in LANES:
        C.require(sum(t["primary_decisions"] for t in trajectories if t["lane"] == lane) * 2
                  == BUDGET["max_primary_requests"], "PLAN_LANE_IMBALANCE", "/trajectories/" + lane)
    C.require(plan["authority"] == "DISABLED" and plan["owner_approval"] is None, "PLAN_AUTHORITY_NOT_DISABLED",
              "/authority")
    plan["_root"] = str(root)
    return plan


def authorization_template(plan: dict, *, sealed_at: str) -> dict:
    """The DISABLED shape Codex/owner would complete; holds no budget and no receipt."""
    doc = {"schema_version": "model_authorization/v1", "document_id": "CURRENT-BRAIN-EVAL-AUTHORIZATION-DISABLED",
           "provenance": {"classification": "REPOSITORY_RECORDED", "author_role": "EVALUATION_PREPARATION",
                          "source_refs": ["docs/recognition_validation/current_brain_eval/plan.json"],
                          "notes": "DISABLED template. No owner receipt, pricing approval or budget. Codex records "
                                   "the owner's capped consent separately; this file grants nothing."},
           "state": "DISABLED", "owner_receipt_ref": None, "source_sha": plan["production_source_sha"],
           "brain_fingerprint": plan["brain_fingerprint"], "retrieval_fingerprint": plan["retrieval_fingerprint"],
           "model": None, "parameter_digest": plan["parameter_digest"], "endpoint_identity": None,
           "corpus_digest": plan["corpus_set_digest"], "annotation_digests": [], "scoring_plan_digest": None,
           "schedule_digest": plan["schedule_set_digest"], "trajectory_count": 0,
           "issued_at": "2030-01-01T00:00:00Z", "expires_at": "2030-01-02T00:00:00Z",
           "max_external_requests": 0, "max_input_tokens_per_request": 0, "max_output_tokens_per_request": 0,
           "max_repair_requests": 0, "max_transport_retries": 0, "max_cost_usd": "0", "pricing_digest": None,
           "stage4_owner_acceptance_ref": None, "seal": None}
    doc["seal"] = {"sha256": C.seal_digest(doc), "sealed_at": sealed_at,
                   "sealer_ref": "EVALUATION-PREPARATION (DISABLED template)"}
    C.validate(doc)
    return doc


def run_identity(plan: dict, source_identity: dict):
    from recognition_validation import model_authority as MA
    from recognition_validation import provider_transport as PT
    return MA.RunIdentity(source_sha=source_identity["source_sha"],
                          brain_fingerprint=source_identity["brain_fingerprint"],
                          retrieval_fingerprint=source_identity["retrieval_fingerprint"],
                          corpus_digest=plan["corpus_set_digest"], schedule_digest=plan["schedule_set_digest"],
                          model=MODEL, endpoint_identity=PT.ENDPOINT_IDENTITY)


def admit_release(plan: dict, authorization: dict, pricing: dict, *, receipt_root, real_clock=None):
    """Every run-level gate, BEFORE a credential or transport exists. Raises the first unmet one."""
    from recognition_validation import model_authority as MA
    from recognition_validation import ports as P
    identity = run_identity(plan, C.source_identity())
    C.require(identity.brain_fingerprint == plan["brain_fingerprint"]
              and identity.retrieval_fingerprint == plan["retrieval_fingerprint"], "RUN_SOURCE_MISMATCH",
              "/fingerprints")
    parameters = MA.EvaluationParameters(BUDGET["max_completion_tokens"])
    C.require(parameters.digest == plan["parameter_digest"], "PARAMETER_PROFILE_MISMATCH", "/parameter_digest")
    authority = MA.ModelAuthority(authorization, pricing=pricing, parameters=parameters, identity=identity,
                                  receipt_root=receipt_root, real_clock=real_clock or P.real_utc_now)
    authority.admit()
    doc = authority.authorization
    for key in ("max_external_requests", "max_repair_requests", "max_transport_retries"):
        C.require(doc[key] <= BUDGET[key], "AUTHORIZATION_EXCEEDS_PLAN", "/" + key)
    C.require(Decimal(doc["max_cost_usd"]) <= Decimal(BUDGET["max_cost_usd"]), "AUTHORIZATION_EXCEEDS_PLAN",
              "/max_cost_usd")
    C.require(doc["max_input_tokens_per_request"] <= plan["max_input_tokens_per_request"],
              "AUTHORIZATION_EXCEEDS_PLAN", "/max_input_tokens_per_request")
    C.require(doc["trajectory_count"] == len(plan["trajectories"]), "AUTHORIZATION_IDENTITY_MISMATCH",
              "/trajectory_count")
    return authority


def run_released(plan_path, authorization_path, pricing_path, *, receipt_root, ledger_path, out_root,
                 credential_reader, run_child=None) -> dict:
    """The released run: admission first, then one fresh child per trajectory, one shared ledger.

    `credential_reader` is called only after admission and its value is passed
    to each child on stdin; it is never written to disk, environment or log."""
    from recognition_validation import child as CH
    plan = load_plan(plan_path)
    authorization = C.loads_strict(Path(authorization_path).read_text(encoding="utf-8"), pointer="/authorization")
    pricing = C.loads_strict(Path(pricing_path).read_text(encoding="utf-8"), pointer="/pricing")
    admit_release(plan, authorization, pricing, receipt_root=receipt_root)
    secret = credential_reader()
    C.require(isinstance(secret, str) and bool(secret), "CREDENTIAL_MISSING", "/credential")
    out_root = Path(out_root)
    results = []
    run_child = run_child or CH.run_in_child
    for trajectory in plan["trajectories"]:
        request = trajectory_request(plan, trajectory, authorization_path=authorization_path,
                                     pricing_path=pricing_path, receipt_root=receipt_root, ledger_path=ledger_path)
        status = run_child(request, out_root=out_root / trajectory["trajectory_id"], stdin_secret=secret)
        results.append({"trajectory_id": trajectory["trajectory_id"], "state": status["state"],
                        "exit_code": status["exit_code"], "complete": status["complete"]})
        if not status["complete"]:
            break   # a halted or failed trajectory ends the paid run; nothing is retried
    return {"schema": "current_brain_eval_run_summary/v1", "trajectories": results}


def trajectory_request(plan: dict, trajectory: dict, *, authorization_path, pricing_path, receipt_root,
                       ledger_path) -> dict:
    from recognition_validation import child as CH
    root = Path(plan["_root"])
    schedule = C.loads_strict((root / plan["artifacts"][trajectory["schedule"]]["path"]).read_text(),
                              pointer="/schedule")
    ticks = [{"ordinal": t["ordinal"], "decision_time": t["decision_time_utc"], "kind": t["kind"]}
             for t in schedule["ticks"] if t["session_id"] == trajectory["session_id"]]
    quotes = None
    if trajectory["quote_policy"] == "CONTROLLED":
        quotes = C.loads_strict((root / plan["artifacts"][trajectory["controlled_quotes"]]["path"]).read_text(),
                                pointer="/controlled_quotes")
    identity = C.source_identity()
    plan_seal = (plan.get("seal") or {}).get("sha256")
    return {"schema": CH.REQUEST_SCHEMA, "mode": "C",
            "corpus_path": str((root / plan["artifacts"][trajectory["corpus"]]["path"]).resolve()),
            "session_id": trajectory["session_id"], "trajectory_id": trajectory["trajectory_id"],
            "ecu": trajectory["ecu"], "contract_id": CONTRACT_ID, "ticks": ticks,
            "quote_policy": trajectory["quote_policy"], "controlled_quotes": quotes, "memory_policy": "EMPTY",
            "fingerprints": {"brain": plan["brain_fingerprint"], "retrieval": plan["retrieval_fingerprint"]},
            "expected_source_identity": identity,
            "run_document": {"schema": "current_brain_eval_trajectory/v1", "plan_seal": plan_seal,
                             "trajectory": trajectory, "source_identity": identity, "venue_lane": "DISARMED"},
            "responder": {"kind": "CURRENT_EXTERNAL", "plan_seal": plan_seal,
                          "plan_path": str((root / "plan.json").resolve()), "client_timeout_seconds": 120.0,
                          "authorization_path": str(Path(authorization_path).resolve()),
                          "pricing_path": str(Path(pricing_path).resolve()),
                          "receipt_root": str(Path(receipt_root).resolve()),
                          "ledger_path": str(Path(ledger_path).resolve()),
                          "corpus_set_digest": plan["corpus_set_digest"],
                          "schedule_set_digest": plan["schedule_set_digest"],
                          "max_input_tokens_per_request": plan.get("max_input_tokens_per_request"),
                          "trajectory_count": len(plan["trajectories"])}}

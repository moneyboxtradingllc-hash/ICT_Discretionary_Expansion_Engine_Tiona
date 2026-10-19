"""Drive one trajectory through the ACTUAL production graph, disarmed.

    LocalCandlePort -> ProductionLoop.scan_once() (injected decision clock)
      -> ProductionScanCycle.scan -> cognition through BrainGateway
      -> participation_authority_bound -> CandidateProducer.produce
      -> conditional plan capture / quote wake -> arm switch (OFF)

Only the edges are doubles: candles and quotes come from availability-
controlled local ports, the venue is a read-only synthetic account whose
every write raises, and the Brain answers at the provider boundary. Every
offered tick yields exactly one recorded event after the actual action. A
declared PREWARM tick advances the real producers with `_scan_once(
invoke_brain=False)` and is never presented as historical Brain cadence.

The trajectory owns a fresh cycle, producer, custody and scratch stores for
its whole session; runs require an isolated runtime root (see `isolation`).
"""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from recognition_validation import contracts as C
from recognition_validation import ports as P

RUNTIME_ROOTS = ("AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "OCCURRENCE_LEDGER_DIR", "REPLAY_SESSIONS_DIR",
                 "PERFORMANCE_TABLES_DIR", "HTF_MEMORY_DIR", "GLOBAL_MEMORY_DIR")
TICK_KINDS = ("PREWARM", "SCAN")


@contextlib.contextmanager
def isolation(root, *, ecu: bool):
    """Point every runtime store inside `root`, enable cognition only through
    the gateway, and refuse arming/paper orders for the duration."""
    root = Path(root).resolve()
    saved = {key: os.environ.get(key) for key in RUNTIME_ROOTS + (
        "AI_BRAIN_ENABLED", "AI_BRAIN_LLM", "BRAIN_ECU_MODE", "EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS",
        "TWO_BRAIN_MODE")}
    cwd = os.getcwd()
    try:
        for key in RUNTIME_ROOTS:
            path = root / "runtime" / key.lower()
            path.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(path)
        os.environ.update(AI_BRAIN_ENABLED="true", AI_BRAIN_LLM="true", BRAIN_ECU_MODE="true" if ecu else "false",
                          EXECUTION_ENABLED="false", ALLOW_PAPER_ORDERS="false", TWO_BRAIN_MODE="off")
        os.chdir(root)
        yield root
    finally:
        os.chdir(cwd)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass
class Tick:
    ordinal: int
    decision_time: datetime
    kind: str = "SCAN"


def minute_schedule(stream, *, prewarm_until: datetime | None = None) -> list[Tick]:
    """Declared counterfactual schedule: one tick per settled release minute."""
    ticks = []
    for ordinal, release in enumerate(stream.releases):
        if release.supersedes is not None:
            continue
        at = release.available_at
        kind = "PREWARM" if prewarm_until is not None and at <= prewarm_until else "SCAN"
        ticks.append(Tick(ordinal=len(ticks), decision_time=at, kind=kind))
    return ticks


@dataclass
class OfflineOrganism:
    loop: object
    cycle: object
    venue: P.RefusingVenueSession
    mission: object
    clock: P.DecisionClock
    contract: object
    last_scan: dict = field(default_factory=dict)


def build_organism(*, stream, clock: P.DecisionClock, store_dir, session_id: str, contract_id: str,
                   session_date: str, issued_at: str, account_fingerprint: str = "acct:offline-replay") -> OfflineOrganism:
    """The real ProductionLoop, disarmed, around offline edges."""
    from broker import topstepx_production_loop as PL
    from broker import topstepx_session_authorization as SA
    from broker.luna_candidate_producer import CandidateProducer
    from broker.topstepx_production_session import ProductionSession
    from broker.topstepx_quote_provider import LiveQuoteProvider
    from live_scan.production_scan_cycle import ProductionScanCycle
    contract = P.synthetic_contract(contract_id)
    venue = P.RefusingVenueSession()
    runtime = P.OfflineRuntime(venue.market_hub, contract)
    quotes = LiveQuoteProvider(venue.market_hub, contract, clock=clock)
    production_session = ProductionSession(
        session=venue, account_fingerprint=account_fingerprint, contract=contract, mission_id="OFFLINE",
        store_dir=str(store_dir), runtime=runtime, quote_provider=quotes, clock=clock, fill_deadline_seconds=0.2)
    authorization = P.synthetic_authorization(store_dir, session_id=session_id, contract_id=contract_id,
                                              session_date=session_date, issued_at=issued_at,
                                              account_fingerprint=account_fingerprint)
    mission = SA.ProductionSessionMission(authorization=authorization, store_dir=str(store_dir))
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=contract_id, session_id=session_id, quote_provider=quotes)
    organism = OfflineOrganism(loop=None, cycle=cycle, venue=venue, mission=mission, clock=clock, contract=contract)
    original_scan = cycle.scan

    def observed_scan(*args, **kwargs):
        result = original_scan(*args, **kwargs)
        organism.last_scan = result
        return result
    cycle.scan = observed_scan
    organism.loop = PL.ProductionLoop(
        production_session=production_session, session_mission=mission,
        producer=CandidateProducer(account_fingerprint=account_fingerprint, contract=contract),
        candles=P.LocalCandlePort(stream, clock), runtime=runtime, account_id=venue.account.id, armed=False,
        scan_cycle=cycle, clock=clock, in_window=lambda: P.production_window_open(clock.now()))
    return organism


def constructed_quote(organism, close: float) -> None:
    """A CONSTRUCTED sided quote at the latest settled close (mechanics only)."""
    tick = organism.contract.tick_size
    organism.venue.market_hub.emit("GatewayQuote", [organism.contract.id, {"bestBid": close, "bestAsk": close + tick}])


def _scope_fields(snapshot):
    from market_data.campaign_scope import read_current_campaign_scope
    scope = read_current_campaign_scope(snapshot or {}) or {}
    campaign = scope.get("campaign") or {}
    return campaign.get("campaign_id"), (campaign.get("scope_proof") or {}).get("proof_id"), scope.get("state")


def _formation_id(snapshot):
    from market_data.reversal_formation import current_block
    block = current_block(snapshot or {}, "bearish") or current_block(snapshot or {}, "bullish") or {}
    return (block.get("formation_authority") or {}).get("occurrence_id")


_BOUNDARY = {"NO_CANDLES": "INGEST", "BRAIN_DEGRADED": "BRAIN", "BRAIN_SLEEP_HOLD": "BRAIN",
             "NO_CANDIDATE": "CANDIDATE", "RISK_REJECTED": "CANDIDATE", "QUALIFIED_CANDIDATE_OBSERVED": "MISSION",
             "CONDITIONAL_PLAN_PUBLISHED": "PLAN_CAPTURE", "TRADING_COGNITION_OFF": "MISSION",
             "WINDOW_CLOSED": "SCAN"}


def run_trajectory(*, organism: OfflineOrganism, stream, ticks, gateway, recorder, quote_closes: bool = True,
                   quote_port=None, network_guard: P.NetworkGuard | None = None) -> dict:
    """Offer every tick; record one event per tick after the action."""
    from market_data.campaign_draw_truth import scan_participation_authority
    guard = network_guard or P.NetworkGuard()
    summary = {"ticks": 0, "events": 0, "primary_calls": 0, "repair_calls": 0, "infrastructure_error": None}
    lineage = f"process:{os.getpid()}:{id(organism.cycle):x}"
    with guard.deny(), gateway.installed():
        for tick in ticks:
            C.require(tick.kind in TICK_KINDS, "TICK_KIND_UNKNOWN", f"/ticks/{tick.ordinal}")
            organism.clock.set(tick.decision_time)
            visible = stream.candles_at(tick.decision_time)
            if quote_closes and visible:
                constructed_quote(organism, visible[-1]["close"])
            if quote_port is not None:
                quote = quote_port.capture()
                if not isinstance(quote, P.MissingQuote):
                    organism.venue.market_hub.emit("GatewayQuote", [organism.contract.id,
                        {"bestBid": quote.best_bid, "bestAsk": quote.best_ask}])
                    # The event was received historically, not afresh on every scan.
                    # Preserve the age used by the actual production price checks.
                    organism.loop.ps.quote_provider._last_at = quote.captured_at
            calls_before = len(gateway.calls)
            organism.last_scan = {}
            if tick.kind == "PREWARM":
                outcome = organism.loop._scan_once(observed_at=tick.decision_time, invoke_brain=False)
            else:
                outcome = organism.loop.scan_once()
            new_calls = gateway.calls[calls_before:]
            primary = sum(1 for call in new_calls if call["purpose"] == "PRIMARY")
            summary["primary_calls"] += primary
            summary["repair_calls"] += len(new_calls) - primary
            snapshot = (organism.last_scan or {}).get("snapshot") or {}
            scope_id, proof_id, scope_state = _scope_fields(snapshot)
            draw = scan_participation_authority(organism.last_scan) if organism.last_scan else None
            candidate = organism.loop.active_candidate
            plan = organism.loop.active_conditional_plan
            cutoff = visible[-1]["timestamp"] if visible else tick.decision_time.isoformat()
            status = (outcome or {}).get("outcome") or "UNKNOWN"
            missing = []
            if not visible:
                missing.append("no_release_available_by_decision_time")
            if tick.kind == "PREWARM":
                missing.append("declared_prewarm_no_cognition")
            if not quote_closes and quote_port is None:
                missing.append("independent_quote_unavailable")
            try:
                recorder.event(
                    scan_key=f"{recorder.trajectory_id}/{cutoff}/{tick.ordinal}",
                    settled_cutoff=cutoff, observed_at=tick.decision_time.isoformat(),
                    event_kind=f"{tick.kind}:{status}", source_event_refs=[],
                    history_revision=int(organism.cycle._history.revision),
                    derived_revision=int(((snapshot.get("derived_state") or {}).get("derived_revision"))
                                         or organism.cycle._history.revision),
                    process_lineage_id=lineage, scope_id=scope_id, scope_proof_id=proof_id,
                    draw_record_id=(draw or {}).get("record_id") if isinstance(draw, dict) else None,
                    formation_id=_formation_id(snapshot),
                    tool_occurrence_id=(candidate.extras.get("selected_tool_occurrence_id")
                                        if candidate is not None else None),
                    candidate_id=getattr(candidate, "candidate_id", None),
                    plan_id=(plan or {}).get("plan_id") if isinstance(plan, dict) else None,
                    boundary=_BOUNDARY.get(status, "SCAN"), outcome=status,
                    first_refusal_code=(outcome or {}).get("reason") if status != "QUALIFIED_CANDIDATE_OBSERVED" else None,
                    primary_call_count=primary, repair_call_count=len(new_calls) - primary,
                    evidence_refs=[], missing_evidence=missing + ([f"scope:{scope_state}"] if scope_state else []))
            except Exception as exc:  # noqa: BLE001 -- a recording failure aborts certification
                summary["infrastructure_error"] = f"{type(exc).__name__}: {exc}"
                break
            summary["ticks"] += 1
            summary["events"] += 1
    summary["network_attempts"] = list(guard.attempts)
    summary["venue_writes"] = list(organism.venue.writes)
    summary["mission_tokens"] = int(getattr(organism.mission, "token_count", 0) or 0)
    summary["mission_attempts"] = int(getattr(organism.mission, "entry_attempt_count", 0) or 0)
    return summary


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run_offline(*, corpus_path, session_id: str, out_root, responder, ecu: bool, trajectory_id: str,
                prewarm_until: str | None = None, ticks_until: str | None = None,
                fingerprints: dict | None = None, ticks=None, quote_policy: str | None = None,
                run_document: dict | None = None) -> dict:
    """One whole-session trajectory from a sealed corpus into a fresh root."""
    from recognition_validation import brain_gateway as G
    from recognition_validation import corpus as K
    from recognition_validation import recorder as REC
    corpus = K.load_corpus(corpus_path)
    loaded = corpus.sessions[session_id]
    identity = C.source_identity()
    if fingerprints:
        C.require(fingerprints == {"brain":identity["brain_fingerprint"],"retrieval":identity["retrieval_fingerprint"]},
                  "RUN_SOURCE_MISMATCH", "/fingerprints")
    C.require(loaded.stream is not None, "RELEASE_STREAM_REQUIRED", f"/sessions/{session_id}")
    stream, entry = loaded.stream, loaded.entry
    ticks = list(ticks) if ticks is not None else minute_schedule(stream, prewarm_until=utc(prewarm_until) if prewarm_until else None)
    if ticks_until:
        ticks = [tick for tick in ticks if tick.decision_time <= utc(ticks_until)]
    C.require(bool(ticks), "EMPTY_SCHEDULE", "/ticks")
    C.require(loaded.entry["instrument"] == "MNQ", "INSTRUMENT_ADAPTER_UNAVAILABLE", "/instrument")
    C.require(all(t.kind in TICK_KINDS for t in ticks), "TICK_ADAPTER_UNAVAILABLE", "/ticks/kind")
    quote_policy = quote_policy or ("CONSTRUCTED" if corpus.document["provenance"]["classification"] == "CONSTRUCTED" else "MISSING")
    C.require(quote_policy in ("CONSTRUCTED", "ARCHIVED", "MISSING"), "QUOTE_POLICY_UNKNOWN", "/quote_policy")
    C.require(quote_policy != "CONSTRUCTED" or corpus.document["provenance"]["classification"] == "CONSTRUCTED",
              "CONSTRUCTED_QUOTES_ON_ARCHIVE", "/quote_policy")
    tick_document = [{"ordinal":t.ordinal,"decision_time":t.decision_time.isoformat(),"kind":t.kind} for t in ticks]
    run_document = run_document or {"schema":"offline_run/v1", "source_identity":identity,
        "corpus_digest":corpus.digest,"session_id":session_id,"ecu":ecu,"trajectory_id":trajectory_id,
        "quote_policy":quote_policy,"ticks":tick_document,"fixture_digest":getattr(responder,"fixture_digest",None)}
    run_digest = C.digest(run_document)
    out_root = Path(out_root)
    C.require(not out_root.exists() or not any(out_root.iterdir()), "OUTPUT_ROOT_REUSE", "/" + str(out_root))
    classification = corpus.document["provenance"]["classification"]
    started_at = P.real_utc_now().isoformat()
    with isolation(out_root, ecu=ecu):
        clock = P.DecisionClock(ticks[0].decision_time)
        organism = build_organism(stream=stream, clock=clock, store_dir=out_root / "store",
                                  session_id=trajectory_id, contract_id=entry["contract_id"],
                                  session_date=entry["market_date"].replace("-", ""),
                                  issued_at=entry["session_window"]["start_utc"])
        recorder = REC.Recorder(out_root / "evidence", run_digest=run_digest, trajectory_id=trajectory_id,
                                classification=classification)
        gateway = G.BrainGateway(responder, trajectory_id=trajectory_id, clock=clock, recorder=recorder,
                                 fingerprints={"brain":identity["brain_fingerprint"],"retrieval":identity["retrieval_fingerprint"]})
        quote_port = None
        if quote_policy == "ARCHIVED":
            C.require(bool(entry["quotes"]), "QUOTE_ARCHIVE_MISSING", "/quotes")
            quotes = C.loads_strict(C.verify_artifact(entry["quotes"], corpus.root).decode("utf-8"))
            quote_port = P.LocalQuotePort(quotes, clock, contract_id=entry["contract_id"], origin="ARCHIVED")
        run_ref = recorder.json_artifact(run_document, kind="run_config", origin="CONSTRUCTED")
        schedule_ref = recorder.json_artifact(tick_document, kind="schedule", origin="CONSTRUCTED")
        summary = run_trajectory(organism=organism, stream=stream, ticks=ticks, gateway=gateway, recorder=recorder,
                                 quote_closes=quote_policy == "CONSTRUCTED", quote_port=quote_port)
    summary.update(evidence_root=str(out_root / "evidence"), corpus_digest=corpus.digest,
                   tick_count=len(ticks), requests=gateway.requests, calls=gateway.calls)
    write_manifest(out_root / "evidence", {
        "schema": "run_manifest/v2", "trajectory_id": trajectory_id, "session_id": session_id,
        "run_digest": run_digest, "run_config_ref": run_ref, "schedule_ref": schedule_ref,
        "source_identity": identity, "quote_policy": quote_policy,
        "evaluation_origin": getattr(responder, "origin", "MOCK"), "ecu": ecu, "corpus_digest": corpus.digest,
        "real_started_at": started_at, "real_completed_at": P.real_utc_now().isoformat(),
        "tick_count": len(ticks), "ticks": summary["ticks"], "events": summary["events"],
        "primary_calls": summary["primary_calls"], "repair_calls": summary["repair_calls"],
        "infrastructure_error": summary["infrastructure_error"],
        "network_attempts": [str(a) for a in summary["network_attempts"]],
        "venue_writes": [str(w) for w in summary["venue_writes"]],
        "mission_tokens": summary["mission_tokens"], "mission_attempts": summary["mission_attempts"],
        "fixture_digest": getattr(responder, "fixture_digest", None)})
    return summary


def write_manifest(root, manifest: dict) -> None:
    """Real-time run bounds and counts; created once, never overwritten."""
    root = Path(root)
    manifest["trace_refs"] = [{"path":name,"sha256":C.sha256_hex((root/name).read_bytes()),
                               "bytes":(root/name).stat().st_size,"origin":"CONSTRUCTED"}
                              for name in ("events.jsonl","brain_calls.jsonl") if (root/name).exists()]
    manifest["seal"] = {"sha256":C.seal_digest(manifest),"sealed_at":P.real_utc_now().isoformat(),
                         "sealer_ref":"OFFLINE_RECORDER; engineering integrity, not owner acceptance"}
    data = json.dumps(manifest, sort_keys=True, indent=1).encode("utf-8")
    with open(Path(root) / "RUN_MANIFEST.json", "xb") as handle:
        handle.write(data)

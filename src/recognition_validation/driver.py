"""Drive one trajectory through the ACTUAL production graph, disarmed.

    LocalCandlePort -> ProductionLoop.scan_once() (injected decision clock)
      -> ProductionScanCycle.scan -> cognition through BrainGateway
      -> participation_authority_bound -> CandidateProducer.produce
      -> conditional plan capture / quote wake -> arm switch (OFF)

Ticks follow the production launcher's loop (tools/topstepx_production_session.py):
the real `WakeRegistry` is bootstrapped (arm, never wake) before the first
non-PREWARM tick and published on the candle port, as the launcher publishes it
on the live provider. Every delivered quote reaches `WakeRegistry.on_quote`, as
the live provider's `_on_quote` does; every newly available release first earns
the launcher's pure structure refresh. A tick then routes exactly like one loop
iteration: `handle_pending_conditional_wake()` first, `scan_once()` otherwise.

    SCAN        the deadline: refresh, deliver the quote, route.
    QUOTE_WAKE  one archived/constructed sided quote available at t (original
                capture time and age kept). Routes only if the registry raised
                an interaction: a plan's own zone wake goes to the brainless
                trigger; any other wake requests a normal fresh evaluation.
    RELEASE     a bar closed: the pure refresh only. Routes only if the refresh
                itself raised an interaction (armed while already inside).

The venue lane is DISARMED unless the run declares REFUSING_VENUE_DOUBLE (Mode
A/B only): then the loop's arm switch is ON against the refusing venue double
and a synthetic replay-local authorization, so the conditional trigger reaches
the runner's final-quote authentication; every venue write still raises and is
recorded. No real account, authorization or order exists anywhere here.

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
from recognition_validation import layers as LY
from recognition_validation import ports as P

RUNTIME_ROOTS = ("AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "OCCURRENCE_LEDGER_DIR", "REPLAY_SESSIONS_DIR",
                 "PERFORMANCE_TABLES_DIR", "HTF_MEMORY_DIR", "GLOBAL_MEMORY_DIR")
TICK_KINDS = ("PREWARM", "SCAN", "QUOTE_WAKE", "RELEASE")
VENUE_LANES = ("DISARMED", "REFUSING_VENUE_DOUBLE")


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
    registry: object = None
    venue_lane: str = "DISARMED"
    last_scan: dict = field(default_factory=dict)


def build_organism(*, stream, clock: P.DecisionClock, store_dir, session_id: str, contract_id: str,
                   session_date: str, issued_at: str, account_fingerprint: str = "acct:offline-replay",
                   venue_lane: str = "DISARMED") -> OfflineOrganism:
    """The real ProductionLoop around offline edges; armed only against the refusing venue double."""
    from live_scan.wake_registry import WakeRegistry
    C.require(venue_lane in VENUE_LANES, "VENUE_LANE_UNKNOWN", "/venue_lane", venue_lane)
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
    registry = WakeRegistry()
    # The registry stamps an interaction raised without `observed_at` (publish-while-inside,
    # armed-inside refresh) with the wall clock (WakeRegistry._observed_at, an inventoried T32
    # site). Offline it reads the injected decision clock instead, like every other port.
    registry._observed_at = lambda value=None: WakeRegistry._observed_at(clock.now() if value is None else value)
    organism = OfflineOrganism(loop=None, cycle=cycle, venue=venue, mission=mission, clock=clock, contract=contract,
                               registry=registry, venue_lane=venue_lane)
    original_scan = cycle.scan

    def observed_scan(*args, **kwargs):
        result = original_scan(*args, **kwargs)
        organism.last_scan = result
        return result
    cycle.scan = observed_scan
    organism.loop = PL.ProductionLoop(
        production_session=production_session, session_mission=mission,
        producer=CandidateProducer(account_fingerprint=account_fingerprint, contract=contract),
        candles=P.LocalCandlePort(stream, clock), runtime=runtime, account_id=venue.account.id,
        armed=venue_lane == "REFUSING_VENUE_DOUBLE",
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
             "CONDITIONAL_PLAN_PUBLISHED": "PLAN_CAPTURE", "CONDITIONAL_PLAN_WAITING": "PLAN_CAPTURE",
             "TRADING_COGNITION_OFF": "MISSION", "WINDOW_CLOSED": "SCAN", "SUBMIT_FAILED": "PRE_VENUE",
             "QUOTE_WAKE_NO_INTERACTION": "SCAN", "QUOTE_WAKE_NO_QUOTE": "INGEST", "RELEASE_STRUCTURE_REFRESHED": "SCAN"}


def _jsonable(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _scrub(node):
    """Drop the per-process uuid4-lineage identities compare.INPUT_TOKEN_KEYS names (campaign
    episode, Draw record, scope campaign ids); content-derived identities stay raw."""
    from recognition_validation.compare import INPUT_TOKEN_KEYS
    if isinstance(node, dict):
        return {k: _scrub(v) for k, v in node.items() if k not in INPUT_TOKEN_KEYS}
    if isinstance(node, list):
        return [_scrub(v) for v in node]
    return node


def _plan_document(plan) -> dict | None:
    """The identities a conditional plan binds (as the loop holds it), for the tick trace.

    The authority payload is recorded without its process-random identities (they never
    repeat across trajectories); its digest is over that same scrubbed payload."""
    if not isinstance(plan, dict):
        return None
    extras = getattr(plan.get("candidate"), "extras", None) or {}
    zone = extras.get("activation_zone") or {}
    authority = plan.get("authority")
    try:
        payload = authority.payload() if authority is not None else None
    except Exception:  # noqa: BLE001 -- recorded as unavailable, never repaired
        payload = None
    return _jsonable({
        "plan_id": plan.get("plan_id"), "published_at": plan.get("published_at"),
        "expires_at": extras.get("plan_expires_at"), "occurrence_id": zone.get("occurrence_id"),
        "direction": zone.get("direction"), "zone_low": zone.get("low"), "zone_high": zone.get("high"),
        "authoring_snapshot_id": extras.get("conditional_plan_snapshot_id"),
        "invalidation_price": getattr(plan.get("candidate"), "invalidation_price", None),
        "structural_invalidation": extras.get("structural_invalidation"),
        "authority_payload_digest": C.digest(_scrub(_jsonable(payload))) if payload is not None else None,
        "authority": _scrub(_jsonable({k: payload.get(k) for k in sorted(payload)
                                       if k not in ("parsed", "brain_result")})) if isinstance(payload, dict) else None})


def _venue_write_document(write) -> dict:
    """A refused venue write for the tick trace, without its per-submission random client tag."""
    name, payload = (write[0], write[1]) if isinstance(write, tuple) and len(write) == 2 else (str(write), None)
    if isinstance(payload, dict):
        return {"call": name, "payload": _jsonable({k: v for k, v in payload.items() if k != "customTag"}),
                "custom_tag_present": "customTag" in payload}
    return {"call": name, "payload": _jsonable(payload), "custom_tag_present": False}


def _plan_events_path(loop) -> Path:
    from ai_retrieval.retrieval_telemetry import session_root
    session = getattr(getattr(loop.cycle, "retrieval_telemetry", None), "session_id", "") or "UNSCOPED"
    return Path(session_root(session)) / "conditional_plan_events.jsonl"


def _deliver_quote(organism, *, visible, quote_closes, quote_port, last_key):
    """Hand the sided quote available at t to the hub (the LiveQuoteProvider) and, once
    published, to the registry -- exactly what the live provider's `_on_quote` does.
    A quote already delivered is not re-delivered: a historical message arrives once."""
    now = organism.clock.now()
    if quote_port is not None:
        quote = quote_port.capture()
        if isinstance(quote, P.MissingQuote):
            return {"state": "MISSING", "reason": quote.reason}, last_key
        bid, ask, captured, origin = quote.best_bid, quote.best_ask, quote.captured_at, quote_port.origin
    elif quote_closes and visible:
        bid = visible[-1]["close"]
        ask, captured, origin = bid + organism.contract.tick_size, now, "CONSTRUCTED_SETTLED_CLOSE"
    else:
        return {"state": "UNAVAILABLE", "reason": "independent_quote_unavailable"}, last_key
    key = (captured.isoformat(), bid, ask)
    evidence = {"origin": origin, "best_bid": bid, "best_ask": ask, "captured_at": captured.isoformat(),
                "age_seconds": (now - captured).total_seconds()}
    if key == last_key:
        return {"state": "ALREADY_DELIVERED", **evidence}, last_key
    organism.venue.market_hub.emit("GatewayQuote", [organism.contract.id, {"bestBid": bid, "bestAsk": ask}])
    # The message was received historically, not afresh on every scan: keep its age.
    organism.loop.ps.quote_provider._last_at = captured
    if organism.loop.candles.wake_registry is not None:
        organism.registry.on_quote(bid=bid, ask=ask, observed_at=captured.isoformat())
    return {"state": "DELIVERED", **evidence}, key


def _route(loop) -> tuple:
    """One launcher loop iteration: a plan's own wake first, then the ordinary scan."""
    out = loop.handle_pending_conditional_wake()
    if out is not None:
        return out, "CONDITIONAL_TRIGGER"
    return loop.scan_once(), "SCAN"


def run_trajectory(*, organism: OfflineOrganism, stream, ticks, gateway, recorder, quote_closes: bool = True,
                   quote_port=None, network_guard: P.NetworkGuard | None = None, market_open: str | None = None) -> dict:
    """Offer every tick; record one event per tick after the action."""
    from market_data.campaign_draw_truth import scan_participation_authority
    guard = network_guard or P.NetworkGuard()
    summary = {"ticks": 0, "events": 0, "primary_calls": 0, "repair_calls": 0, "infrastructure_error": None,
               "quote_wakes_routed": 0, "conditional_triggers": 0}
    lineage = f"process:{os.getpid()}:{id(organism.cycle):x}"
    loop, registry = organism.loop, organism.registry
    last_key, seen_releases, plan_rows = None, None, 0
    with guard.deny(), gateway.installed():
        for tick in ticks:
            C.require(tick.kind in TICK_KINDS, "TICK_KIND_UNKNOWN", f"/ticks/{tick.ordinal}")
            organism.clock.set(tick.decision_time)
            visible = stream.candles_at(tick.decision_time)
            calls_before, writes_before = len(gateway.calls), len(organism.venue.writes)
            wakes_before, plan_before = len(registry.wakes), _plan_document(loop.active_conditional_plan)
            economics_before = dict(getattr(loop.ps.runner, "final_quote_economics", {}) or {}) \
                if getattr(loop.ps, "runner", None) is not None else {}
            organism.last_scan = {}
            refreshed = interaction = bootstrapped = False
            route = "PREWARM"
            if tick.kind == "PREWARM":
                quote, last_key = _deliver_quote(organism, visible=visible, quote_closes=quote_closes,
                                                 quote_port=quote_port, last_key=last_key)
                outcome = loop._scan_once(observed_at=tick.decision_time, invoke_brain=False)
            else:
                quote, last_key = _deliver_quote(organism, visible=visible, quote_closes=quote_closes,
                                                 quote_port=quote_port, last_key=last_key)
                if loop.candles.wake_registry is None:
                    # STARTUP: arm and seed, never wake; only then may the quote path see it.
                    bid, ask = P.admitted_sided_prices(loop.ps)
                    registry.bootstrap_from_bars(loop.candles.fetch_1m_candles("MNQ", lookback_bars=300),
                                                 organism.contract.id, bid=bid, ask=ask)
                    loop.candles.wake_registry = registry
                    bootstrapped = True
                elif seen_releases is not None and len(visible) != seen_releases:
                    # A bar closed: the launcher's pure canonical refresh, never a Brain call by itself.
                    registry.note_bar_closed()
                    if registry.consume_structure():
                        bid, ask = P.admitted_sided_prices(loop.ps)
                        registry.refresh_from_bars(loop.candles.fetch_1m_candles("MNQ", lookback_bars=300),
                                                   organism.contract.id, bid=bid, ask=ask)
                        refreshed = True
                interaction = registry.consume_interaction()
                if tick.kind == "SCAN" or interaction:
                    outcome, route = _route(loop)
                elif tick.kind == "QUOTE_WAKE":
                    route = "WAIT"
                    outcome = {"outcome": "QUOTE_WAKE_NO_QUOTE" if quote["state"] == "MISSING"
                               else "QUOTE_WAKE_NO_INTERACTION", "reason": quote.get("reason")}
                else:
                    route = "WAIT"
                    outcome = {"outcome": "RELEASE_STRUCTURE_REFRESHED", "reason": None}
                summary["quote_wakes_routed"] += int(tick.kind == "QUOTE_WAKE" and interaction)
                summary["conditional_triggers"] += int(route == "CONDITIONAL_TRIGGER")
            seen_releases = len(visible) if tick.kind != "PREWARM" else seen_releases
            new_calls = gateway.calls[calls_before:]
            primary = sum(1 for call in new_calls if call["purpose"] == "PRIMARY")
            summary["primary_calls"] += primary
            summary["repair_calls"] += len(new_calls) - primary
            snapshot = (organism.last_scan or {}).get("snapshot") or {}
            scope_id, proof_id, scope_state = _scope_fields(snapshot)
            draw = scan_participation_authority(organism.last_scan) if organism.last_scan else None
            candidate = loop.active_candidate
            plan = loop.active_conditional_plan
            cutoff = visible[-1]["timestamp"] if visible else tick.decision_time.isoformat()
            status = (outcome or {}).get("outcome") or "UNKNOWN"
            missing = []
            if not visible:
                missing.append("no_release_available_by_decision_time")
            if tick.kind == "PREWARM":
                missing.append("declared_prewarm_no_cognition")
            if quote["state"] in ("MISSING", "UNAVAILABLE"):
                missing.append(quote["reason"])
            economics = dict(getattr(loop.ps.runner, "final_quote_economics", {}) or {}) \
                if getattr(loop.ps, "runner", None) is not None else {}
            boundary = _BOUNDARY.get(status, "SCAN")
            if route == "CONDITIONAL_TRIGGER":
                boundary = ("PRE_VENUE" if len(organism.venue.writes) > writes_before
                            else "FINAL_QUOTE" if economics and economics != economics_before else "PLAN_TRIGGER")
            try:
                refs = []
                if tick.kind != "PREWARM":
                    path = _plan_events_path(loop)
                    rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
                    new_rows, plan_rows = [json.loads(r) for r in rows[plan_rows:]], len(rows)
                    trace_doc = _jsonable({
                        "schema": "offline_tick_trace/v1", "venue_lane": organism.venue_lane,
                        "tick": {"ordinal": tick.ordinal, "kind": tick.kind,
                                 "decision_time": tick.decision_time.isoformat(), "settled_cutoff": cutoff},
                        "quote": quote, "route": route,
                        "registry": {"bootstrapped": bootstrapped, "structure_refreshed": refreshed,
                                     "interaction_consumed": interaction, "armed": len(registry.armed()),
                                     "new_wakes": registry.wakes[wakes_before:],
                                     # Raised during this route (e.g. armed while inside): spent by
                                     # the NEXT offered tick, never by this one.
                                     "interaction_pending_after_route": bool(
                                         registry.health().get("interaction_pending"))},
                        "plan_before": plan_before, "plan_after": _plan_document(plan), "plan_events": new_rows,
                        "final_quote_economics": economics if economics != economics_before else None,
                        "mission": {"tokens": int(getattr(organism.mission, "token_count", 0) or 0),
                                    "attempts": int(getattr(organism.mission, "entry_attempt_count", 0) or 0)},
                        "venue_writes": [_venue_write_document(w) for w in organism.venue.writes[writes_before:]],
                        "brain_calls": {"primary": primary, "repair": len(new_calls) - primary},
                        "outcome": outcome})
                    refs.append(recorder.json_artifact(trace_doc, kind="tick_trace", origin="CONSTRUCTED"))
                    # Mission 4: the six layers exactly as the producers returned them at this tick.
                    refs.append(recorder.json_artifact(_jsonable(LY.project(
                        tick=tick, scan=organism.last_scan, candidate=candidate, plan=plan, outcome=outcome,
                        route=route, trace=trace_doc, releases=stream.visible(tick.decision_time),
                        market_open=market_open,
                        history_revision=organism.cycle._history.revision)), kind="layer_projection",
                        origin="CONSTRUCTED"))
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
                    plan_id=((plan or {}).get("plan_id") if isinstance(plan, dict)
                             else (outcome or {}).get("conditional_plan_id")
                             or ((plan_before or {}).get("plan_id") if route == "CONDITIONAL_TRIGGER" else None)),
                    boundary=boundary, outcome=status,
                    first_refusal_code=(outcome or {}).get("reason") if status != "QUALIFIED_CANDIDATE_OBSERVED" else None,
                    primary_call_count=primary, repair_call_count=len(new_calls) - primary,
                    evidence_refs=refs, missing_evidence=missing + ([f"scope:{scope_state}"] if scope_state else []))
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
                run_document: dict | None = None, process_receipt: dict | None = None,
                network_guard: P.NetworkGuard | None = None, venue_lane: str | None = None) -> dict:
    """One whole-session trajectory from a sealed corpus into a fresh root.

    The CLI only ever calls this inside a fresh child (`child.child_main`), which
    passes its `process_receipt`; a direct in-process call is recorded as
    IN_PROCESS and the report keeps process isolation UNPROVEN for it.
    """
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
    venue_lane = venue_lane or (run_document or {}).get("venue_lane") or "DISARMED"
    C.require(venue_lane in VENUE_LANES, "VENUE_LANE_UNKNOWN", "/venue_lane", venue_lane)
    C.require(venue_lane == "DISARMED" or getattr(responder, "origin", "MOCK") in ("MOCK", "HISTORICAL"),
              "REFUSING_VENUE_LANE_MODE_C", "/venue_lane")
    tick_document = [{"ordinal":t.ordinal,"decision_time":t.decision_time.isoformat(),"kind":t.kind} for t in ticks]
    run_document = run_document or {"schema":"offline_run/v1", "source_identity":identity,
        "corpus_digest":corpus.digest,"session_id":session_id,"ecu":ecu,"trajectory_id":trajectory_id,
        "quote_policy":quote_policy,"ticks":tick_document,"fixture_digest":getattr(responder,"fixture_digest",None),
        "venue_lane":venue_lane}
    run_digest = C.digest(run_document)
    out_root = Path(out_root)
    # A child's own request/scratch directory is the only thing allowed to precede the run.
    existing = {p.name for p in out_root.iterdir()} if out_root.exists() else set()
    C.require(existing <= ({"child"} if process_receipt else set()), "OUTPUT_ROOT_REUSE", "/" + str(out_root))
    process = process_receipt or {"kind": "IN_PROCESS", "pid": os.getpid(),
                                  "note": "not a fresh child; process isolation UNPROVEN"}
    classification = corpus.document["provenance"]["classification"]
    started_at = P.real_utc_now().isoformat()
    with isolation(out_root, ecu=ecu):
        clock = P.DecisionClock(ticks[0].decision_time)
        organism = build_organism(stream=stream, clock=clock, store_dir=out_root / "store",
                                  session_id=trajectory_id, contract_id=entry["contract_id"],
                                  session_date=entry["market_date"].replace("-", ""),
                                  issued_at=entry["session_window"]["start_utc"], venue_lane=venue_lane)
        recorder = REC.Recorder(out_root / "evidence", run_digest=run_digest, trajectory_id=trajectory_id,
                                classification=classification)
        gateway = G.BrainGateway(responder, trajectory_id=trajectory_id, clock=clock, recorder=recorder,
                                 fingerprints={"brain":identity["brain_fingerprint"],"retrieval":identity["retrieval_fingerprint"]})
        quote_port = None
        if quote_policy == "ARCHIVED":
            C.require(bool(entry["quotes"]), "QUOTE_ARCHIVE_MISSING", "/quotes")
        if quote_policy != "MISSING" and entry["quotes"]:
            # An explicit sided quote stream (archived, or CONSTRUCTED for a CONSTRUCTED corpus) is
            # the only quote source; no settled close is substituted for it.
            quotes = C.loads_strict(C.verify_artifact(entry["quotes"], corpus.root).decode("utf-8"))
            quote_port = P.LocalQuotePort(quotes, clock, contract_id=entry["contract_id"], origin=quote_policy)
        C.require(quote_port is not None or not any(t.kind == "QUOTE_WAKE" for t in ticks),
                  "QUOTE_WAKE_WITHOUT_QUOTE_STREAM", "/ticks/kind")
        run_ref = recorder.json_artifact(run_document, kind="run_config", origin="CONSTRUCTED")
        schedule_ref = recorder.json_artifact(tick_document, kind="schedule", origin="CONSTRUCTED")
        summary = run_trajectory(organism=organism, stream=stream, ticks=ticks, gateway=gateway, recorder=recorder,
                                 quote_closes=quote_policy == "CONSTRUCTED" and quote_port is None, quote_port=quote_port,
                                 network_guard=network_guard, market_open=entry["session_window"]["start_utc"])
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
        "fixture_digest": getattr(responder, "fixture_digest", None), "process_isolation": process,
        "venue_lane": venue_lane, "quote_wakes_routed": summary["quote_wakes_routed"],
        "conditional_triggers": summary["conditional_triggers"]})
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

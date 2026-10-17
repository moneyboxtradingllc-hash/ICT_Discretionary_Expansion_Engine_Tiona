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
        scan_cycle=cycle, clock=clock, in_window=lambda: True)
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
                   network_guard: P.NetworkGuard | None = None) -> dict:
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

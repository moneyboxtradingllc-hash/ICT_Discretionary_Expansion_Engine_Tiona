"""Shared disarmed-loop harness for the LOCAL-AUTHORITY-20261026 tests.

Not a test module. It drives the REAL ProductionLoop/ProductionScanCycle over
the archived Friday tape (or a clearly labelled constructed tape) with a
CONTROLLED Brain transport and CONTROLLED quotes. Execution is disarmed and any
venue write raises; every result reports zero orders, tokens and attempts.

Nothing here is natural model evidence, a historical quote or an entry intent:
controlled replies prove wiring and admission only.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

import test_production_scan_loop as G
import test_protected_structure_continuity as P
import test_reversal_foundation_proof_closure as RF
from broker import topstepx_production_loop as PL
from broker import topstepx_session_authorization as SA
from broker.luna_candidate_producer import CandidateProducer
from broker.topstepx_production_session import ProductionSession
from broker.topstepx_quote_provider import LiveQuoteProvider
from live_scan.production_scan_cycle import ProductionScanCycle

CONTROL = {"model": "MOCK_CONTROLLED", "quotes": "CONTROLLED_NOT_HISTORICAL",
           "account": "FIXTURE_ONLY"}


def mirrored_tape(tape, axis=58_500.0):
    """CONSTRUCTED price mirror (p -> axis - p); never a historical session."""
    out = []
    for bar in tape:
        out.append({**bar, "open": axis - bar["open"], "high": axis - bar["low"],
                    "low": axis - bar["high"], "close": axis - bar["close"]})
    return out


def controlled_reply(out, payload, *, direction, act, entry, story="CONTROLLED", watch=False):
    """A stand-down read in `direction`, or an entry using real catalog rows."""
    if not act:
        return {**out, "narrative_direction": direction, "allowed_direction": direction,
                "forbidden_direction": "bearish" if direction == "bullish" else "bullish",
                "current_action": "stand_down", "recommended_tool_family": ["none"],
                "recommended_playbook_family": "none", "invalidation_id": None,
                "invalidation_level": None, "objective_id": None, "active_draw": "none",
                "campaign_scope_proposal": None}
    reply = RF._valid_model_reply(payload, direction=direction)
    above = direction == "bearish"
    taken, toward, held = (("buy-side", "sell-side", "protected high") if above
                           else ("sell-side", "buy-side", "protected low"))
    move = "lower" if above else "higher"
    reply.update(market_story=(f"{story} raid and intact structure with confirmed "
                               f"{direction} delivery."),
                 dominant_reasoning=(f"{story}: price delivers {move} after {taken} "
                                     f"liquidity rejection; the {held} and settled "
                                     f"body/structural break support {direction} delivery "
                                     f"toward {toward} liquidity. PO3 is context, and "
                                     "existing risk and execution rules still apply."),
                 campaign_scope_proposal=None)
    tools = [r for r in payload.get("authorized_tool_catalog", [])
             if r.get("direction") == direction and r.get("execution_eligible") is True
             and r.get("tool_family") in ("fvg", "po3_reversal_order_block")]
    if watch and tools:
        # A `watching` plan waits for its zone: geometry is chosen from the
        # zone's far edge, not from the current price.
        edge = tools[0].get("zone_high" if above else "zone_low")
        entry = edge if isinstance(edge, (int, float)) else entry
    stops = [r for r in payload.get("authorized_invalidations", [])
             if isinstance(r.get("price"), (int, float))
             and (r["price"] > entry if above else r["price"] < entry)]
    targets = [r for r in payload.get("authorized_objectives", [])
               if isinstance(r.get("price"), (int, float))
               and (r["price"] < entry if above else r["price"] > entry)]
    if stops and targets and tools:
        stop = (min if above else max)(stops, key=lambda r: r["price"])
        target = (min if above else max)(targets, key=lambda r: r["price"])
        tool = tools[0]
        reply.update(current_action="propose_entry", invalidation_id=stop["invalidation_id"],
                     invalidation_level=stop["price"], objective_id=target["objective_id"],
                     active_draw=("sell side liquidity below" if above
                                  else "buy side liquidity above"),
                     recommended_tool_family=[tool["tool_family"]],
                     recommended_tool_occurrence_id=tool["occurrence_id"])
    return reply


class Candles:
    def __init__(self, tape):
        from live_scan.wake_registry import WakeRegistry
        self.tape, self.end = tape, 0
        # The real production registry a published conditional plan arms.
        self.wake_registry = WakeRegistry()

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return [dict(b) for b in self.tape[:self.end][-lookback_bars:]]


def run(monkeypatch, root, *, ecu, profile, warmup, schedule, act_from, direction,
        tape=None, session="LA-OFFLINE", cycle_class=ProductionScanCycle, watch=False,
        plan_seconds=1800):
    """Drive the real disarmed loop. Returns every scan, output and object."""
    tape = tape or P.TAPE
    for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(root / key))
    clock = [datetime.fromisoformat(tape[0]["timestamp"])]
    payloads = []

    def place(payload):
        payloads.append(payload)
        raise AssertionError("DISARMED HARNESS MUST NEVER WRITE AN ORDER")

    venue = G.Session(place=place)
    runtime = G.Runtime(venue.market_hub)
    quotes = LiveQuoteProvider(venue.market_hub, RF.MNQ, clock=lambda: clock[0])
    ps = ProductionSession(session=venue, account_fingerprint=G.FP, contract=RF.MNQ,
                           mission_id="LA", store_dir=str(root), runtime=runtime,
                           quote_provider=quotes, clock=lambda: clock[0])
    auth = G.authorization(root, session_id=session, contract_id=P.C,
                           session_date="20261023", decision_window="09:00-14:00",
                           issued_at="2026-10-23T13:00:00+00:00")
    mission = SA.ProductionSessionMission(authorization=auth, store_dir=str(root))
    kwargs = {"local_authority_profile": profile} if profile is not None else {}
    cycle = cycle_class(symbol="MNQ", contract_id=P.C, session_id=session,
                        quote_provider=quotes, **kwargs)
    candles = Candles(tape)
    producer = CandidateProducer(account_fingerprint=G.FP, contract=RF.MNQ)
    loop = PL.ProductionLoop(production_session=ps, session_mission=mission,
                             producer=producer, candles=candles, runtime=runtime,
                             account_id=77, armed=False, scan_cycle=cycle,
                             clock=lambda: clock[0], in_window=lambda: True)
    scans, original = [], cycle.scan

    def capture(*a, **k):
        result = original(*a, **k)
        scans.append(result)
        return result

    monkeypatch.setattr(cycle, "scan", capture)

    def tick(hm, brain, bid=None):
        """One settled minute; `bid` is a CONTROLLED quote override (not historical)."""
        cutoff = P._cut(hm)
        candles.end = next(i + 1 for i, b in enumerate(tape) if b["timestamp"] == cutoff)
        bar = tape[candles.end - 1]
        clock[0] = datetime.fromisoformat(cutoff) + timedelta(minutes=1)
        price = bar["close"] if bid is None else bid
        venue.market_hub.emit("GatewayQuote", [P.C, {"bestBid": price, "bestAsk": price + .25}])
        return loop._scan_once(invoke_brain=brain)

    tick(warmup, False)
    calls = []
    current = {"hm": None}

    def mutate(out, n, payload):
        entry = tape[candles.end - 1]["close"]
        reply = controlled_reply(out, payload, direction=direction,
                                 act=current["hm"] >= act_from, entry=entry, watch=watch)
        if watch and reply.get("current_action") == "propose_entry":
            # A CONTROLLED `watching` plan over the same catalog geometry.
            reply = {**reply, "current_action": "watching",
                     "plan_expires_at": (clock[0] + timedelta(seconds=plan_seconds)).isoformat()}
        return reply

    RF._mock_current_brain(monkeypatch, calls, output_mutator=mutate)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    outputs = {}
    for hm in schedule:
        current["hm"] = hm
        # As `scan_once`: no Brain call while a conditional plan is armed.
        outputs[hm] = tick(hm, loop.active_conditional_plan is None)
    candidates = [hm for hm, out in outputs.items()
                  if out.get("outcome") == PL.QUALIFIED_CANDIDATE_OBSERVED]
    return {"outputs": outputs, "candidates": candidates, "scans": scans, "loop": loop,
            "cycle": cycle, "producer": producer, "venue": venue, "mission": mission,
            "clock": clock, "payloads": payloads, "calls": calls, "tick": tick,
            "zero_orders": venue.place_calls == 0 and payloads == [],
            "tokens": mission.token_count, "attempts": mission.entry_attempt_count,
            "control": dict(CONTROL)}


def produce(result, scan, snapshot=None, brain_result=None):
    """The actual default CandidateProducer recheck on a scan (or altered snapshot)."""
    from market_data.campaign_draw_truth import scan_participation_authority
    snap = scan["snapshot"] if snapshot is None else snapshot
    return result["producer"].produce(
        brain_result=brain_result or scan["brain_result"], brain_input=scan["brain_input"],
        snapshot=snap, qualification=scan["qualification"],
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id=scan["snapshot_id"], market_data_timestamp=snap["timestamp"],
        latest_closed_bar_timestamp=snap["timestamp"], now=result["clock"][0],
        require_campaign_lifecycle=True, campaign_draw=scan_participation_authority(scan),
        campaign_session_id=result["cycle"].session_id)


def minutes(start, end):
    return list(P._minutes(start, end))


def fresh_root(tmp_path_factory, name):
    return tmp_path_factory.mktemp(name)


__all__ = ["run", "produce", "minutes", "mirrored_tape", "controlled_reply", "CONTROL",
           "copy", "pytest"]

"""The authentic PO3 graph end to end, through the real ProductionLoop.

Stage 4 obligation F. Everything upstream of the venue is production code:
the real ProductionLoop._scan_once (coherent 300-bar window, real
ProductionScanCycle, participation_authority_bound, CandidateProducer with the
Lifecycle gate, daily-loss budget, sizing, the arm switch, trade-mission
opening, gated_submit with the live final quote, token minting and the
attempt ledger). Only three things are doubles: the candle store replays the
lawful tape minute by minute, the Brain transport is mocked (the W5
establish/activate/first-candidate replies, then an adversarial bearish entry
naming the retained PO3 formation), and the venue session raises on every
write, so the order endpoint can be REACHED but never used.

Tape: Codex's natural W5 seed plus the S4C healthy/replaced twins
(test_po3_anchor_replacement_revocation). The bearish campaign is ACTIVE and
the Lifecycle permits participation at 15:06 on both twins; the twins differ
only in the 15:03 bar that replaces the formation's 5m anchor.

  * HEALTHY, armed: the first ACTIVE_DELIVERY retrace minute reaches the venue
    seam exactly once, with one trade mission, one minted token and one
    consumed attempt, carrying the retained formation's exact identity.
  * HEALTHY, disarmed: the same candidate is produced and stops at the arm
    switch -- no mission file, token, attempt or venue call.
  * REPLACED, armed: the same Lifecycle permission, the same Brain naming the
    same formation; the loop refuses at the PO3 tool gate before any mission,
    token or venue call.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_po3_anchor_replacement_revocation as C
import test_po3_execution_identity as X
import test_po3_post_settlement_death as D
import test_production_scan_loop as P
import test_reversal_foundation_proof_closure as RF
from broker import topstepx_production_loop as PL
from broker import topstepx_session_authorization as SA
from broker.luna_candidate_producer import CandidateProducer
from broker.topstepx_client import TopstepXContract
from broker.topstepx_production_session import ProductionSession
from broker.topstepx_quote_provider import LiveQuoteProvider

FORMATION_ID = C.FORMATION_ID
MNQ = TopstepXContract(id=T.CONTRACT, name="MNQZ6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)


class _Candles:
    """The candle store, replaying the lawful tape up to the current minute."""

    def __init__(self, tape):
        self.tape, self.end = tape, 0

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return [dict(bar) for bar in self.tape[:self.end][-lookback_bars:]]


def _loop(root, monkeypatch, seq, *, ecu, arm_at):
    """Run the session to 15:06; the operator's arm switch is ON from `arm_at`
    (None: never). Returns per-minute loop outcomes, the loop, the venue double,
    the session mission, the Brain's named occurrences and the venue payloads."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = D._tape(seq)
    clock = [datetime.fromisoformat(tape[0]["timestamp"])]
    payloads = []

    def place(payload):
        payloads.append(dict(payload))
        raise P.VenueTouched("venue order endpoint reached")
    venue = P.Session(place=place)
    runtime = P.Runtime(venue.market_hub)
    quotes = LiveQuoteProvider(venue.market_hub, MNQ, clock=lambda: clock[0])
    ps = ProductionSession(session=venue, account_fingerprint=P.FP, contract=MNQ,
                           mission_id="M", store_dir=str(root), runtime=runtime,
                           quote_provider=quotes, clock=lambda: clock[0],
                           fill_deadline_seconds=0.2)
    auth = P.authorization(root, session_id="S4-F", contract_id=T.CONTRACT,
                           session_date="20260819", decision_window="09:30-16:00",
                           issued_at="2026-08-19T13:00:00+00:00")
    mission = SA.ProductionSessionMission(authorization=auth, store_dir=str(root))
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-F",
                                quote_provider=quotes)
    candles = _Candles(tape)
    loop = PL.ProductionLoop(
        production_session=ps, session_mission=mission,
        producer=CandidateProducer(account_fingerprint=P.FP, contract=MNQ),
        candles=candles, runtime=runtime, account_id=77, armed=arm_at == "13:00",
        scan_cycle=cycle, clock=lambda: clock[0], in_window=lambda: True)

    def tick(end, brain):
        bar = tape[end - 1]
        loop.armed = arm_at is not None and bar["timestamp"][11:16] >= arm_at
        candles.end = end
        clock[0] = datetime.fromisoformat(bar["timestamp"]) + timedelta(minutes=1)
        venue.market_hub.emit("GatewayQuote", [T.CONTRACT, {
            "bestBid": bar["close"], "bestAsk": bar["close"] + MNQ.tick_size}])
        return loop._scan_once(invoke_brain=brain)
    for end in range(20, 97):
        tick(end, False)
    chosen = {}
    RF._mock_current_brain(monkeypatch, [], output_mutator=lambda out, n, payload: C._reply(
        out, n, payload, tape[candles.end - 1]["close"], chosen))
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    out = {}
    for end in range(97, len(tape) + 1):
        hm = tape[end - 1]["timestamp"][11:16]
        out[hm] = tick(end, True)
        if hm == "15:06":
            break
    return out, loop, venue, mission, chosen, payloads


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_the_retained_formation_reaches_the_venue_seam_once(tmp_path, monkeypatch, ecu):
    out, loop, venue, mission, chosen, payloads = _loop(
        tmp_path / "armed", monkeypatch, C._HEALTHY, ecu=ecu, arm_at="15:06")
    # Disarmed until 15:05: the T4 FVG and the 15:01/15:02 PO3 candidates are
    # produced and only observed.
    for hm in ("14:38", "15:01", "15:02"):
        assert out[hm]["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED, (hm, out[hm])
        assert out[hm]["execution"] == PL.EXECUTION_DISARMED, hm
    # Armed at 15:06: the retained formation travels the whole graph to the
    # venue seam -- one mission, one minted token, one consumed attempt, one
    # order request, which the venue double refuses (it raises on every write).
    first = out["15:06"]
    assert first["outcome"] == PL.SUBMIT_FAILED, first
    # The venue double refused the request; the runner's reconciliation finds
    # no position and no order, and the spent authorization stays spent.
    assert "SUBMIT_REJECTED" in first["detail"] and "did not land" in first["detail"], first
    assert first["attempt_consumed"] is True
    assert (first["sizing"]["stop_price"], first["sizing"]["target_price"]) == (29519.25, 29504.75)
    assert mission.token_count == 1 and mission.entry_attempt_count == 1
    assert venue.place_calls == 1 and len(payloads) == 1
    candidate = loop.active_candidate
    assert candidate.extras["selected_tool_occurrence_id"] == FORMATION_ID
    assert (candidate.direction, candidate.entry_price, candidate.invalidation_price) == (
        "bearish", 29513.0, 29519.25)
    assert payloads[0]["contractId"] == T.CONTRACT and payloads[0]["accountId"] == 77


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_disarmed_produces_the_same_candidate_and_stops_at_the_arm_switch(
        tmp_path, monkeypatch, ecu):
    out, loop, venue, mission, chosen, payloads = _loop(
        tmp_path / "disarmed", monkeypatch, C._HEALTHY, ecu=ecu, arm_at=None)
    first = out["15:06"]
    assert first["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED, first
    assert first["execution"] == PL.EXECUTION_DISARMED
    assert loop.active_candidate.extras["selected_tool_occurrence_id"] == FORMATION_ID
    assert venue.place_calls == 0 and payloads == []
    assert mission.token_count == 0 and mission.entry_attempt_count == 0
    assert not [f for f in os.listdir(tmp_path / "disarmed") if f.startswith("trade_mission_")]


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_a_replaced_anchor_refuses_at_the_tool_gate_before_any_mission(
        tmp_path, monkeypatch, ecu):
    out, loop, venue, mission, chosen, payloads = _loop(
        tmp_path / "replaced", monkeypatch, C._REPLACED, ecu=ecu, arm_at="15:06")
    first = out["15:06"]
    assert chosen[max(chosen)] == FORMATION_ID           # the Brain still names it
    assert first["outcome"] == PL.NO_CANDIDATE, first
    assert first["reason"] == "tool_not_detected", first
    assert venue.place_calls == 0 and payloads == []
    assert mission.token_count == 0 and mission.entry_attempt_count == 0


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_a_spent_mission_refuses_every_later_candidate(tmp_path, monkeypatch, ecu):
    out, loop, venue, mission, chosen, payloads = _loop(
        tmp_path / "spent", monkeypatch, C._HEALTHY, ecu=ecu, arm_at="13:00")
    # Armed from the start, the W5 first participation (T4, 14:38) uses the
    # session's only trade mission; the venue refuses it and the attempt stays
    # spent.
    assert out["14:38"]["outcome"] == PL.SUBMIT_FAILED, out["14:38"]
    assert out["14:38"]["attempt_consumed"] is True
    # Every later healthy PO3 candidate is still produced, and refused by the
    # mission gate before any token or venue call.
    for hm in ("15:01", "15:02", "15:06"):
        assert out[hm]["outcome"] == PL.TRADE_MISSION_REFUSED, (hm, out[hm])
    assert venue.place_calls == 1 and len(payloads) == 1
    assert mission.token_count == 1 and mission.entry_attempt_count == 1

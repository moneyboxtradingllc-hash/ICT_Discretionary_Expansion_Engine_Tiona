"""The actual production final quote must remain inside a sealed watch zone."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from broker import topstepx_execution_runner as R
from broker import topstepx_session_ledger as L
from broker.topstepx_combine_risk import build_production_bracket
from broker.topstepx_execution_runner import ExecutionRunner
from broker.topstepx_slippage import QuoteCapture
from test_conditional_plan_authority import context


class MintBoundaryReached(Exception):
    """The tests stop at token minting, before any venue method can run."""


class ReadOnlySession:
    def __init__(self):
        self.place_calls = 0

    def open_positions(self):
        return []

    def query_orders(self, *, contract_id=None):
        return []

    def place_order(self, _payload):
        self.place_calls += 1
        raise AssertionError("venue order endpoint must remain unreachable")


def _verified_trigger(monkeypatch, phase="continuation"):
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

    fixtures, snapshot, draw, authored, _result, brain_input, auth, producer, authority = \
        context(monkeypatch, phase)
    now = fixtures.NOW + timedelta(seconds=1)
    original = authority.payload()["brain_result"]
    lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output={},
        narrative_continuity=original["narrative_continuity"],
        campaign_draw=draw, session_id=auth.session_id,
        contract_id=auth.contract_id, brain_authority_available=False)
    snapshot["campaign_lifecycle"] = lifecycle
    candidate = fixtures.produce(
        p=producer, res=original, bi=brain_input, qual={"qualified": True},
        snapshot=snapshot, now=now, snapshot_id="final-quote-trigger-scan",
        conditional_trigger=True, require_campaign_lifecycle=True,
        campaign_draw=draw, campaign_session_id=auth.session_id,
        conditional_plan_authority=authority,
        conditional_plan_candidate=authored,
        conditional_session_authorization=auth,
        process_session_id=auth.session_id,
        conditional_plan_trigger_event={
            "plan_id": authored.candidate_id,
            "occurrence_id": authored.extras["selected_tool_occurrence_id"],
            "reason": "conditional_plan_zone_reached"})
    # ProductionLoop adds this exact identity after CandidateProducer returns.
    candidate.extras["conditional_plan_id"] = authored.candidate_id
    return (fixtures, authored, candidate, authority, producer, now)


def _runner_and_market(tmp_path, fixtures, candidate, authority, producer, now,
                       final_bid, final_ask):
    session = ReadOnlySession()
    runner = ExecutionRunner(
        session=session, account_fingerprint=candidate.account_fingerprint,
        contract=fixtures.MNQ, clock=lambda: now)
    runner.confirm_readiness({"verdict": "READY"})
    runner._to(R.WAITING_FOR_CANDIDATE, "test ready")
    runner.execution_lane = "production"
    runner.conditional_plan_authority = authority
    runner.conditional_plan_scope = (
        producer._conditional_plan_scope if producer is not None else None)
    runner.max_risk_usd = 250.0
    runner.max_stop_points = 40.0
    runner.max_contracts = 4
    runner.min_reward_to_risk = 1.0
    runner.approved_quantity_ceiling = 4
    runner.production_volatility_evidence = dict(
        candidate.extras.get("volatility_evidence") or {})
    runner.geometry = build_production_bracket(
        direction=candidate.direction, entry_price=candidate.entry_price,
        invalidation_level=candidate.invalidation_price,
        target_price=candidate.objective.price, contract=fixtures.MNQ,
        evidence=runner.production_volatility_evidence,
        max_risk_usd=runner.max_risk_usd, max_contracts=runner.max_contracts,
        min_reward_to_risk=runner.min_reward_to_risk)["geometry"]
    market = {
        "current_price": candidate.entry_price,
        "high_since": candidate.entry_price,
        "low_since": candidate.entry_price,
        "tick_size": fixtures.MNQ.tick_size,
        "snapshot_id": candidate.snapshot_id,
        "contract_id": candidate.contract_id,
        "account_fingerprint": candidate.account_fingerprint,
        "account_state_digest": "", "data_age_seconds": 0.1,
        "in_window": True, "manual_activity": False, "now": now,
        "invalidation_timeframes": {"5m": {"recent_candles": [{
            "timestamp": "2026-08-05T15:00:00+00:00", "close": 29865.0,
            "temporal_status": "settled", "complete": True}]}},
    }
    quote_provider = lambda: QuoteCapture(
        captured_at=now, best_bid=final_bid, best_ask=final_ask,
        last_trade=final_bid, contract_id=candidate.contract_id,
        market_data_age_seconds=0.1)
    return runner, market, quote_provider, session, \
        L.SessionLedger.load_or_new(candidate.account_fingerprint,
                                    "20260805", str(tmp_path))


def _submit_to_mint_boundary(runner, candidate, market, quote_provider, ledger,
                             minted):
    def mint():
        minted.append(True)
        raise MintBoundaryReached

    return runner.gated_submit(
        account_id=1, ledger=ledger, candidate_snapshot=candidate,
        market=market, latest_price=candidate.entry_price,
        mint_token=mint, quote_provider=quote_provider)


@pytest.mark.parametrize("price_position", ["inside", "lower_edge", "upper_edge"])
def test_verified_conditional_final_quote_inside_inclusive_zone_reaches_mint(
        monkeypatch, tmp_path, price_position):
    fixtures, _, candidate, authority, producer, now = _verified_trigger(monkeypatch)
    zone = authority.payload()["activation_zone"]
    price = {"inside": (zone["low"] + zone["high"]) / 2,
             "lower_edge": zone["low"], "upper_edge": zone["high"]}[price_position]
    runner, market, quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority, producer, now,
        final_bid=price - 0.25, final_ask=price)
    minted = []
    with pytest.raises(MintBoundaryReached):
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert minted == [True]
    assert session.place_calls == 0
    assert candidate.extras["selected_tool_zone"] == {
        "low": zone["low"], "high": zone["high"]}
    assert candidate.invalidation_price == authority.payload()["invalidation_price"]
    assert candidate.direction == authority.payload()["direction"]
    assert candidate.extras["selected_tool_occurrence_id"] == \
        authority.payload()["occurrence_id"]
    assert candidate.objective.identity == authority.payload()["objective"]["identity"]


@pytest.mark.parametrize("price_position", ["above", "below"])
def test_verified_conditional_final_quote_outside_zone_refuses_before_mint(
        monkeypatch, tmp_path, price_position):
    fixtures, _, candidate, authority, producer, now = _verified_trigger(monkeypatch)
    zone = authority.payload()["activation_zone"]
    price = zone["high"] + 0.25 if price_position == "above" else zone["low"] - 0.25
    runner, market, quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority, producer, now,
        final_bid=price - 0.25, final_ask=price)
    minted = []
    with pytest.raises(R.RunnerHalt) as refused:
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert refused.value.state == R.STALE_CANDIDATE
    assert runner.final_quote_economics["refusal_reason"] == \
        "conditional_plan_final_quote_outside_authorized_zone"
    assert minted == []
    assert runner.geometry is None
    assert session.place_calls == 0


@pytest.mark.parametrize(
    "mutation", ["missing_context", "wrong_scope", "fabricated_context",
                 "missing_plan_id", "widened_zone"])
def test_final_quote_requires_sealed_plan_and_original_zone(
        monkeypatch, tmp_path, mutation):
    fixtures, _, candidate, authority, producer, now = _verified_trigger(monkeypatch)
    zone = authority.payload()["activation_zone"]
    if mutation == "widened_zone":
        candidate.extras["selected_tool_zone"] = {
            "low": zone["low"] - 1.0, "high": zone["high"] + 1.0}
        price = zone["high"] + 0.25
    else:
        price = (zone["low"] + zone["high"]) / 2
    runner, market, quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority, producer, now,
        final_bid=price - 0.25, final_ask=price)
    if mutation == "missing_context":
        runner.conditional_plan_authority = None
    elif mutation == "wrong_scope":
        runner.conditional_plan_scope = object()
    elif mutation == "fabricated_context":
        runner.conditional_plan_authority = {"state": "VERIFIED"}
    elif mutation == "missing_plan_id":
        candidate.extras.pop("conditional_plan_id")
    minted = []
    with pytest.raises(R.RunnerHalt):
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert minted == []
    assert session.place_calls == 0


def test_final_quote_uses_quote_capture_directional_side():
    quote = QuoteCapture(
        captured_at=datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc),
        best_bid=29862.0, best_ask=29864.0, last_trade=29862.0,
        contract_id="CON.F.US.MNQ.U26", market_data_age_seconds=0.1)
    assert quote.executable_reference("bullish") == quote.best_ask
    assert quote.executable_reference("bearish") == quote.best_bid


def test_bearish_runner_prices_the_bid_before_refusing_mismatched_plan(
        monkeypatch, tmp_path):
    from broker.topstepx_candidate_freshness import LiquidityObjective

    fixtures, _, candidate, authority, producer, now = _verified_trigger(monkeypatch)
    zone = authority.payload()["activation_zone"]
    bid = (zone["low"] + zone["high"]) / 2
    ask = bid + fixtures.MNQ.tick_size
    # A deliberately mismatched bearish instruction must still be priced from
    # the bid, then refused against the sealed bullish plan before minting.
    candidate.direction = "bearish"
    candidate.invalidation_price = 29870.0
    candidate.objective = LiquidityObjective(
        identity="opposing_external_liquidity:sellside@29840",
        kind="opposing_external_liquidity", price=29840.0, created_at=now)
    candidate.extras["structural_invalidation"] = {
        "structure_type": "protected_high", "structure_identity": "bearish-stop",
        "authorized_catalog_row": {
            "type": "protected_high", "timeframe": "5m", "price": 29870.0,
            "registered_at": "2026-08-05T15:00:00+00:00"}}
    runner, market, quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority, producer, now,
        final_bid=bid, final_ask=ask)
    minted = []
    with pytest.raises(R.RunnerHalt):
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert runner.final_quote_economics["final_entry_reference"] == bid
    assert minted == []
    assert session.place_calls == 0


def test_expired_plan_is_refused_at_the_final_quote(monkeypatch, tmp_path):
    fixtures, _, candidate, authority, producer, now = _verified_trigger(monkeypatch)
    zone = authority.payload()["activation_zone"]
    price = (zone["low"] + zone["high"]) / 2
    expiry = datetime.fromisoformat(authority.payload()["expires_at"])
    final_now = expiry
    runner, market, _quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate, authority, producer, final_now,
        final_bid=price - 0.25, final_ask=price)
    # The final capture is current at the expiry instant; validity still ends
    # strictly before expiry.
    quote = lambda: QuoteCapture(
        captured_at=final_now, best_bid=price - 0.25, best_ask=price,
        last_trade=price - 0.25, contract_id=candidate.contract_id,
        market_data_age_seconds=0.1)
    minted = []
    with pytest.raises(R.RunnerHalt):
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert runner.final_quote_economics["refusal_reason"] == \
        "conditional_plan_expired_before_final_quote"
    assert minted == []
    assert session.place_calls == 0


def test_nonconditional_candidate_without_plan_context_keeps_old_quote_path(
        monkeypatch, tmp_path):
    import test_runner_gate_wiring as ordinary

    fixtures = ordinary
    candidate = ordinary.snapshot()
    candidate.extras = {}
    now = fixtures.NOW + timedelta(seconds=1)
    price = candidate.entry_price
    runner, market, quote, session, ledger = _runner_and_market(
        tmp_path, fixtures, candidate,
        # The final gate ignores these unless the candidate carries a plan id.
        authority=None, producer=None, now=now,
        final_bid=price - 0.25, final_ask=price)
    runner.conditional_plan_authority = None
    runner.conditional_plan_scope = None
    minted = []
    with pytest.raises(MintBoundaryReached):
        _submit_to_mint_boundary(runner, candidate, market, quote, ledger, minted)
    assert minted == [True]
    assert session.place_calls == 0


@pytest.mark.parametrize("failure", ["outside_zone", "missing_final_context"])
def test_real_conditional_production_loop_terminalizes_final_zone_refusal(
        monkeypatch, tmp_path, failure):
    """A final quote refusal closes only the unused mission, through production."""
    from types import SimpleNamespace

    from broker.topstepx_production_loop import ProductionLoop, SUBMIT_FAILED
    from broker.topstepx_production_session import ProductionSession
    from broker.topstepx_session_authorization import ProductionSessionMission
    import broker.topstepx_production_loop as loop_module
    import live_scan.production_scan_cycle as cycle_module

    (fixtures, snapshot, draw, authored, _result, brain_input, auth,
     producer, authority) = context(monkeypatch)
    snapshot["timeframes"] = {"5m": {"recent_candles": [{
        "timestamp": "2026-08-05T15:00:00+00:00", "close": 29865.0,
        "temporal_status": "settled", "complete": True}]}}
    zone = authority.payload()["activation_zone"]
    now = fixtures.NOW + timedelta(seconds=1)
    plan = {
        "plan_id": authored.candidate_id,
        "candidate": authored,
        "authority": authority,
        "parsed": dict(authored.extras["conditional_plan_brain_output"]),
        "brain_result": dict(authored.extras["conditional_plan_brain_result"]),
        "published_at": fixtures.NOW.isoformat(),
    }
    scan = {
        "snapshot": snapshot,
        "brain_block": {"source": "preauthorized_plan_trigger",
                        "output": None, "fallback_reason": None},
        "brain_input": brain_input,
        "campaign_draw_truth": draw,
        "qualification": {"qualified": True},
        "engine_inventory": {"liquidity": "PRESENT_AND_POPULATED"},
        "snapshot_id": "terminal-refusal-trigger",
        "market_data_timestamp": now.isoformat(),
        "latest_closed_bar_timestamp": "2026-08-05T15:30:00+00:00",
    }

    venue = ReadOnlySession()
    final_ask = ((float(zone["high"]) + fixtures.MNQ.tick_size)
                 if failure == "outside_zone" else
                 (float(zone["low"]) + float(zone["high"])) / 2)
    final_quote = lambda: QuoteCapture(
        captured_at=now, best_bid=final_ask - fixtures.MNQ.tick_size,
        best_ask=final_ask, last_trade=final_ask - fixtures.MNQ.tick_size,
        contract_id=fixtures.MNQ.id, market_data_age_seconds=0.1)
    mission_owner = ProductionSessionMission(
        authorization=auth, store_dir=str(tmp_path))
    mission_owner.load_existing()
    ledger = L.SessionLedger.load_or_new(
        auth.account_fingerprint, "20260805", str(tmp_path))
    ps = ProductionSession(
        session=venue, account_fingerprint=auth.account_fingerprint,
        contract=fixtures.MNQ, mission_id=auth.session_id,
        store_dir=str(tmp_path), ledger=ledger, quote_provider=final_quote,
        clock=lambda: now, session_id=auth.session_id)
    if failure == "missing_final_context":
        real_build_runner = ps.build_runner

        def build_runner_without_plan_authority(candidate, **kwargs):
            runner = real_build_runner(candidate, **kwargs)
            runner.conditional_plan_authority = None
            return runner

        ps.build_runner = build_runner_without_plan_authority
    runtime = SimpleNamespace(health=lambda: {"last_quote_age": 0.1})
    candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **_kwargs: True),
        store_dir=str(tmp_path))
    cycle = SimpleNamespace(session_id=auth.session_id,
                            contract_id=auth.contract_id)
    loop = ProductionLoop.__new__(ProductionLoop)
    loop.ps = ps
    loop.mission = mission_owner
    loop.producer = producer
    loop.candles = candles
    loop.runtime = runtime
    loop.cycle = cycle
    loop.account_id = 1
    loop.clock = lambda: now
    loop.armed = True
    loop.active_conditional_plan = plan

    recorded_decisions = []
    recorded_plan_events = []
    loop._record_decision = lambda *args, **kwargs: recorded_decisions.append(
        (args, kwargs))
    loop._record_plan_events = lambda plan_id, events: recorded_plan_events.extend(
        (plan_id, dict(event)) for event in events)
    monkeypatch.setattr(loop_module.DLB, "resolve", lambda **_kwargs: {
        "entry_permitted": True, "allowed_planned_risk": 200.0})
    brain_calls = []
    monkeypatch.setattr(cycle_module, "run_narrative_brain",
                        lambda *_args, **_kwargs: brain_calls.append(True))

    outcome = loop._execute_conditional_plan(
        scan, conditional_event={
            "plan_id": authored.candidate_id,
            "occurrence_id": zone["occurrence_id"],
            "reason": "conditional_plan_zone_reached",
            "price": (float(zone["low"]) + float(zone["high"])) / 2,
        }, in_window=True)

    assert outcome["outcome"] == SUBMIT_FAILED
    assert outcome["final_quote_economics"] is not None, outcome
    assert outcome["mission_state"] == "TERMINAL_REFUSAL"
    assert outcome["attempt_consumed"] is False
    expected_reason = (
        "conditional_plan_final_quote_outside_authorized_zone"
        if failure == "outside_zone" else
        "conditional_plan_final_quote_authority_missing_or_unbound")
    assert outcome["final_quote_economics"]["refusal_reason"] == expected_reason
    assert loop.active_conditional_plan is None
    assert mission_owner.active_mission is None
    assert mission_owner.trade_missions[0].attempt_count == 0
    assert mission_owner.token_count == 0
    assert mission_owner.trades_used() == 0
    assert venue.place_calls == 0
    assert brain_calls == []
    assert any(kwargs.get("execution_economics", {}).get("refusal_reason") ==
               expected_reason
               for _args, kwargs in recorded_decisions)
    assert any(event.get("event") == "economics_refused"
               and event.get("reason") == expected_reason
               for _plan_id, event in recorded_plan_events)

    # Mission state is durable across a new session-mission object. The plan is
    # process-local, so a new production loop starts with no live plan to revive.
    reloaded = ProductionSessionMission(
        authorization=auth, store_dir=str(tmp_path))
    reloaded.load_existing()
    assert reloaded.trade_missions[0].state == "TERMINAL_REFUSAL"
    assert reloaded.active_mission is None
    assert reloaded.trades_used() == 0
    next_fixtures, next_snapshot, next_draw, _old, next_result, next_input, \
        _next_auth, next_producer, _next_authority = context(monkeypatch)
    next_candidate = next_fixtures.produce(
        p=next_producer, res=next_result, bi=next_input,
        qual={"qualified": True}, snapshot=next_snapshot,
        snapshot_id="after-final-quote-refusal", now=now,
        conditional_plan=True, require_campaign_lifecycle=True,
        campaign_draw=next_draw, campaign_session_id=auth.session_id)
    assert next_candidate.snapshot_id != authored.snapshot_id
    later = reloaded.open_trade_mission(
        positions=0, working_orders=0, unknown_external=False, in_window=True)
    assert later.mission_id.endswith("-T2")

    restarted = ProductionLoop(
        production_session=ps, session_mission=reloaded, producer=producer,
        candles=candles, runtime=runtime, account_id=1, armed=True,
        scan_cycle=cycle, clock=lambda: now)
    assert restarted.active_conditional_plan is None

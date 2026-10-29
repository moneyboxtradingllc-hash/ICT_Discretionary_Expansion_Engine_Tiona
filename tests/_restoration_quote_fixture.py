"""Actual historical gated_submit trajectory, stopped before token mint."""
from datetime import timedelta
from pathlib import Path
import json
import pytest
import test_luna_candidate_producer as T
from broker import topstepx_execution_runner as R
from broker import topstepx_session_ledger as L
from broker.topstepx_combine_risk import build_production_bracket
from broker.topstepx_slippage import QuoteCapture

class MintBoundary(Exception):
    pass

class NoVenue:
    def open_positions(self): return []
    def query_orders(self, **kwargs): return []
    def place_order(self, *args, **kwargs):
        raise AssertionError('NO VENUE ORDER PERMITTED')

def trajectory(tmp_path, quote, expired=False, attach=None):
    now = T.NOW
    candidate = T.produce(
        res=T.result(parsed=T.parsed(current_action='watching',invalidation_level=29855.0,
                     plan_expires_at=(now+timedelta(seconds=1)).isoformat())),
        bi=T.brain_input(price=29865.0,prot_low=29855.0),conditional_trigger=True)
    candidate.extras['conditional_plan_id'] = 'parent-plan'
    runner = R.ExecutionRunner(session=NoVenue(),account_fingerprint=T.FP,
                               contract=T.MNQ,clock=lambda: now)
    runner.confirm_readiness({'verdict':'READY'})
    runner._to(R.WAITING_FOR_CANDIDATE,'offline fixture')
    runner.execution_lane='production'
    runner.geometry=build_production_bracket(direction=candidate.direction,
        entry_price=candidate.entry_price,invalidation_level=candidate.invalidation_price,
        target_price=candidate.objective.price,contract=T.MNQ,
        evidence=candidate.extras.get('volatility_evidence') or {})['geometry']
    runner.approved_quantity_ceiling=runner.geometry.size
    runner.production_volatility_evidence=candidate.extras.get('volatility_evidence') or {}
    if attach: attach(runner,candidate)
    if expired: now += timedelta(seconds=2)
    market=dict(current_price=candidate.entry_price,high_since=candidate.entry_price,
                low_since=candidate.entry_price,tick_size=.25,snapshot_id=candidate.snapshot_id,
                contract_id=candidate.contract_id,account_fingerprint=candidate.account_fingerprint,
                account_state_digest='',data_age_seconds=.1,in_window=True,manual_activity=False,now=now,
                invalidation_timeframes={'5m':{'recent_candles':[{
                    'timestamp':'2026-08-05T15:00:00+00:00','close':29865.0,
                    'temporal_status':'settled','complete':True}]}})
    def mint(): raise MintBoundary('ALL PRE-MINT GATES PASSED')
    try:
        runner.gated_submit(account_id=1,
            ledger=L.SessionLedger.load_or_new(T.FP,'20260805',str(tmp_path)),
            candidate_snapshot=candidate,market=market,latest_price=candidate.entry_price,
            mint_token=mint,quote_provider=lambda:QuoteCapture(captured_at=now,
                best_bid=quote-.25,best_ask=quote,last_trade=quote-.25,
                contract_id=candidate.contract_id,market_data_age_seconds=.1))
    except MintBoundary:
        return 'MINT_BOUNDARY',runner,candidate
    except R.RunnerHalt as exc:
        return exc.state,runner,candidate
    raise AssertionError('unexpected return')


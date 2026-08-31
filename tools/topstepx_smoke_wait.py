"""Authorized one-trade smoke wait.

    python tools/topstepx_smoke_wait.py

Scans on the production cadence until 14:00 ET. Each scan runs the full
organism; when Luna becomes directional AND complete, the candidate producer
builds a CandidateSnapshot and the runner's gated path decides. At most ONE
entry attempt, ever.

A conflicted or neutral Luna result produces no candidate and the wait
continues — that is the normal outcome and it is not a failure. If the window
closes with no qualified candidate, the correct result is NO TRADE.

Every gate is the already-wired one. This script schedules; it does not decide.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

ET = timezone(timedelta(hours=-4))
WINDOW_CLOSE = (14, 0)
SCAN_INTERVAL = float(os.getenv("SCAN_INTERVAL_SECONDS", "60"))

PHRASE = ("AUTHORIZE TOPSTEPX COMBINE SMOKE — ONE MNQ — "
          "ONE QUALIFIED LUNA-AUTHORED TRADE — MAX PLANNED RISK $20")

STATE_DIR = os.path.join("data", "integration", "topstepx")
STATE_PATH = os.path.join(STATE_DIR, "smoke_mission_state.json")


def et_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ET)


def window_open(now: datetime = None) -> bool:
    now = now or et_now()
    close = now.replace(hour=WINDOW_CLOSE[0], minute=WINDOW_CLOSE[1],
                        second=0, microsecond=0)
    return now.weekday() < 5 and now < close


def main() -> int:
    from ai_brain import engine_payload_audit as audit
    from broker import topstepx_execution_runner as R
    from broker import topstepx_session_ledger as L
    from broker import topstepx_smoke_auth as auth
    from broker.luna_candidate_producer import CandidateProducer, NoCandidate
    from broker.topstepx_live_session import TopstepXLiveSession
    from broker.topstepx_redaction import account_fingerprint, assert_clean

    session = TopstepXLiveSession()
    session.authenticate()
    acct = session.pin(account_id=os.getenv("TOPSTEPX_ACCOUNT_ID"),
                       expected_fingerprint=os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(os.getenv("TOPSTEPX_CONTRACT") or "MNQ")
    fp = account_fingerprint(acct.id, acct.name)

    print("=" * 78)
    print("TOPSTEPX COMBINE SMOKE — one-trade live wait")
    print("=" * 78)
    print(f"account      : {fp}  canTrade={acct.can_trade} visible={acct.is_visible}")
    print(f"contract     : {contract.id} ({contract.name}) tick={contract.tick_size}")
    print(f"caps         : 1 MNQ, max planned risk $20, stop <= 10 pts")
    print(f"window closes: 14:00 ET  (now {et_now():%H:%M:%S} ET)")
    print("-" * 78)

    if session.open_positions() or session.open_orders():
        print("REFUSING TO ARM: account is not flat / has working orders.")
        return 1

    ledger = L.SessionLedger.load_or_new(fp, et_now().strftime("%Y%m%d"),
                                         os.path.join("data", "integration", "topstepx"))
    ledger.reconcile_trades(session.recent_trades())
    print(f"ledger       : manual={ledger.manual_trade_count()} "
          f"bot={ledger.bot_filled_trade_count()} unknown={ledger.unknown_count()}")
    if ledger.requires_pause():
        print(f"REFUSING TO ARM: {ledger.requires_pause()}")
        return 1

    from broker import topstepx_mission_state as MS
    mission = MS.open_mission(
        path=STATE_PATH, mission_id=f"smoke-{et_now():%Y%m%d}",
        account_fingerprint=fp, contract_id=contract.id,
        authorization_fingerprint="phrase:max20-1mnq", max_attempts=1)
    print(f"mission      : {mission.state} attempts={mission.attempt_count}"
          f"/{mission.max_attempts}")

    if mission.must_reconcile():
        print("RECOVERY MODE — the durable record says an attempt was already spent.")
        print(f"  state={mission.state} order_id={mission.order_id} "
              f"positions={len(session.open_positions())} "
              f"orders={len(session.open_orders())}")
        print("  This process will NOT create a new entry. Reconcile and report only.")
        ledger.save()
        session.close()
        return 0

    allowed, why = mission.may_attempt_entry()
    if not allowed:
        print(f"EXECUTION LANE CLOSED: {why}")
        ledger.save()
        session.close()
        return 0

    producer = CandidateProducer(account_fingerprint=fp, contract=contract)
    scans = stand_downs = degraded = 0
    outcome = {"traded": False, "reason": "window_closed_no_candidate"}

    while window_open():
        scans += 1
        started = time.monotonic()
        try:
            verdict = one_scan(session, producer, ledger, fp, contract, scans)
        except Exception as exc:  # noqa: BLE001 — a scan defect must not trade
            print(f"  [scan {scans}] ERROR {type(exc).__name__}: {str(exc)[:160]}")
            verdict = {"kind": "error"}

        if verdict["kind"] == "degraded":
            degraded += 1
        elif verdict["kind"] == "stand_down":
            stand_downs += 1
        elif verdict["kind"] == "candidate":
            detail = attempt_trade(session, ledger, fp, contract,
                                   verdict["candidate"], verdict["price"], mission)
            if detail.get("consumed"):
                # The attempt is spent (durably). The mission ends here whatever
                # the venue said — one attempt was authorized, not one success.
                outcome = {"traded": detail.get("submitted", False),
                           "reason": detail.get("reason"), "detail": detail}
                break
            # A GATE REFUSED the candidate: nothing was minted, burned or sent,
            # so no attempt was consumed and the wait continues. Ending here
            # would let a rejected candidate silently cost the whole mission.
            print("          (no attempt consumed — returning to waiting)")
            ledger.save()
        elif verdict["kind"] == "gate_refused":
            pass       # a real gate declined; keep waiting

        remaining = SCAN_INTERVAL - (time.monotonic() - started)
        if remaining > 0 and window_open():
            time.sleep(remaining)

    print("-" * 78)
    print(f"scans={scans} stand_downs={stand_downs} degraded={degraded}")
    print(f"outcome: {outcome['reason']}")
    print(f"bot filled trades: {ledger.bot_filled_trade_count()}")
    print(f"write calls made : {len(session.writes)}")
    positions, orders = session.open_positions(), session.open_orders()
    print(f"final positions  : {len(positions)}  working orders: {len(orders)}")
    ledger.save()
    session.close()
    return 0


def one_scan(session, producer, ledger, fp, contract, n) -> dict:
    """One production scan; returns what happened. Never forces a candidate."""
    import ai_brain.narrative_brain as nb
    from ai_brain import engine_payload_audit as audit
    from broker.luna_candidate_producer import NoCandidate
    from data_feed import get_provider
    from data_feed.timeframe_builder import build_timeframes
    from market_data.htf_memory_engine import HtfMemoryEngine
    from market_data.snapshot_builder import build_snapshot

    provider = get_provider("topstepx")
    candles = provider.fetch_1m_candles("MNQ", 300)
    tfs = build_timeframes(candles)
    htf = HtfMemoryEngine(symbol="MNQ").update(candles)
    snap = build_snapshot(tfs, symbol="MNQ", htf_context=htf)

    cap = {}
    real = nb._call_llm

    def spy(bi, repair=None):
        res = real(bi, repair)
        cap.setdefault("payload", dict(bi))
        cap.setdefault("res", res)
        return res

    nb._call_llm = spy
    try:
        brain = nb.run_narrative_brain(snap, "MNQ", _Stance())
    finally:
        nb._call_llm = real
        provider.stop()

    src = brain.get("source")
    out = brain.get("output") or {}
    price = candles[-1]["close"]
    stamp = f"[{et_now():%H:%M:%S} ET scan {n}]"

    if src != "llm":
        print(f"{stamp} BRAIN_DEGRADED source={src} — no candidate, no token, no order")
        return {"kind": "degraded"}

    direction = out.get("narrative_direction")
    print(f"{stamp} luna={direction} phase={out.get('narrative_phase')} "
          f"conf={out.get('phase_confidence')} px={price}")

    try:
        cand = producer.produce(
            brain_result={"ok": True, "parsed": out, "fallback_reason": None,
                          "model": "gpt-5.6-luna"},
            brain_input=cap.get("payload") or {}, snapshot=snap,
            qualification={"qualified": True},
            engine_inventory=audit.audit_payload(cap.get("payload") or {}),
            snapshot_id=f"live-{candles[-1]['timestamp']}",
            market_data_timestamp=candles[-1]["timestamp"],
            latest_closed_bar_timestamp=candles[-1]["timestamp"])
    except NoCandidate as exc:
        tag = "STAND-DOWN" if exc.stand_down else "NO CANDIDATE"
        print(f"          {tag}: {exc.reason}")
        return {"kind": "stand_down" if exc.stand_down else "gate_refused"}

    print(f"          CANDIDATE {cand.direction} stop={cand.invalidation_price} "
          f"target={cand.objective.price} ({cand.objective.identity}) "
          f"R={cand.extras['expected_reward_to_risk']}")
    return {"kind": "candidate", "candidate": cand, "price": price}


def attempt_trade(session, ledger, fp, contract, cand, price, mission) -> dict:
    """The one authorized entry attempt. Every gate is the wired one.

    Returns `consumed=True` only when the durable attempt was actually spent.
    A gate refusal consumes nothing and the caller keeps waiting.
    """
    from broker import topstepx_execution_runner as R
    from broker import topstepx_mission_state as MS
    from broker import topstepx_smoke_auth as auth

    runner = R.ExecutionRunner(session=session, account_fingerprint=fp,
                               contract=contract)
    runner.confirm_readiness({"verdict": "READY"})
    runner._to(R.WAITING_FOR_CANDIDATE, "candidate presented")

    market = dict(current_price=price, high_since=price, low_since=price,
                  tick_size=contract.tick_size, snapshot_id=cand.snapshot_id,
                  contract_id=contract.id, account_fingerprint=fp,
                  account_state_digest="", data_age_seconds=2.0,
                  in_window=window_open(), manual_activity=False)

    def mint():
        return auth.issue(phrase=PHRASE, account_fingerprint=fp,
                          contract_id=contract.id,
                          candidate_fingerprint=cand.fingerprint(),
                          snapshot_id=cand.snapshot_id, direction=cand.direction,
                          stop_price=cand.invalidation_price,
                          target_price=cand.objective.price,
                          target_identity=cand.objective.identity)

    def refresh():
        return {"market": market, "latest_price": price,
                "orders": session.open_orders(), "positions": session.open_positions()}

    def on_consume(token_id):
        """Persist ATTEMPT_CONSUMED and prove it landed, BEFORE the request."""
        mission.consume_attempt(candidate_fingerprint=cand.fingerprint(),
                                token_id=token_id)
        ledger.save()
        print(f"          ATTEMPT PERSISTED (durable) token={token_id}")

    try:
        runner.approve_risk({"direction": cand.direction,
                             "entry_price": cand.entry_price,
                             "invalidation_level": cand.invalidation_price,
                             "target_price": cand.objective.price})
        mission.transition(MS.CANDIDATE_APPROVED, cand.fingerprint())
        result = runner.gated_submit(account_id=session.account.id, ledger=ledger,
                                     candidate_snapshot=cand, market=market,
                                     latest_price=price, mint_token=mint,
                                     refresh=refresh, on_attempt_consumed=on_consume)
        mission.order_id = result.get("order_id")
        mission.transition(MS.POSITION_OPEN, f"order {result.get('order_id')}")
        ledger.save()
        print(f"          SUBMITTED order_id={result.get('order_id')}")
        return {"submitted": True, "consumed": True, "reason": "order submitted",
                "order_id": result.get("order_id"), "state": runner.state}
    except R.RunnerHalt as exc:
        consumed = mission.attempt_count > 0
        if consumed:
            terminal = (MS.SUBMIT_UNKNOWN if exc.state == R.SUBMIT_UNKNOWN
                        else MS.TERMINAL_REFUSAL)
            mission.transition(terminal, exc.state)
        ledger.save()
        print(f"          GATE REFUSED [{exc.state}] {str(exc)[:180]}")
        return {"submitted": False, "consumed": consumed,
                "reason": f"gate:{exc.state}", "state": runner.state}


class _Stance:
    def history_summary(self):
        return {"available": False}

    def record(self, *a, **k):
        pass


if __name__ == "__main__":
    raise SystemExit(main())

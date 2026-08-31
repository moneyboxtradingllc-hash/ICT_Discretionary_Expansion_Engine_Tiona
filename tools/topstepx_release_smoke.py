"""FULL-STACK-RELEASE-SMOKE-1 — the completed stack, the night before PRAC.

    python tools/topstepx_release_smoke.py --phase a          # real Terra only
    python tools/topstepx_release_smoke.py --phase b --i-authorize-one-prac-canary
    python tools/topstepx_release_smoke.py --phase ab --i-authorize-one-prac-canary

WHY THIS EXISTS RATHER THAN `topstepx_execution_smoke.py`. That tool builds its
own payload and runs its own poll loop; an AST trace shows it reaches NONE of the
current lifecycle -- not `ExecutionRunner`, not `prompt_fill_authority`, not
`acquire_full_fill`, not `authorize_actual_fill`, not `protective_children`, not
`reanchor_protection_to_structure`, not `verify_protection`. A green run of it
would certify machinery that no longer governs production.

So this is a WRAPPER, never a fork: every decision below belongs to the
production `ExecutionRunner` methods it calls.

TWO PHASES, DELIBERATELY SEPARATE PROPOSITIONS.

    PHASE A   the real external Brain is live and production-compatible.
              Real snapshot, real prompt, real provider, real parser, real
              fingerprint. DISARMED -- it authors no order. A `stand_down` is a
              PASS: the question is whether Terra WORKS, not whether it will
              trade on demand. Never re-rolled for a better answer.

    PHASE B   one 1-MNQ PRAC canary through the CURRENT execution authority.
              This is a DIAGNOSTIC, and its geometry is SMOKE geometry -- it is
              never described as Terra's thesis.

Merging them into one "AI-authored trade" tonight would read stronger and prove
less. `Terra decided -> broker filled` is tomorrow's proposition, and only a
naturally occurring candidate under unmodified doctrine can earn it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

STORE_DIR = os.path.join("data", "integration", "topstepx")


def _require_str(name: str):
    """The configured value, or None. NEVER a fallback account."""
    return (os.environ.get(name) or "").strip() or None


def _require_int(name: str):
    v = _require_str(name)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _forbidden_map(name: str) -> dict:
    """Accounts to refuse outright, as "id:reason" pairs (bare ids allowed)."""
    out = {}
    for part in (_require_str(name) or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, reason = part.partition(":")
        try:
            out[int(key.strip())] = reason.strip() or "REFUSED_BY_CONFIGURATION"
        except ValueError:
            continue
    return out

#: PRAC ONLY.
#:
#: The original reasoning here was that these are hard-pinned CONSTANTS rather
#: than configuration, because a canary that can be pointed at another account
#: by an env var is one typo away from a funded account. That argument is
#: sound and is NOT being discarded -- but the literals were one operator's
#: brokerage account numbers, which cannot ship in shared source.
#:
#: THE THREAT MODEL IS THEREFORE STATED HONESTLY, NOT PAPERED OVER: this file
#: now takes its pin from the environment, which means the "one typo" risk is
#: real for whoever installs it. The mitigations are that there is NO default
#: (an unset pin refuses instead of running), the forbidden list is checked
#: FIRST, and the run still hard-stops on any mismatch.
#:
#: If you want the original stronger guarantee, replace these three reads with
#: your own literals in your own private fork -- do not add a default here.
PRAC_ACCOUNT_ID = _require_int("PRAC_ACCOUNT_ID")
PRAC_FINGERPRINT = _require_str("PRAC_ACCOUNT_FINGERPRINT")
#: The canary keeps its own SHORT reason vocabulary, separate from the
#: release profile's operator-facing text.
FORBIDDEN_ACCOUNTS = _forbidden_map("PRAC_SMOKE_FORBIDDEN_ACCOUNTS")

SMOKE_SIZE = 1
SMOKE_DIRECTION = "bullish"          # deterministic canary side, not a prediction
SMOKE_STOP_POINTS = 10.0             # ~$20 on 1 MNQ, far inside the $250 cap
SMOKE_TARGET_POINTS = 20.0           # R = 2.0, far above the 1.0 floor
#: Production's `ProductionSession(max_market_age=30.0)` default -- reused
#: rather than inventing a smoke-specific freshness policy.
MAX_QUOTE_AGE_SECONDS = 30.0
PHRASE = ("AUTHORIZE TOPSTEPX COMBINE SMOKE — ONE MNQ — "
          "ONE QUALIFIED LUNA-AUTHORED TRADE — MAX PLANNED RISK $20")


def log(msg=""):
    print(msg, flush=True)


def assert_prac(account) -> None:
    """PRAC or nothing. Refused by identity, never by convention."""
    why = FORBIDDEN_ACCOUNTS.get(int(account.id))
    if why:
        raise SystemExit(f"HARD STOP: resolved a {why} account ({account.id})")
    # AN UNSTATED PIN IS A REFUSAL, NOT A PASS. Checked before the comparison so
    # `None != account.id` can never be the thing that lets an unconfigured run
    # proceed, and so the message says what to fix.
    if PRAC_ACCOUNT_ID is None or PRAC_FINGERPRINT is None:
        raise SystemExit(
            "HARD STOP: no account pin configured. Set PRAC_ACCOUNT_ID and "
            "PRAC_ACCOUNT_FINGERPRINT for this install; this canary ships with "
            "no default account on purpose.")
    if int(account.id) != PRAC_ACCOUNT_ID:
        raise SystemExit(f"HARD STOP: account {account.id} is not PRAC {PRAC_ACCOUNT_ID}")
    from broker.topstepx_redaction import account_fingerprint
    fp = account_fingerprint(account.id, account.name)
    if fp != PRAC_FINGERPRINT:
        raise SystemExit(f"HARD STOP: fingerprint {fp} is not {PRAC_FINGERPRINT}")


# ── PHASE A ───────────────────────────────────────────────────────────────────

def phase_a(evidence: dict) -> bool:
    """One REAL Terra inference through the production path. No order.

    Runs the production snapshot builder and the production Brain entry point.
    The decision window is NOT overridden and NOT consulted -- this asks whether
    the external Brain is reachable and production-compatible, which is a
    different question from whether the bot may trade right now.
    """
    from ai_brain.narrative_brain import enabled, json_mode_enabled, run_narrative_brain
    from ai_brain.production_model import brain_contract_fingerprint, resolve_model
    from broker.topstepx_live_session import TopstepXLiveSession
    from broker.topstepx_market_runtime import TopstepXMarketRuntime
    from data_feed.topstepx_provider import TopstepXDataProvider
    from market_data.snapshot_builder import build_snapshot

    log("=" * 74)
    log("PHASE A — REAL EXTERNAL TERRA, DISARMED")
    log("=" * 74)
    if not enabled():
        log("  FAIL: AI_BRAIN_ENABLED does not resolve true")
        return False
    model = resolve_model(armed=True)
    log(f"  brain enabled       : True   json_mode: {json_mode_enabled()}")
    log(f"  model resolves      : {model}")
    log(f"  brain fingerprint   : {brain_contract_fingerprint()}")

    session = TopstepXLiveSession()
    session.authenticate()
    account = session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                          expected_fingerprint=os.environ.get(
                              "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    assert_prac(account)
    contract = session.resolve_contract(os.getenv("TOPSTEPX_CONTRACT", "MNQ"))
    runtime = TopstepXMarketRuntime(session, contract)
    runtime.connect()
    candles = TopstepXDataProvider(session=session, autostart=False,
                                   store_dir=os.path.join("data", "market_data", "topstepx"))
    candles.start("MNQ", runtime=runtime)
    runtime.start("release_smoke")
    bars = candles.fetch_1m_candles("MNQ", lookback_bars=300)
    log(f"  candles             : {len(bars or [])}")

    # Production hands `build_snapshot` a raw_data TIMEFRAME DICT, not a bar
    # list, and `build_timeframes` is the owner that produces it. Passing the
    # 1m list directly raised `'list' object has no attribute 'get'` -- caught
    # here rather than by inventing a private reconstruction of the timeframes.
    from data_feed.timeframe_builder import build_timeframes
    raw_data = build_timeframes(bars)
    snapshot = build_snapshot(raw_data, symbol="MNQ")
    tb = (snapshot or {}).get("toolbox") or {}
    log(f"  snapshot sections   : {len(snapshot or {})}   "
        f"tool_instances: {len(tb.get('tool_instances') or [])}")

    from ai_brain.stance_memory import StanceMemory  # production stance owner
    started = time.time()
    out = run_narrative_brain(snapshot, "MNQ", StanceMemory())
    latency = time.time() - started
    runtime.stop()

    # `run_narrative_brain` returns the thesis under "output". An earlier read
    # of "parsed_output" -- the key used in the PERSISTED ARTIFACT, not in the
    # return value -- found nothing and reported a successful 24s Terra call as
    # a FAIL. The artifact and the return value are different contracts.
    parsed = (out or {}).get("output") or {}
    usage = (out or {}).get("llm_usage") or {}
    source = (out or {}).get("source")
    returned = (out or {}).get("llm_model")
    log(f"\n  source              : {source}")
    log(f"  model returned      : {returned}")
    log(f"  latency             : {latency:.2f}s")
    log(f"  tokens              : {json.dumps(usage, default=str)[:160]}")
    log(f"  fallback_reason     : {(out or {}).get('fallback_reason')}")
    log(f"  direction           : {parsed.get('narrative_direction')}   "
        f"action: {parsed.get('current_action')}")
    log(f"  tool family         : {parsed.get('recommended_tool_family')}")
    log(f"  invalidation        : {parsed.get('invalidation_level')}   "
        f"objective: {parsed.get('objective_id')}")

    evidence["phase_a"] = {
        "source": source, "model_requested": model, "model_returned": returned,
        "latency_seconds": round(latency, 3), "usage": usage,
        "fallback_reason": (out or {}).get("fallback_reason"),
        "brain_fingerprint": brain_contract_fingerprint(),
        "direction": parsed.get("narrative_direction"),
        "current_action": parsed.get("current_action"),
        "recommended_tool_family": parsed.get("recommended_tool_family"),
        "invalidation_level": parsed.get("invalidation_level"),
        "objective_id": parsed.get("objective_id"),
        "candidate_produced": False,
    }
    # A real provider response, parsed by the production contract, is the gate.
    ok = source == "llm" and returned == model and bool(parsed)
    log(f"\n  PHASE A             : {'PASS' if ok else 'FAIL'}"
        f"{'' if ok else '  (no real provider response through production parsing)'}")
    if ok and parsed.get("current_action") == "stand_down":
        log("  NOTE                : stand_down is a VALID pass. Not re-rolled.")
    return ok


# ── PHASE B ───────────────────────────────────────────────────────────────────

def phase_b(evidence: dict) -> bool:
    """ONE 1-MNQ PRAC canary through the CURRENT production execution authority."""
    from broker import topstepx_execution_runner as R
    from broker import topstepx_smoke_auth as AUTH
    from broker.topstepx_combine_risk import build_bracket
    from broker.topstepx_live_session import TopstepXLiveSession
    from broker.topstepx_redaction import account_fingerprint
    from broker.topstepx_session_ledger import bot_tag

    log("\n" + "=" * 74)
    log("PHASE B — ONE 1-MNQ PRAC CANARY (SMOKE GEOMETRY, NOT A TERRA THESIS)")
    log("=" * 74)

    session = TopstepXLiveSession()
    session.authenticate()
    account = session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                          expected_fingerprint=os.environ.get(
                              "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    assert_prac(account)
    contract = session.resolve_contract(os.getenv("TOPSTEPX_CONTRACT", "MNQ"))
    fp = account_fingerprint(account.id, account.name)

    positions, orders = session.open_positions(), session.open_orders()
    foreign = [o for o in orders if str(o.get("contract_id")) == str(contract.id)]
    log(f"  account             : {account.id}  {fp}")
    log(f"  contract            : {contract.id}  tick {contract.tick_size}")
    log(f"  balance before      : {account.balance}")
    log(f"  pre-entry positions : {len(positions)}   working orders: {len(orders)}")
    if positions or foreign:
        log("  HARD STOP           : not flat, or foreign orders on our contract")
        return False

    # LIVE EXECUTABLE QUOTE, mirroring production. The previous canary anchored
    # its geometry to the last CLOSED canonical 1m bar (29528.25) while the
    # market was at 29545.75 -- 17.5 points of STALENESS, not slippage. The fill
    # then made the smoke geometry unlawful (R collapsed to 0.091) and the
    # runner correctly refused to re-anchor. That was the WRAPPER's fault:
    # production reprices against a live quote at the submit boundary, and this
    # tool did not.
    #
    # Side convention is production's own, from the slippage contract:
    #     BUY entry_slippage = fill_price - captured_best_ask
    # so the executable reference for a BUY is the ASK.
    from broker.topstepx_market_runtime import TopstepXMarketRuntime
    from broker.topstepx_quote_provider import LiveQuoteProvider
    runtime = TopstepXMarketRuntime(session, contract)
    runtime.connect()
    runtime.start("release_smoke_quote")
    quotes = LiveQuoteProvider(runtime.hub, contract)
    deadline = time.time() + 30.0
    while time.time() < deadline and not quotes.has_quote():
        time.sleep(0.5)
    q = quotes.describe()
    log("")
    log(f"  LIVE QUOTE           : bid {q.get('best_bid')}  ask {q.get('best_ask')}  "
        f"age {q.get('age_seconds')}s  has_quote={q.get('has_quote')}")
    if not q.get("has_quote") or q.get("best_ask") is None:
        log("  HARD STOP           : no executable quote; refusing to anchor on stale data")
        runtime.stop()
        return False
    age = float(q.get("age_seconds") or 999)
    if age > MAX_QUOTE_AGE_SECONDS:
        log(f"  HARD STOP           : quote age {age}s exceeds {MAX_QUOTE_AGE_SECONDS}s")
        runtime.stop()
        return False
    ref = float(q["best_ask"])              # BUY executes at the ask
    evidence.setdefault("phase_b_quote", {"bid": q.get("best_bid"), "ask": q.get("best_ask"),
                                          "age_seconds": age, "reference": ref,
                                          "side_convention": "BUY -> best_ask"})
    runtime.stop()
    stop_abs = ref - SMOKE_STOP_POINTS
    target_abs = ref + SMOKE_TARGET_POINTS
    log(f"\n  SMOKE CANARY ABSOLUTES (diagnostic geometry, NOT market structure)")
    log(f"  reference           : {ref}")
    log(f"  smoke stop          : {stop_abs}   ({SMOKE_STOP_POINTS} pts)")
    log(f"  smoke objective     : {target_abs}   ({SMOKE_TARGET_POINTS} pts)")

    geo = build_bracket(direction=SMOKE_DIRECTION, entry_price=ref,
                        invalidation_level=stop_abs, target_price=target_abs,
                        contract=contract, size=SMOKE_SIZE,
                        max_risk_usd=R.PRODUCTION_MAX_RISK_USD,
                        max_stop_points=R.ABSOLUTE_MAX_STOP_POINTS,
                        min_reward_to_risk=R.MIN_REWARD_TO_RISK,
                        max_contracts=R.PRODUCTION_MAX_CONTRACTS)
    log(f"  geometry            : stop {geo.stop_price} target {geo.target_price} "
        f"risk ${geo.risk_usd:.2f} R={geo.reward_usd / geo.risk_usd:.2f} "
        f"signed_ticks {geo.signed_stop_ticks()}/{geo.signed_target_ticks()}")

    runner = R.ExecutionRunner(session=session, account_fingerprint=fp, contract=contract)
    runner.execution_lane = "release_smoke"
    runner.geometry = geo
    runner.max_risk_usd = R.PRODUCTION_MAX_RISK_USD
    runner.max_stop_points = R.ABSOLUTE_MAX_STOP_POINTS
    runner.max_contracts = R.PRODUCTION_MAX_CONTRACTS
    runner.min_reward_to_risk = R.MIN_REWARD_TO_RISK
    # THE POINT OF THIS TOOL: the current post-fill lifecycle owns the outcome.
    runner.prompt_fill_authority = True
    # FLIGHT RECORDER. The first canary was rejected (order 3420877831, status 5)
    # and the venue body existed only inside an exception, in memory, on a
    # process that then exited -- the exact class of loss PROD-20260810 fixed for
    # production and that this wrapper failed to configure. Both fields are
    # required before `_recording()` returns true.
    runner.submission_store_dir = STORE_DIR
    runner.submission_session_id = f"RELEASE-SMOKE-{datetime.now(timezone.utc):%Y%m%d}"
    runner.submission_mission_id = runner.submission_session_id

    runner.token = AUTH.issue(phrase=PHRASE, account_fingerprint=fp,
                              contract_id=contract.id,
                              max_risk_usd=geo.risk_usd + 1.0,
                              max_stop_points=SMOKE_STOP_POINTS,
                              candidate_fingerprint="release-smoke-canary",
                              snapshot_id="release-smoke",
                              direction=SMOKE_DIRECTION, stop_price=geo.stop_price,
                              target_price=geo.target_price,
                              target_identity="release_smoke_canary")
    tag = bot_tag(runner.token.token_id)
    log(f"  custom tag          : {tag}   (fills stay attributable)")

    t0 = time.time()
    try:
        result = runner.submit(account_id=account.id, custom_tag=tag)
    except Exception as exc:  # noqa: BLE001
        log(f"  SUBMIT FAILED       : {type(exc).__name__}: {str(exc)[:200]}")
        evidence["phase_b"] = {"submit_error": f"{type(exc).__name__}: {exc}"}
        return False
    ack_ms = int((time.time() - t0) * 1000)
    log(f"  ACK                 : order {runner.order_id} in {ack_ms}ms   state {runner.state}")

    outcome = runner.protection_outcome
    if outcome is None:                       # submit() returns before the hook
        outcome = runner.establish_structural_protection()
    log(f"\n  established          : {outcome.get('established')}")
    fill = outcome.get("fill") or {}
    log(f"  fill                 : {fill.get('size')} @ {fill.get('fill_price')} "
        f"across {fill.get('fill_count')} execution(s)")
    anchor = outcome.get("anchor") or {}
    auth = anchor.get("authorization") or {}
    log(f"  post-fill risk       : {auth.get('stop_points')} pts  ${auth.get('risk_usd')}  "
        f"R={auth.get('reward_to_risk')}")
    log(f"  child ids            : {anchor.get('child_ids')}")
    log(f"  re-anchored to       : {anchor.get('moved')}")
    for leg, proof in (anchor.get("proofs") or {}).items():
        log(f"  {leg:20s} proven={proof.get('proven')}  price={proof.get('price')}")
    ver = anchor.get("verification") or {}
    log(f"  joint verification   : verified={ver.get('verified')} "
        f"anchored={ver.get('anchored_to_structure')}")

    evidence["phase_b"] = {
        "account_id": account.id, "account_fingerprint": fp,
        "contract": contract.id, "side": SMOKE_DIRECTION, "size": SMOKE_SIZE,
        "reference_price": ref, "authorized_stop": geo.stop_price,
        "authorized_target": geo.target_price,
        "provisional_stop_ticks": geo.signed_stop_ticks(),
        "provisional_target_ticks": geo.signed_target_ticks(),
        "custom_tag": tag, "order_id": runner.order_id, "ack_ms": ack_ms,
        "balance_before": account.balance,
        "protection_outcome": outcome,
    }

    log("\n  CONTROLLED FLATTEN (diagnostic — never held for the target)")
    cleanup = runner.abandon_unfilled_entry("release smoke canary complete")
    log(f"  safe                 : {cleanup.get('safe')}")
    log(f"  final state          : {cleanup.get('final_state')}")
    evidence["phase_b"]["cleanup"] = cleanup

    time.sleep(2.0)
    final_pos, final_ord = session.open_positions(), session.open_orders()
    mine = [o for o in final_ord if runner.mission_owns_order(o)]
    log(f"  final positions      : {len(final_pos)}   mission orders: {len(mine)}")
    evidence["phase_b"]["final"] = {"positions": len(final_pos),
                                    "mission_orders": len(mine),
                                    "all_working_orders": len(final_ord)}
    return bool(outcome.get("established")) and cleanup.get("safe") and not final_pos and not mine


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="a", choices=("a", "b", "ab"))
    ap.add_argument("--i-authorize-one-prac-canary", action="store_true",
                    help="required for PHASE B; exactly one 1-MNQ entry attempt")
    args = ap.parse_args(argv)

    evidence = {"started_utc": datetime.now(timezone.utc).isoformat(),
                "head": os.popen("git rev-parse HEAD").read().strip()}
    ok_a = ok_b = None
    if "a" in args.phase:
        ok_a = phase_a(evidence)
        if not ok_a:
            log("\nSTOPPING: PHASE A did not pass; no broker write.")
            return 2
    if "b" in args.phase:
        if not args.i_authorize_one_prac_canary:
            log("\nPHASE B NOT RUN: --i-authorize-one-prac-canary absent.")
            return 2
        ok_b = phase_b(evidence)

    os.makedirs(STORE_DIR, exist_ok=True)
    path = os.path.join(STORE_DIR,
                        f"release_smoke_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, default=str)
    log(f"\n  EVIDENCE            : {path}")
    log(f"  PHASE A             : {ok_a}")
    log(f"  PHASE B             : {ok_b}")
    return 0 if (ok_a is not False and ok_b is not False) else 2


if __name__ == "__main__":
    raise SystemExit(main())

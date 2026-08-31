"""Production session entry point: the caller the production path never had.

Until now `build_production_bracket` had zero callers and `gated_submit` was
reached only from smoke tooling running smoke caps. This is the production lane.

Read-only by default. It authenticates, pins, connects the market hub, opens the
lane, prints resolved doctrine, and proves the measurement wiring end to end
WITHOUT placing an order. Arming requires the explicit flag AND a durable
one-attempt authorization.

    python tools/topstepx_production_session.py --proof
    python tools/topstepx_production_session.py --arm --mission-id <id>
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# PROD-20260807: stdout was piped and Python buffered it, so a three-hour live
# session showed 0 bytes of log while it ran. A production session must be
# observable WHILE it runs, not after it exits.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001 -- observability must never block a launch
    pass

from broker.topstepx_production_doctrine import DoctrineConflict, assert_no_conflict  # noqa: E402
from broker.topstepx_production_session import ProductionLaneRefused, ProductionSession  # noqa: E402
from broker.topstepx_redaction import assert_clean, redacted_account_label  # noqa: E402

STORE_DIR = os.path.join("data", "integration", "topstepx")
# The single component permitted to pump and reconnect the market hub.
PUMP_OWNER = "production-startup"


class StartupRefusal(RuntimeError):
    """Startup conditions that make a production session illegitimate."""


def candle_count(candles, symbol: str) -> int:
    """Completed-candle count, or -1 while the feed is still warming/stale.

    A stale feed raises rather than returning a number, and that refusal is
    correct — but a diagnostic must be able to REPORT it without dying.
    """
    try:
        return len(candles.fetch_1m_candles(symbol, lookback_bars=5000) or [])
    except Exception:  # noqa: BLE001 — reported below, never fatal to the proof
        return -1


LEGACY_PAPER_PACKAGE = os.path.join("src", "paper_execution")


def legacy_paper_subsystem_state() -> str:
    """Report the legacy Alpaca paper subsystem as it actually is."""
    if not os.path.isdir(LEGACY_PAPER_PACKAGE):
        return "REMOVED"
    return "PRESENT - NOT PRODUCTION-REACHABLE"


def retired_paths_reachable() -> list:
    """Runtime proof that no retired path became reachable in THIS process.

    Checked against loaded modules rather than source text: the question is not
    whether Alpaca code exists on disk (it does, archived and quarantined) but
    whether this launcher actually pulled any of it in.
    """
    import sys

    offenders = []
    for name in list(sys.modules):
        low = name.lower()
        if "alpaca" in low or low.startswith("paper_execution"):
            offenders.append(name)
    return sorted(offenders)


def persistence_telemetry(*, symbol: str) -> dict:
    """Resolved persistence health. Never prints a fingerprint or account id."""
    from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
    from ai_retrieval import vector_store

    eng = ThesisLifecycleEngine(symbol=symbol)
    q = getattr(eng, "quarantined", None)
    active = eng._active or None
    isolated = bool(os.getenv("AI_BRAIN_DIR")) and bool(os.getenv("GLOBAL_MEMORY_DIR"))
    # Reported so the retired record's whereabouts stay visible. It is outside
    # every production search path; this line documents that, it does not load it.
    # The instrument name is READ from the doctrine, never spelled here: a bare
    # retired symbol in the launcher is exactly what DECON-3 forbids, and the
    # doctrine module is the single authority on what is retired.
    from doctrine.instrument_identity import RETIRED_INSTRUMENTS
    quarantine = os.path.join("data", "replay_sessions", "_quarantine",
                              "retired_instrument")
    archived = sorted(n for n in (os.listdir(quarantine)
                                  if os.path.isdir(quarantine) else [])
                      if n.upper() in RETIRED_INSTRUMENTS)
    retired = ("archived and production-unreachable" if archived
               else "none archived")
    return {
        "retired_qqq_thesis": retired,
        "state": "account fingerprint verified",
        "peak_source": "same account (foreign history quarantined)",
        "thesis": f"{symbol} / {'active' if active else 'none'}",
        "foreign_thesis": (f"quarantined ({q['reason']}: {q.get('stored_instrument')})"
                           if q else "none in active production state"),
        "test_persistence": "redirected" if isolated else "production roots (live run)",
        "vector_records": vector_store.count(),
        **descriptive_memory_telemetry(),
    }


def _regime_authority_line() -> str:
    """Resolved regime authority, and whether production can be vetoed by it."""
    from regime_authority.regime_authority_mode import regime_authority_mode
    mode = regime_authority_mode()
    return f"{mode} / no mechanical production veto"


def descriptive_memory_telemetry() -> dict:
    """Descriptive-memory corpus health.

    An empty corpus is reported as EMPTY, never as a failure: on day one there
    is nothing to have learned, and telemetry that reads like a fault trains the
    operator to ignore it.
    """
    from datetime import datetime

    import pytz

    from ai_retrieval import descriptive_memory as DM
    from ai_retrieval import retrieval_contract as RC
    from ai_retrieval import vector_store
    from doctrine.instrument_identity import retrieval_eligible

    today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
    records = vector_store.load_records()
    descriptive = [r for r in records
                   if r.get("memory_type") == DM.MEMORY_TYPE_DESCRIPTIVE]
    outcome = [r for r in records
               if r.get("memory_type") == DM.MEMORY_TYPE_OUTCOME]
    expired = [r for r in descriptive if DM.is_expired(r, today)]
    foreign = [r for r in records if not retrieval_eligible(r)[0]]
    from ai_retrieval.retrieval import retrieval_startup_state
    memory = retrieval_startup_state()
    return {
        "retrieval_enabled": memory["enabled"],
        "memory_startup_state": memory["state"],
        "memory_store": "local JSONL",
        "memory_record_count": len(records),
        "descriptive_records": len(descriptive),
        "outcome_validated_records": len(outcome),
        "expired_records": len(expired),
        "foreign_records_blocked": len(foreign),
        "retrieval_authority": RC.AUTHORITY_LABEL,
        "retention_days": RC.MAX_AGE_DAYS,
        # The launcher never authors. A session's own memory is written
        # afterwards by tools/author_descriptive_session_memory.py, with
        # explicit operator approval.
        "current_session_memory": "not authored (post-session, operator-approved)",
    }


def execution_path_telemetry(*, armed: bool, mission_id: str, symbol: str) -> str:
    """Resolved production doctrine, printed before anything can execute."""
    from datetime import datetime, timezone

    from broker import topstepx_session_authorization as SA
    from broker.topstepx_combine_risk import SLIPPAGE_RESERVE_TICKS_PER_SIDE
    from doctrine import instrument_identity as II
    from ai_brain.production_model import describe as describe_brain
    from live_scan.production_scan_cycle import decision_window

    _brain = describe_brain(armed=armed)
    _cap = persistence_telemetry(symbol=symbol)

    cfg_start, cfg_end, cfg_tz = decision_window()
    _w = effective_window()
    enforced = f"{_w['start']}-{_w['end']} {SA.PRODUCTION_WINDOW_TZ}"
    session_id = mission_id or f"PROD-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    lines = [
        "",
        "  PRODUCTION EXECUTION PATH    : WIRED",
        f"  ARM STATE                    : {'ARMED' if armed else 'DISARMED'}",
        f"  SESSION ID                   : {session_id}",
        f"  MAXIMUM BOT TRADES           : {SA.MAX_BOT_TRADES_PER_SESSION}",
        f"  MAXIMUM ATTEMPTS PER TRADE   : {SA.MAX_ATTEMPTS_PER_TRADE_MISSION}",
        "  MAXIMUM ALL-IN RISK          : $250.00",
        "  PREFERRED STOP RANGE         : 0-35 points",
        "  ABSOLUTE STOP CEILING        : 40 points",
        "  MAXIMUM CONTRACTS            : 15 MNQ",
        f"  COMPOUNDING                  : {'ON' if SA.COMPOUNDING else 'OFF'}",
        f"  DECISION WINDOW (ENFORCED)   : {enforced}",
        f"  DECISION WINDOW (SCAN CFG)   : {cfg_start}-{cfg_end} {cfg_tz}",
    ]
    if _w["override"]:
        # An extended day must never be inferable only from a time comparison.
        lines += [
            f"  SESSION DATE OVERRIDE        : {_w['session_date']} (operator ruling)",
            f"  NORMAL WINDOW (SUSPENDED)    : {SA.PRODUCTION_WINDOW_START}-"
            f"{SA.PRODUCTION_WINDOW_END} {SA.PRODUCTION_WINDOW_TZ}",
            f"  HARD FLATTEN                 : {_w['hard_flatten']} "
            f"{SA.PRODUCTION_WINDOW_TZ}",
            "  OVERRIDE SCOPE               : this session date only; every other "
            "date reverts automatically",
        ]
    else:
        lines.append("  SESSION DATE OVERRIDE        : none (normal production window)")
    if (cfg_start, cfg_end) != (_w["start"], _w["end"]):
        # Surfaced, never silently reconciled: the legacy equity scan envs are
        # wider than the futures production window, and the wider one must not win.
        lines.append("    NOTE                       : scan config differs from the "
                     "enforced production window; ENFORCED wins")
    lines += [
        f"  PRODUCTION BRAIN MODEL       : {_brain['model'] or 'UNRESOLVED'}",
        f"  BRAIN TIER                   : {_brain['tier']}",
        f"  JSON MODE                    : {'ENFORCED' if _brain['json_mode_required'] else 'OFF'}",
        f"  REASONING EFFORT             : {_brain['reasoning_effort'] or 'API default (unset)'}",
        f"  BRAIN CONTRACT FINGERPRINT   : ...{_brain['contract_fingerprint'][-6:]}",
        f"  MODEL FALLBACK               : {_brain['model_fallback']}",
        f"  CAPITAL STATE                : {_cap['state']}",
        f"  PEAK EQUITY SOURCE           : {_cap['peak_source']}",
        f"  ACTIVE THESIS                : {_cap['thesis']}",
        f"  FOREIGN THESIS               : {_cap['foreign_thesis']}",
        f"  RETIRED QQQ THESIS           : {_cap['retired_qqq_thesis']}",
        f"  TEST PERSISTENCE             : {_cap['test_persistence']}",
        f"  VECTOR RETRIEVAL RECORDS     : {_cap['vector_records']}",
        f"  REGIME AUTHORITY             : {_regime_authority_line()}",
        f"  AI RETRIEVAL                 : "
        f"{'enabled' if _cap['retrieval_enabled'] else 'DISABLED'}",
        f"  MEMORY STARTUP STATE         : {_cap['memory_startup_state']}",
        f"  DESCRIPTIVE MEMORY STORE     : {_cap['memory_store']}",
        f"  RECORD COUNT                 : {_cap['memory_record_count']}"
        f"{' (EMPTY -- nothing learned yet, not a fault)' if not _cap['memory_record_count'] else ''}",
        f"  DESCRIPTIVE RECORDS          : {_cap['descriptive_records']}",
        f"  OUTCOME-VALIDATED RECORDS    : {_cap['outcome_validated_records']}",
        f"  EXPIRED RECORDS              : {_cap['expired_records']}",
        f"  FOREIGN RECORDS BLOCKED      : {_cap['foreign_records_blocked']}",
        f"  RETRIEVAL AUTHORITY          : {_cap['retrieval_authority'].lower().replace('_', ' ')}",
        f"  MEMORY RETENTION             : {_cap['retention_days']} days (retrieval only)",
        f"  CURRENT-SESSION MEMORY       : {_cap['current_session_memory']}",
        "  MARKET RUNTIME               : 1 hub / 1 pump / 1 reconnect authority",
        "  CANDLE CONSUMER              : attached",
        "  QUOTE CONSUMER               : attached",
        "  SCAN CYCLE                   : active (authoritative build_snapshot)",
        "  CANDIDATE PRODUCER           : active",
        "  PRODUCTION BRACKET BUILDER   : active",
        "  EXECUTION RUNNER             : active",
        "  ENTRY MEASUREMENT            : active",
        "  EXIT MEASUREMENT             : active",
        f"  SLIPPAGE RESERVE             : {SLIPPAGE_RESERVE_TICKS_PER_SIDE:g} ticks entry"
        f" + {SLIPPAGE_RESERVE_TICKS_PER_SIDE:g} ticks exit, provisional",
        "  SMOKE CONSTANTS              : inactive",
        "",
        "  DATA SOURCE                  : TopstepX",
        "  EXECUTION VENUE              : TopstepX",
        f"  STRATEGY INSTRUMENT          : {II.PRODUCTION_INSTRUMENT}",
        f"  ACTIVE CONTRACT              : {II.PRODUCTION_CONTRACT}",
        # Deliberately NOT "ALPACA RUNTIME: REMOVED". The legacy paper_execution
        # subsystem is still physically present; it is blocked and unreachable,
        # which is a different claim. Telemetry that overstates a retirement is
        # how a live path gets assumed dead.
        "  ALPACA PRODUCTION PATH       : BLOCKED",
        "  ALPACA DATA PROVIDER         : ARCHIVED",
        f"  LEGACY ALPACA PAPER SUBSYSTEM: {legacy_paper_subsystem_state()}",
        "  QQQ PRODUCTION PATH          : BLOCKED",
        "  RETIRED-EVIDENCE RETRIEVAL   : BLOCKED",
        f"  ACTIVE RETRIEVAL INSTRUMENT  : {II.PRODUCTION_INSTRUMENT}",
        "  PROVIDER FALLBACK            : NONE",
    ]
    return "\n".join(lines)


def load_or_refuse_authorization(*, armed: bool, session_id: str, fingerprint: str,
                                 contract_id: str, now):
    """Armed execution requires a DURABLE authorization, never a flag alone."""
    from broker import topstepx_session_authorization as SA

    path = os.path.join(STORE_DIR, f"session_auth_{session_id}.json")
    auth = SA.SessionAuthorization.load(path)
    if auth is None:
        if armed:
            raise SA.AuthorizationRefused(
                f"NO_SESSION_AUTHORIZATION: no durable record at {path}; "
                f"--arm alone does not authorize execution")
        return None
    return auth.verify(account_fingerprint=fingerprint, contract_id=contract_id,
                       session_date=now.strftime("%Y%m%d"), now=now)


def run_production_scans(*, ps, runtime, candles, session, contract, armed: bool,
                         symbol: str, mission_id: str, scans: int,
                         interval: float, until_close: bool = False) -> list:
    """The scan-to-execution loop. `armed` gates the only order-capable branch."""
    import time
    from datetime import datetime, timezone

    from broker import topstepx_session_authorization as SA
    from broker import topstepx_session_lifecycle as LIFECYCLE
    from broker.luna_candidate_producer import CandidateProducer
    from broker.topstepx_production_loop import ProductionLoop

    now = datetime.now(timezone.utc)
    session_id = mission_id or f"PROD-{now.strftime('%Y%m%d')}"
    fingerprint = os.environ["TOPSTEPX_ACCOUNT_FINGERPRINT"]

    auth = load_or_refuse_authorization(
        armed=armed, session_id=session_id, fingerprint=fingerprint,
        contract_id=contract.id, now=now)
    if auth is None:
        # Disarmed rehearsal: an in-memory record that authorizes nothing. It is
        # never written to disk, so it cannot later be mistaken for a real one.
        auth = SA.SessionAuthorization(
            session_id=session_id, account_fingerprint=fingerprint,
            contract_id=contract.id, session_date=now.strftime("%Y%m%d"),
            decision_window=SA.window_text(now.strftime("%Y%m%d")),
            # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1. The rehearsal carries the same
            # signed budget so a disarmed run exercises the REAL governed path
            # rather than stalling at "budget unknown" and losing the
            # qualified-candidate telemetry a rehearsal exists to produce.
            #
            # It grants nothing: this record is never written to disk, and
            # `--arm` -- not this object -- is what makes an order reachable.
            daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD)

    mission = SA.ProductionSessionMission(authorization=auth, store_dir=STORE_DIR)
    mission.load_existing()

    # PROVENANCE. `ProductionSession` was built before the authorization was
    # resolved, so its session id fell through to the date-derived default and
    # its authorization fingerprint was never set at all. On 2026-08-11 that
    # filed V13's flight record under the RETIRED `PROD-20260811` with an empty
    # fingerprint, and the identity mismatch is what let a filled trade look
    # like it had never reached the venue. Bound here, from the one object that
    # is authoritative about both.
    ps.session_id = auth.session_id
    ps.authorization_fingerprint = auth.fingerprint()

    loop = ProductionLoop(
        production_session=ps, session_mission=mission,
        producer=CandidateProducer(account_fingerprint=fingerprint, contract=contract),
        candles=candles, runtime=runtime, account_id=session.account.id,
        symbol=symbol, armed=armed,
        in_window=lambda: production_window_open())

    def should_continue(i: int) -> bool:
        """Continuous mode: the window governs ENTRIES, exposure governs exit.

        Leaving at 14:00 with a position open would abandon it to its brackets
        with nobody reconciling, so the loop stays alive until the account is
        genuinely flat.
        """
        if not until_close:
            return i < scans
        if production_window_open():
            return True
        if before_production_window():
            return True                      # BEFORE the bell: stay alive, wait
        # UNKNOWN IS NOT FLAT. A raising venue read used to propagate out of
        # here and kill the loop -- a fail-OPEN death at the one moment the
        # process might still be carrying exposure. Staying alive on an
        # unreadable venue is the same law the reconciler and the lifecycle
        # resolver enforce.
        try:
            # AN INCOMPLETE ORDER VIEW IS NOT A REASON TO GO HOME. `searchOpen`
            # omits Suspended bracket children, so its silence cannot end a
            # session that may still be carrying a staged protective order. Only
            # a COMPLETE discovery may retire the management loop.
            found = _DISC.discover_orders(session, contract_id=contract.id)
            if not found["complete"]:
                return True
            flat = not session.open_positions() and not (found["working"] or [])
        except Exception:  # noqa: BLE001
            return True                  # cannot see the venue: keep managing
        return not flat                      # past the window: manage, then stop

    # EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — EXPLICIT OWNERSHIP, NO GLOBALS.
    #
    # This thread is the SOLE WRITER of the registry. The market-data pump is
    # given the same object only so it can read the published snapshot and set
    # events; it never refreshes, never detects, never calls the Brain. If the
    # provider cannot carry it, `wake` stays None and the loop keeps its former
    # uninterrupted sleep — no session is ever blocked by the watcher.
    wake = None
    try:
        from live_scan.wake_registry import WakeRegistry
        wake = WakeRegistry()
        # STARTUP BOOTSTRAP — ARM ONLY, NEVER WAKE, NO BRAIN CALL.
        #
        # The registry was empty until the first bar closed, so for up to a
        # minute after a restart nothing was armed and no OUTSIDE -> INSIDE
        # detector existed for a gap that already existed. Price could enter and
        # leave inside that window unseen.
        #
        # This seeds from the SAME pure path the refresh uses -- cached completed
        # bars -> shared annotator -> canonical constructor -> wake-only registry.
        # It touches no snapshot, no toolbox, no producer, no risk, no Brain. The
        # normal initial `scan_once()` below remains the first production
        # decision, and bootstrap deliberately emits no wake so it cannot cause
        # an immediate duplicate second call about the same unchanged state.
        try:
            _bid, _ask = admitted_sided_prices(ps)
            wake.bootstrap_from_bars(
                candles.fetch_1m_candles(symbol, lookback_bars=300),
                contract.id, bid=_bid, ask=_ask)
        except Exception:  # noqa: BLE001 — a cold cache is not a startup failure
            pass
        # ONLY NOW may the pump see the registry. Bootstrap is the single place
        # the main thread writes `_episode`, and publishing afterwards is what
        # makes that safe: until this line the pump holds no reference to it.
        candles.wake_registry = wake
    except Exception:  # noqa: BLE001 — waking is an optimisation, never a gate
        wake = None
    scan_started = time.monotonic()

    label = "until close" if until_close else f"{scans} scans"
    print(f"\n  PRODUCTION SCANS             : {label} @ {interval:g}s"
          f"{' (event wake armed)' if wake is not None else ''}")
    results, i = [], 0
    while should_continue(i):
        # PRE-WINDOW: LUNA THINKS, EXECUTION WAITS.
        #
        # An earlier version of this repair held the loop and skipped the scan
        # before 09:30 to save Brain tokens. That defeated the entire reason for
        # being up early: the bot is running before the bell so the Brain
        # ORIENTS on the developing premarket -- structure, liquidity, raids,
        # directional transition -- instead of forming its first read cold at
        # the open. Yesterday's 22-minute late arm cost a 334-point move; a
        # sleeping process would have cost the same thing in a different way.
        #
        # Nothing here needs to gate execution: `in_window` is already the hard
        # routing boundary inside the scan cycle, so a pre-window scan can
        # think, narrate and analyse while remaining structurally unable to
        # create exposure. Spend is the wrong thing to optimise here.
        if hard_flatten_due():
            # Checked BEFORE the scan, never after: a scan that produced a
            # candidate at 15:55:00 would already have been refused by the
            # window, but running one at all past the flatten ruling wastes the
            # minute the ruling exists to spend on getting flat.
            from broker import topstepx_session_authorization as _SA
            w = effective_window()
            print(f"\n  HARD FLATTEN                 : {w['hard_flatten']} "
                  f"{_SA.PRODUCTION_WINDOW_TZ} reached -- closing position "
                  f"and cancelling working orders")
            # THE CERTIFIED AUTHORITY, WHEN ONE IS IN SCOPE. `loop.ps.runner`
            # carries mission lineage and the durable halt ladder, so the
            # end-of-session flatten goes through the same safety authority as
            # every other liquidation rather than a second policy of its own.
            # BOTH AUTHORITIES ARE HANDED OVER EXPLICITLY.
            #   runner -> mission lineage, via the certified emergency authority
            #   ledger -> the session's own token ids, which are the ONLY thing
            #             that can attribute an order once no mission is in
            #             scope. Without it nothing is provable and the shutdown
            #             escalates rather than cancelling by instrument.
            _ps = getattr(loop, "ps", None)
            fr = hard_flatten(session, contract,
                              runner=getattr(_ps, "runner", None),
                              ledger=getattr(_ps, "ledger", None))
            print(f"    positions before           : {fr['positions_before']}")
            print(f"    working orders before      : {fr['orders_before']}")
            print(f"    position closed            : {fr['closed']}")
            print(f"    orders cancelled           : {len(fr['cancelled'])}")
            print(f"    ORDER AUTHORITY            : {fr.get('authority')} "
                  f"(attribution: {fr.get('attribution')})")
            if fr.get("unproven"):
                print(f"    UNATTRIBUTED, NOT CANCELLED: {fr['unproven']}")
            if fr.get("operator_escalation"):
                print(f"    OPERATOR ACTION REQUIRED   : {fr['operator_escalation']}")
            print(f"    FLAT                       : {fr['flat']}")
            if fr["errors"]:
                for e in fr["errors"]:
                    print(f"    ERROR                      : {e}")
            results.append({"outcome": "HARD_FLATTEN", "detail": w["hard_flatten"],
                            **fr})
            break
        scan_started = time.monotonic()
        out = loop.scan_once()
        results.append(out)
        i += 1
        extra = ""
        if out.get("direction"):
            act = str(out.get("action") or "")[:40]
            extra = (f" | DIRECTION={out['direction']} ACTION={act or '-'} "
                     f"CANDIDATE=none ({out.get('reason', '-')})")
        if out["outcome"] == "QUALIFIED_CANDIDATE_OBSERVED":
            s = out["sizing"]
            extra = (f" | {out['direction']} {s['size']} MNQ "
                     f"stop {s['stop_points']:.2f}pt (${s['risk_usd']:.2f}) "
                     f"{s['stop_range']} RR {s['reward_to_risk']} -> {out['execution']}")
        # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — MEMORY FAILURE MUST BE VISIBLE AS
        # MEMORY FAILURE. Silence here would mean "the tape was quiet" and
        # "durable memory broke" look identical to the operator, which is the
        # same epistemic lie the ledger exists to end. Printed ONLY when the
        # state is not healthy, so a working session stays readable; this is
        # observability and touches no decision, payload or gate.
        _mem = getattr(loop.cycle, "last_occurrence_persistence_status", "")
        if _mem and _mem not in ("LEDGER_HEALTHY", "LEDGER_NOT_CONFIGURED"):
            _err = str(getattr(loop.cycle,
                               "last_occurrence_persistence_error", ""))[:80]
            extra += f" | OCCURRENCE MEMORY {_mem}{': ' + _err if _err else ''}"
        print(f"   scan {i}{'' if until_close else f'/{scans}'}: {out['outcome']}"
              f"{' - ' + out.get('detail', '') if out.get('detail') else ''}{extra}")
        # SESSION-CAP-GRACEFUL-SHUTDOWN-1 -- THE COOPERATIVE EXIT.
        #
        # `SESSION_COMPLETE` is now emitted ONLY once entry authority is spent
        # AND fresh venue truth proved no exposure, no owned working orders and
        # no unresolved mission. That is a terminal DECISION, so the loop leaves
        # normally and the caller's own shutdown path runs -- pump joined, hub
        # closed once. Before this, terminal was only a LABEL: on 2026-08-25 it
        # printed 160 times across 19 minutes and the process had to be killed
        # from outside, because nothing here could conclude "my job is finished".
        if out["outcome"] == LIFECYCLE.SESSION_COMPLETE:
            print("")
            print(f"  {LIFECYCLE.SESSION_COMPLETE}             : "
                  f"{out.get('detail', '')}")
            print("  SESSION GRACEFUL EXIT        : venue proven flat and "
                  "order-clean; leaving the scan loop")
            break
        if should_continue(i):
            # EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — ONE WAIT SEAM.
            #
            # This was `time.sleep(interval)`: a FIXED DELAY AFTER WORK, so a
            # 19s Luna call produced a 79s start-to-start interval (measured,
            # n=151). On 2026-08-21 that put the scans at 10:23:51 and 10:25:11
            # around a ~60s live entry window, and the trade was never presented.
            #
            # Now: deadline-based, and interruptible.
            #   no event      -> true ~60s START-TO-START cadence
            #   bar closed    -> refresh the wake registry, NO Brain call
            #   price entered -> immediate fresh scan
            #
            # The events are level-triggered, so one raised while Luna was
            # mid-flight is still pending here and costs one immediate cycle.
            # ONE IMMUTABLE DEADLINE, computed from when this scan STARTED.
            # Recomputing `interval` after each event would let a bar closing
            # every minute postpone ordinary cognition forever -- fixing
            # "bar close calls Luna" by inventing "bar close never calls Luna".
            deadline = scan_started + interval
            if wake is None:
                time.sleep(max(0.0, deadline - time.monotonic()))
            else:
                # ONLY TWO THINGS MAY END THE WAIT: an actionable interaction, or
                # the original deadline. A bar close is neither.
                #
                # The first version of this fell out of the wait after a
                # structure refresh and straight into the next `scan_once()`,
                # which made every settled bar a Luna call -- Option A wearing
                # Option B's clothes. Proven against the real loop: a
                # structure-only event returned in 1.0s of a 6s deadline and
                # spent a provider call on nothing.
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    wake.wait(remaining)
                    # STRUCTURE FIRST, INTERACTION SECOND. A bar close earns a
                    # PURE canonical refresh on this owner thread -- never
                    # `build_snapshot`, never the toolbox, never a stateful
                    # tracker -- and by itself never a Luna call.
                    if wake.consume_structure():
                        # SAME FRESHNESS LAW AS BOOTSTRAP. A newly born zone must
                        # not be claimed INSIDE from a stale stored quote: that
                        # claim both fires a wake the scan cannot price AND seeds
                        # the episode INSIDE, so the first genuinely fresh entry
                        # then reads INSIDE -> INSIDE and never wakes. One
                        # ungoverned quote would have cost the real interaction.
                        _bid, _ask = admitted_sided_prices(ps)
                        try:
                            wake.refresh_from_bars(
                                candles.fetch_1m_candles(symbol, lookback_bars=300),
                                contract.id, bid=_bid, ask=_ask)
                        except Exception:  # noqa: BLE001 — a stale feed is not fatal
                            pass
                        # The refresh itself may raise an interaction when a
                        # newly armed zone ALREADY contains a FRESH executable
                        # quote. That is the 10:24 case and it is a real signal.
                        if wake.consume_interaction():
                            break
                        # Structure only: keep waiting, SAME deadline.
                        continue
                    # Consumed immediately before acting on it, never at the end
                    # of a scan: an interaction raised while the previous scan
                    # was running is still pending here and is spent by the cycle
                    # it causes.
                    if wake.consume_interaction():
                        break
    print(f"  FINAL STATE                  : {loop.final_flat_state()}")

    # EVIDENCE-SUBSTRATE-PHASE0 — archive the session tape.
    #
    # The rolling collector file holds a few days and is overwritten. A session
    # traded without its own archived bars can NEVER be counterfactually scored
    # -- not at any later date, by any amount of effort. Everything else on the
    # roadmap can be added retroactively; this cannot.
    #
    # Runs after the scan loop has finished and touches nothing it produced.
    try:
        from broker.trade_lineage import archive_tape
        _bars = candles.fetch_1m_candles(symbol, lookback_bars=5000) or []
        _tape = archive_tape(
            session_id=getattr(getattr(ps, "retrieval_telemetry", None),
                               "session_id", "") or "UNSCOPED",
            contract_id=getattr(getattr(candles, "contract", None), "id", ""),
            bars=_bars,
            decision_timestamps=[r.get("market_data_timestamp")
                                 for r in results if isinstance(r, dict)])
        print(f"  SESSION TAPE                 : {_tape.get('bar_count')} bars "
              f"archived (write_ok={_tape.get('tape_write_ok')})")
    except Exception as _exc:  # noqa: BLE001 -- capture may never cost a session
        print(f"  SESSION TAPE                 : NOT ARCHIVED ({type(_exc).__name__})")
    return results


def _now_et(now_et=None):
    from zoneinfo import ZoneInfo

    from broker import topstepx_session_authorization as SA
    from datetime import datetime
    return now_et or datetime.now(ZoneInfo(SA.PRODUCTION_WINDOW_TZ))


def effective_window(now_et=None) -> dict:
    """The ruling in force for the date `now_et` falls on."""
    from broker import topstepx_session_authorization as SA
    return SA.window_for(_now_et(now_et).strftime("%Y%m%d"))


def production_window_open(now_et=None) -> bool:
    """Whether a NEW ENTRY may be created, in America/New_York.

    The end boundary is STRICT. At the closing minute the machine's job changes
    from finding trades to getting flat, so 15:54:59 is eligible and 15:55:00 is
    not -- `<=` would have handed the whole closing minute back as tradeable.
    Management is never gated by this; only entry is.
    """
    now = _now_et(now_et)
    w = effective_window(now)
    return w["start"] <= now.strftime("%H:%M") < w["end"]


def before_production_window(now_et=None) -> bool:
    """Is the decision window still AHEAD of us today?

    PRE-BELL LIFECYCLE (2026-08-20). `should_continue` asked only
    `production_window_open()` and then, if flat, stopped -- a rule written for
    the state AFTER the close. Before the open it read identically, so arming at
    09:02 exited with ZERO scans: "the window is not open and I am flat" is
    `session complete` after 14:00 and `not started yet` at 09:02, and the
    controller could not tell them apart.

    The operating requirement is armed + alive + flat + OBSERVING before the
    bell, so the window changing state at 09:30 must not require the PROCESS to
    change state. This predicate separates the two states; it deliberately does
    NOT gate scanning. Luna thinks before the bell; execution waits for it, and
    `in_window` inside the scan cycle is what enforces that.
    """
    now = _now_et(now_et)
    return now.strftime("%H:%M") < effective_window(now)["start"]


def hard_flatten_due(now_et=None) -> bool:
    """Whether the day's ruling says: close what is open, now.

    Distinct from the window closing. A date with no `hard_flatten` keeps the
    existing behaviour -- entries stop, the loop stays alive and MANAGES an open
    position rather than abandoning it to its brackets.
    """
    now = _now_et(now_et)
    hf = effective_window(now)["hard_flatten"]
    return bool(hf) and now.strftime("%H:%M") >= hf


#: The MECHANISM lives in `broker/topstepx_hard_flatten.py`, never here. The
#: entrypoint decides WHEN to flatten; the execution layer decides HOW. An AST
#: guard forbids this file from containing an order-capable call at all.
from broker.topstepx_hard_flatten import hard_flatten  # noqa: E402
from broker import topstepx_order_discovery as _DISC  # noqa: E402


def _flat_and_clear(session, contract) -> bool:
    """The session's closing claim about the account. POSITIVE PROOF ONLY.

    Reports False when the order view is INCOMPLETE, because the last line an
    operator reads before walking away must not say FLAT on the strength of a
    query that is documented to hide staged protective children.
    """
    try:
        found = _DISC.discover_orders(session, contract_id=contract.id)
        if not found["complete"]:
            return False
        return not session.open_positions() and not (found["working"] or [])
    except Exception:  # noqa: BLE001
        return False


def startup_history_telemetry(candles) -> str:
    """What the warm-up actually achieved. Printed, always.

    STARTUP-HISTORY-WIRING (2026-08-12). The warm-up verdict existed on the
    provider from the day it was written and no caller ever read it, so a total
    historical failure and a perfect one printed the same banner. A failure that
    cannot be seen is a failure that gets launched on.
    """
    rep = candles.startup_history_report() or {}
    return "\n".join([
        "",
        "  STARTUP HISTORY WARM-UP",
        f"    attempted                  : {rep.get('attempted')}",
        f"    requested horizon (minutes) : {rep.get('minutes_back')}",
        f"    bars returned by venue      : {rep.get('returned')}",
        f"    bars added to canonical     : {rep.get('added')}",
        f"    oldest returned             : {rep.get('oldest_returned')}",
        f"    newest returned             : {rep.get('newest_returned')}",
        f"    canonical bar count         : {rep.get('bar_count')}",
        f"    canonical first             : {rep.get('first')}",
        f"    canonical last              : {rep.get('last')}",
        f"    canonical continuous        : {rep.get('continuous')}",
        f"    gaps / missing minutes      : {rep.get('gap_count')} / "
        f"{rep.get('missing_minutes')}",
        f"    warm-up error               : {rep.get('error')}",
    ])


def admitted_sided_prices(ps) -> tuple:
    """THE ONE sided quote the wake path may treat as a current interaction.

    EVENT-WAKE-ACTIONABLE-STRUCTURE-1. The registry used to be handed
    `candles.last_quote`, a stored provider dict that is never cleared and
    carries no enforced age. A quote from before a stall stayed numeric forever,
    so a stale ask that happened to sit inside a zone could be claimed as INSIDE
    -- and an INSIDE claim SUPPRESSES the next entry wake. Meanwhile
    `_reference_price` refuses that very quote, so the scan the suppression
    relied on could not price a trade either.

        CANDIDATE PRODUCER   "that quote is stale, I cannot trade it"
        WAKE REGISTRY        "looks like an inside price to me"

    Those two may never disagree, so this asks the SAME authority the submit
    boundary asks. Nothing new is measured and no threshold is copied: the age
    field, the ceiling and the refusal all stay owned by
    `topstepx_execution_price` / `topstepx_slippage`.

    Returns (bid, ask) already admitted as fresh and sided, or (None, None).
    None is not "price is outside" -- it is "inside is NOT PROVEN", and the
    registry treats an unprovable interaction as no interaction. The occurrence
    is still armed, so the first genuinely fresh quote can establish it.

    Never raises: a broken quote lane may not block startup or cost a scan.
    """
    try:
        from broker.topstepx_execution_price import executable_price, from_capture
        block = from_capture(ps.quote_provider.capture())
        return (executable_price(block, "bearish"),   # bid
                executable_price(block, "bullish"))   # ask
    except Exception:  # noqa: BLE001 — unavailable, never fabricated
        return (None, None)


def check_startup(session, *, armed: bool, mission_id: str, provider: str,
                  runtime=None, candles=None) -> list:
    """Conditions that forbid a production session from opening."""
    refusals = []
    if runtime is not None:
        h = runtime.health()
        if not h["pump_owner"]:
            refusals.append("AMBIGUOUS_PUMP_OWNERSHIP: no component owns the market pump")
        elif h["pump_owner"] != PUMP_OWNER:
            refusals.append(
                f"DUPLICATE_RECONNECT_AUTHORITY: pump owned by '{h['pump_owner']}', "
                f"expected '{PUMP_OWNER}'")
        if not h["pump_thread_alive"]:
            refusals.append("PUMP_THREAD_DEAD: the market pump thread is not alive")
        if len(h["active_contracts"]) != 1:
            refusals.append(
                f"CONFLICTING_ACTIVE_CONTRACTS: {h['active_contracts']}")
    if not session.account or not getattr(session.account, "id", None):
        refusals.append("NO_PINNED_ACCOUNT: no account pinned; routing is unproven")
    if not os.environ.get("TOPSTEPX_ACCOUNT_FINGERPRINT"):
        refusals.append("NO_FINGERPRINT: pin cannot be verified against an expected account")
    if getattr(session, "contract", None) is None:
        refusals.append("NO_CONTRACT: no resolved contract; size and tick value are unknown")
    if getattr(session, "market_hub", None) is None:
        refusals.append("NO_MARKET_HUB: no live quote stream; slippage cannot be captured")
    from doctrine import instrument_identity as II
    try:
        II.assert_production_instrument(os.environ.get("SCAN_SYMBOL"),
                                        where="SCAN_SYMBOL")
    except II.InstrumentIdentityError as exc:
        refusals.append(f"RETIRED_OR_FOREIGN_INSTRUMENT: {exc}")
    reachable = retired_paths_reachable()
    if reachable:
        refusals.append(
            f"RETIRED_PATH_REACHABLE: this process loaded {', '.join(reachable[:4])}; "
            f"a retired venue must never be importable from the production launcher")
    contract = getattr(getattr(session, "contract", None), "id", "")
    if contract and contract != II.PRODUCTION_CONTRACT:
        refusals.append(
            f"FOREIGN_CONTRACT: {contract} is not {II.PRODUCTION_CONTRACT}")
    if provider != "topstepx":
        refusals.append(
            f"FOREIGN_DATA_PROVIDER: DATA_PROVIDER={provider or 'unset'}; production "
            f"requires native topstepx data, never a substitute venue's prices")
    try:
        assert_no_conflict()
    except DoctrineConflict as exc:
        refusals.append(f"DOCTRINE_CONFLICT: {exc}")
    if armed and not mission_id:
        refusals.append("NO_MISSION_ID: an armed session needs a durable authorization identity")
    if armed and candles is not None:
        # STARTUP-HISTORY-AUTHORITY (2026-08-12, PROD-20260812). The armed lane
        # proves its history is fit to reason from BEFORE anything downstream
        # exists: before Terra is asked, before a candidate is produced, before a
        # mission or token is minted, before order authority is granted. The
        # observe/proof lanes keep the tolerant behaviour deliberately -- a
        # read-only rehearsal watching a chart fill in is useful, and an armed
        # session doing the same thing is the defect this refuses.
        from data_feed import startup_history_authority as SHA
        verdict = SHA.evaluate(backfill_report=candles.startup_history_report(),
                               candles=candles.canonical_candles(),
                               process_started_at=candles.connected_at)
        refusals.extend(verdict["refusals"])
    if armed:
        # UPGRADE-...-TERRA (2026-08-06): the model is resolved by the single
        # authority, or the armed session refuses. The legacy chain fell through
        # AI_MODEL to gpt-4o-mini, so a missing value ran production on a weaker
        # model while telemetry still named the intended one.
        from ai_brain.production_model import ModelResolutionError, resolve_model
        try:
            resolve_model(armed=True)
        except ModelResolutionError as exc:
            refusals.append(str(exc))
        # LUNA-JSON-DEFECT (2026-08-06): with BRAIN_JSON_MODE unset, the model is
        # held to JSON by prose alone and 2 of 38 live calls came back malformed.
        # Config alone is not enough -- an accidental .env edit would silently
        # put Luna back on prose instruction, so an armed session refuses.
        # Calls the Brain's OWN predicate so the guard cannot drift from it.
        # DECONTAMINATE (2026-08-06): load-bearing persistence must belong to
        # THIS account and THIS instrument. A foreign thesis or a foreign capital
        # peak changes what the Brain is told and how drawdown is judged.
        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
        eng = ThesisLifecycleEngine(symbol=os.environ.get("SCAN_SYMBOL", "MNQ"))
        q = getattr(eng, "quarantined", None)
        if q and q.get("reason") == "foreign_instrument":
            refusals.append(
                f"FOREIGN_THESIS_STATE: active thesis belongs to "
                f"{q['stored_instrument']}, session trades {q['session_instrument']}; "
                f"quarantine or remove it before arming")
        from ai_brain.narrative_brain import JSON_MODE_TRUTHY, json_mode_enabled
        if not json_mode_enabled():
            raw = os.getenv("BRAIN_JSON_MODE")
            refusals.append(
                f"BRAIN_JSON_MODE_DISABLED: structured output is not enforced "
                f"(BRAIN_JSON_MODE={raw!r}); an armed session will not run Luna on "
                f"prose-only JSON instruction. Set one of {JSON_MODE_TRUTHY}.")
        # ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07). Ten
        # descriptive memories were authored on 2026-08-06 and discovered the
        # next morning to be unreachable: the flag was absent, so the scan-loop
        # hook short-circuited before ever reading them. Every other telemetry
        # line looked healthy. A corpus that exists and cannot be read is the
        # same silent-degradation class as the retired data-provider fallback --
        # so an armed session refuses rather than running memory-blind while
        # reporting a healthy memory store.
        from ai_retrieval.retrieval import RETRIEVAL_TRUTHY, retrieval_startup_state
        memory = retrieval_startup_state()
        if memory["refuses_armed_startup"]:
            refusals.append(
                f"MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED: "
                f"{memory['descriptive_records']} descriptive records are on "
                f"disk but AI_RETRIEVAL_ENABLED={memory['raw_flag']!r} resolves "
                f"disabled, so the Brain would receive none of them. Set one of "
                f"{RETRIEVAL_TRUTHY}, or author no corpus.")
    return refusals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="store_true",
                    help="permit an entry attempt (still requires authorization)")
    ap.add_argument("--proof", action="store_true",
                    help="read-only lifecycle proof; never places an order")
    ap.add_argument("--mission-id", default="")
    ap.add_argument("--observe", type=float, default=20.0,
                    help="--proof: seconds to wait for a live quote")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--scans", type=int, default=0,
                    help="run N production scans (0 = startup telemetry only)")
    ap.add_argument("--until-close", action="store_true",
                    help="scan until the window closes, then manage any open "
                         "position to a clean flat state")
    ap.add_argument("--interval", type=float, default=60.0,
                    help="seconds between production scans")
    args = ap.parse_args(argv)

    from broker.topstepx_live_session import TopstepXLiveSession
    from broker.topstepx_market_runtime import TopstepXMarketRuntime
    from data_feed.topstepx_provider import TopstepXDataProvider

    # authenticate -> pin -> ONE shared runtime -> attach consumers -> one pump
    if args.arm:
        os.environ["PRODUCTION_ARMED_SESSION"] = "true"   # model resolution fails closed

    session = TopstepXLiveSession()
    session.authenticate()
    # The fingerprint is ENFORCED at the pin, not merely carried alongside it.
    # Pinning by id alone resolves whichever account now holds that id; the
    # expected fingerprint is what refuses a configured account that changed
    # between runs — the whole point of the pinning law.
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(args.symbol)

    runtime = TopstepXMarketRuntime(session, contract)
    runtime.connect()

    candles = TopstepXDataProvider(session=session, autostart=False,
                                   store_dir=os.path.join("data", "market_data",
                                                          "topstepx"))
    candles.start(args.symbol, runtime=runtime)          # consumer, starts no pump

    # LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 — THE SECOND CONSUMER.
    #
    # Every trade already arrives with price, size and a millisecond timestamp,
    # and the candle aggregator sums them into OHLCV and drops the rest. That is
    # correct for a candle and irreversible for a profile: no REST endpoint
    # carries price attribution, so a session that runs without this recorder is
    # a session that can never have a volume profile.
    #
    # It attaches BESIDE the candle provider on the one shared hub -- `SignalRHub.on`
    # appends handlers precisely so a second consumer cannot unsubscribe the
    # first -- and shares no state with it. It computes nothing, publishes
    # nothing to the Brain, and has no route to any strategy surface. It records.
    #
    # Attached before the pump starts so no trade is missed between start and
    # subscribe; a failure here costs CAPTURE, never the session.
    #
    # NO SUCCESS TELEMETRY. This file is closure-bound, so display-only churn in
    # it invalidates live authorizations -- the cost `production_model` records
    # as "real and accepted". The FAILURE branch is kept: a silently swallowed
    # exception would let a whole session record nothing while looking healthy,
    # which is the false-green class, not observability.
    try:
        from market_data.vap_provider import VapCaptureProvider
        from market_data.vap_store import VAP_RETENTION_DAYS, prune
        _vap_store = os.path.join("data", "market_data", "topstepx")
        VapCaptureProvider(contract_id=contract.id, tick_size=contract.tick_size,
                           instrument=args.symbol,
                           store_dir=_vap_store).attach(runtime)
        prune(_vap_store, contract.id, retention_days=VAP_RETENTION_DAYS)
    except Exception as exc:                             # noqa: BLE001
        print(f"  vap capture        : UNAVAILABLE ({type(exc).__name__}: {exc})")

    runtime.start(PUMP_OWNER)                            # the only reader
    print(startup_history_telemetry(candles))

    refusals = check_startup(session, armed=args.arm, mission_id=args.mission_id,
                             provider=os.environ.get("DATA_PROVIDER", ""),
                             runtime=runtime, candles=candles)
    if refusals:
        runtime.stop()
        print("PRODUCTION SESSION REFUSED")
        for r in refusals:
            print(f"  - {r}")
        return 2

    ps = ProductionSession(session=session,
                           account_fingerprint=os.environ["TOPSTEPX_ACCOUNT_FINGERPRINT"],
                           contract=contract,
                           mission_id=args.mission_id or "READONLY-PROOF",
                           store_dir=STORE_DIR, runtime=runtime)
    try:
        lane = ps.open_lane()
    except ProductionLaneRefused as exc:
        runtime.stop()
        print(f"PRODUCTION LANE REFUSED: {exc}")
        return 2

    out = ps.telemetry()
    assert_clean(out)                    # telemetry never carries a credential
    print(out)
    print(f"\n  ACCOUNT                      : {redacted_account_label(session.account)}")
    print(f"  LANE                         : {lane['lane']}")
    print(f"  NEW ENTRY PERMITTED          : {lane['new_entry_permitted']}")
    print(f"  ARMED                        : {args.arm}")
    print(execution_path_telemetry(armed=args.arm, mission_id=args.mission_id,
                                   symbol=args.symbol))
    if lane["lane"] == "RECOVERY":
        print("  RECOVERY                     : unresolved context found; "
              "reconciling the existing position, NOT entering again")
    if args.proof:
        # Prove BOTH consumers advance under the one pump, rather than assuming
        # the subscriptions took. The wait lives HERE, in the diagnostic; the
        # submit boundary never waits for a quote.
        import time
        start_candles = candle_count(candles, args.symbol)
        deadline = time.time() + args.observe
        while time.time() < deadline:
            if (ps.quote_provider.has_quote() and runtime.last_trade_at is not None
                    and candle_count(candles, args.symbol) > start_candles):
                break
            time.sleep(0.5)

        q = ps.quote_provider.describe()
        h = runtime.health()
        now_candles = candle_count(candles, args.symbol)
        print(f"\n  QUOTE CONSUMER               : "
              f"{'attached' if q['has_quote'] else 'attached (no quote yet)'}")
        if q["has_quote"]:
            print(f"  EXECUTABLE BID/ASK           : {q['best_bid']} / {q['best_ask']}")
        print(f"  CANDLE CONSUMER              : attached "
              f"({start_candles} -> {now_candles} candles)")
        print(f"  CANDLE CONTRACT              : {candles.contract.id}")
        print(f"  QUOTE CONTRACT               : {q['contract_id']}")
        print(f"  RECONNECTS OBSERVED          : {h['reconnects']}")
        print(f"  ACCOUNT STILL FLAT           : "
              f"{_flat_and_clear(session, contract)}")

    if args.scans or args.until_close:
        from broker.topstepx_session_authorization import AuthorizationRefused
        try:
            run_production_scans(ps=ps, runtime=runtime, candles=candles,
                                 session=session, contract=contract, armed=args.arm,
                                 symbol=args.symbol, mission_id=args.mission_id,
                                 scans=args.scans, interval=args.interval,
                                 until_close=args.until_close)
        except AuthorizationRefused as exc:
            # Fail closed and loudly: an unauthorized armed session must end,
            # never quietly fall back to a disarmed run that looks successful.
            print(f"\n  ARMED SESSION REFUSED        : {exc}")
            candles.stop()
            runtime.stop()
            return 2

    if not args.arm:
        print("\n  No order will be placed: the session is not armed.")

    # shutdown: detach consumers -> signal owner -> join thread -> close hub once
    candles.stop()
    runtime.stop()
    print(f"  SHUTDOWN                     : pump joined, hub closed once "
          f"(alive={runtime.is_running})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

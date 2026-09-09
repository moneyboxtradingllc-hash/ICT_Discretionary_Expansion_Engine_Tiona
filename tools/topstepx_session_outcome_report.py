"""READ-ONLY. What a finished production session actually did, from its records.

PROD-20260908 EVIDENCE REQUEST. A session outcome told from memory or from
terminal scrollback is not evidence. This assembles one from the durable stores
the session itself wrote, and every path it reads is the one its WRITER names:

    data/integration/topstepx/session_auth_<session>.json
        `tools/topstepx_production_session.py:332` -- the signed authorization:
        window, budget, trade and attempt law, bound fingerprints.

    data/integration/topstepx/trade_mission_<session>_<n>.json
        `SA.ProductionSessionMission` -- one file per mission, carrying its
        terminal (or non-terminal) state and whether its attempt was spent.

    data/integration/topstepx/submissions_<session>.jsonl
        `topstepx_submission_record.ledger_path` -- the flight recorder,
        written BEFORE transport. A submission absent here never left.

    data/replay_sessions/<session>/memory_retrieval/candidate_decisions.jsonl
        `topstepx_production_loop._record_decision` -- per-scan disposition and
        rejection reason. This is where stand-down reasons are DURABLE; the
        terminal lines are a copy, not the record.

    data/replay_sessions/<session>/memory_retrieval/retrieval_scans.jsonl
        `ai_retrieval.retrieval_telemetry.telemetry_path` -- per-scan timing.

    data/ai_brain/ai_calls_<session>_*.jsonl   -- brain calls, latency, fallbacks
    data/ops/incidents_<yyyymmdd>.json          -- `position_supremacy` incidents

ZERO IS REPORTED, NEVER OMITTED. "no trades" and "no trade ledger" are
different facts, and a report that prints nothing for both is useless for
exactly the session where it matters. A missing store says MISSING and says
what that implies.

WITH `--venue` IT ALSO AUTHENTICATES AND READS -- positions, order discovery
(and whether discovery was COMPLETE), and settled trades since the window
opened, for P&L against actual venue fields. It places nothing: no order
endpoint is reachable from this module.

    python tools/topstepx_session_outcome_report.py --session PROD-20260908
    python tools/topstepx_session_outcome_report.py --session PROD-20260908 --venue
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

STORE_DIR = os.path.join("data", "integration", "topstepx")
MISSING = "MISSING"


def _rows(path: str) -> "list | None":
    """Every JSON row, or None if the store is not there at all."""
    if not os.path.exists(path):
        return None
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _doc(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _span(rows, *keys):
    """(first, last) over the first present timestamp key. Never guesses."""
    stamps = []
    for row in rows or []:
        for key in keys:
            if row.get(key):
                stamps.append(str(row[key]))
                break
    stamps.sort()
    return (stamps[0], stamps[-1]) if stamps else (None, None)


def authorization(store_dir: str, session: str) -> dict:
    doc = _doc(os.path.join(store_dir, f"session_auth_{session}.json"))
    return {"present": doc is not None, "doc": doc or {}}


def missions(store_dir: str, session: str) -> list:
    out = []
    for path in sorted(glob.glob(os.path.join(
            store_dir, f"trade_mission_{session}_*.json"))):
        doc = _doc(path) or {}
        out.append({"path": path, "mission_id": doc.get("mission_id"),
                    "state": doc.get("state"), "order_id": doc.get("order_id"),
                    "attempt_count": doc.get("attempt_count"),
                    "token_spent": doc.get("token_spent"),
                    "venue_attributed": doc.get("venue_attributed")})
    return out


def decisions(session: str) -> dict:
    from ai_retrieval.retrieval_telemetry import session_root
    root = session_root(session)
    rows = _rows(os.path.join(root, "candidate_decisions.jsonl"))
    if rows is None:
        return {"present": False, "root": root}
    # THE WRITER'S OWN KEY NAMES. `build_record` stores the terminal verdict as
    # `final_disposition` / `final_rejection_reason`; the constructor arguments
    # are called `disposition` / `rejection_reason` and reading THOSE off the
    # row yields None for every record. Measured on PROD-20260908: 279 rows all
    # tallied as "?", which reported the stand-down reasons as unknown when the
    # ledger held them in full.
    #
    # `reconcile` is the module's own owner of the disposition count and is
    # CALLED rather than reimplemented -- a second tally beside it is how the
    # evidence and the report drift apart.
    from broker.candidate_decision_record import reconcile
    tally = collections.Counter()
    for row in rows:
        tally[(str(row.get("final_disposition") or "?"),
               str(row.get("final_rejection_reason") or ""),
               str(row.get("detail") or ""))] += 1
    first, last = _span(rows, "timestamp_et", "recorded_at")
    return {"present": True, "root": root, "count": len(rows),
            "first": first, "last": last, "tally": tally,
            "reconciliation": reconcile(rows)}


def scans(session: str) -> dict:
    from ai_retrieval.retrieval_telemetry import telemetry_path
    path = telemetry_path(session)
    rows = _rows(path)
    if rows is None:
        return {"present": False, "path": path}
    # `retrieval_telemetry.build_record` writes `timestamp_et`. Omitting it
    # printed "first None .. last None" over 279 perfectly good rows.
    first, last = _span(rows, "timestamp_et", "at_et", "at_utc", "recorded_at")
    return {"present": True, "path": path, "count": len(rows),
            "first": first, "last": last}


def brain_calls(session: str) -> dict:
    paths = sorted(glob.glob(os.path.join("data", "ai_brain",
                                          f"ai_calls_{session}_*.jsonl")))
    if not paths:
        return {"present": False}
    rows = []
    for path in paths:
        rows.extend(_rows(path) or [])
    first, last = _span(rows, "at_utc")
    failed = [r for r in rows if not r.get("ok")]
    fellback = [r for r in rows if r.get("fallback_reason")]
    return {"present": True, "paths": paths, "count": len(rows),
            "first": first, "last": last,
            "not_ok": len(failed), "fallbacks": len(fellback),
            "max_scan": max((r.get("scan") or 0 for r in rows), default=0)}


def submissions(store_dir: str, session: str) -> dict:
    from broker import topstepx_submission_record as SUB
    path = SUB.ledger_path(store_dir, session)
    rows = _rows(path)
    if rows is None:
        return {"present": False, "path": path}
    # THE WRITER'S KEY IS `state`. `open_submission` writes state /
    # operation / success / venue_order_id; there is no `phase` and no `event`.
    # Measured on PROD-20260909: four real submission rows all printed as "?",
    # which reported the flight recorder as unreadable for the first session
    # that actually used it.
    return {"present": True, "path": path, "count": len(rows),
            "states": collections.Counter(str(r.get("state") or "?")
                                          for r in rows),
            "operations": collections.Counter(str(r.get("operation") or "?")
                                              for r in rows),
            "rows": [{"submission_id": r.get("submission_id"),
                      "mission_id": r.get("mission_id"),
                      "state": r.get("state"),
                      "operation": r.get("operation"),
                      "success": r.get("success"),
                      "venue_order_id": r.get("venue_order_id"),
                      "error_code": r.get("error_code"),
                      "error_message": r.get("error_message"),
                      "transport_exception": r.get("transport_exception")}
                     for r in rows]}


def incidents(session_date: str) -> dict:
    path = os.path.join("data", "ops", f"incidents_{session_date}.json")
    doc = _doc(path)
    if doc is None:
        return {"present": False, "path": path}
    rows = doc if isinstance(doc, list) else doc.get("incidents") or [doc]
    return {"present": True, "path": path, "count": len(rows), "rows": rows[:10]}


def session_start_iso(session_date: str) -> "str | None":
    """The instant this session's window opened, from the authorization's date.

    NOT UTC midnight. `recent_trades` defaults there, and on a Monday that
    reaches back to Sunday 20:00 ET -- a prior session's P&L leaking into this
    one. `daily_loss_budget.session_start_utc` already owns this derivation, so
    it is CALLED, never re-implemented beside it.
    """
    if not session_date:
        return None
    from broker import topstepx_session_authorization as SA
    from broker.daily_loss_budget import session_start_utc
    window = SA.window_for(session_date)
    start = session_start_utc(session_date=session_date,
                              window_start=window["start"],
                              tz_name=SA.PRODUCTION_WINDOW_TZ)
    return None if start is None else start.isoformat()


def at_the_venue(symbol: str, since_iso: str) -> dict:
    """Authenticate, pin, and READ. Positions, discovery, settled trades."""
    from broker import topstepx_order_discovery as DISC
    from broker.daily_loss_budget import budget_pnl
    from broker.topstepx_live_session import TopstepXLiveSession
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))

    session = TopstepXLiveSession()
    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get(
                    "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(symbol)
    positions = session.open_positions()
    found = DISC.discover_orders(session, contract_id=contract.id)
    trades = None
    try:
        from datetime import datetime
        trades = session.recent_trades(
            since=datetime.fromisoformat(since_iso)) if since_iso else None
    except Exception as exc:  # noqa: BLE001 -- an unread venue is UNKNOWN
        trades = None
        found = dict(found, errors=list(found.get("errors") or [])
                     + [f"recent_trades: {type(exc).__name__}: {exc}"])
    return {"contract_id": contract.id, "positions": positions,
            "found": found, "trades": trades,
            "pnl": budget_pnl(trades) if trades is not None else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--store-dir", default=STORE_DIR)
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--venue", action="store_true",
                    help="also authenticate and READ positions/orders/trades")
    args = ap.parse_args()
    S = args.session

    print(f"SESSION OUTCOME -- {S}")
    print("READ-ONLY. Nothing here is written, and nothing is inferred from "
          "terminal output.\n")

    auth = authorization(args.store_dir, S)
    print("── AUTHORIZATION ────────────────────────────────────────────────")
    if not auth["present"]:
        print(f"  {MISSING}: no session_auth_{S}.json. The session either never "
              f"issued one or wrote it elsewhere; ARM STATE IS UNKNOWN.")
        session_date = ""
    else:
        d = auth["doc"]
        session_date = str(d.get("session_date") or "")
        for key in ("session_id", "session_date", "issued_at", "armed",
                    "maximum_trades", "maximum_attempts_per_trade",
                    "daily_loss_budget_usd", "maximum_risk_per_trade",
                    "maximum_contracts", "absolute_stop_ceiling",
                    "brain_model", "account_fingerprint",
                    "brain_contract_fingerprint"):
            if key in d:
                print(f"  {key:<28}: {d[key]}")

    print("\n── MISSIONS ─────────────────────────────────────────────────────")
    ms = missions(args.store_dir, S)
    if not ms:
        print("  0 missions. NO TRADE MISSION WAS EVER OPENED this session.")
        print("  (an explicit zero: the store was read and held no "
              f"trade_mission_{S}_*.json)")
    for m in ms:
        print(f"  {m['mission_id']}: state={m['state']} "
              f"attempts={m['attempt_count']} token_spent={m['token_spent']} "
              f"order_id={m['order_id']} attributed={m['venue_attributed']}")

    print("\n── FLIGHT RECORDER (submissions) ────────────────────────────────")
    sub = submissions(args.store_dir, S)
    if not sub["present"]:
        print(f"  {MISSING}: {sub['path']}")
        print("  No ledger file. Combined with 0 missions this means NO ORDER "
              "WAS EVER SUBMITTED -- the recorder writes BEFORE transport, so "
              "an absent ledger cannot hide a sent order.")
    else:
        print(f"  {sub['count']} row(s) in {sub['path']}")
        for state, n in sub["states"].most_common():
            print(f"      state {state:<28} {n}")
        for op, n in sub["operations"].most_common():
            print(f"      op    {op:<28} {n}")
        for r in sub["rows"]:
            line = (f"      {r['mission_id']}  {r['operation']}  "
                    f"{r['state']}  success={r['success']}  "
                    f"order={r['venue_order_id']}")
            # errorCode 0 IS the ProjectX success code. Printing "err=0"
            # beside "success=True" reads as a failure that did not happen.
            if r["error_code"] not in (None, 0) or r["error_message"]:
                line += f"  err={r['error_code']} {r['error_message'] or ''}"
            if r["transport_exception"]:
                line += f"  TRANSPORT={r['transport_exception']}"
            print(line)

    print("\n── SCANS AND STAND-DOWNS ────────────────────────────────────────")
    dec = decisions(S)
    if not dec["present"]:
        print(f"  {MISSING}: no candidate_decisions.jsonl under {dec['root']}")
        print("  Per-scan stand-down reasons are NOT durable for this session; "
              "terminal output is the only copy and is not evidence.")
    else:
        print(f"  {dec['count']} recorded decision(s)")
        print(f"  first: {dec['first']}")
        print(f"  last : {dec['last']}")
        for (disp, reason, detail), n in dec["tally"].most_common():
            line = f"      {n:>5}  {disp}"
            if reason:
                line += f"  {reason}"
            if detail and detail != reason:
                line += f"  -- {detail}"
            print(line)
        rec = dec.get("reconciliation") or {}
        if rec:
            print(f"  reconciliation (candidate_decision_record.reconcile):")
            print(f"      {json.dumps(rec, default=str)[:400]}")
    sc = scans(S)
    print(f"  retrieval scan rows        : "
          f"{sc['count'] if sc['present'] else MISSING + ' ' + sc['path']}")
    if sc["present"]:
        print(f"    first {sc['first']}  ..  last {sc['last']}")

    print("\n── BRAIN ────────────────────────────────────────────────────────")
    bc = brain_calls(S)
    if not bc["present"]:
        print(f"  {MISSING}: no data/ai_brain/ai_calls_{S}_*.jsonl")
    else:
        print(f"  {bc['count']} call(s), highest scan number {bc['max_scan']}")
        print(f"  first {bc['first']}  ..  last {bc['last']}")
        print(f"  not-ok: {bc['not_ok']}    fallbacks: {bc['fallbacks']}")

    print("\n── INCIDENTS ────────────────────────────────────────────────────")
    inc = incidents(session_date or S.replace("PROD-", ""))
    if not inc["present"]:
        print(f"  none recorded ({inc['path']} absent)")
    else:
        print(f"  {inc['count']} incident(s) in {inc['path']}")
        for row in inc["rows"]:
            print(f"      {json.dumps(row, default=str)[:300]}")

    print("\n── TIMING BOUNDARIES ────────────────────────────────────────────")
    print("  These are THREE different instants and must not be conflated:")
    print("    entry cutoff        the authorization window's end; after it no "
          "NEW entry may be opened")
    print("    management end      protective/exit handling continues past the "
          "cutoff while a position is open")
    print("    process shutdown    when the loop actually stopped -- the last "
          "decision row above is its lower bound")
    if dec["present"]:
        print(f"  last durable decision : {dec['last']}")
    if bc["present"]:
        print(f"  last brain call       : {bc['last']}")

    print("\n── FINAL DURABLE STATE ──────────────────────────────────────────")
    # PROD-20260908 OWNER FINDING: "process stopped does not by itself identify
    # those states." It does not, and neither does this tool pretend otherwise.
    #
    # THERE IS NO SHUTDOWN RECORD. `topstepx_session_lifecycle` classifies and
    # never persists, and nothing else writes an end-of-session marker. So the
    # exit instant is NOT durable; what IS durable is the last artifact each
    # store wrote, which bounds it from below and nothing more.
    stamps = []
    if dec["present"] and dec["last"]:
        stamps.append(("last decision record", dec["last"]))
    if sc["present"] and sc["last"]:
        stamps.append(("last retrieval scan", sc["last"]))
    if bc["present"] and bc["last"]:
        stamps.append(("last brain call", bc["last"]))
    print("  SHUTDOWN TIMESTAMP  : NOT DURABLY RECORDED -- no component writes "
          "an end-of-session marker.")
    print("  Lower bound only, from the last write of each store:")
    for label, stamp in stamps:
        print(f"      {label:<22}: {stamp}")

    # ARM STATE. `--arm` is a PROCESS FLAG. The authorization authorizes; the
    # flag arms. Neither the flag nor the fact that a process once held it is
    # written anywhere, so a finished session has no durable arm state to read.
    armed_field = auth["doc"].get("armed") if auth["present"] else None
    print(f"  DURABLE ARM STATE   : "
          f"{'NONE -- --arm is a process flag, not a signed term; nothing on '
             'disk records it' if armed_field is None
             else armed_field}")

    if not auth["present"]:
        print("  AUTHORIZATION       : no durable record")
    else:
        # NOT A FIXED WORD. "UNCONSUMED" was printed unconditionally, so a
        # session that opened two missions and spent both attempts still read
        # as unconsumed -- the report contradicting the two mission lines
        # directly above it. Consumption is computed against the
        # authorization's own trade law.
        spent = sum(int(m.get("attempt_count") or 0) for m in ms)
        allowed = auth["doc"].get("maximum_trades")
        if not ms:
            state = "UNCONSUMED"
        elif allowed is not None and len(ms) >= int(allowed):
            state = (f"ENTRY AUTHORITY EXHAUSTED ({len(ms)}/{allowed} trades "
                     f"opened; no further entry was permitted)")
        else:
            state = f"PARTIALLY CONSUMED ({len(ms)}/{allowed} trades opened)"
        print(f"  AUTHORIZATION       : record present -- {state}")
        print(f"    missions opened         : {len(ms)}")
        print(f"    attempts spent          : {spent}")
        pinned = auth["doc"].get("brain_contract_fingerprint") or ""
        try:
            from ai_brain.production_model import brain_contract_fingerprint
            current = brain_contract_fingerprint()
        except Exception as exc:  # noqa: BLE001
            current = f"UNREADABLE ({type(exc).__name__})"
        print(f"    brain fingerprint bound : {pinned}")
        print(f"    brain fingerprint now   : {current}")
        if pinned and current and pinned != current:
            print("    THIS AUTHORIZATION CANNOT AUTHORIZE A FUTURE SESSION: "
                  "`verify` refuses with AUTHORIZATION_BRAIN_CONTRACT_CHANGED. "
                  "Issue a new one bound to the deployed checkout.")
        print(f"    session_date bound      : "
              f"{auth['doc'].get('session_date')} (this date only)")

    if args.venue:
        print("\n── AT THE VENUE (authenticated read) ────────────────────────")
        since = session_start_iso(session_date)
        if since is None:
            print("  P&L WINDOW UNKNOWN: without the authorization's session "
                  "date the window start cannot be derived, and UTC midnight "
                  "would let a prior session's trades leak in. Trades are NOT "
                  "read on a window this tool cannot establish.")
        else:
            print(f"  settled trades counted from : {since}")
        try:
            v = at_the_venue(args.symbol, since or "")
        except Exception as exc:  # noqa: BLE001 -- unreadable is UNKNOWN
            print(f"  UNKNOWN: the venue could not be read: "
                  f"{type(exc).__name__}: {exc}")
            print("  'we cannot see' is not 'there is nothing there'.")
            return 0
        found = v["found"]
        print(f"  contract          : {v['contract_id']}")
        print(f"  open positions    : {len(v['positions'])}")
        print(f"  order discovery   : {found['source']} "
              f"(answered={found['answered']}, complete={found['complete']})")
        if not found["complete"]:
            print("    ! INCOMPLETE. A surface that omits Suspended children "
                  "cannot prove absence. Working-order state is UNKNOWN.")
        print(f"  working orders    : {len(found['working'] or [])}")
        for err in found["errors"]:
            print(f"    ! {err}")
        if v["pnl"] is None:
            print("  P&L               : UNKNOWN (settled trades not read)")
        else:
            p = v["pnl"]
            print(f"  gross P&L         : {p['gross_session_pnl']} "
                  f"(venue profitAndLoss)")
            print(f"  fees+commissions  : {p['total_transaction_cost']}")
            print(f"  net P&L           : {p['budget_session_pnl']} "
                  f"({p['label']})")
    else:
        print("\n  (add --venue to also read positions, working orders and "
              "settled P&L from the account)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

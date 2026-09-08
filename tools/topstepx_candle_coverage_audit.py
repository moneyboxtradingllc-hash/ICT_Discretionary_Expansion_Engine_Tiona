"""READ-ONLY. What the candle store actually holds, from its own timestamps.

PROD-20260908 EVIDENCE REQUEST. A session summary reported a candle gap as a
single number. A single number cannot answer the only questions that matter:

    IS THAT NUMBER ABSENT MINUTE SLOTS, OR ELAPSED ENDPOINT TIME?
        They are different quantities and they are not close. Between two
        stored bars 90 hours apart, elapsed time is 5400 minutes while the
        absent slots the venue owed us may be a few dozen -- the rest of that
        span is a weekend the venue never printed into.

    WHICH ABSENCES ARE VERIFIED CLOSURES, WHICH ARE COLLECTION DOWNTIME, AND
    WHICH ARE NEITHER-KNOWN?
        `venue_calendar.classify` is the only authority here, and it is allowed
        to answer SPECIAL_SCHEDULE_UNKNOWN. A slot it cannot vouch for is
        reported UNKNOWN and stays UNKNOWN. It is never rounded to "closed"
        because that is the convenient answer.

    DID ANY UNEXPLAINED ABSENCE TOUCH A WINDOW A DECISION ACTUALLY READ?
        Pass --session-start/--session-end and every absence is placed against
        that window and against the lookback horizon behind it.

IT WRITES NOTHING AND OPENS NO SOCKET. It reads the append-only journal at
`data/market_data/topstepx/<contract>.jsonl` and nothing else. The journal is
legally allowed to hold duplicate and out-of-order rows (see
`market_data.canonical_history`), so the audit reports the raw shape AND the
last-occurrence-wins normalization, and never conflates them.

    python tools/topstepx_candle_coverage_audit.py \\
        --session-start 2026-09-08T07:00:00-04:00

Absences are classified by the FLOOR of each missing minute, in Eastern time,
by the same `venue_calendar` the live path uses. No schedule is restated here.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from data_feed import candle_continuity as CONT  # noqa: E402
from market_data import venue_calendar as CAL  # noqa: E402

STORE_DIR = os.path.join("data", "market_data", "topstepx")
MINUTE = timedelta(minutes=1)

#: Classes the venue calendar VERIFIES as non-printing. An absence here is
#: explained. Anything else is not, and TRADING_OPEN least of all.
VERIFIED_CLOSED = (CAL.WEEKLY_MARKET_CLOSED, CAL.SCHEDULED_DAILY_MAINTENANCE,
                   CAL.SCHEDULED_INTRADAY_TRADING_HALT)


def _parse(value):
    if not value:
        return None
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def read_journal(path: str) -> dict:
    """Raw rows, unfiltered, plus the shape the journal is IN."""
    rows, unreadable = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                CONT.parse_ts(row["timestamp"])
            except Exception:  # noqa: BLE001 -- a bad line is a fact, not a crash
                unreadable += 1
                continue
            rows.append(row)
    keys = [CONT.canonical_key(r) for r in rows]
    out_of_order = sum(1 for a, b in zip(keys, keys[1:]) if b < a)
    return {"rows": rows, "unreadable": unreadable, "raw_count": len(rows),
            "distinct": len(set(keys)), "out_of_order": out_of_order}


def classify_absences(missing: list) -> dict:
    """Bucket every absent minute by what the venue calendar says about it."""
    buckets = {"verified_closed": [], "trading_open": [], "unknown": []}
    by_rule = {}
    for moment in missing:
        verdict = CAL.classify(moment)
        klass = verdict["class"]
        by_rule.setdefault(f"{klass}: {verdict['rule']}", 0)
        by_rule[f"{klass}: {verdict['rule']}"] += 1
        if klass in VERIFIED_CLOSED:
            buckets["verified_closed"].append(moment)
        elif klass == CAL.TRADING_OPEN:
            buckets["trading_open"].append(moment)
        else:
            buckets["unknown"].append(moment)
    return {**buckets, "by_rule": by_rule}


def _runs(moments: list) -> list:
    """Contiguous minute runs, so absences are reported with real endpoints."""
    runs = []
    for moment in sorted(moments):
        if runs and moment - runs[-1][1] == MINUTE:
            runs[-1][1] = moment
        else:
            runs.append([moment, moment])
    return [{"first": a.isoformat(), "last": b.isoformat(),
             "minutes": int((b - a) / MINUTE) + 1} for a, b in runs]


def audit(path: str, *, session_start=None, session_end=None,
          horizon_minutes: int = 300) -> dict:
    journal = read_journal(path)
    if not journal["rows"]:
        return {"path": path, "empty": True}
    ordered = CONT.normalize(journal["rows"])
    first, last = CONT.canonical_key(ordered[0]), CONT.canonical_key(ordered[-1])

    # THE TWO QUANTITIES, SEPARATELY. `elapsed` is wall time between the stored
    # endpoints; `absent` is interior minute slots with no bar. Reporting one
    # under the other's name is the error this tool exists to stop.
    elapsed = int((last - first) / MINUTE)
    gaps = CONT.find_gaps(ordered)
    missing = [_parse(m) for g in gaps for m in g["missing"]]
    absent = len(missing)

    classes = classify_absences(missing)
    unexplained = classes["trading_open"]

    # WARM-UP / COLLECTION BOUNDARY. Absences before the session started are
    # not this session's blindness; they are what the archive did not have when
    # it opened. Named separately rather than folded into either side.
    pre_session = [m for m in unexplained if session_start and m < session_start]
    in_session = [m for m in unexplained
                  if session_start and m >= session_start
                  and (session_end is None or m <= session_end)]
    post_session = [m for m in unexplained
                    if session_end and m > session_end]

    # Did an unexplained absence sit inside the lookback a decision reads?
    horizon_floor = (session_start - timedelta(minutes=horizon_minutes)
                     if session_start else None)
    in_horizon = [m for m in unexplained
                  if horizon_floor and horizon_floor <= m < session_start]

    return {
        "path": path, "empty": False,
        "bytes": os.path.getsize(path),
        "journal": {k: journal[k] for k in
                    ("raw_count", "distinct", "out_of_order", "unreadable")},
        "stored_first": first.isoformat(), "stored_last": last.isoformat(),
        "stored_bars": len(ordered),
        "elapsed_minutes_between_endpoints": elapsed,
        "absent_minute_slots": absent,
        "gap_count": len(gaps),
        "absent_verified_closed": len(classes["verified_closed"]),
        "absent_unknown_schedule": len(classes["unknown"]),
        "absent_while_trading_open": len(unexplained),
        "by_rule": classes["by_rule"],
        "unexplained_runs": _runs(unexplained),
        "unknown_runs": _runs(classes["unknown"]),
        "unexplained_pre_session": len(pre_session),
        "unexplained_in_session": len(in_session),
        "unexplained_post_session": len(post_session),
        "unexplained_in_lookback_horizon": len(in_horizon),
        "horizon_minutes": horizon_minutes,
        "in_session_runs": _runs(in_session),
    }


def render(report: dict) -> None:
    print(f"\n=== {report['path']} ===")
    if report.get("empty"):
        print("  store is empty or unreadable; nothing to audit.")
        return
    j = report["journal"]
    print(f"  bytes                    : {report['bytes']}")
    print(f"  journal rows             : {j['raw_count']} raw, "
          f"{j['distinct']} distinct minutes, "
          f"{j['out_of_order']} out-of-order, {j['unreadable']} unreadable")
    print(f"  stored FIRST timestamp   : {report['stored_first']}")
    print(f"  stored LAST  timestamp   : {report['stored_last']}")
    print(f"  bars held (normalized)   : {report['stored_bars']}")
    print("  -- the two quantities, not interchangeable --")
    print(f"  elapsed minutes endpoint-to-endpoint : "
          f"{report['elapsed_minutes_between_endpoints']}")
    print(f"  ABSENT interior minute slots         : "
          f"{report['absent_minute_slots']}  in {report['gap_count']} gap(s)")
    print("  -- what the venue calendar says about those absences --")
    print(f"  verified closure (weekend/maintenance/halt) : "
          f"{report['absent_verified_closed']}")
    print(f"  UNKNOWN schedule (calendar cannot vouch)    : "
          f"{report['absent_unknown_schedule']}")
    print(f"  absent WHILE TRADING OPEN (unexplained)     : "
          f"{report['absent_while_trading_open']}")
    for rule, count in sorted(report["by_rule"].items(),
                              key=lambda kv: -kv[1]):
        print(f"      {count:>6}  {rule}")
    for label, key in (("unexplained", "unexplained_runs"),
                       ("UNKNOWN-schedule", "unknown_runs")):
        runs = report[key]
        if not runs:
            continue
        print(f"  {label} runs ({len(runs)}):")
        for run in runs[:20]:
            print(f"      {run['first']} .. {run['last']}  "
                  f"({run['minutes']} min)")
        if len(runs) > 20:
            print(f"      ... {len(runs) - 20} more")
    print("  -- placed against the session window --")
    print(f"  unexplained BEFORE session start (warm-up / collection downtime)"
          f" : {report['unexplained_pre_session']}")
    print(f"  unexplained INSIDE the session                                 "
          f" : {report['unexplained_in_session']}")
    print(f"  unexplained AFTER session end                                  "
          f" : {report['unexplained_post_session']}")
    print(f"  unexplained inside the {report['horizon_minutes']}-minute lookback "
          f"behind the open : {report['unexplained_in_lookback_horizon']}")
    for run in report["in_session_runs"]:
        print(f"      IN-SESSION HOLE {run['first']} .. {run['last']}  "
              f"({run['minutes']} min)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=STORE_DIR)
    ap.add_argument("--contract", default="",
                    help="audit one contract's journal; default is every one")
    ap.add_argument("--session-start", default="",
                    help="ISO timestamp; absences before it are named as "
                         "warm-up / collection downtime, not session blindness")
    ap.add_argument("--session-end", default="")
    ap.add_argument("--horizon-minutes", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.contract:
        paths = [os.path.join(args.store_dir,
                              f"{args.contract.replace('.', '_')}.jsonl")]
    else:
        paths = sorted(glob.glob(os.path.join(args.store_dir, "*.jsonl")))
    if not paths:
        print(f"no candle journal under {args.store_dir}")
        return 2

    reports = []
    for path in paths:
        if not os.path.exists(path):
            print(f"no candle journal at {path}")
            return 2
        reports.append(audit(path,
                             session_start=_parse(args.session_start),
                             session_end=_parse(args.session_end),
                             horizon_minutes=args.horizon_minutes))
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for report in reports:
            render(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

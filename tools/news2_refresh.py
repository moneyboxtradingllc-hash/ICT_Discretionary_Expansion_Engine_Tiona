"""NEWS-2 refresh: fetch scheduled events, headlines and market mood; persist FACTS.

    python3 tools/news2_refresh.py                 # full refresh, prints a report
    python3 tools/news2_refresh.py --no-venue      # skip the TopstepX bar read

OBSERVE-ONLY AND READ-ONLY. HTTP GET to public sources, plus (unless
--no-venue) one read-only TopstepX bar request through the write-incapable
session. It places nothing, writes nothing to any venue, calls no model, and
the trading process never reads what it persists.

Optional keys (from the environment / .env): FRED_API_KEY, FINNHUB_API_KEY.
A missing key is reported as that source being UNAVAILABLE -- never as calm.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from news.factual import brief as BRIEF                  # noqa: E402
from news.factual import calendar as CAL                 # noqa: E402
from news.factual import calendar_sources as SRC         # noqa: E402
from news.factual import headlines as HEAD               # noqa: E402
from news.factual import model as M                      # noqa: E402
from news.factual import mood as MOOD                    # noqa: E402


def _bars(minutes_back: int) -> tuple:
    """Read-only TopstepX 1m bars. Returns (bars, error)."""
    try:
        from broker.topstepx_readonly import TopstepXReadOnlySession
        s = TopstepXReadOnlySession(os.getenv("TOPSTEPX_USERNAME", ""),
                                    os.getenv("TOPSTEPX_API_KEY", ""))
        s.assert_no_write_surface()
        s.authenticate()
        s.resolve_contract(os.getenv("TOPSTEPX_CONTRACT", "MNQ"))
        return s.bars_1m(minutes_back=minutes_back), None
    except Exception as exc:  # noqa: BLE001 -- no bars is an UNKNOWN, not a crash
        return [], f"{type(exc).__name__}: {exc}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-venue", action="store_true", help="skip the TopstepX bar read")
    ap.add_argument("--bars-minutes", type=int, default=2 * 24 * 60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.getcwd(), ".env"))
    except Exception:  # noqa: BLE001
        pass

    now = M.utc_now()
    fred_key = os.getenv("FRED_API_KEY") or None
    results = [SRC.fetch_bls(now=now), SRC.fetch_fed_fomc(now=now),
               SRC.fetch_fred(api_key=fred_key, now=now), SRC.fetch_forexfactory(now=now)]
    state = CAL.build_calendar_state(results, now=now)
    cal_path = CAL.persist(state)

    bars, bars_error = ([], "skipped (--no-venue)") if args.no_venue else _bars(args.bars_minutes)
    mood = MOOD.build_mood(bars=bars, api_key=fred_key, now=now)
    if bars_error and mood["mnq_overnight"]["data_state"] == M.UNKNOWN:
        mood["mnq_overnight"]["reason"] = f"{mood['mnq_overnight']['reason']}; bars: {bars_error}"
    heads = HEAD.collect_headlines(finnhub_key=os.getenv("FINNHUB_API_KEY") or None, now=now)
    for it in heads["items"]:
        it["observed_reaction"] = HEAD.observed_reaction(it.get("published_at"), bars)
    brief = BRIEF.build_brief(now=now, calendar_state=state, headlines=heads, mood=mood)
    brief_path = BRIEF.persist(brief)

    if args.json:
        print(json.dumps(brief, indent=1, default=str))
        return 0

    print("\nNEWS-2 REFRESH -- OBSERVE-ONLY. Facts with provenance; no lean, no model call.")
    print(f"  built_at        : {state['built_at']}")
    print(f"  calendar state  : {state['data_state']}"
          + (f"  ({state['data_state_reason']})" if state['data_state_reason'] else ""))
    print(f"  calendar file   : {cal_path}")
    print(f"  brief file      : {brief_path}")
    print("\n-- SOURCES --")
    for s in state["sources"]:
        print(f"  {s['source_name']:20} {s['authority']:12} {s['status']:13} "
              f"records={s['record_count']:<4} {s['reason'] or ''}")
    for s in heads["sources"]:
        print(f"  {s['source_name']:20} {'headlines':12} {s['status']:13} "
              f"records={s['record_count']:<4} {s.get('reason') or ''}")
    print("\n-- SCHEDULED EVENTS, next 7 days (ET) --")
    horizon = now.timestamp() + 7 * 86400
    shown = 0
    for e in state["events"]:
        t = M.parse_instant(e["scheduled_at"])
        if t is None or not (now.timestamp() - 3600 <= t.timestamp() <= horizon):
            continue
        shown += 1
        srcs = ",".join(sorted({r["source_name"] for r in e["sources"]}))
        print(f"  {e['scheduled_local'][:16]}  {e['category']:15} {e['data_state']:8} "
              f"{e['cross_check_status']:13} basis={e['time_basis']:17} "
              f"impact={e['impact_class'] or '-':6} sources={srcs}")
        for c in e["conflicts"]:
            print(f"        CONFLICT {c['source']}: {c['scheduled_at']}")
    if not shown:
        print("  none in the next 7 days -- read this together with the source "
              "statuses above; an empty list is only meaningful when sources are ok")
    cats = sorted({e["category"] for e in state["events"]})
    missing = [c for c in M.CATEGORIES if c not in cats]
    print(f"\n  categories seen : {', '.join(cats) or 'none'}")
    print(f"  never seen      : {', '.join(missing) or 'none'} "
          f"(not in any source window -- not the same as 'no event')")

    print("\n-- MARKET MOOD (facts; FRED values are delayed daily closes) --")
    mo = mood["mnq_overnight"]
    print(f"  MNQ overnight   : {mo['data_state']}  "
          + (f"{mo.get('move_points')} pts ({mo.get('move_pct')}%) vs {mo.get('prior_close_at')}"
             if mo['data_state'] != M.UNKNOWN else (mo.get('reason') or '')))
    for sid, v in mood["series"].items():
        print(f"  {sid:15} : {v['data_state']:8} value={v.get('value')} "
              f"observation_date={v.get('observation_date')} age_days={v.get('age_days')} "
              f"{v.get('reason') or ''}")
    print(f"\n-- HEADLINES: {len(heads['items'])} in the last {heads['lookback_hours']:g}h "
          f"({heads['data_state']}) --")
    for it in heads["items"][:10]:
        print(f"  {str(it.get('published_at'))[:16]}  [{it['source_name']}] {it['headline'][:100]}")
    print("\nNothing above was given to the Brain, the scan or any execution path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

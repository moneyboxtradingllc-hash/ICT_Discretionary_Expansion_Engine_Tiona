"""NEWS-2 event-window MEASUREMENT for one session. Read-only; decides nothing.

    python3 tools/news2_event_window_audit.py --session PROD-20260928

For every recorded scan decision it answers, from the calendar snapshot that
existed at that moment: was a scheduled event inside -15/+15, -10/+5 or -5/+5
minutes, and what did the bot decide? It is post-session telemetry for a future
owner ruling on blackouts. It blocks nothing and changes nothing.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from news.factual import calendar as CAL                 # noqa: E402
from news.factual import model as M                      # noqa: E402


def load_decisions(session: str, root: str = "data/replay_sessions") -> list:
    path = os.path.join(root, session, "memory_retrieval", "candidate_decisions.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def audit(decisions: list, *, store_dir: str = CAL.STORE_DIR) -> dict:
    per_window = collections.defaultdict(lambda: collections.Counter())
    rows, no_calendar = [], 0
    for d in decisions:
        ts = M.parse_instant(d.get("timestamp_et") or d.get("timestamp"))
        if ts is None:
            continue
        state = CAL.load_latest(store_dir, at=ts)
        facts = CAL.event_window_facts(ts, state)
        if not state:
            no_calendar += 1
        disp = d.get("final_disposition")
        for name, w in facts["windows"].items():
            per_window[name]["inside" if w["inside"] else "outside"] += 1
            if w["inside"]:
                per_window[name][f"inside:{disp}"] += 1
                rows.append({"at": M.iso(ts), "window": name, "disposition": disp,
                             "events": [e["name"] for e in w["events"]]})
    return {"decisions": len(decisions), "without_calendar": no_calendar,
            "windows": {k: dict(v) for k, v in per_window.items()}, "inside_rows": rows}


def price_reactions(session: str, *, bars=None, store_dir: str = CAL.STORE_DIR) -> list:
    """MNQ move from each tier-1 event's minute to +5/+15/+30. Measured, not judged."""
    from news.factual.headlines import observed_reaction
    day = session.rsplit("-", 1)[-1]
    if bars is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.getcwd(), ".env"))
        except Exception:  # noqa: BLE001
            pass
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from news2_refresh import _bars
        bars, _err = _bars(3 * 24 * 60)
    state = CAL.load_latest(store_dir)
    out = []
    for e in (state or {}).get("events") or []:
        t = M.parse_instant(e.get("scheduled_at"))
        if t is None or t.astimezone(M.ET).strftime("%Y%m%d") != day:
            continue
        if e["category"] not in M.ANALYSIS_TIER1:
            continue
        out.append({"event": e["name"], "category": e["category"],
                    "scheduled_at": e["scheduled_at"],
                    "reaction": observed_reaction(e["scheduled_at"], bars,
                                                  horizons=(5, 15, 30))})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-price", action="store_true",
                    help="read-only TopstepX bars: MNQ move around each tier-1 event")
    args = ap.parse_args(argv)
    out = audit(load_decisions(args.session))
    if args.with_price:
        out["event_price_reaction"] = price_reactions(args.session)
    if args.json:
        print(json.dumps(out, indent=1, default=str))
        return 0
    print(f"\nNEWS-2 EVENT-WINDOW AUDIT -- {args.session} -- MEASUREMENT ONLY")
    print(f"  decisions            : {out['decisions']}")
    print(f"  with no calendar     : {out['without_calendar']} "
          f"(UNKNOWN -- not counted as 'no event')")
    for name, c in out["windows"].items():
        print(f"  window {name:8}: {c}")
    for r in out["inside_rows"][:40]:
        print(f"    {r['at'][:19]}  {r['window']:8} {r['disposition']:18} {', '.join(r['events'])}")
    for r in out.get("event_price_reaction") or []:
        print(f"  price around {r['category']:14} {r['scheduled_at'][:16]}: {r['reaction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

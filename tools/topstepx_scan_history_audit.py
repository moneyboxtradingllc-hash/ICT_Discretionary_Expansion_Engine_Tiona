"""READ-ONLY. What history each scan ACTUALLY held, from the archived snapshots.

PROD-20260908 OWNER FINDING. A post-session, REST-healed store cannot establish
what an earlier scan had available: the store was repaired at startup, and every
scan after that reads a tape the store no longer resembles. Reading source to
argue a window "must have" failed closed is not evidence either. The archived
per-scan snapshots ARE the evidence -- they hold the exact 1m tape handed to the
Brain and the session-context statuses as they stood at decision time.

    data/ai_brain/<yyyymmdd>_<hhmmss>_MNQ.json
        raw_snapshot.timeframes.1m.recent_candles   the history the scan used
        raw_snapshot.session_context.contexts[]     per-window status at that
                                                    scan, UNAVAILABLE_HISTORY
                                                    included

THREE OUTCOMES, NAMED APART, because collapsing them is the error this exists
to prevent:

    WITHHELD          the window resolved UNAVAILABLE_HISTORY (or carried no
                      coverage), so incomplete levels were NOT published to the
                      Brain. Absence was declared.
    AVAILABLE         the window carried facts. Context was there.
    HOLED             the 1m tape the scan actually used was itself
                      discontinuous. This is the one that would matter, and it
                      is reported per scan rather than argued from the loop's
                      source.

"missing history had no effect" is a CONCLUSION, and this tool does not draw
it. It reports which scans were withheld, which were available, and whether any
scan's own tape was holed.

    python tools/topstepx_scan_history_audit.py --day 20260908
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

from data_feed import candle_continuity as CONT  # noqa: E402

ARCHIVE = os.path.join("data", "ai_brain")


def _snapshot(path: str) -> "dict | None":
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("raw_snapshot")
    except Exception:  # noqa: BLE001 -- an unreadable archive row is a fact
        return None


def audit_one(path: str) -> dict:
    snap = _snapshot(path)
    if not isinstance(snap, dict):
        return {"path": path, "readable": False}

    bars = (((snap.get("timeframes") or {}).get("1m") or {})
            .get("recent_candles") or [])
    ordered = CONT.normalize([b for b in bars if isinstance(b, dict)])
    gaps = CONT.find_gaps(ordered) if ordered else []
    first = CONT.canonical_key(ordered[0]).isoformat() if ordered else None
    last = CONT.canonical_key(ordered[-1]).isoformat() if ordered else None

    ctx = snap.get("session_context") or {}
    contexts = (ctx.get("contexts") or {}) if isinstance(ctx, dict) else {}
    statuses = {}
    for name, block in contexts.items():
        if isinstance(block, dict):
            statuses[name] = str(block.get("status"))

    return {"path": path, "readable": True,
            "bars": len(ordered), "first": first, "last": last,
            "gap_count": len(gaps),
            "missing_minutes": sum(g["missing_minutes"] for g in gaps),
            "gaps": [(g["first_missing"], g["last_missing"]) for g in gaps[:3]],
            "context_available": bool(ctx.get("available")) if ctx else False,
            "statuses": statuses}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="yyyymmdd")
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--instrument", default="MNQ")
    ap.add_argument("--show-holed", type=int, default=10)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(
        args.archive, f"{args.day}_*_{args.instrument}.json")))
    if not paths:
        print(f"no archived snapshots matching "
              f"{args.day}_*_{args.instrument}.json under {args.archive}")
        return 2

    rows = [audit_one(p) for p in paths]
    readable = [r for r in rows if r["readable"]]
    print(f"SCAN HISTORY AUDIT -- {args.day} {args.instrument}")
    print(f"  archived snapshots : {len(rows)} "
          f"({len(rows) - len(readable)} unreadable)")
    if not readable:
        return 3

    holed = [r for r in readable if r["gap_count"]]
    empty = [r for r in readable if r["bars"] == 0]
    print("\n── THE 1m TAPE EACH SCAN ACTUALLY USED ─────────────────────────")
    print(f"  scans with a CONTINUOUS window : "
          f"{len(readable) - len(holed) - len(empty)}")
    print(f"  scans with a HOLED window      : {len(holed)}")
    print(f"  scans with NO bars at all      : {len(empty)}")
    bars = [r["bars"] for r in readable if r["bars"]]
    if bars:
        print(f"  bars per scan                  : min {min(bars)}, "
              f"max {max(bars)}")
        print(f"  earliest bar in any scan       : "
              f"{min(r['first'] for r in readable if r['first'])}")
        print(f"  latest bar in any scan         : "
              f"{max(r['last'] for r in readable if r['last'])}")
    for r in holed[:args.show_holed]:
        print(f"    HOLED {os.path.basename(r['path'])}: "
              f"{r['missing_minutes']} missing across {r['gap_count']} gap(s) "
              f"{r['gaps']}")
    if len(holed) > args.show_holed:
        print(f"    ... {len(holed) - args.show_holed} more")

    print("\n── SESSION CONTEXT AT DECISION TIME ────────────────────────────")
    unavailable_block = sum(1 for r in readable if not r["context_available"])
    print(f"  scans where the whole block was unavailable : {unavailable_block}")
    per_window = collections.defaultdict(collections.Counter)
    for r in readable:
        for name, status in r["statuses"].items():
            per_window[name][status] += 1
    if not per_window:
        print("  no per-window statuses recorded in these snapshots")
    for name in sorted(per_window):
        counts = ", ".join(f"{s}={n}" for s, n in
                           per_window[name].most_common())
        print(f"    {name:<28} {counts}")

    print("\n── WHAT THIS DOES AND DOES NOT ESTABLISH ───────────────────────")
    print("  ESTABLISHED: whether each scan's own 1m tape was continuous, and")
    print("  which context windows declared absence rather than publishing")
    print("  incomplete levels.")
    print("  NOT ESTABLISHED HERE: that missing history had no effect. That is")
    print("  a conclusion about the decision, not a property of the record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""COGNITION-ESCALATION-ROUTER-1 -- diagnostic. READ ONLY, NO RULE CHANGE.

Dumps one record per replayable archived scan (flags + clauses + denominators)
so selectivity can be judged from evidence instead of from a single headline
percentage. Nothing here proposes a rule; the leave-one-clause-out table is a
DIAGNOSTIC, not a search for a winner.

No provider call, no broker call, no paid run.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from shadow_router_replay import replay_day, ARCHIVE  # noqa: E402

DESIGN_DAY = "20260824"

CLAUSES = ("R1_path_contested", "R2_bidirectional", "R3_counter+intervening",
           "R4_counter+transfer")


def clause_map(rec):
    p = rec["predicates"]
    counter = p["counter_path_at_location"]
    return {
        "R1_path_contested": p["path_contested"],
        "R2_bidirectional": p["bidirectional_at_location"],
        "R3_counter+intervening": counter and p["intervening_protected_structure"],
        "R4_counter+transfer": counter and p["transfer_evidence_present"],
    }


def dump(days, out_path):
    records = []
    for day in days:
        for rec in replay_day(day):
            p = rec["predicates"]
            records.append({
                "day": day,
                "file": rec["_file"],
                "tier": rec["tier"],
                "eligible": rec["_eligible"],
                "at_location": rec["at_location_count"],
                "owner": rec["path_owner"],
                "status": rec["path_status"],
                "directions": rec["directions_at_location"],
                "flags": p,
                "clauses": clause_map(rec),
            })
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh)
    return records


def pct(a, b):
    return f"{a/b:6.1%}" if b else "     -"


def flag_table(records):
    print("\n" + "=" * 92)
    print("B. INDEPENDENT FACTUAL FLAGS -- per session (count / rate of that session's scans)")
    print("=" * 92)
    flags = ("path_contested", "bidirectional_at_location",
             "counter_path_at_location", "intervening_protected_structure",
             "transfer_evidence_present", "path_state_unavailable")
    by_day = collections.defaultdict(list)
    for r in records:
        by_day[r["day"]].append(r)
    print(f"{'session':>10} {'scans':>6} " + " ".join(f"{f[:15]:>16}" for f in flags))
    for day in sorted(by_day):
        rows = by_day[day]
        n = len(rows)
        cells = []
        for f in flags:
            c = sum(1 for r in rows if r["flags"][f])
            cells.append(f"{c:5d} {pct(c, n)}"[:16].rjust(16))
        print(f"{day:>10} {n:6d} " + " ".join(cells))
    n = len(records)
    cells = []
    for f in flags:
        c = sum(1 for r in records if r["flags"][f])
        cells.append(f"{c:5d} {pct(c, n)}"[:16].rjust(16))
    print(f"{'ALL':>10} {n:6d} " + " ".join(cells))


def clause_table(records):
    print("\n" + "=" * 92)
    print("B2. ROUTING CLAUSES -- which clause actually fires")
    print("=" * 92)
    by_day = collections.defaultdict(list)
    for r in records:
        by_day[r["day"]].append(r)
    print(f"{'session':>10} {'scans':>6} {'terra':>6} " +
          " ".join(f"{c:>24}" for c in CLAUSES))
    for day in sorted(by_day) + ["ALL"]:
        rows = records if day == "ALL" else by_day[day]
        n = len(rows)
        t = sum(1 for r in rows if r["tier"] == "terra_shadow")
        cells = [f"{sum(1 for r in rows if r['clauses'][c]):5d} "
                 f"{pct(sum(1 for r in rows if r['clauses'][c]), n)}".rjust(24)
                 for c in CLAUSES]
        print(f"{day:>10} {n:6d} {t:6d} " + " ".join(cells))

    print("\n  CLAUSE OVERLAP (terra scans only, whole corpus):")
    combos = collections.Counter()
    for r in records:
        if r["tier"] != "terra_shadow":
            continue
        combos[" + ".join(c for c in CLAUSES if r["clauses"][c])] += 1
    terra = sum(combos.values())
    for combo, c in combos.most_common():
        print(f"    {c:5d}  {pct(c, terra)} of terra   {combo}")

    print("\n  SOLE-CAUSE ANALYSIS (terra scans where exactly ONE clause fired):")
    for c in CLAUSES:
        sole = sum(1 for r in records if r["tier"] == "terra_shadow"
                   and [k for k in CLAUSES if r["clauses"][k]] == [c])
        print(f"    {c:>24}  sole cause on {sole:5d} scans  {pct(sole, terra)} of terra")


def denominator_table(records, label):
    print("\n" + "=" * 92)
    print(f"C. DENOMINATORS -- {label}")
    print("=" * 92)
    sets = {
        "1. all replayable decision scans": records,
        "2. scans with a tool AT LOCATION": [r for r in records if r["at_location"] > 0],
        "3. scans with an EXECUTION-ELIGIBLE tool": [r for r in records if r["eligible"] > 0],
        "3b. at-location AND eligible": [r for r in records
                                         if r["at_location"] > 0 and r["eligible"] > 0],
    }
    for name, rows in sets.items():
        n = len(rows)
        t = sum(1 for r in rows if r["tier"] == "terra_shadow")
        print(f"  {name:<44} scans {n:5d}   terra {t:5d}  {pct(t, n)}")


def counterfactual(records, label):
    print("\n" + "=" * 92)
    print(f"D. LEAVE-ONE-CLAUSE-OUT (diagnostic only, no rule change) -- {label}")
    print("=" * 92)
    n = len(records)
    full = sum(1 for r in records if any(r["clauses"].values()))
    print(f"  {'full current rule':<34} terra {full:5d}  {pct(full, n)}")
    for drop in CLAUSES:
        t = sum(1 for r in records
                if any(v for k, v in r["clauses"].items() if k != drop))
        delta = full - t
        print(f"  {'minus ' + drop:<34} terra {t:5d}  {pct(t, n)}"
              f"   (removes {delta:5d} scans)")
    print("\n  EACH CLAUSE ALONE:")
    for only in CLAUSES:
        t = sum(1 for r in records if r["clauses"][only])
        print(f"  {'only ' + only:<34} terra {t:5d}  {pct(t, n)}")


def specimens(records):
    print("\n" + "=" * 92)
    print("E. SPECIMEN AUDIT -- 2026-08-24")
    print("=" * 92)
    want = ("101000", "104257", "105200", "105715", "112052")
    for r in records:
        if r["day"] != DESIGN_DAY:
            continue
        stamp = r["file"].split("_")[1]
        if stamp not in want:
            continue
        f = r["flags"]
        print(f"\n  [{stamp[:2]}:{stamp[2:4]}:{stamp[4:]}]  ->  {r['tier'].upper()}")
        print(f"     active path            owner={r['owner']}  status={r['status']}")
        print(f"     at-location            {r['at_location']} rows, directions={r['directions'] or '-'}")
        print(f"     counter_path           {f['counter_path_at_location']}")
        print(f"     bidirectional          {f['bidirectional_at_location']}")
        print(f"     intervening structure  {f['intervening_protected_structure']}")
        print(f"     transfer evidence      {f['transfer_evidence_present']}")
        print(f"     path_contested         {f['path_contested']}")
        fired = [c for c in CLAUSES if r["clauses"][c]]
        print(f"     clauses fired          {', '.join(fired) or 'none'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "ai_shadow",
                                                    "router_diagnostic_records.json"))
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    if args.rebuild or not os.path.exists(args.cache):
        days = sorted({os.path.basename(f)[:8]
                       for f in glob.glob(os.path.join(ARCHIVE, "*_MNQ.json"))})
        os.makedirs(os.path.dirname(args.cache), exist_ok=True)
        records = dump(days, args.cache)
    else:
        with open(args.cache, encoding="utf-8") as fh:
            records = json.load(fh)

    print(f"replayable scans: {len(records)}")
    flag_table(records)
    clause_table(records)
    denominator_table(records, "WHOLE CORPUS")
    ex = [r for r in records if r["day"] != DESIGN_DAY]
    denominator_table(ex, "EXCLUDING the design day 2026-08-24")
    counterfactual(records, "WHOLE CORPUS")
    counterfactual(ex, "EXCLUDING 2026-08-24")
    counterfactual([r for r in records if r["day"] == DESIGN_DAY], "2026-08-24 ONLY")
    specimens(records)


if __name__ == "__main__":
    main()

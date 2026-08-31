"""COGNITION-ESCALATION-ROUTER-1 -- archived escalation rates. READ ONLY.

No provider is called and no paid run is performed: this replays snapshots the
organism already archived and asks what the router WOULD have said.

WHY ACTIVE PATH IS RECOMPUTED, NOT READ. `active_path_state` only began being
written into the archive on the evening of 2026-08-24, so reading it would give
one partial day and ten empty ones. The path is therefore rebuilt exactly the
way production builds it -- `extract_occurrences` per scan into an `ActivePath`
that carries across the session -- which is the same replay the ACTIVE-PATH
suite certifies against.

COST IS ESTIMATED FROM THE EXISTING SHOOTOUT, never from a new paid run:
luna $0.011/call, terra $0.131/call (lean shootout, 2026-08-24, 37 calls).
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

from cognition.escalation_router import (LUNA_SHADOW,  # noqa: E402
                                         TERRA_SHADOW, route)
from market_state.active_path import ActivePath, extract_occurrences  # noqa: E402
from broker.luna_candidate_producer import (authorized_objective_catalog,  # noqa: E402
                                            authorized_tool_catalog)
from ai_brain.brain_input import build_brain_input                   # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")

COST_PER_CALL = {LUNA_SHADOW: 0.011, TERRA_SHADOW: 0.131}


def _payload(snapshot):
    """Rebuild the PRODUCTION pre-provider payload for this archived scan.

    An earlier version of this tool resolved the reference price by walking
    snapshot keys by hand and got `None` on all 975 scans -- `execution_price`
    publishes `best_bid`/`best_ask`/`last_trade` and deliberately no
    `current_price`, because EXEC-PRICE-FRESHNESS forbids a settled close from
    masquerading as an executable one. The objective catalog was therefore
    always empty and the `counter_path + intervening` clause could never fire:
    a measurement artefact that read exactly like a finding.

    So the reference comes from the same authority production uses, and the
    catalogs are the production functions themselves. No second pricing model.
    """
    bi = build_brain_input(snapshot, {"available": False})
    ref = (bi.get("market") or {}).get("current_price")
    try:
        bi["authorized_objectives"] = authorized_objective_catalog(
            snapshot, bi, ref)
    except Exception:  # noqa: BLE001
        bi["authorized_objectives"] = []
    return bi


def replay_day(day, limit=None):
    files = sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json")))
    if limit:
        files = files[:limit]
    ap, prior, rows = ActivePath(), {}, []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        contract = snap.get("contract_id") or "CON.F.US.MNQ.U26"
        try:
            ap.enforce_lifecycle(snap.get("timestamp"), contract)
            occ = extract_occurrences(snap, prior, contract)
            ap.ingest(occ)
            prior = ((snap.get("protected_swings") or {}).get("by_timeframe")
                     or prior)
            aps = ap.state()
            ap.mark_scan_end()
        except Exception:  # noqa: BLE001
            aps = {"state_available": False,
                   "unavailable_reason": "path_state_unavailable"}
        try:
            bi = _payload(snap)
            cat = bi.get("authorized_tool_catalog") or []
            objs = bi.get("authorized_objectives") or []
        except Exception:  # noqa: BLE001
            bi = {}
            try:
                cat = authorized_tool_catalog(snap)
            except Exception:  # noqa: BLE001
                cat = []
            objs = []
        ref = (bi.get("market") or {}).get("current_price") if isinstance(bi, dict) else None
        v = route(active_path_state=aps, tool_catalog=cat, objective_catalog=objs,
                  reference_price=ref, tick_size=0.25)
        v["_file"] = os.path.basename(f)
        v["_eligible"] = sum(1 for r in cat if r.get("execution_eligible"))
        rows.append(v)
    return rows


def summarise(rows, label):
    n = len(rows)
    if not n:
        print(f"  {label}: no scans")
        return None
    terra = [r for r in rows if r["tier"] == TERRA_SHADOW]
    at_loc = [r for r in rows if r["at_location_count"] > 0]
    opp = [r for r in rows if r["_eligible"] > 0]
    unavail = [r for r in rows if r["predicates"]["path_state_unavailable"]]

    reasons = collections.Counter()
    overlaps = collections.Counter()
    for r in terra:
        for reason in r["reasons"]:
            reasons[reason] += 1
        overlaps[" + ".join(r["reasons"])] += 1

    blended = (len(terra) * COST_PER_CALL[TERRA_SHADOW]
               + (n - len(terra)) * COST_PER_CALL[LUNA_SHADOW])
    all_luna = n * COST_PER_CALL[LUNA_SHADOW]
    all_terra = n * COST_PER_CALL[TERRA_SHADOW]

    print(f"\n{label}")
    print(f"  scans                     {n}")
    print(f"  luna_shadow               {n - len(terra):5d}  {(n-len(terra))/n:6.1%}")
    print(f"  terra_shadow              {len(terra):5d}  {len(terra)/n:6.1%}")
    if at_loc:
        t = sum(1 for r in at_loc if r["tier"] == TERRA_SHADOW)
        print(f"  at-location scans only    {len(at_loc):5d}  terra {t/len(at_loc):6.1%}")
    if opp:
        t = sum(1 for r in opp if r["tier"] == TERRA_SHADOW)
        print(f"  eligible-candidate only   {len(opp):5d}  terra {t/len(opp):6.1%}")
    print(f"  path_state_unavailable    {len(unavail):5d}  {len(unavail)/n:6.1%}")
    if reasons:
        print("  reason frequency:")
        for reason, c in reasons.most_common():
            print(f"      {c:5d}  {c/n:6.1%}  {reason}")
        print("  reason combinations:")
        for combo, c in overlaps.most_common():
            print(f"      {c:5d}  {combo}")
    print(f"  cost  blended ${blended:7.3f} | all-luna ${all_luna:7.3f} "
          f"| all-terra ${all_terra:7.3f}")
    return {"scans": n, "terra": len(terra), "blended": blended,
            "all_luna": all_luna, "all_terra": all_terra}


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--days", nargs="*", default=None)
    ap_.add_argument("--limit", type=int, default=None)
    args = ap_.parse_args()

    days = args.days or sorted({os.path.basename(f)[:8]
                                for f in glob.glob(os.path.join(ARCHIVE, "*_MNQ.json"))})
    print("=" * 78)
    print("  COGNITION-ESCALATION-ROUTER-1  --  archived shadow rates (no paid calls)")
    print("=" * 78)

    everything, totals = [], []
    for day in days:
        rows = replay_day(day, args.limit)
        s = summarise(rows, f"[{day}]")
        if s:
            totals.append(s)
        everything.extend(rows)

    summarise(everything, "[ALL SESSIONS]")
    if totals:
        b = sum(t["blended"] for t in totals)
        l = sum(t["all_luna"] for t in totals)
        t_ = sum(t["all_terra"] for t in totals)
        print(f"\n  corpus cost: blended ${b:.2f} vs all-luna ${l:.2f} "
              f"vs all-terra ${t_:.2f}")
        if t_ > l:
            print(f"  blended captures {(t_-b)/(t_-l):6.1%} of the saving "
                  f"between all-terra and all-luna")


if __name__ == "__main__":
    main()

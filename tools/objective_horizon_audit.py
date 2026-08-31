"""OBJECTIVE-HORIZON CONFLICT -- audit only. NO ROUTER AUTHORITY, NO RULE CHANGE.

Asks one question: can existing PRE-PROVIDER catalogs truthfully express the
complexity R3 was reaching for, WITHOUT inventing new market intelligence?

The concept is NOT "protected structure exists somewhere ahead" (that was R3,
which withheld 0 of 224 counter-path scans and so was just `counter_path`). It
is a genuine HORIZON CHOICE on the side the trade would actually be taken:

    a nearer authorised objective that is structurally defensible
    AND a farther authorised objective on the same side
    that can only be reached THROUGH intact protected structure

Every field used here already exists and is already published to the Brain --
`valid_for`, `price`, `protected_level_between_entry_and_target`,
`nearest_intervening_protected_level`. Nothing is recomputed and no new
detector is built.

Two variants are measured, weakest first:

    A  near.protected_between is False AND far.protected_between is True
    B  A, and additionally the far objective's nearest intervening level IS the
       near objective itself -- the near objective is the thing standing in the
       way, which is the 2026-08-24 10:52 shape exactly

MIRROR-SYMMETRIC by construction: the side is chosen as OPPOSITE(owner), so a
bullish reaction inside a bearish path is tested identically. No level, price or
direction from any specific session appears anywhere in this file.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from market_state.active_path import ActivePath, extract_occurrences  # noqa: E402
from cognition.escalation_router import (AT_LOCATION_RELATIONS,  # noqa: E402
                                         OPPOSITE)
from shadow_router_replay import _payload, ARCHIVE  # noqa: E402


def horizon_conflict(objectives, direction, reference):
    """Is there a near/far horizon CHOICE on `direction`'s side?

    Returns (variant_a, variant_b, detail). Truthful about absence: fewer than
    two objectives on the side is not a conflict, it is one option.
    """
    if not direction or reference is None:
        return False, False, None
    side = [o for o in (objectives or [])
            if isinstance(o, dict) and o.get("valid_for") == direction
            and o.get("price") is not None]
    if len(side) < 2:
        return False, False, None
    side.sort(key=lambda o: abs(float(o["price"]) - float(reference)))
    near = side[0]
    near_clean = not near.get("protected_level_between_entry_and_target")
    if not near_clean:
        # Even the nearest objective is behind structure: there is no
        # defensible near destination to choose, so there is no CHOICE.
        return False, False, None
    blocked = [o for o in side[1:]
               if o.get("protected_level_between_entry_and_target")]
    if not blocked:
        return False, False, None
    a = True
    # Variant B: the near objective IS the structure the far one must cross.
    try:
        npx = round(float(near["price"]), 4)
        b = any(o.get("nearest_intervening_protected_level") is not None
                and round(float(o["nearest_intervening_protected_level"]), 4) == npx
                for o in blocked)
    except (TypeError, ValueError):
        b = False
    detail = {"near": near.get("objective_id"), "near_price": near.get("price"),
              "far": [o.get("objective_id") for o in blocked],
              "far_price": [o.get("price") for o in blocked],
              "blocking_level": blocked[0].get("nearest_intervening_protected_level")}
    return a, b, detail


def audit_day(day):
    ap, prior, out = ActivePath(), {}, []
    for f in sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        contract = snap.get("contract_id") or "CON.F.US.MNQ.U26"
        try:
            ap.enforce_lifecycle(snap.get("timestamp"), contract)
            ap.ingest(extract_occurrences(snap, prior, contract))
            prior = ((snap.get("protected_swings") or {}).get("by_timeframe") or prior)
            aps = ap.state()
            ap.mark_scan_end()
        except Exception:  # noqa: BLE001
            aps = {"state_available": False}
        try:
            bi = _payload(snap)
        except Exception:  # noqa: BLE001
            continue
        cat = bi.get("authorized_tool_catalog") or []
        objs = bi.get("authorized_objectives") or []
        ref = (bi.get("market") or {}).get("current_price")

        owner = aps.get("owner") if aps.get("state_available") is not False else None
        owner = owner if owner in ("bullish", "bearish") else None
        at_loc = [r for r in cat
                  if str(r.get("price_relation") or "") in AT_LOCATION_RELATIONS]
        counter_dir = OPPOSITE[owner] if owner else None
        counter = bool(counter_dir) and any(
            str(r.get("direction")) == counter_dir for r in at_loc)

        a, b, detail = horizon_conflict(objs, counter_dir, ref)
        out.append({"day": day, "file": os.path.basename(f), "owner": owner,
                    "status": aps.get("status"), "at_location": len(at_loc),
                    "counter_path": counter, "horizon_a": bool(counter and a),
                    "horizon_b": bool(counter and b), "detail": detail,
                    "n_objectives": len(objs), "reference": ref})
    return out


def main():
    days = sorted({os.path.basename(f)[:8]
                   for f in glob.glob(os.path.join(ARCHIVE, "*_MNQ.json"))})
    recs = []
    for d in days:
        recs += audit_day(d)

    out = os.path.join(ROOT, "data", "ai_shadow", "objective_horizon_records.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(recs, fh)

    print("=" * 94)
    print("  OBJECTIVE-HORIZON CONFLICT -- discrimination against counter-path")
    print("=" * 94)
    by = collections.defaultdict(list)
    for r in recs:
        by[r["day"]].append(r)
    hdr = (f"{'session':>10} {'scans':>6} {'counter':>8} "
           f"{'horizonA':>9} {'withheld':>9} {'horizonB':>9} {'withheldB':>10}")
    print(hdr)

    def line(label, rows):
        cp = [r for r in rows if r["counter_path"]]
        a = sum(1 for r in cp if r["horizon_a"])
        b = sum(1 for r in cp if r["horizon_b"])
        wa = f"{(len(cp)-a)/len(cp):8.1%}" if cp else "       -"
        wb = f"{(len(cp)-b)/len(cp):9.1%}" if cp else "        -"
        print(f"{label:>10} {len(rows):6d} {len(cp):8d} {a:9d} {wa:>9} {b:9d} {wb:>10}")

    for d in sorted(by):
        line(d, by[d])
    line("ALL", recs)
    line("EX-0824", [r for r in recs if r["day"] != "20260824"])


if __name__ == "__main__":
    main()

"""HORIZON-A vs HORIZON-B -- final design gate. AUDIT ONLY, NO ROUTER AUTHORITY.

Both predicates are built from published objective facts only. Nothing here
reads Luna output, a selected target, model confidence, future price, a
timestamp, or an objective_id's NAME -- ids are carried for reporting and are
never semantic authority.

DIRECTIONAL ORDERING LAW (no cross-side mixing, no array order):

    bearish counter-path trade:   reference > near > far
    bullish counter-path trade:   reference < near < far

Near/far come from SIGNED directional distance against the canonical reference
price, and every objective must be `valid_for` the counter-path direction.

STRUCTURAL IDENTITY, HONESTLY BOUNDED. `enumerate_objectives` builds
protected-swing objectives from `protected_swings.protected_high/low`, while the
intervening rows come from `protected_swings.by_timeframe` -- two views of one
tracker that share no `swing_id`. No persistent structural identifier exists to
join them, and this unit does not invent one. HORIZON-B therefore asserts
PRICE identity, tick-tolerant, plus side/kind agreement. That limitation is
reported, not hidden.
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
                                         OPPOSITE, route)
from shadow_router_replay import _payload, ARCHIVE  # noqa: E402

#: MNQ venue tick. Passed in for the comparison; NOT baked into the predicate.
MNQ_TICK = 0.25


def same_level(a, b, tick_size=None) -> bool:
    """Do two prices denote ONE structural level?

    Raw float equality would make the predicate depend on producer rounding, so
    equality is tick-tolerant: within half a tick is the same tradeable price.
    """
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if tick_size and float(tick_size) > 0:
        return abs(a - b) <= float(tick_size) / 2.0
    return round(a, 4) == round(b, 4)


def _signed_distance(price, reference, direction):
    """Positive = further along the trade's own direction. Never absolute."""
    return (reference - price) if direction == "bearish" else (price - reference)


def horizon(objectives, direction, reference, tick_size=None):
    """Return (A, B, detail). Truthful about absence: one option is no choice."""
    if not direction or reference is None:
        return False, False, None
    side = []
    for o in (objectives or []):
        if not isinstance(o, dict) or o.get("valid_for") != direction:
            continue
        if o.get("price") is None:
            continue
        d = _signed_distance(float(o["price"]), float(reference), direction)
        # ORDERING LAW: an objective behind the entry is not a horizon at all.
        if d <= 0:
            continue
        side.append((d, o))
    if len(side) < 2:
        return False, False, None
    side.sort(key=lambda t: t[0])

    # Collapse duplicate levels so one structural level cannot masquerade as a
    # near/far PAIR and manufacture a conflict out of a repeated objective.
    unique = []
    for d, o in side:
        if not any(same_level(o["price"], u["price"], tick_size) for _, u in unique):
            unique.append((d, o))
    if len(unique) < 2:
        return False, False, None

    near_d, near = unique[0]
    if near.get("protected_level_between_entry_and_target"):
        # Even the nearest destination is behind structure: no defensible near
        # objective exists, therefore no CHOICE between banking and projecting.
        return False, False, None

    blocked = [o for d, o in unique[1:]
               if o.get("protected_level_between_entry_and_target")]
    if not blocked:
        return False, False, None

    # HORIZON-B: the level blocking a farther objective IS the near objective.
    b_hits = [o for o in blocked
              if same_level(o.get("nearest_intervening_protected_level"),
                            near.get("price"), tick_size)]
    detail = {
        "near_id": near.get("objective_id"), "near_kind": near.get("kind"),
        "near_price": near.get("price"), "near_distance": round(near_d, 2),
        "far": [(o.get("objective_id"), o.get("price"),
                 o.get("nearest_intervening_protected_level")) for o in blocked],
        "b_matched": [o.get("objective_id") for o in b_hits],
    }
    return True, bool(b_hits), detail


def scan_day(day, tick_size=MNQ_TICK):
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
        verdict = route(active_path_state=aps, tool_catalog=cat,
                        objective_catalog=objs)

        owner = verdict.get("path_owner")
        cdir = OPPOSITE[owner] if owner in ("bullish", "bearish") else None
        at_loc = [r for r in cat
                  if str(r.get("price_relation") or "") in AT_LOCATION_RELATIONS]
        counter = bool(cdir) and any(str(r.get("direction")) == cdir for r in at_loc)
        a, b, detail = horizon(objs, cdir, ref, tick_size)
        out.append({
            "day": day, "file": os.path.basename(f), "owner": owner,
            "status": verdict.get("path_status"), "counter_dir": cdir,
            "reference": ref, "at_location": len(at_loc), "counter_path": counter,
            "A": bool(counter and a), "B": bool(counter and b), "detail": detail,
            "R1": verdict["predicates"]["path_contested"],
            "R4": (verdict["predicates"]["counter_path_at_location"]
                   and verdict["predicates"]["transfer_evidence_present"]),
        })
    return out


def main():
    days = sorted({os.path.basename(f)[:8]
                   for f in glob.glob(os.path.join(ARCHIVE, "*_MNQ.json"))})
    recs = []
    for d in days:
        recs += scan_day(d)
    out = os.path.join(ROOT, "data", "ai_shadow", "horizon_ab_records.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(recs, fh)
    print(f"replayable scans: {len(recs)}   (records -> {out})")


if __name__ == "__main__":
    main()

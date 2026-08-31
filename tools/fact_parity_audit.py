"""Does Terra see the same market the deterministic lane sees?

SEAL-PROD-20260807-SESSION-EVIDENCE (2026-08-07).

THE LAW: no execution-relevant market fact may exist in the deterministic lane
while being silently absent, or semantically different, in Terra's factual
packet.

This audits FACT parity only. Terra and the deterministic engine are supposed
to reach different conclusions -- that is the entire point of putting
discretion in the middle. What they may never do is reason over different
facts. PROD-20260807 had exactly that failure twice: retrieval read liquidity
from a differently-shaped structure than the snapshot published, and the
delivery vocabulary was taken from the wrong producer.

Read-only over a sealed archive.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

PARITY = "PARITY"
INTENTIONAL = "INTENTIONAL_DIFFERENCE"
DEFECT = "DEFECT"

#: fact -> (authoritative producer, dotted path in Terra's packet)
FACTS = [
    ("current price/reference", "market_data.current_price", "market.current_price"),
    ("delivery", "shared_market_context._delivery", "delivery.state"),
    ("buy-side liquidity", "liquidity_engine.nearest_buy_side", "liquidity.nearest_buy_side"),
    ("sell-side liquidity", "liquidity_engine.nearest_sell_side", "liquidity.nearest_sell_side"),
    ("liquidity sweep/raid state", "liquidity_engine.events", "liquidity.events"),
    ("protected high", "protected_swings.protected_high", "protected_swings.protected_high.level"),
    ("protected low", "protected_swings.protected_low", "protected_swings.protected_low.level"),
    ("active draw", "liquidity_engine.active_draw", "liquidity.active_draw.level"),
    ("PO3 / narrative phase", "po3_engine", "delivery.po3_15m.phase"),
    ("volatility", "volatility_engine", "STRUCTURE_WITNESS.volatility_state"),
    ("session phase", "session_clock", "session"),
    ("market regime", "market_regime", "governance_context.market_regime"),
    ("authorized objectives", "enumerate_objectives()", "AUTHORIZED_OBJECTIVES"),
    ("authorized invalidations", "authorized_invalidation_catalog()",
     "AUTHORIZED_INVALIDATIONS"),
]

#: Facts whose absence from the packet is a deliberate design choice, with the
#: reason recorded. Anything NOT listed here that is absent is a defect.
INTENTIONAL_ABSENCE = {
    "market regime": ("regime is observe_only and has no mechanical veto; it "
                      "reaches Terra as narrative context, not as a gate"),
    "volatility": ("volatility is consumed by the deterministic qualification "
                   "lane; it is not an input Terra selects objects with"),
}


#: Facts the LIVE session genuinely lacked, repaired afterwards. Recording the
#: repair does not erase the defect -- the archive keeps the runtime truth.
REPAIRED_AFTER_SESSION = {
    "authorized objectives": ("the catalog was not published to Terra during "
                              "PROD-20260807; repaired by f19cf97"),
    "authorized invalidations": ("not published to Terra during PROD-20260807; "
                                 "repaired by f19cf97"),
}


def dig(obj, path: str):
    """Walk a dotted path. An explicitly-null parent means the fact was
    PRESENT and empty -- Terra was told the level does not exist, which is
    parity, not absence. Only a missing key is absence."""
    for part in path.split("."):
        if not isinstance(obj, dict):
            return "__EMPTY__"
        if part not in obj:
            return "__ABSENT__"
        obj = obj[part]
        if obj is None:
            return "__EMPTY__"
    return obj


def audit_scan(artifact: dict) -> list:
    """One scan -> per-fact parity rows."""
    packet = artifact.get("input_payload") or {}
    rows = []
    for fact, producer, path in FACTS:
        terra = dig(packet, path)
        if terra == "__EMPTY__":
            status, note, shown = PARITY, "explicitly null: the fact does not exist yet", "null (stated)"
        elif terra != "__ABSENT__":
            status, note, shown = PARITY, "", json.dumps(terra, default=str)[:90]
        elif fact in INTENTIONAL_ABSENCE:
            status, note, shown = INTENTIONAL, INTENTIONAL_ABSENCE[fact], "ABSENT"
        elif fact in REPAIRED_AFTER_SESSION:
            status, note, shown = DEFECT, REPAIRED_AFTER_SESSION[fact], "ABSENT"
        else:
            status, note, shown = DEFECT, "present deterministically, absent from Terra's packet", "ABSENT"
        rows.append({"fact": fact, "producer": producer, "terra_path": path,
                     "terra_value": shown, "status": status, "note": note})
    return rows


def catalog_parity(artifact: dict) -> dict:
    """PHASE 7: the catalog Terra was shown == enumerate_objectives().

    ONE CANONICAL OBJECTIVE UNIVERSE. If the Brain can build a second catalog
    internally, an id means two different things on the two sides of the wire.
    """
    from broker.luna_candidate_producer import (authorized_invalidation_catalog,
                                                authorized_objective_catalog,
                                                enumerate_objectives)
    packet = artifact.get("input_payload") or {}
    price = ((packet.get("market") or {}).get("current_price"))
    try:
        price = float(price)
    except (TypeError, ValueError):
        return {"comparable": False, "reason": "no reference price"}

    deterministic = enumerate_objectives({}, packet)
    published = authorized_objective_catalog({}, packet, price)
    invalidations = authorized_invalidation_catalog(packet)

    det_ids = {(o["kind"], round(float(o["price"]), 4)) for o in deterministic}
    pub_ids = {(o["kind"], round(float(o["price"]), 4)) for o in published}
    return {
        "comparable": True,
        "deterministic_objectives": len(deterministic),
        "published_objectives": len(published),
        "identity_match": det_ids == pub_ids,
        "only_deterministic": sorted(det_ids - pub_ids),
        "only_published": sorted(pub_ids - det_ids),
        "all_have_ids": all(o.get("objective_id") for o in published),
        "all_have_side": all("side" in (o.get("supporting_evidence") or {})
                             or o.get("kind") == "protected_swing"
                             for o in published),
        "all_have_source": all(o.get("source") for o in published),
        "invalidations": len(invalidations),
        "invalidations_have_ids": all(i.get("invalidation_id")
                                      for i in invalidations),
        "deterministic_is_stable": deterministic == enumerate_objectives({}, packet),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", default="PROD-20260807")
    args = ap.parse_args(argv)

    root = os.path.join("data", "replay_sessions", args.session_id, "brain")
    files = sorted(glob.glob(os.path.join(root, "*.json")))
    if not files:
        print(f"  no archived Brain artifacts under {root}")
        return 1

    # Representative coverage across the session's four regimes, by clock.
    windows = [("early bearish move", "0930", "1030"),
               ("reversal", "1030", "1130"),
               ("mid-morning rally", "1130", "1245"),
               ("later bearish move", "1245", "1400")]
    picks = []
    for label, lo, hi in windows:
        chosen = [f for f in files
                  if lo <= os.path.basename(f).split("_")[1][:4] < hi]
        if chosen:
            picks.append((label, chosen[len(chosen) // 2]))

    print("=" * 100)
    print(f"  DETERMINISTIC <-> TERRA FACT PARITY  --  {args.session_id}")
    print("=" * 100)
    defects, rows_all, cat_results = [], [], []
    for label, path in picks:
        artifact = json.load(open(path, encoding="utf-8"))
        rows = audit_scan(artifact)
        rows_all.append((label, os.path.basename(path), rows))
        cat_results.append((label, catalog_parity(artifact)))
        print(f"\n  {label.upper()}  ({os.path.basename(path)})")
        print(f"  {'FACT':28} {'PRODUCER':38} {'STATUS':22} VALUE")
        for r in rows:
            print(f"  {r['fact']:28} {r['producer']:38} {r['status']:22} "
                  f"{r['terra_value'][:46]}")
            if r["status"] == DEFECT:
                defects.append((label, r["fact"], r["note"]))

    print("\n" + "=" * 100)
    print("  OBJECTIVE CATALOG PARITY (PHASE 7)")
    print("=" * 100)
    catalog_ok = True
    for label, c in cat_results:
        if not c.get("comparable"):
            print(f"  {label:24} NOT COMPARABLE: {c.get('reason')}")
            continue
        ok = (c["identity_match"] and c["all_have_ids"] and c["all_have_source"]
              and c["invalidations_have_ids"] and c["deterministic_is_stable"])
        catalog_ok &= ok
        print(f"  {label:24} deterministic={c['deterministic_objectives']} "
              f"published={c['published_objectives']} "
              f"identity_match={c['identity_match']} ids={c['all_have_ids']} "
              f"invalidations={c['invalidations']}/{c['invalidations_have_ids']} "
              f"-> {'PARITY' if ok else 'MISMATCH'}")
        if c["only_deterministic"] or c["only_published"]:
            print(f"      only_deterministic={c['only_deterministic']} "
                  f"only_published={c['only_published']}")

    intentional = sum(1 for _, _, rows in rows_all
                      for r in rows if r["status"] == INTENTIONAL)
    print("\n" + "=" * 100)
    print(f"  facts audited          : {sum(len(r) for _, _, r in rows_all)}")
    print(f"  scans covered          : {len(rows_all)}")
    print(f"  PARITY                 : {sum(1 for _, _, rows in rows_all for r in rows if r['status'] == PARITY)}")
    print(f"  INTENTIONAL_DIFFERENCE : {intentional}")
    print(f"  DEFECT                 : {len(defects)}")
    for d in defects:
        print(f"      {d[0]}: {d[1]} -- {d[2]}")
    # The archive keeps the runtime truth; this reports whether the defect it
    # recorded still exists in the code today.
    src = open("src/ai_brain/narrative_brain.py", encoding="utf-8").read()
    repaired_now = ("authorized_objective_catalog" in src
                    and "authorized_invalidation_catalog" in src)
    historical = [d for d in defects if d[1] in REPAIRED_AFTER_SESSION]
    outstanding = [d for d in defects if d[1] not in REPAIRED_AFTER_SESSION]
    print(f"      historical (repaired since) : {len(historical)}")
    print(f"      outstanding                 : {len(outstanding)}")
    print(f"  CATALOG PUBLISHED TODAY: {repaired_now}")
    print(f"  FACT PARITY (runtime)  : {'PASS' if not defects else 'DEFECTS FOUND'}")
    print(f"  FACT PARITY (current)  : "
          f"{'PASS' if not outstanding and repaired_now else 'DEFECTS OUTSTANDING'}")
    print(f"  CATALOG PARITY         : {'PASS' if catalog_ok else 'FAIL'}")

    out = os.path.join("data", "replay_sessions", args.session_id,
                       "fact_parity.json")
    if os.path.isdir(os.path.dirname(out)):
        json.dump({"scans": [{"window": w, "artifact": a, "facts": r}
                             for w, a, r in rows_all],
                   "catalog_parity": [{"window": w, **c} for w, c in cat_results],
                   "defects": defects,
                   "defects_historical_repaired": historical,
                   "defects_outstanding": outstanding,
                   "catalog_published_today": repaired_now,
                   "fact_parity": "PASS" if not defects else "DEFECTS_FOUND",
                   "fact_parity_current": ("PASS" if not outstanding and repaired_now
                                           else "DEFECTS_OUTSTANDING"),
                   "catalog_parity_result": "PASS" if catalog_ok else "FAIL"},
                  open(out, "w", encoding="utf-8"), indent=1, default=str)
        print(f"\n  written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

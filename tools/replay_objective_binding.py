"""Replay archived Terra proposals through canonical objective binding.

BUILD-CANONICAL-EXTERNAL-BRAIN-EXECUTION-BRIDGE (2026-08-07).

Read-only. Uses the ARCHIVED PROD-20260807 Brain decisions -- Terra is never
called again. For each `propose-entry` scan it reconstructs which authorized
catalog entry corresponds to the level Terra actually named in prose, binds by
`objective_id`, and runs the real CandidateProducer.

This measures ONE thing: how many proposals were lost to the prose join key
rather than to doctrine. It says nothing about whether those trades would have
won.

LIMIT, stated: the live `qualification` object is not persisted by the
production path, so it cannot be replayed. Rejections owned by qualification
(`direction_disagreement`, `qualification_rejected`, `playbook_unauthorized`)
are therefore NOT exercised here, and every count below is an upper bound.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from broker.luna_candidate_producer import (CandidateProducer,  # noqa: E402
                                            NoCandidate,
                                            authorized_objective_catalog)
from broker.topstepx_client import TopstepXContract              # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
PRICE = re.compile(r"\d{5}(?:\.\d{1,2})?")


def named_levels(text: str) -> list:
    """Every price Terra actually wrote, in the order written."""
    return [float(m) for m in PRICE.findall(str(text or ""))]


def select_objective_id(draw_text: str, catalog: list, direction: str,
                        reference: float):
    """The catalog entry matching the FIRST level Terra named that is both in
    the catalog and on the correct side. This is the selection Terra would have
    made itself had the catalog been published to it."""
    on_side = [c for c in catalog
               if (c["price"] > reference if direction == "bullish"
                   else c["price"] < reference)]
    for level in named_levels(draw_text):
        for c in on_side:
            if abs(c["price"] - level) < 0.01:
                return c["objective_id"], c["price"]
    return None, None


def main() -> int:
    files = sorted(glob.glob("data/ai_brain/20260807_*_MNQ.json"))
    old, new = {}, {}
    rows = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        po = d.get("parsed_output") or {}
        ip = d.get("input_payload") or {}
        if "propose" not in str(po.get("current_action") or "").lower()[:20]:
            continue
        et = os.path.basename(f)[9:15]
        direction = po.get("narrative_direction")
        reference = (ip.get("market") or {}).get("current_price")

        def run(parsed):
            return CandidateProducer(account_fingerprint="acct:replay",
                                     contract=MNQ).produce(
                brain_result={"ok": True, "parsed": parsed,
                              "fallback_reason": None,
                              "model": d.get("llm_model")},
                brain_input=ip, snapshot={}, qualification={"qualified": True},
                engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
                snapshot_id=et, market_data_timestamp=str(ip.get("timestamp")),
                latest_closed_bar_timestamp=str(ip.get("timestamp")),
                in_window=True, now=datetime.now(timezone.utc))

        try:
            run(po); old_r = "CANDIDATE"
        except NoCandidate as e:
            old_r = e.reason
        except Exception as e:  # noqa: BLE001
            old_r = f"ERROR:{type(e).__name__}"
        old[old_r] = old.get(old_r, 0) + 1

        catalog = authorized_objective_catalog({}, ip, reference)
        oid, opx = select_objective_id(po.get("active_draw"), catalog,
                                       direction, reference)
        if oid is None:
            new_r, opx = "no_named_level_in_catalog", None
        else:
            try:
                run({**po, "objective_id": oid}); new_r = "CANDIDATE"
            except NoCandidate as e:
                new_r = e.reason
            except Exception as e:  # noqa: BLE001
                new_r = f"ERROR:{type(e).__name__}"
        new[new_r] = new.get(new_r, 0) + 1
        rows.append((et, direction, old_r, oid, opx, new_r))

    print("=" * 100)
    print("  ARCHIVED PROPOSAL REPLAY -- prose join key vs canonical objective_id")
    print("=" * 100)
    print(f"{'ET':8}{'dir':10}{'OLD (prose)':30}{'objective_id':16}{'price':10}{'NEW (id)'}")
    for et, dr, o, oid, opx, n in rows:
        print(f"{et:8}{str(dr):10}{o:30}{str(oid or '-'):16}"
              f"{str(opx or '-'):10}{n}")
    print()
    print(f"  proposals replayed : {len(rows)}")
    print(f"  OLD outcomes       : {dict(sorted(old.items(), key=lambda x: -x[1]))}")
    print(f"  NEW outcomes       : {dict(sorted(new.items(), key=lambda x: -x[1]))}")
    print()
    gained = new.get("CANDIDATE", 0) - old.get("CANDIDATE", 0)
    print(f"  candidates OLD     : {old.get('CANDIDATE', 0)}")
    print(f"  candidates NEW     : {new.get('CANDIDATE', 0)}")
    print(f"  recovered by binding: {gained}   "
          f"(previously lost to plumbing, not doctrine)")
    print()
    print("  NOT a claim these would have been profitable trades.")
    print("  Upper bound: live qualification is unrecoverable and not replayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

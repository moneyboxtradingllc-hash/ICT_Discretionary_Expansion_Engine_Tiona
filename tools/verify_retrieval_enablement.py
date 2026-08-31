"""Read-only proof that descriptive-memory retrieval is live.

ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07).

Ten descriptive memories were authored on 2026-08-06 and found the next morning
to be unreachable: `AI_RETRIEVAL_ENABLED` was absent, so the scan-loop hook
short-circuited before ever reading them. Every other telemetry line looked
healthy.

This tool calls the SAME hook the production scan loop calls, against the SAME
live corpus, and asserts on the result. It lives in `tools/` deliberately --
`load_dotenv()` resolves `.env` by walking up from the calling file, so a probe
written outside the repository silently loads no environment at all and then
reports "disabled" for the wrong reason.

Reads only. Writes nothing. Calls no model and no venue.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from ai_retrieval import vector_store as V                       # noqa: E402
from ai_retrieval.retrieval import (raw_retrieval_flag,          # noqa: E402
                                    retrieval_enabled,
                                    retrieval_startup_state,
                                    retrieve_for_snapshot)


def snapshot(session, regime, vol, ndir, nphase, delivery, bos=1, conf=70.0,
             exh=False, contract="CON.F.US.MNQ.U26"):
    return {"session": session, "contract": contract,
            "market_regime": {"regime_label": regime, "volatility_state": vol},
            "narrative_authority": {"narrative_direction": ndir,
                                    "narrative_phase": nphase,
                                    "active_liquidity_draw": "29500"},
            "shared_context": {"delivery_state": delivery,
                               "exhaustion_present": exh},
            "protected_swings": {},
            "liquidity": {"nearest_buy_side": 29800.0,
                          "nearest_sell_side": 29200.0},
            "STRUCTURE_WITNESS": {tf: {"bos_event": i < bos, "mss_event": False}
                                  for i, tf in enumerate(("15m", "5m", "3m", "1m"))},
            "phase_confidence_summary": {"mean": conf, "min": conf, "max": conf}}


PROBES = [
    ("conflicted rotation", snapshot("lunch", "range_rotation", "toxic",
                                     "conflicted", "transition",
                                     "accumulation_building", conf=65.0, exh=True),
     "expect eligible August 6 analogs"),
    ("exhaustion", snapshot("morning_continuation", "range_rotation", "toxic",
                            "conflicted", "exhaustion", "accumulation_building",
                            conf=85.0, exh=True),
     "expect the true exhaustion segment first"),
    ("bullish expansion", snapshot("ny_open", "expansion_up", "stable", "bullish",
                                   "continuation", "full_distribution_alignment",
                                   bos=2, conf=80.0),
     "expect 0 after the contradiction gate"),
]


def main() -> int:
    failures = []
    state = retrieval_startup_state()
    records = sorted(V.load_records(), key=lambda r: r["segment_start"])
    label = {r["memory_id"]: i for i, r in enumerate(records, 1)}

    print("=" * 82)
    print("  RETRIEVAL ENABLEMENT PROOF")
    print("=" * 82)
    print(f"  AI_RETRIEVAL_ENABLED raw : {raw_retrieval_flag()!r}")
    print(f"  resolved                 : {retrieval_enabled()}")
    print(f"  resolution source        : {state['resolution_source']}")
    print(f"  corpus records           : {state['record_count']}")
    print(f"  descriptive records      : {state['descriptive_records']}")
    print(f"  memory startup state     : {state['state']}")
    print(f"  store path               : {V._store_path()}")
    print()

    if not retrieval_enabled():
        failures.append("retrieval resolves DISABLED")
    if state["state"] != "ready":
        failures.append(f"startup state is {state['state']}")

    for name, snap, expectation in PROBES:
        r = retrieve_for_snapshot(snap, "MNQ")
        print("-" * 82)
        print(f"  {name}   ({expectation})")
        print(f"    enabled             : {r.get('enabled')}")
        print(f"    corpus_size         : {r.get('corpus_size')}")
        print(f"    retrieval_authority : {r.get('retrieval_authority')}")
        print(f"    contradiction-gated : "
              f"{r.get('rejected_reasons', {}).get('load_bearing_contradiction', 0)}")
        print(f"    RETURNED            : {r.get('returned')}")
        for a in r.get("analogs", []):
            extra = ""
            if a.get("recurrence_count"):
                extra = (f"  [recurrence x{a['recurrence_count']} "
                         f"{[label.get(m, '?') for m in a['grouped_memory_ids']]}"
                         f" rep=#{label.get(a['representative_memory_id'], '?')}]")
            print(f"      #{label.get(a['memory_id'], '?'):<2} "
                  f"sim={a['similarity']:.4f} {a['segment']:<22}"
                  f"auth={a['authority']} ov={a['outcome_validated']} "
                  f"lw={a['levels_withheld']}{extra}")
            if a["authority"] != "CONTEXT_ONLY":
                failures.append(f"{name}: analog authority {a['authority']}")
            if a["outcome_validated"] is not False:
                failures.append(f"{name}: analog claims an outcome")
        if not r.get("analogs"):
            print("      (none)")

        # NON-VACUOUS: the hook must have actually read the corpus.
        if r.get("enabled") is not True:
            failures.append(f"{name}: hook reports enabled={r.get('enabled')}")
        if r.get("corpus_size") != state["record_count"]:
            failures.append(f"{name}: hook saw corpus_size={r.get('corpus_size')}, "
                            f"store holds {state['record_count']}")
        if name == "bullish expansion" and r.get("returned"):
            failures.append("bullish expansion returned an analog")
        if name in ("conflicted rotation", "exhaustion") and not r.get("returned"):
            failures.append(f"{name}: returned nothing from a 10-record corpus")

    print("=" * 82)
    if failures:
        print("  RESULT: FAILED")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  RESULT: retrieval ENABLED, production hook reads the live corpus,")
    print("          every returned analog CONTEXT_ONLY and outcome-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

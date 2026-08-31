"""Read-only per-scan telemetry simulation against the live corpus.

ADD-PER-SCAN-MEMORY-RETRIEVAL-TELEMETRY (2026-08-07). Calls the same hook the
production scan loop calls; writes telemetry to a temporary session root, never
to the live corpus. No model call, no venue call.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
os.environ["REPLAY_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="telemetry-sim-")

from ai_retrieval import retrieval_telemetry as T          # noqa: E402
from ai_retrieval.retrieval import (retrieval_startup_state,  # noqa: E402
                                    retrieve_for_snapshot)


def snap(session, regime, vol, ndir, nphase, delivery, exh=False, liquidity=True):
    s = {"session": session, "contract": "CON.F.US.MNQ.U26",
         "market_regime": {"regime_label": regime, "volatility_state": vol},
         "narrative_authority": {"narrative_direction": ndir,
                                 "narrative_phase": nphase,
                                 "active_liquidity_draw": "29500"},
         "shared_context": {"delivery_state": delivery, "exhaustion_present": exh},
         "protected_swings": {},
         "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
                               for tf in ("15m", "5m", "3m", "1m")},
         "phase_confidence_summary": {"mean": 65.0, "min": 55.0, "max": 75.0}}
    s["liquidity"] = ({"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0}
                      if liquidity else {})
    return s


CASES = [
    ("conflicted rotation", snap("lunch", "range_rotation", "toxic",
                                 "conflicted", "transition",
                                 "accumulation_building", exh=True)),
    ("exhaustion", snap("morning_continuation", "range_rotation", "toxic",
                        "conflicted", "exhaustion", "accumulation_building",
                        exh=True)),
    ("bullish expansion", snap("ny_open", "expansion_up", "stable", "bullish",
                               "continuation", "full_distribution_alignment")),
    ("incomplete query", snap("lunch", "range_rotation", "toxic", "conflicted",
                              "transition", "accumulation_building", exh=True,
                              liquidity=False)),
]

s = T.RetrievalTelemetrySession("PROD-SIM", instrument="MNQ",
                                contract="CON.F.US.MNQ.U26")
for i, (label, ctx) in enumerate(CASES):
    result = retrieve_for_snapshot(ctx, "MNQ")
    rec = s.record_scan(scan_id=f"scan-{i+1}", result=result,
                        startup_state=retrieval_startup_state())
    print("=" * 84)
    print(f"  {label}   (scan-{i+1})")
    print(f"    retrieval_enabled      : {rec['retrieval_enabled']}")
    print(f"    query_complete         : {rec['query_complete']}  "
          f"missing={rec['missing_required_query_blocks'] or 'none'}")
    if rec["incomplete_query_reason"]:
        print(f"    reason                 : {rec['incomplete_query_reason']}")
    print(f"    corpus_size            : {rec['corpus_size']}")
    print(f"    contradiction_gated    : {rec['contradiction_gated_count']} "
          f"reasons={rec['contradiction_reason_counts'] or '{}'} "
          f"(occurrences={rec['contradiction_reason_occurrences']})")
    print(f"    below_threshold        : {rec['below_threshold_count']}")
    print(f"    recurrence collapsed   : {rec['recurrence_members_collapsed']} "
          f"(semantic groups={rec['semantic_recurrence_groups']})")
    print(f"    session_cap_excluded   : {rec['session_cap_excluded_count']}")
    print(f"    RETURNED               : {rec['returned_analog_count']}")
    print(f"    stage accounting       : {rec['stage_accounting_total']} vs corpus "
          f"{rec['corpus_size']} -> reconciles={rec['stage_accounting_reconciles']}")
    for a in rec["returned_analogs"]:
        extra = ""
        if a.get("recurrence_count"):
            extra = (f"  [{a['recurrence_type']} x{a['recurrence_count']} "
                     f"{a['grouped_memory_id_suffixes']}]")
        print(f"      ...{a['memory_id_suffix']} sim={a['similarity']} "
              f"{a['segment']:<22}{a['source_session_id']} "
              f"auth={a['authority']} lw={a['levels_withheld']}{extra}")
    print(f"    telemetry written      : {rec.get('telemetry_write_ok')}")

print("=" * 84)
summ = s.summary()
for k in ("total_scans", "retrieval_enabled_scans", "scans_with_analogs",
          "scans_without_analogs", "incomplete_query_scans",
          "total_analog_presentations", "unique_memory_ids_retrieved",
          "unique_source_sessions_retrieved", "semantic_recurrence_groups_presented",
          "recurrence_members_collapsed", "total_contradiction_gated_records",
          "contradiction_reason_counts", "session_cap_exclusions",
          "authority_values_seen", "degraded_observability"):
    print(f"  {k:38}: {summ[k]}")
print(f"\n  telemetry path: {T.telemetry_path('PROD-SIM')}")

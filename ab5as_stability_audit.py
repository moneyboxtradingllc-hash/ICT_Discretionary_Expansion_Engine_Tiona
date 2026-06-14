"""AB-5A-S — LLM Brain directional stability audit (evidence only).

Repeats the LLM call N times on each FROZEN June 11 snapshot (identical input,
identical frozen retrieval, identical empty memory) and measures directional
consensus. Calls _call_llm directly (raw LLM judgment, pre-repair) to isolate
LLM instability from the hardening pipeline. No authority/generation/execution.
"""
import os, sys, json, glob, re, statistics, tempfile
sys.path.insert(0, "src"); sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(".env")
os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                   "AI_BRAIN_MODEL": "gpt-4o-mini", "AI_BRAIN_TIMEOUT_SECONDS": "18",
                   "AI_BRAIN_DIR": tempfile.mkdtemp(), "AI_RETRIEVAL_DIR": "data/ai_retrieval"})
import ai_brain.narrative_brain as nb
from ai_brain.brain_input import build_brain_input
from ai_brain.brain_validation import normalize_output
from ai_retrieval.retrieval import retrieve_analogs

N = int(os.getenv("STABILITY_N", "12"))   # reps per point (see report for rationale vs 25)
SEM = {"above_high": "bearish", "below_low": "bullish"}

def enrich(snap):
    s = (snap.get("ai_context", {}) or {}).get("summary", "")
    m = re.search(r"Liquidity sweep (above_high|below_low) on (\w+)", s)
    sweep, tf = (m.group(1), m.group(2)) if m else (None, None); deliv = SEM.get(sweep)
    bias = (snap.get("qualification", {}) or {}).get("direction", "neutral")
    snap = dict(snap); snap["ai_context"] = {"directional_bias": bias, "market_narrative": s[:300]}
    snap["shared_context"] = {"delivery_state": f"{deliv}_delivery" if deliv else "unknown",
                              "delivery_confidence": 25 if deliv else 0, "exhaustion_present": True}
    snap["po3"] = ({tf: {"phase": "manipulation", "manipulation_direction": deliv,
                         "manipulation_direction_source": "sweep_semantics"}} if deliv else {})
    snap["liquidity"] = ({tf: {"sweep_detected": True, "sweep_direction": sweep,
                               "reclaim_detected": True, "nearest_sell_side_liquidity": 699.6}} if sweep else {})
    snap["protected_swings"] = {"protected_high": ({"level": 702.5} if sweep == "above_high" else None),
                                "protected_low": None}
    snap["narrative_authority"] = {"active_liquidity_draw":
                                   {"side": "sell_side", "level": 699.6} if sweep == "above_high" else {"side": "buy_side", "level": 702}}
    snap["timeframes"] = {"1m": {"candles": [{"open": 701.4, "high": 701.6, "low": 701.2, "close": 701.42}],
                                 "last_candle": {"close": 701.42}}}
    return snap

POINTS = [("10:00","100049"),("10:05","100553"),("10:25","102553"),
          ("10:29","102955"),("11:00","110052"),("13:17","131741")]

# ── retrieval + memory stability (deterministic check) ────────────────────────
def retr_sig(snap):
    r = retrieve_analogs(snap, k=5, authoritative_only=True, min_similarity=0.0, persist_log=False)
    return [(a["timestamp"], a["similarity"]) for a in r["analogs"]]

print(f"AB-5A-S stability audit | reps per point N={N}\n")
scorecard = []
for label, et in POINTS:
    g = glob.glob(f"data/live_snapshots/20260611_{et}_QQQ.json")
    if not g:
        print(f"{label}: no snapshot"); continue
    snap = enrich(json.load(open(g[0], encoding="utf-8")))
    bi = build_brain_input(snap, {"available": False})
    # freeze retrieval; verify determinism
    s1, s2 = retr_sig(snap), retr_sig(snap)
    retr_stable = (s1 == s2)
    bi["memory_retrieval"] = {"count": len(s1), "analogs": []}

    dirs, confs, phases, forbids, tools, plays = [], [], [], [], [], []
    fails = 0
    for _ in range(N):
        c = nb._call_llm(bi)
        if not c["ok"]:
            fails += 1; continue
        p, _notes = normalize_output(c["parsed"])
        dirs.append((p.get("narrative_direction") or "?").lower())
        confs.append(int(p.get("phase_confidence") or 0))
        phases.append((p.get("narrative_phase") or "?").lower())
        fb = p.get("forbidden_direction"); forbids.append(str(fb).lower() if fb else "none")
        tools.append(str(p.get("recommended_tool_family")))
        plays.append(str(p.get("recommended_playbook_family")))

    def dist(xs):
        d = {}
        for x in xs: d[x] = d.get(x, 0) + 1
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))
    n_ok = len(dirs)
    top = max(dist(dirs).values()) if dirs else 0
    consensus = round(100 * top / n_ok) if n_ok else 0
    band = ("HIGH" if consensus >= 90 else "MODERATE" if consensus >= 75
            else "LOW" if consensus >= 60 else "UNSTABLE")
    scorecard.append((label, consensus, band, dist(dirs)))
    print(f"== {label} (ET {et}) | ok={n_ok}/{N} fails={fails} | retrieval_stable={retr_stable}")
    print(f"   direction: {dist(dirs)}  -> consensus {consensus}% [{band}]")
    if confs:
        print(f"   confidence: mean={statistics.mean(confs):.0f} med={statistics.median(confs):.0f} "
              f"min={min(confs)} max={max(confs)} sd={statistics.pstdev(confs):.1f}")
    print(f"   forbidden: {dist(forbids)}")
    print(f"   phase: {dist(phases)}")
    print(f"   tools: {dist(tools)}")
    print(f"   playbook: {dist(plays)}")
    print()

print("=== DIRECTIONAL STABILITY SCORECARD ===")
for label, c, band, dd in scorecard:
    print(f"   {label:6} {c:3}%  {band:9} {dd}")

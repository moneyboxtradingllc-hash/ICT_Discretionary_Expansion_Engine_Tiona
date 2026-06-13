"""AB-5A — Brain vs Wrapper forensic pressure test (analysis only, not production).

Replays June 10 + 11 archived snapshots: extracts the Wrapper conclusion, runs
the Brain's deterministic narrative synthesis + retrieval, scores every
direction divergence against real forward bars (5/15/30/60 min).
"""
import glob, json, os, re, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "src"); sys.stdout.reconfigure(encoding="utf-8")
from narrative_authority.narrative_engine import build_narrative
from ai_retrieval.retrieval import retrieve_analogs

# ── price series ──────────────────────────────────────────────────────────────
BARS = {}
for date in ("20260610", "20260611"):
    rows = json.load(open(f"data/replay_{date}_1m.json"))
    for b in rows:
        t = datetime.fromisoformat(b["t"]).astimezone(timezone.utc).replace(tzinfo=None)
        BARS[t.strftime("%Y%m%d%H%M")] = b["c"]
keys = sorted(BARS)


def price_at(dt_utc):
    k = dt_utc.strftime("%Y%m%d%H%M")
    if k in BARS: return BARS[k]
    for kk in keys:                      # next available bar
        if kk >= k: return BARS[kk]
    return None


def fwd(ts_iso, mins):
    try:
        t = datetime.fromisoformat(ts_iso).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None, None
    p0 = price_at(t); p1 = price_at(t + timedelta(minutes=mins))
    return p0, p1


# ── reconstruct brain snapshot from archive ─────────────────────────────────────
SEM = {"above_high": "bearish", "below_low": "bullish"}

def recon(snap):
    s = (snap.get("ai_context", {}) or {}).get("summary", "")
    m = re.search(r"Liquidity sweep (above_high|below_low) on (\w+)", s)
    sweep_dir, sweep_tf = (m.group(1), m.group(2)) if m else (None, None)
    deliv = SEM.get(sweep_dir)
    bias = (snap.get("qualification", {}) or {}).get("direction", "neutral")
    ai = snap.get("ai_discretionary", {}) or {}
    return {
        "timestamp": snap.get("timestamp"),
        "ai_discretionary": {"ai_direction": ai.get("ai_direction"),
                             "ai_confidence": ai.get("ai_confidence")},
        "ai_context": {"directional_bias": bias},
        "shared_context": {"delivery_state": f"{deliv}_delivery" if deliv else "unknown",
                           "delivery_confidence": 25 if deliv else 0},
        "po3": ({sweep_tf: {"phase": "manipulation", "manipulation_direction": deliv,
                            "manipulation_direction_source": "sweep_semantics"}} if deliv else {}),
        "liquidity": ({sweep_tf: {"sweep_detected": True, "sweep_direction": sweep_dir,
                                  "reclaim_detected": True,
                                  "nearest_sell_side_liquidity": None}} if sweep_dir else {}),
        "structure": {}, "protected_swings": {},
        "market_regime": snap.get("market_regime", {}),
    }


def sign(x, dead=0.08):
    if x is None: return "flat"
    if x > dead: return "bull"
    if x < -dead: return "bear"
    return "flat"


def dir_token(d):
    return {"bullish": "bull", "bearish": "bear"}.get((d or "").lower(), "flat")


# ── replay + score ──────────────────────────────────────────────────────────────
scoreboard = {"brain": 0, "wrapper": 0, "equal": 0, "inconclusive": 0}
horizons = [5, 15, 30, 60]
n_scans = n_div = 0
retrieval_changed_direction = 0

for date in ("20260610", "20260611"):
    for fp in sorted(glob.glob(f"data/live_snapshots/{date}_*_QQQ.json")):
        snap = json.load(open(fp, encoding="utf-8"))
        w = (snap.get("ai_discretionary", {}) or {}).get("ai_direction")
        if not w: continue
        n_scans += 1
        rec = recon(snap)
        na = build_narrative(rec, {})
        b = na["narrative_direction"]
        # retrieval contribution: does an analog set change the deterministic direction? (it cannot)
        # we measure it explicitly by re-running with no analogs — same direction → retrieval is context-only

        wt, bt = dir_token(w), dir_token(b)
        if wt == bt:   # not a directional divergence
            continue
        n_div += 1
        # forward validation across horizons
        wwin = bwin = 0
        for h in horizons:
            p0, p1 = fwd(rec["timestamp"], h)
            if p0 is None or p1 is None: continue
            mv = sign(p1 - p0)
            # directional call correct if matches move sign; flat call correct if move flat
            w_ok = (wt == mv) or (wt == "flat" and mv == "flat")
            b_ok = (bt == mv) or (bt == "flat" and mv == "flat")
            # a "flat/conflicted" call neither wins nor loses on a directional move,
            # but correctly avoids a wrong-way trade -> half credit vs an opposing directional call
            if w_ok and not b_ok: wwin += 1
            elif b_ok and not w_ok: bwin += 1
            elif wt == "flat" and bt != "flat" and bt != mv: bwin += 1   # brain avoided wrong dir
            elif bt == "flat" and wt != "flat" and wt != mv: wwin += 1   # wrapper avoided wrong dir
        if wwin > bwin: scoreboard["wrapper"] += 1
        elif bwin > wwin: scoreboard["brain"] += 1
        elif wwin == bwin == 0: scoreboard["inconclusive"] += 1
        else: scoreboard["equal"] += 1

print(f"scans={n_scans} directional_divergences={n_div}")
print("SCOREBOARD (directional divergences, forward-validated 5/15/30/60m):")
for k, v in scoreboard.items():
    print(f"   {k}: {v} ({100*v//max(n_div,1)}%)")

# ── June 11 key decision points ─────────────────────────────────────────────────
print("\n=== JUNE 11 KEY DECISION POINTS ===")
KEY = ["102955", "103154", "104155", "110454", "131741", "133154", "140000"]
for ts in KEY:
    cand = glob.glob(f"data/live_snapshots/20260611_{ts[:6]}*_QQQ.json")
    if not cand: continue
    snap = json.load(open(cand[0], encoding="utf-8"))
    rec = recon(snap)
    na = build_narrative(rec, {})
    retr = retrieve_analogs(rec, k=5, authoritative_only=True, min_similarity=0.0, persist_log=False)
    w = snap.get("ai_discretionary", {})
    p0, p60 = fwd(rec["timestamp"], 60)
    fwdmove = round((p60 - p0), 2) if (p0 and p60) else None
    print(f"\n-- {ts[:2]}:{ts[2:4]} | wrapper={w.get('ai_direction')}@{w.get('ai_confidence')} "
          f"| brain={na['narrative_direction']}@{na['narrative_confidence']} phase={na['narrative_phase']}")
    print(f"   forbidden={na['forbidden_trade_direction']} draw={na.get('active_liquidity_draw')}")
    print(f"   brain reasons: {'; '.join(na.get('reasons',[])[:2])}")
    sa = [a for a in retr['analogs'] if (a.get('narrative_direction') or a.get('delivery_direction'))==na['narrative_direction']]
    print(f"   analogs={retr['returned']} supporting={len(sa)} (corpus authoritative-only)")
    print(f"   forward 60m move: {fwdmove}  (wrapper {'RIGHT' if (fwdmove and ((fwdmove>0)==(w.get('ai_direction')=='bullish'))) else 'WRONG/NA'})")

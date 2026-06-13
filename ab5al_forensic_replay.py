"""AB-5A-L — full LLM Brain forensic replay (analysis only; not production).

Wrapper + Deterministic Brain over ALL June 10/11 scans (free); the LIVE LLM
Brain over the mandatory deep-dive points + a stratified divergence sample
(real GPT calls). Forward-validated 5/15/30/60m on real bars.
"""
import os, sys, json, glob, re, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "src"); sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(".env")
os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                   "AI_BRAIN_MODEL": "gpt-4o-mini", "AI_BRAIN_TIMEOUT_SECONDS": "20",
                   "AI_BRAIN_DIR": tempfile.mkdtemp(), "AI_RETRIEVAL_DIR": "data/ai_retrieval"})
import ai_brain.narrative_brain as nb
from ai_brain.stance_memory import StanceMemory
from narrative_authority.narrative_engine import build_narrative

# ── bars ────────────────────────────────────────────────────────────────────
BARS = {}
for d in ("20260610", "20260611"):
    for b in json.load(open(f"data/replay_{d}_1m.json")):
        t = datetime.fromisoformat(b["t"]).astimezone(timezone.utc).replace(tzinfo=None)
        BARS[t.strftime("%Y%m%d%H%M")] = b["c"]
bkeys = sorted(BARS)
def price_at(t):
    k = t.strftime("%Y%m%d%H%M")
    if k in BARS: return BARS[k]
    for kk in bkeys:
        if kk >= k: return BARS[kk]
    return None
def fwd(ts, m):
    try: t = datetime.fromisoformat(ts).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception: return None, None
    return price_at(t), price_at(t + timedelta(minutes=m))

SEM = {"above_high": "bearish", "below_low": "bullish"}
def enrich(snap):
    s = (snap.get("ai_context", {}) or {}).get("summary", "")
    m = re.search(r"Liquidity sweep (above_high|below_low) on (\w+)", s)
    sweep, tf = (m.group(1), m.group(2)) if m else (None, None)
    deliv = SEM.get(sweep)
    bias = (snap.get("qualification", {}) or {}).get("direction", "neutral")
    p0, _ = fwd(snap.get("timestamp", ""), 0)
    snap = dict(snap)
    snap["ai_context"] = {"directional_bias": bias, "market_narrative": s[:300]}
    snap["shared_context"] = {"delivery_state": f"{deliv}_delivery" if deliv else "unknown",
                              "delivery_confidence": 25 if deliv else 0, "exhaustion_present": True}
    snap["po3"] = ({tf: {"phase": "manipulation", "manipulation_direction": deliv,
                         "manipulation_direction_source": "sweep_semantics"}} if deliv else {})
    snap["liquidity"] = ({tf: {"sweep_detected": True, "sweep_direction": sweep,
                               "reclaim_detected": True, "nearest_sell_side_liquidity": 699.6}} if sweep else {})
    snap["protected_swings"] = {"protected_high": None, "protected_low": None}
    snap["narrative_authority"] = {}
    if p0: snap["timeframes"] = {"1m": {"candles": [{"open": p0, "high": p0+.2, "low": p0-.2, "close": p0}],
                                        "last_candle": {"close": p0}}}
    return snap

def tok(d): return {"bullish":"bull","bearish":"bear"}.get((d or "").lower(), "flat")
def sgn(x, dz=0.08): return "flat" if x is None or abs(x)<dz else ("bull" if x>0 else "bear")

snaps = []
for d in ("20260610", "20260611"):
    for fp in sorted(glob.glob(f"data/live_snapshots/{d}_*_QQQ.json")):
        sn = json.load(open(fp, encoding="utf-8"))
        if (sn.get("ai_discretionary", {}) or {}).get("ai_direction"):
            snaps.append(sn)

# ── pass 1: wrapper + deterministic over ALL scans (free) ──────────────────────
rows = []
for sn in snaps:
    w = (sn.get("ai_discretionary", {}) or {}).get("ai_direction")
    det = build_narrative(enrich(sn), {})["narrative_direction"]
    rows.append({"ts": sn.get("timestamp"), "w": w, "det": det, "sn": sn})

div_idx = [i for i, r in enumerate(rows) if tok(r["w"]) != tok(r["det"])]
print(f"total scans={len(rows)} wrapper-vs-deterministic divergences={len(div_idx)}")

# ── pass 2: LLM on mandatory points + stratified sample of divergences ─────────
MAND = {"100049","100553","102955","110052","131741","140000","102553","103553"}
sample = set()
for i in div_idx[::max(1, len(div_idx)//30)]:   # ~30 sampled divergences
    sample.add(i)
# add mandatory by timestamp match
for i, r in enumerate(rows):
    tsc = (r["ts"] or "").replace("-","").replace(":","")
    if any(mm in tsc for mm in MAND):
        sample.add(i)

llm_dir = {}; fb = {"count":0, "reasons":{}}; calls=0
sm = StanceMemory(persist=False)
for i in sorted(sample):
    sn = enrich(rows[i]["sn"])
    res = nb.run_narrative_brain(sn, "QQQ", sm)
    calls += 1
    llm_dir[i] = res["output"]["narrative_direction"]
    if res["source"] != "llm":
        fb["count"] += 1
        fb["reasons"][res.get("fallback_reason")] = fb["reasons"].get(res.get("fallback_reason"),0)+1
print(f"LLM live calls={calls} fallbacks={fb['count']} reasons={fb['reasons']}")

# ── scoreboard on sampled divergences: LLM vs wrapper vs deterministic ─────────
sb = {"llm_better":0,"wrapper_better":0,"det_better":0,"equal":0,"inconclusive":0}
H=[5,15,30,60]
for i in sample:
    if i not in div_idx and tok(rows[i]["w"])==tok(llm_dir.get(i)): continue
    w,det,llm = tok(rows[i]["w"]), tok(rows[i]["det"]), tok(llm_dir.get(i))
    sc={"w":0,"det":0,"llm":0}
    for h in H:
        p0,p1 = fwd(rows[i]["ts"], h)
        if p0 is None or p1 is None: continue
        mv=sgn(p1-p0)
        for who,t in (("w",w),("det",det),("llm",llm)):
            if t==mv or (t=="flat" and mv=="flat"): sc[who]+=1
            elif t!="flat" and t!=mv: sc[who]-=1
    best=max(sc, key=sc.get); top=sc[best]
    if list(sc.values()).count(top)>1: sb["equal"]+=1
    elif all(v==0 for v in sc.values()): sb["inconclusive"]+=1
    elif best=="llm": sb["llm_better"]+=1
    elif best=="w": sb["wrapper_better"]+=1
    else: sb["det_better"]+=1
print("\nSAMPLED SCOREBOARD (LLM vs Wrapper vs Deterministic, fwd-validated):")
for k,v in sb.items(): print(f"   {k}: {v}")

# ── deep dive ──────────────────────────────────────────────────────────────────
print("\n=== JUNE 11 DEEP DIVE (live LLM) ===")
for label,stamp in [("10:00 raid","100049"),("10:05 resp","100553"),("10:29 LONG","102955"),
                    ("11:00 prot-low","110052"),("13:17 SHORT","131741")]:
    cand=[i for i,r in enumerate(rows) if stamp in (r["ts"] or "").replace("-","").replace(":","")]
    if not cand: continue
    i=cand[0]; r=rows[i]; sn=enrich(r["sn"])
    res=nb.run_narrative_brain(sn,"QQQ",StanceMemory(persist=False)); o=res["output"]
    p0,p60=fwd(r["ts"],60); mv=round((p60-p0),2) if (p0 and p60) else None
    print(f"\n-- {label} | wrapper={r['w']} | det={r['det']} | LLM={o['narrative_direction']} (src={res['source']}) | fwd60={mv}")
    print(f"   LLM story: {(o['market_story'] or '')[:260]}")
    print(f"   phase={o['narrative_phase']} forbidden={o['forbidden_direction']} draw={o['active_draw']} PHstat={o['protected_high_status']}")
    print(f"   dominant_reasoning: {(o['dominant_reasoning'] or '')[:220]}")
    print(f"   must_not_do={o['must_not_do']} rec_playbook={o['recommended_playbook_family']}")

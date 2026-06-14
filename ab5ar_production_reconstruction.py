"""AB-5A-R/H2 — PRODUCTION-input blind reconstruction (evidence only).

Same chronological blind replay as AB-5A-R, but feeds the snapshot WITH real
mechanical structure bias (derived from bars) and uses the REAL production
build_brain_input (via run_narrative_brain). NO manual stripping in the harness
— decontamination happens inside build_brain_input (AI-BRAIN-H2). This confirms
whether the production-clean input reproduces the AB-5A-R clean result.
"""
import os, sys, json, glob, re, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "src"); sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(".env")
BLIND = open("data/.blind_corpus_path").read().strip()
os.environ.update({"AI_BRAIN_ENABLED": "true", "AI_BRAIN_LLM": "true",
                   "AI_BRAIN_MODEL": "gpt-4o-mini", "AI_BRAIN_TIMEOUT_SECONDS": "18",
                   "AI_BRAIN_DIR": tempfile.mkdtemp(), "AI_RETRIEVAL_DIR": BLIND})
import ai_brain.narrative_brain as nb
from ai_brain.stance_memory import StanceMemory

BARS = []
for b in json.load(open("data/replay_20260611_1m.json")):
    t = datetime.fromisoformat(b["t"]).astimezone(timezone.utc).replace(tzinfo=None)
    BARS.append((t, b["o"], b["h"], b["l"], b["c"]))
def upto(t): return [b for b in BARS if b[0] <= t]
def price_at(t):
    u = upto(t); return u[-1][4] if u else None

SEM = {"above_high": "bearish", "below_low": "bullish"}

def struct_bias(t):
    """Real mechanical 2-swing structure bias from bars (the thing H2 strips)."""
    u = upto(t)
    if len(u) < 20: return "neutral", None, None
    highs = [b[2] for b in u[-20:]]; lows = [b[3] for b in u[-20:]]
    sh, sl = max(highs), min(lows)
    mid = len(u) - 10
    rh, rl = max(b[2] for b in u[-10:]), min(b[3] for b in u[-10:])
    ph, pl = max(b[2] for b in u[-20:-10]), min(b[3] for b in u[-20:-10])
    if rh > ph and rl > pl: bias = "bullish"
    elif rh < ph and rl < pl: bias = "bearish"
    else: bias = "neutral"
    return bias, round(sh, 2), round(sl, 2)

class Prot:
    def __init__(self): self.ph=None; self.pl=None
    def update(self, t, sweep):
        u = upto(t)
        if len(u) < 16: return
        w = u[-16:]; px = u[-1][4]
        if sweep == "above_high": self.ph = {"level": round(max(x[2] for x in w), 2)}
        elif sweep == "below_low": self.pl = {"level": round(min(x[3] for x in w), 2)}
        if self.ph and px > self.ph["level"]*1.0005: self.ph=None
        if self.pl and px < self.pl["level"]*0.9995: self.pl=None

def make_snapshot(snap, t, prot):
    """Build a PRODUCTION-shaped snapshot (incl. structure bias) — NOT stripped."""
    s = (snap.get("ai_context", {}) or {}).get("summary", "")
    m = re.search(r"Liquidity sweep (above_high|below_low) on (\w+)", s)
    sweep, tf = (m.group(1), m.group(2)) if m else (None, None)
    prot.update(t, sweep); deliv = SEM.get(sweep)
    u = upto(t); px = u[-1][4] if u else None
    win = u[-20:] if len(u) >= 20 else u
    ss = round(min(x[3] for x in win), 2) if win else None
    bs = round(max(x[2] for x in win), 2) if win else None
    draw = ({"side":"sell_side","level":ss} if deliv=="bearish" and ss else
            {"side":"buy_side","level":bs} if deliv=="bullish" and bs else
            {"side":"sell_side","level":ss} if prot.ph and ss else
            {"side":"buy_side","level":bs} if prot.pl and bs else None)
    sb, sh, sl = struct_bias(t)
    return {
        "timestamp": snap.get("timestamp"), "session": snap.get("session"),
        # PRODUCTION structure WITH bias + state — build_brain_input must strip it
        "structure": {tf2: {"bias": sb, "state": f"{sb}_continuation" if sb!="neutral" else "range_bound",
                            "last_swing_high": sh, "last_swing_low": sl,
                            "bos": False, "mss": False} for tf2 in ("15m","5m","3m","1m")},
        "ai_context": {"directional_bias": sb, "market_narrative": s[:200]},   # NOT stripped
        "shared_context": {"delivery_state": f"{deliv}_delivery" if deliv else "unknown",
                           "delivery_confidence": 25 if deliv else 0, "exhaustion_present": True},
        "po3": ({tf: {"phase":"manipulation","manipulation_direction":deliv,
                      "manipulation_direction_source":"sweep_semantics"}} if deliv else {}),
        "liquidity": ({tf: {"sweep_detected":True,"sweep_direction":sweep,"reclaim_detected":True,
                            "nearest_sell_side_liquidity":ss,"nearest_buy_side_liquidity":bs}} if sweep else {}),
        "protected_swings": {"protected_high":prot.ph,"protected_low":prot.pl},
        "narrative_authority": {"narrative_direction": sb, "forbidden_trade_direction": None,
                                "active_liquidity_draw": draw},
        "market_regime": snap.get("market_regime", {}),
        "council": {"report": {"dominant_position": "no"}},
        "timeframes": {"1m": {"candles":[{"open":b[1],"high":b[2],"low":b[3],"close":b[4]} for b in u[-5:]],
                              "last_candle":{"close":px}}},
        "position_monitor": {"has_open_position": False},
    }

def longc(o): return (o["narrative_direction"]=="bullish" and o["forbidden_direction"]!="bullish"
                      and "wait" not in str(o["recommended_tool_family"]).lower()
                      and "confirmation_required" not in str(o["recommended_tool_family"]).lower())
def shortc(o): return (o["narrative_direction"]=="bearish" and o["forbidden_direction"]!="bearish"
                       and "wait" not in str(o["recommended_tool_family"]).lower()
                       and "confirmation_required" not in str(o["recommended_tool_family"]).lower())
def et(t): return (t - timedelta(hours=4)).strftime("%H:%M")

def run_window(s_hhmm, e_hhmm, step):
    prot = Prot(); sm = StanceMemory(persist=False); rows = []; last = None
    for fp in sorted(glob.glob("data/live_snapshots/20260611_*_QQQ.json")):
        ts = os.path.basename(fp).split("_")[1]
        if not (s_hhmm <= ts[:4] <= e_hhmm): continue
        tt = datetime(2026,6,11,int(ts[:2]),int(ts[2:4])) + timedelta(hours=4)
        if last and (tt-last).total_seconds() < step*60: continue
        last = tt
        snap = make_snapshot(json.load(open(fp,encoding="utf-8")), tt, prot)
        res = nb.run_narrative_brain(snap, "QQQ", sm)   # PRODUCTION path
        o = res["output"]
        rows.append({"et":et(tt),"src":res["source"],"dir":o["narrative_direction"],
                     "forbid":o["forbidden_direction"],"long":longc(o),"short":shortc(o),
                     "contaminated": res["source"]=="contaminated_input"})
    return rows

def milestones(rows):
    f=lambda p: next((r["et"] for r in rows if p(r)), None)
    return {"first_bearish":f(lambda r:r["dir"]=="bearish"),
            "first_forbid_bullish":f(lambda r:r["forbid"]=="bullish"),
            "first_short_candidate":f(lambda r:r["short"]),
            "first_long_candidate":f(lambda r:r["long"]),
            "any_bullish_narr":any(r["dir"]=="bullish" for r in rows),
            "contaminated_calls":sum(1 for r in rows if r["contaminated"])}

if __name__ == "__main__":
    import sys as _s
    mode = _s.argv[1] if len(_s.argv) > 1 else "primary"
    if mode == "primary":
        rows = run_window("0938","1100",4)
        print("=== PRODUCTION BLIND RECON 09:38-11:00 (real build_brain_input) ===")
        for r in rows:
            print(f"{r['et']} src={r['src']:18} dir={r['dir']:10} forbid={str(r['forbid']):8} "
                  f"long={r['long']} short={r['short']}")
        print("\nMILESTONES:", json.dumps(milestones(rows), indent=1))
    else:
        print("=== 3-RUN STABILITY (10:00-10:42, production input) ===")
        for i in range(3):
            rows = run_window("1000","1042",4)
            ms = milestones(rows)
            near = [r for r in rows if r["et"] in ("10:26","10:30","10:28")]
            forbids_long = all(r["forbid"]=="bullish" or r["dir"]!="bullish" for r in near) if near else None
            window_short = any(r["short"] and "1020"<=r["et"].replace(":","")<="1040" for r in rows)
            print(f"RUN {i+1}: first_bearish={ms['first_bearish']} first_short={ms['first_short_candidate']} "
                  f"bullish_narrs={sum(1 for r in rows if r['dir']=='bullish')} "
                  f"long_cands={sum(1 for r in rows if r['long'])} "
                  f"10:29_forbids_long={forbids_long} short_in_window={window_short} "
                  f"contaminated={ms['contaminated_calls']}")

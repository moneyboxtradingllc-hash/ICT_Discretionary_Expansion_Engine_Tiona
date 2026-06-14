"""AB-5A-R — blind chronological reconstruction (evidence only).

Feeds June 11 scans in time order; protected swings + stance memory + retrieval
(June-10-only corpus) update chronologically; no future data, no answer hints.
Runs the LLM Brain in sequence and detects milestones AFTER the replay.
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

# ── bars (June 11) ────────────────────────────────────────────────────────────
BARS = []
for b in json.load(open("data/replay_20260611_1m.json")):
    t = datetime.fromisoformat(b["t"]).astimezone(timezone.utc).replace(tzinfo=None)
    BARS.append((t, b["o"], b["h"], b["l"], b["c"]))
def bars_upto(t):  return [b for b in BARS if b[0] <= t]
def price_at(t):
    up = bars_upto(t);  return up[-1][4] if up else None

SEM = {"above_high": "bearish", "below_low": "bullish"}

class ProtState:
    """Chronological protected high/low from bars (no future data)."""
    def __init__(self): self.ph = None; self.pl = None
    def update(self, t, sweep_dir):
        up = bars_upto(t)
        if len(up) < 16: return
        window = up[-16:]
        px = up[-1][4]
        if sweep_dir == "above_high":
            self.ph = {"level": round(max(w[2] for w in window), 2)}
        elif sweep_dir == "below_low":
            self.pl = {"level": round(min(w[3] for w in window), 2)}
        if self.ph and px > self.ph["level"] * 1.0005: self.ph = None
        if self.pl and px < self.pl["level"] * 0.9995: self.pl = None

def enrich_chrono(snap, t, prot):
    s = (snap.get("ai_context", {}) or {}).get("summary", "")
    m = re.search(r"Liquidity sweep (above_high|below_low) on (\w+)", s)
    sweep, tf = (m.group(1), m.group(2)) if m else (None, None)
    prot.update(t, sweep)
    deliv = SEM.get(sweep)
    up = bars_upto(t); px = up[-1][4] if up else None
    # active draw: opposite resting pool from recent bars
    win = up[-20:] if len(up) >= 20 else up
    sell_side = round(min(w[3] for w in win), 2) if win else None
    buy_side = round(max(w[2] for w in win), 2) if win else None
    draw = None
    if deliv == "bearish" and sell_side: draw = {"side": "sell_side", "level": sell_side}
    elif deliv == "bullish" and buy_side: draw = {"side": "buy_side", "level": buy_side}
    elif prot.ph and sell_side: draw = {"side": "sell_side", "level": sell_side}
    elif prot.pl and buy_side: draw = {"side": "buy_side", "level": buy_side}
    out = dict(snap)
    # BLIND: strip the structure-tainted summary so the LLM is not handed the bias
    out["ai_context"] = {"directional_bias": "neutral", "market_narrative": ""}
    out["shared_context"] = {"delivery_state": f"{deliv}_delivery" if deliv else "unknown",
                             "delivery_confidence": 25 if deliv else 0, "exhaustion_present": True}
    out["po3"] = ({tf: {"phase": "manipulation", "manipulation_direction": deliv,
                        "manipulation_direction_source": "sweep_semantics"}} if deliv else {})
    out["liquidity"] = ({tf: {"sweep_detected": True, "sweep_direction": sweep,
                              "reclaim_detected": True,
                              "nearest_sell_side_liquidity": sell_side,
                              "nearest_buy_side_liquidity": buy_side}} if sweep else {})
    out["protected_swings"] = {"protected_high": prot.ph, "protected_low": prot.pl}
    out["narrative_authority"] = {"active_liquidity_draw": draw}
    out["timeframes"] = {"1m": {"candles": [{"open": b[1], "high": b[2], "low": b[3], "close": b[4]}
                                            for b in up[-5:]], "last_candle": {"close": px}}}
    return out

def long_candidate(o):
    return (o["narrative_direction"] == "bullish" and o["forbidden_direction"] != "bullish"
            and "wait" not in str(o["recommended_tool_family"]).lower()
            and "confirmation_required" not in str(o["recommended_tool_family"]).lower())
def short_candidate(o):
    return (o["narrative_direction"] == "bearish" and o["forbidden_direction"] != "bearish"
            and "wait" not in str(o["recommended_tool_family"]).lower()
            and "confirmation_required" not in str(o["recommended_tool_family"]).lower())

def et(t): return (t - timedelta(hours=4)).strftime("%H:%M")

def run_window(start_hhmm, end_hhmm, step_min, label):
    files = sorted(glob.glob("data/live_snapshots/20260611_*_QQQ.json"))
    prot = ProtState(); sm = StanceMemory(persist=False)
    rows = []; last_t = None
    for fp in files:
        ts = os.path.basename(fp).split("_")[1]   # ET HHMMSS
        hhmm = ts[:4]
        if not (start_hhmm <= hhmm <= end_hhmm): continue
        # sample at step_min resolution
        tt = datetime(2026, 6, 11, int(ts[:2]), int(ts[2:4])) + timedelta(hours=4)  # ET->UTC
        if last_t and (tt - last_t).total_seconds() < step_min * 60:
            continue
        last_t = tt
        snap = json.load(open(fp, encoding="utf-8"))
        es = enrich_chrono(snap, tt, prot)
        res = nb.run_narrative_brain(es, "QQQ", sm)
        o = res["output"]
        rows.append({"et": et(tt), "src": res["source"], "px": price_at(tt),
                     "ph": (prot.ph or {}).get("level"), "pl": (prot.pl or {}).get("level"),
                     "draw": (es["narrative_authority"]["active_liquidity_draw"] or {}).get("side"),
                     "deliv": es["shared_context"]["delivery_state"],
                     "dir": o["narrative_direction"], "phase": o["narrative_phase"],
                     "forbid": o["forbidden_direction"], "tools": o["recommended_tool_family"],
                     "long": long_candidate(o), "short": short_candidate(o),
                     "reason": (o["dominant_reasoning"] or "")[:140]})
    return rows

def milestones(rows):
    def first(pred): return next((r["et"] for r in rows if pred(r)), None)
    return {
        "first_bearish_narrative": first(lambda r: r["dir"] == "bearish"),
        "first_bullish_narrative": first(lambda r: r["dir"] == "bullish"),
        "first_forbid_bullish": first(lambda r: r["forbid"] == "bullish"),
        "first_forbid_bearish": first(lambda r: r["forbid"] == "bearish"),
        "first_short_candidate": first(lambda r: r["short"]),
        "first_long_candidate": first(lambda r: r["long"]),
        "first_protected_high": first(lambda r: r["ph"] is not None),
        "first_sell_side_draw": first(lambda r: r["draw"] == "sell_side"),
        "first_bearish_delivery": first(lambda r: "bearish" in (r["deliv"] or "")),
    }

if __name__ == "__main__":
    print("=== PRIMARY BLIND RECONSTRUCTION 09:38-11:00 ET (~4-min sampling) ===")
    rows = run_window("0938", "1100", 4, "primary")
    print(f"{'ET':6}{'px':8}{'PH':8}{'draw':10}{'deliv':18}{'LLMdir':10}{'forbid':9}{'long':6}{'short':6}")
    for r in rows:
        print(f"{r['et']:6}{str(r['px']):8}{str(r['ph']):8}{str(r['draw']):10}{r['deliv']:18}"
              f"{r['dir']:10}{str(r['forbid']):9}{str(r['long']):6}{str(r['short']):6}")
    ms = milestones(rows)
    print("\nMILESTONES:")
    for k, v in ms.items(): print(f"   {k}: {v}")

"""AB-6A — ECU full-session reconstruction campaign (observe-only).

Replays one day chronologically through the installed ECU brain (BRAIN_ECU_MODE
+ AI_BRAIN_LLM), prior-day-only retrieval, ~10-min sampling. Records every
thesis/playbook/tool. No optimization, no changes — dyno observation.

Usage: python ab6a_campaign.py <YYYYMMDD> <prior1,prior2,...> [step_min]
"""
import os, sys, json, glob, re, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0,"src"); sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(".env")

DATE = sys.argv[1]
PRIOR = [d for d in sys.argv[2].split(",") if d] if len(sys.argv) > 2 else []
STEP = int(sys.argv[3]) if len(sys.argv) > 3 else 10

# blind prior-day retrieval corpus
blind = tempfile.mkdtemp(prefix=f"ab6a_{DATE}_")
os.environ.update({"BRAIN_ECU_MODE":"true","AI_BRAIN_ENABLED":"true","AI_BRAIN_LLM":"true",
                   "AI_BRAIN_MODEL":"gpt-4o-mini","AI_BRAIN_TIMEOUT_SECONDS":"16",
                   "AI_BRAIN_DIR":tempfile.mkdtemp(),"AI_RETRIEVAL_DIR":blind})
from ai_retrieval.vector_store import clear
from ai_retrieval.backfill import backfill_dates
clear()
if PRIOR:
    backfill_dates(tuple(PRIOR), "QQQ")

import ai_brain.ecu as ecu
from ai_brain.ecu import produce_thesis
from qualification.trade_qualification_engine import qualify_trade
from playbooks.playbook_classifier import classify_playbook
from toolbox.toolbox_engine import run_toolbox
from ai_brain.stance_memory import StanceMemory
ecu._STANCE = StanceMemory(persist=False)

BARS=[]
for b in json.load(open(f"data/replay_{DATE}_1m.json")):
    t=datetime.fromisoformat(b["t"]).astimezone(timezone.utc).replace(tzinfo=None); BARS.append((t,b["o"],b["h"],b["l"],b["c"]))
def upto(t): return [x for x in BARS if x[0]<=t]
SEM={"above_high":"bearish","below_low":"bullish"}
def mk(snap,t):
    s=(snap.get("ai_context",{}) or {}).get("summary","")
    m=re.search(r"Liquidity sweep (above_high|below_low) on (\w+)",s); sweep,tf=(m.group(1),m.group(2)) if m else (None,None); deliv=SEM.get(sweep)
    u=upto(t); px=u[-1][4] if u else None
    return {"timestamp":snap.get("timestamp"),"symbol":"QQQ","ai_context":{"directional_bias":"neutral","market_narrative":s[:150]},
            "structure":{tf2:{"bias":"neutral","mss":True,"bos":True,"last_swing_high":(max(x[2] for x in u[-15:]) if len(u)>=15 else None),"last_swing_low":(min(x[3] for x in u[-15:]) if len(u)>=15 else None)} for tf2 in ("15m","5m","3m","1m")},
            "shared_context":{"delivery_state":f"{deliv}_delivery" if deliv else "unknown","delivery_confidence":25 if deliv else 0,"exhaustion_present":True},
            "po3":({tf:{"phase":"manipulation","manipulation_direction":deliv,"manipulation_direction_source":"sweep_semantics"}} if deliv else {}),
            "liquidity":({tf2:{"sweep_detected":True,"sweep_direction":sweep,"reclaim_detected":True} for tf2 in ("15m","5m","3m","1m")} if sweep else {}),
            "volatility":{tf2:{"state":"expanding"} for tf2 in ("15m","5m","3m","1m")},"risk":{"trade_allowed":True},
            "expansion":{tf2:{"state":"early_expansion","displacement_detected":True} for tf2 in ("15m","5m","3m","1m")},
            "protected_swings":{"protected_high":({"level":round(max(x[2] for x in u[-15:]),2)} if sweep=="above_high" and len(u)>=15 else None),
                                "protected_low":({"level":round(min(x[3] for x in u[-15:]),2)} if sweep=="below_low" and len(u)>=15 else None)},
            "narrative_authority":{"active_liquidity_draw":({"side":"sell_side"} if deliv=="bearish" else {"side":"buy_side"} if deliv=="bullish" else None)},
            "market_regime":{"regime_label":"range_rotation","volatility_state":"unstable","expansion_state":"exhaustion_risk"},
            "timeframes":{"1m":{"candles":[{"open":b[1],"high":b[2],"low":b[3],"close":b[4]} for b in u[-5:]],"last_candle":{"close":px}}},
            "position_monitor":{"has_open_position":False}}
def et(t): return (t-timedelta(hours=4)).strftime("%H:%M")

rows=[]; last=None
for fp in sorted(glob.glob(f"data/live_snapshots/{DATE}_*_QQQ.json")):
    ts=os.path.basename(fp).split("_")[1]
    if not ("0930"<=ts[:4]<="1500"): continue
    tt=datetime(int(DATE[:4]),int(DATE[4:6]),int(DATE[6:8]),int(ts[:2]),int(ts[2:4]))+timedelta(hours=4)
    if last and (tt-last).total_seconds()<STEP*60: continue
    last=tt
    snap=mk(json.load(open(fp,encoding="utf-8")),tt); snap["brain_thesis"]=produce_thesis(snap)
    snap["qualification"]=qualify_trade(snap); pb=classify_playbook(snap); snap["playbook"]=pb
    tb=run_toolbox(snap); bt=snap["brain_thesis"]
    rows.append({"et":et(tt),"dir":bt["direction"],"forbid":bt["forbidden_direction"],
                 "opp":bt["opportunity"],"opp_type":bt["opportunity_type"],"conf":bt["confidence"],
                 "playbook":pb["selected_playbook"],"tool":tb["preferred_tool"],
                 "tool_src":tb.get("preferred_tool_source"),"src":bt["source"]})

# aggregates
from collections import Counter
dirs=Counter(r["dir"] for r in rows); pbs=Counter(r["playbook"] for r in rows if r["playbook"]!="no_playbook")
tools=Counter(r["tool"] for r in rows if r["tool"]); toolsrc=Counter(r["tool_src"] for r in rows if r["tool"])
dchg=sum(1 for i in range(1,len(rows)) if rows[i]["dir"]!=rows[i-1]["dir"])
pchg=sum(1 for i in range(1,len(rows)) if rows[i]["playbook"]!=rows[i-1]["playbook"])
tchg=sum(1 for i in range(1,len(rows)) if rows[i]["tool"]!=rows[i-1]["tool"])
summary={"date":DATE,"scans":len(rows),"direction_counts":dict(dirs),
         "playbook_freq":dict(pbs),"tool_freq":dict(tools),"tool_source":dict(toolsrc),
         "direction_changes":dchg,"playbook_changes":pchg,"tool_changes":tchg,
         "first_bearish":next((r["et"] for r in rows if r["dir"]=="bearish"),None),
         "first_bullish":next((r["et"] for r in rows if r["dir"]=="bullish"),None),
         "first_opportunity":next((r["et"] for r in rows if r["opp"]),None)}
json.dump({"summary":summary,"rows":rows},open(f"data/ab6a_{DATE}.json","w"),indent=1)
print(f"=== AB-6A {DATE} (step={STEP}m, prior={PRIOR}) ===")
print(json.dumps(summary,indent=1))
print("\nTIMELINE:")
for r in rows:
    print(f"  {r['et']} {r['dir']:10} opp={r['opp']!s:5} pb={r['playbook']:24} tool={str(r['tool']):20} ({r['tool_src']})")

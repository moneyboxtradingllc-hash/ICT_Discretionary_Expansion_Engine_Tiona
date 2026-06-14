"""AB-6B probe — observe-only. Captures, for June 11 09:30-11:00, the Brain's
RAW playbook_family + opportunity_type + dominant_reasoning, alongside the
classifier's selected_playbook + direction_source, to distinguish:
  (a) the LLM explicitly choosing liquidity_sweep_reversal, vs
  (b) opportunity_type being routed to LSR by _PHASE_TO_PLAYBOOK.
No code/ownership/prompt changes. Reuses the AB-6A reconstruction snapshot.
"""
import os, sys, json, glob, re, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0,"src"); sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(".env")

DATE="20260611"; PRIOR=("20260608","20260609","20260610")
blind=tempfile.mkdtemp(prefix="ab6b_")
os.environ.update({"BRAIN_ECU_MODE":"true","AI_BRAIN_ENABLED":"true","AI_BRAIN_LLM":"true",
                   "AI_BRAIN_MODEL":"gpt-4o-mini","AI_BRAIN_TIMEOUT_SECONDS":"16",
                   "AI_BRAIN_DIR":tempfile.mkdtemp(),"AI_RETRIEVAL_DIR":blind})
from ai_retrieval.vector_store import clear
from ai_retrieval.backfill import backfill_dates
clear(); backfill_dates(PRIOR,"QQQ")
import ai_brain.ecu as ecu
from ai_brain.ecu import produce_thesis
from qualification.trade_qualification_engine import qualify_trade
from playbooks.playbook_classifier import classify_playbook, _score_liquidity_sweep_reversal, \
    _score_trend_continuation, _score_manipulation_to_distribution, _score_failed_breakout_reversal, \
    _score_opening_drive, _score_range_expansion
from toolbox.toolbox_engine import run_toolbox
from ai_brain.stance_memory import StanceMemory
ecu._STANCE=StanceMemory(persist=False)

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
    if not ("0930"<=ts[:4]<="1100"): continue
    tt=datetime(int(DATE[:4]),int(DATE[4:6]),int(DATE[6:8]),int(ts[:2]),int(ts[2:4]))+timedelta(hours=4)
    if last and (tt-last).total_seconds()<5*60: continue
    last=tt
    snap=mk(json.load(open(fp,encoding="utf-8")),tt); snap["brain_thesis"]=produce_thesis(snap)
    snap["qualification"]=qualify_trade(snap); pb=classify_playbook(snap)
    bt=snap["brain_thesis"]
    scores={"LSR":_score_liquidity_sweep_reversal(snap),"trend":_score_trend_continuation(snap),
            "m2d":_score_manipulation_to_distribution(snap),"fbr":_score_failed_breakout_reversal(snap),
            "open":_score_opening_drive(snap),"range":_score_range_expansion(snap)}
    rows.append({"et":et(tt),"dir":bt["direction"],"opp":bt["opportunity"],"opp_type":bt["opportunity_type"],
                 "llm_playbook_family":bt.get("playbook_family"),"selected":pb["selected_playbook"],
                 "dir_source":pb.get("direction_source"),"scores":scores,
                 "reasoning":(bt.get("dominant_reasoning") or "")[:500]})

json.dump(rows,open("data/ab6b_june11_probe.json","w"),indent=1)
print(f"=== AB-6B PROBE June 11 09:30-11:00 ({len(rows)} scans) ===\n")
for r in rows:
    print(f"{r['et']} dir={r['dir']:9} opp={r['opp']!s:5} opp_type={r['opp_type']:13} "
          f"LLM_playbook={str(r['llm_playbook_family']):28} -> selected={r['selected']:25} src={r['dir_source']}")
    print(f"      mechanical_scores={r['scores']}")
    if r['reasoning']: print(f"      reasoning: {r['reasoning']}\n")

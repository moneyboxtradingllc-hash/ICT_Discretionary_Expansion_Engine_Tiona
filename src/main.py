import sys
import os
import random
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_data.snapshot_builder import build_snapshot
from state.market_memory import MarketMemory

EASTERN = pytz.timezone("America/New_York")


def generate_mock_candles(
    start_dt: datetime, count: int, tf_minutes: int, base_price: float = 19500.0
) -> list:
    candles = []
    price = base_price

    for i in range(count):
        ts = start_dt + timedelta(minutes=tf_minutes * i)
        move = random.uniform(-8, 8)
        o = round(price, 2)
        c = round(price + move, 2)
        h = round(max(o, c) + random.uniform(0.5, 4), 2)
        l = round(min(o, c) - random.uniform(0.5, 4), 2)
        v = random.randint(300, 4000)
        candles.append({
            "timestamp": ts.isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
        price = c

    return candles


def _raw_data(anchor: datetime) -> dict:
    return {
        "15m": generate_mock_candles(anchor - timedelta(hours=6),    count=24, tf_minutes=15),
        "5m":  generate_mock_candles(anchor - timedelta(hours=2),    count=24, tf_minutes=5),
        "3m":  generate_mock_candles(anchor - timedelta(minutes=60), count=20, tf_minutes=3),
        "1m":  generate_mock_candles(anchor - timedelta(minutes=15), count=15, tf_minutes=1),
    }


def _divider(char="-", width=60):
    print(char * width)


def _print_price_level(pl: dict):
    lt      = pl.get("level_type",        "no_zone")
    zl      = pl.get("zone_low")
    zh      = pl.get("zone_high")
    mid     = pl.get("midpoint")
    current = pl.get("current_price")
    dist    = pl.get("distance_to_zone")
    rel     = pl.get("price_relation",    "unknown")
    entered = pl.get("entered_zone",      False)
    inval   = pl.get("invalidated",       False)
    inv_lv  = pl.get("invalidation_level")
    src_tf  = pl.get("source_tf")

    print(f"  Price Level      : {lt}  (source: {src_tf})")
    if zl is not None:
        print(f"    Zone           : {zl} - {zh}  (mid: {mid})")
        dist_str = f"{dist} pts away" if dist and dist > 0 else "inside zone"
        print(f"    Current Price  : {current}  ({rel.replace('_',' ')}, {dist_str})")
        print(f"    Entered Zone   : {'Yes' if entered else 'No'}")
        print(f"    Invalidated    : {'YES' if inval else 'No'}")
        if inv_lv is not None:
            print(f"    Invalidation   : {inv_lv}")
    else:
        print(f"    No zone identified for this tool")


def _print_trigger_prep(tp: dict):
    raw_ts  = tp.get("raw_trigger_status",       "?")
    eff_ts  = tp.get("effective_trigger_status",  "?")
    ex_rdy  = tp.get("execution_ready",           False)
    confirms = tp.get("confirmation_needed",      [])
    invals   = tp.get("invalidation_conditions",  [])

    print(f"  Trigger Prep:")
    print(f"    Earned (raw)   : {raw_ts.upper()}")
    if eff_ts != raw_ts:
        print(f"    Effective      : {eff_ts.upper()}  [Risk Governor override]")
    else:
        print(f"    Effective      : {eff_ts.upper()}")
    print(f"    Execution Ready: {'YES' if ex_rdy else 'No'}")
    if confirms:
        print(f"    Confirmation needed:")
        for item in confirms:
            print(f"      > {item}")
    if invals:
        print(f"    Zone invalidated by:")
        for item in invals:
            print(f"      x {item}")


def _print_readiness(candidate: dict):
    tool   = candidate["tool"]
    score  = candidate["score"]
    raw    = candidate.get("raw_status",       "?")
    eff    = candidate.get("effective_status", "?")
    r      = candidate.get("readiness", {})

    print(f"  Tool             : {tool}")
    print(f"  Score            : {score}")
    print(f"  Earned (raw)     : {raw.upper()}")

    if eff != raw:
        print(f"  Effective        : {eff.upper()}  [Risk Governor override]")
    else:
        print(f"  Effective        : {eff.upper()}")

    reasons = candidate.get("reasons", [])
    if reasons:
        print(f"  Why present:")
        for reason in reasons:
            print(f"    + {reason}")

    prereqs = r.get("prerequisites_missing", [])
    if prereqs:
        print(f"  Prerequisites missing:")
        for item in prereqs:
            print(f"    ! {item}")

    gaps = r.get("score_gaps", [])
    if gaps:
        print(f"  Score gaps (confidence boosters not yet met):")
        for item in gaps:
            print(f"    ~ {item}")

    if not prereqs and not gaps:
        print(f"  All prerequisites met and score gaps closed")

    promote = r.get("promotion_criteria", [])
    next_st = r.get("next_status")
    if next_st and promote:
        print(f"  Promotes to {next_st.upper()} when:")
        for item in promote:
            print(f"    > {item}")
    elif raw == "actionable":
        print(f"  Already ACTIONABLE - no further promotion needed")

    invalidation = r.get("invalidation_criteria", [])
    if invalidation:
        print(f"  Setup invalidated by:")
        for item in invalidation:
            print(f"    x {item}")

    # Price level and trigger prep
    pl = candidate.get("price_level")
    tp = candidate.get("trigger_prep")
    if pl:
        _print_price_level(pl)
    if tp:
        _print_trigger_prep(tp)

    warnings = candidate.get("warnings", [])
    if warnings:
        print(f"  Warnings:")
        for w in warnings:
            print(f"    ! {w}")


def _print_snapshot_breakdown(snap: dict):
    qual = snap.get("qualification", {})
    pb   = snap.get("playbook",      {})
    risk = snap.get("risk",          {})
    tb   = snap.get("toolbox",       {})

    # Qualification
    print()
    _divider()
    print("QUALIFICATION")
    _divider()
    print(f"  Status  : {qual.get('status','?').upper()}")
    print(f"  Grade   : {qual.get('grade','?')}")
    print(f"  Score   : {qual.get('opportunity_score', 0)}")
    print(f"  Driver  : {qual.get('primary_driver','?')}")
    print(f"  Dir     : {qual.get('direction','?')}")

    # Playbook
    print()
    _divider()
    print("PLAYBOOK")
    _divider()
    print(f"  Selected    : {pb.get('selected_playbook','?').upper()}")
    print(f"  Status      : {pb.get('status','?').upper()}")
    print(f"  Confidence  : {pb.get('playbook_confidence', 0)}")
    print(f"  Direction   : {pb.get('direction','?')}")

    # Risk Governor
    print()
    _divider()
    print("RISK GOVERNOR")
    _divider()
    print(f"  Tier     : {risk.get('risk_tier','?').upper()}")
    print(f"  Allowed  : {risk.get('trade_allowed', False)}")
    print(f"  Reason   : {risk.get('authority_reason','?')}")
    blocks = risk.get("blocks", [])
    if blocks:
        print(f"  Blocks:")
        for b in blocks:
            print(f"    ! {b}")
    restrictions = risk.get("restrictions", [])
    if restrictions:
        print(f"  Restrictions:")
        for r in restrictions[:3]:
            print(f"    - {r}")

    # Toolbox
    print()
    _divider()
    print("TOOLBOX - Entry Trigger Prep (Phase 1L)")
    _divider()

    best_raw = tb.get("best_available_raw_status",       "no_tool")
    best_eff = tb.get("best_available_effective_status", "no_tool")
    print(f"  Best available (raw)      : {best_raw.upper()}")
    if best_eff != best_raw:
        print(f"  Best available (effective): {best_eff.upper()}  [Risk Governor override]")
    else:
        print(f"  Best available (effective): {best_eff.upper()}")
    print()

    candidates = tb.get("tool_candidates", [])
    if not candidates:
        status_msg = tb.get("toolbox_status", "no_tool")
        warnings   = tb.get("warnings", [])
        print(f"  No tool candidates. Status: {status_msg}")
        for w in warnings:
            print(f"  ! {w}")
    else:
        preferred_tool = tb.get("preferred_tool")
        near_ties      = tb.get("near_tie_tools", [])
        tb_warnings    = tb.get("warnings", [])

        if tb_warnings:
            for w in tb_warnings:
                print(f"  ! {w}")
            print()

        for idx, candidate in enumerate(candidates):
            label = " [PREFERRED]" if candidate["tool"] == preferred_tool else ""
            if candidate["tool"] in near_ties:
                label += " (near-tie)"
            print(f"  -- Candidate {idx + 1}{label}")
            _print_readiness(candidate)
            if idx < len(candidates) - 1:
                print()

    # TIER-2A (2026-07-10) — legacy AI wrapper (discretionary/fusion/debate)
    # retired; the ECU Brain block is the single AI organ.


def _run_live_scan():
    from data_feed import get_provider
    from data_feed.provider_interface import DataFeedError
    from data_feed.timeframe_builder import build_timeframes
    from data_feed.market_clock import is_within_scan_window

    symbol   = os.getenv("SCAN_SYMBOL",       "QQQ")
    lookback = int(os.getenv("SCAN_LOOKBACK_BARS", "300"))
    start_t  = os.getenv("SCAN_START_TIME",   "08:30")
    end_t    = os.getenv("SCAN_END_TIME",      "15:00")
    now_str  = datetime.now(EASTERN).strftime("%H:%M ET")

    _divider("=")
    print(f"Phase 1O - Live Scan | {symbol} | {now_str}")
    _divider("=")
    print()

    if not is_within_scan_window(start_t, end_t):
        print(f"  Outside scan window ({start_t} - {end_t} ET). Current time: {now_str}")
        print("  Set SCAN_START_TIME / SCAN_END_TIME in .env to adjust the window.")
        return

    try:
        provider = get_provider()
    except DataFeedError as exc:
        print(f"  [DATA FEED ERROR] {exc}")
        return

    print(f"  Fetching {lookback} x 1m bars for {symbol} ...")
    try:
        candles_1m = provider.fetch_1m_candles(symbol, lookback)
    except DataFeedError as exc:
        print(f"  [FETCH ERROR] {exc}")
        return

    if not candles_1m:
        print(f"  No candles returned for {symbol}. Market may be closed or feed unavailable.")
        return

    raw_data = build_timeframes(candles_1m)
    counts   = {tf: len(bars) for tf, bars in raw_data.items()}
    print(f"  Bars built : " + " | ".join(f"{tf}={n}" for tf, n in counts.items()))
    print()

    memory   = MarketMemory(max_snapshots=20)
    snapshot = build_snapshot(raw_data, memory=memory)

    _divider("=")
    print(f"Live Snapshot | {symbol} | {snapshot.get('session', 'unknown')} session")
    _divider("=")

    _print_snapshot_breakdown(snapshot)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    if os.getenv("LIVE_MODE", "false").lower() == "true":
        if os.getenv("RUN_SCAN_LOOP", "false").lower() == "true":
            from live_scan.scan_loop import run_scan_loop
            run_scan_loop()
        else:
            _run_live_scan()
        return

    # ── Mock path (unchanged) ──────────────────────────────────────────────────
    memory    = MarketMemory(max_snapshots=20)
    anchor_et = datetime.now(EASTERN).replace(hour=9, minute=45, second=0, microsecond=0)

    _divider("=")
    print("Phase 1L - Entry Trigger Prep / Price-Level Awareness (5 snapshots)")
    _divider("=")
    print()

    last_snapshot = None
    for i in range(5):
        random.seed(42 + i * 7)
        anchor   = anchor_et + timedelta(minutes=i)
        snapshot = build_snapshot(_raw_data(anchor), memory=memory)
        last_snapshot = snapshot

        qual   = snapshot.get("qualification", {})
        pb     = snapshot.get("playbook",      {})
        risk   = snapshot.get("risk",          {})
        tb     = snapshot.get("toolbox",       {})

        preferred   = tb.get("preferred_tool", "none")
        eff_status  = tb.get("toolbox_status", "?")
        pb_name     = pb.get("selected_playbook", "?")
        pb_dir      = pb.get("direction", "?")
        candidates  = tb.get("tool_candidates", [])
        pref_c      = next((c for c in candidates if c["tool"] == preferred), {})
        raw_status  = pref_c.get("raw_status", eff_status)
        t_status    = pref_c.get("trigger_prep", {}).get("effective_trigger_status", "?")
        pl_rel      = pref_c.get("price_level",  {}).get("price_relation", "?")

        status_str  = (
            f"{raw_status}->BLOCKED" if eff_status == "blocked_by_risk" and raw_status != eff_status
            else eff_status
        )

        print(
            f"  [{i+1}] qual={qual.get('status','?'):<10} "
            f"pb={pb_name:<28} dir={pb_dir:<8} "
            f"risk={risk.get('risk_tier','?'):<8} "
            f"tool={str(preferred):<26} ({status_str})"
            f"  trig={t_status}  price={pl_rel}"
        )

    print()
    _divider("=")
    print("Snapshot 5 - Full Phase 1L Entry Trigger Breakdown")
    _divider("=")

    _print_snapshot_breakdown(last_snapshot)


if __name__ == "__main__":
    main()

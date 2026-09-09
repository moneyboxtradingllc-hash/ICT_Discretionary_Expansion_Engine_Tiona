"""READ-ONLY. What the bot PLANNED, what the market DID, and the gap between.

"Was it a dumb trade?" is not answerable from P&L. A loss can be a correct
read that was early, a correct read stopped on noise, or a genuinely bad
thesis -- and those three demand different responses. Only the price path
between entry and exit separates them, so this reconstructs it from the
records the session already wrote:

    submissions_<session>.jsonl     the PLAN. `geometry` carries the bracket
                                    the bot authored: entry, stop, target, and
                                    both distances, as decided BEFORE the order
                                    was sent.
    trade_mission_<session>_<n>.json  the OUTCOME the VENUE reported: fill
                                    price, exit price, exit type, timestamps.
    data/market_data/topstepx/*.jsonl  the PATH. Every minute between fill and
                                    flat, and afterwards.

FOUR MEASUREMENTS PER TRADE:

    MFE   maximum favourable excursion -- the best the trade was ever worth
    MAE   maximum adverse excursion -- the worst it was ever down
    REACH how close the best price came to the target, in points and as a
          fraction of the distance it needed to cover
    AFTER what price did in the window following the exit. This is the one
          that separates "wrong" from "early", and it is reported for both
          winners and losers because a winner that would have run twice as far
          is also information.

NOTHING HERE IS A VERDICT. It measures; the reading is the operator's. In
particular it never says a stop was "too tight" -- the stop is the structural
invalidation, and a trade that reached it was, by the bot's own doctrine,
invalidated.

    python tools/topstepx_trade_postmortem.py --session PROD-20260909
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from data_feed import candle_continuity as CONT  # noqa: E402

STORE_DIR = os.path.join("data", "integration", "topstepx")
CANDLES = os.path.join("data", "market_data", "topstepx")
POINT_VALUE = 2.00          # MNQ, $ per point per contract


def _num(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def load_geometry(store_dir: str, session: str) -> dict:
    """mission_id -> the bracket the bot authored, from the flight recorder."""
    path = os.path.join(store_dir, f"submissions_{session}.jsonl")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            geo = row.get("geometry") or {}
            if geo and row.get("mission_id"):
                out[row["mission_id"]] = {
                    "geometry": geo, "side": row.get("side"),
                    "quantity": row.get("quantity"),
                    "stop_ticks": row.get("signed_stop_loss_ticks"),
                    "target_ticks": row.get("signed_take_profit_ticks")}
    return out


def load_missions(store_dir: str, session: str) -> list:
    out = []
    for path in sorted(glob.glob(os.path.join(
            store_dir, f"trade_mission_{session}_*.json"))):
        with open(path, encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def load_candles(candles_dir: str, contract_id: str) -> list:
    safe = (contract_id or "").replace(".", "_")
    path = os.path.join(candles_dir, f"{safe}.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return CONT.normalize(rows)


def _times(mission: dict) -> dict:
    """Entry and exit instants, each with the field they came from.

    The mission records several timestamps and NOT one called "filled_at".
    Rather than pick one silently, the field used is carried alongside so a
    reader can see which instant a measurement is anchored to.
    """
    entry = exit_ = None
    entry_src = exit_src = "none"
    for row in mission.get("history") or []:
        if not isinstance(row, dict):
            continue
        state = str(row.get("state") or row.get("to") or "")
        stamp = row.get("at") or row.get("transition_at") or row.get("timestamp")
        if not stamp:
            continue
        if entry is None and "POSITION_OPEN" in state:
            entry, entry_src = stamp, f"history:{state}"
        if "COMPLETE" in state or "EXIT" in state:
            exit_, exit_src = stamp, f"history:{state}"
    if entry is None and mission.get("acknowledged_at"):
        entry, entry_src = mission["acknowledged_at"], "acknowledged_at"
    if entry is None and mission.get("submitted_at"):
        entry, entry_src = mission["submitted_at"], "submitted_at"
    if mission.get("flat_confirmed_at"):
        exit_, exit_src = mission["flat_confirmed_at"], "flat_confirmed_at"
    if exit_ is None and mission.get("transition_at"):
        exit_, exit_src = mission["transition_at"], "transition_at"
    return {"entry": CONT.parse_ts(entry) if entry else None,
            "exit": CONT.parse_ts(exit_) if exit_ else None,
            "entry_source": entry_src, "exit_source": exit_src}


def _window(candles: list, lo, hi) -> list:
    out = []
    for c in candles:
        k = CONT.canonical_key(c)
        if k is None:
            continue
        if lo is not None and k < lo:
            continue
        if hi is not None and k > hi:
            continue
        out.append(c)
    return out


def excursions(bars: list, *, entry: float, bullish: bool) -> dict:
    """MFE and MAE in points, plus the extremes that produced them."""
    highs = [(_num(b.get("high")), CONT.canonical_key(b)) for b in bars]
    lows = [(_num(b.get("low")), CONT.canonical_key(b)) for b in bars]
    highs = [(v, t) for v, t in highs if v is not None]
    lows = [(v, t) for v, t in lows if v is not None]
    if not highs or not lows:
        return {}
    best_high, at_high = max(highs, key=lambda x: x[0])
    worst_low, at_low = min(lows, key=lambda x: x[0])
    if bullish:
        mfe, mfe_at, mfe_px = best_high - entry, at_high, best_high
        mae, mae_at, mae_px = entry - worst_low, at_low, worst_low
    else:
        mfe, mfe_at, mfe_px = entry - worst_low, at_low, worst_low
        mae, mae_at, mae_px = best_high - entry, at_high, best_high
    return {"mfe_points": round(mfe, 2), "mfe_at": mfe_at, "mfe_price": mfe_px,
            "mae_points": round(mae, 2), "mae_at": mae_at, "mae_price": mae_px,
            "bars": len(bars)}


def touched(bars: list, level: float, *, above: bool) -> object:
    for b in bars:
        hi, lo = _num(b.get("high")), _num(b.get("low"))
        if above and hi is not None and hi >= level:
            return CONT.canonical_key(b)
        if not above and lo is not None and lo <= level:
            return CONT.canonical_key(b)
    return None


def interval_coverage(candles: list, lo, hi) -> tuple:
    """Coverage of [lo, hi), using the candle owner's minute identities.

    A candle describes a whole minute, not an instantaneous price. Full bars
    can witness a touch inside the interval; a boundary bar cannot locate its
    high/low before versus after a sub-minute entry/exit. Missing/invalid OHLC
    counts as missing evidence. A last bar alone never proves continuity.
    """
    coverage = dict(start=lo, end=hi, resolution="1m", status="UNKNOWN",
                    missing_minutes=[], boundary_minutes=[], seconds=None)
    if lo is None or hi is None or hi <= lo:
        coverage["reason"] = "missing/invalid interval bounds"
        return coverage, [], []
    coverage["seconds"] = (hi - lo).total_seconds()
    indexed = {CONT.canonical_key(c): c for c in CONT.normalize(candles)}
    cursor = lo.replace(second=0, microsecond=0)
    overlapping, full = [], []
    while cursor < hi:
        candle = indexed.get(cursor)
        high = _num((candle or {}).get("high"))
        low = _num((candle or {}).get("low"))
        if candle is None or high is None or low is None or high < low:
            coverage["missing_minutes"].append(cursor.isoformat())
        else:
            overlapping.append(candle)
            if cursor >= lo and cursor + CONT.MINUTE <= hi:
                full.append(candle)
            else:
                coverage["boundary_minutes"].append(cursor.isoformat())
        cursor += CONT.MINUTE
    coverage.update(status="INCOMPLETE" if coverage["missing_minutes"] else "COMPLETE",
                    observed_bars=len(overlapping), full_bars=len(full))
    coverage["reason"] = ("missing minute evidence" if coverage["missing_minutes"]
                           else "all intersecting minutes recorded")
    return coverage, overlapping, full


def touch_evidence(coverage: dict, overlapping: list, full: list,
                   level, *, above: bool) -> dict:
    if level is None:
        return {"status": "UNKNOWN", "reason": "missing direction/level"}
    hit = touched(full, level, above=above)
    if hit is not None:
        return {"status": "YES", "at": hit, "reason": "touch in a fully contained 1m bar"}
    if touched(overlapping, level, above=above) is not None:
        return {"status": "UNKNOWN", "reason": "1m boundary bar cannot locate the touch inside the interval"}
    if coverage["status"] != "COMPLETE":
        return {"status": "UNKNOWN", "reason": coverage["reason"]}
    if coverage.get("boundary_minutes"):
        return {"status": "UNKNOWN", "reason": "boundary 1m bar is only partially inside the interval"}
    return {"status": "NO", "reason": "complete minute coverage; no intersecting bar reaches the level"}


def _direction(value) -> str | None:
    value = str(value or "").strip().lower()
    if value in {"bullish", "long"}:
        return "bullish"
    if value in {"bearish", "short"}:
        return "bearish"
    return None


def _unknown_coverage(reason: str) -> dict:
    return {"start": None, "end": None, "resolution": "1m",
            "status": "UNKNOWN", "missing_minutes": [],
            "boundary_minutes": [], "seconds": None, "observed_bars": 0,
            "full_bars": 0, "reason": reason}


def analyse(mission: dict, plan: dict, candles: list, after_minutes: int) -> dict:
    geo = (plan or {}).get("geometry") or {}
    direction = _direction(geo.get("direction"))
    bullish = direction == "bullish" if direction is not None else None
    entry_plan = _num(geo.get("entry_price"))
    stop_px = _num(geo.get("stop_price"))
    target_px = _num(geo.get("target_price"))
    stop_pts = _num(geo.get("stop_points"))
    target_pts = _num(geo.get("target_points"))
    fill = _num(mission.get("fill_price"))
    exit_px = _num(mission.get("exit_price"))
    qty = _num(mission.get("filled_quantity")) or _num(plan.get("quantity"))
    t = _times(mission)

    entry_ref = fill if fill is not None else entry_plan
    out = {"mission_id": mission.get("mission_id"), "direction": direction,
           "side": plan.get("side"), "quantity": qty,
           "planned_entry": entry_plan, "fill_price": fill,
           "stop_price": stop_px, "target_price": target_px,
           "stop_points": stop_pts, "target_points": target_pts,
           "exit_price": exit_px, "exit_type": mission.get("exit_type"),
           "state": mission.get("state"), "times": t, "entry_ref": entry_ref}

    if fill is not None and entry_plan is not None and bullish is not None:
        out["entry_slippage_points"] = round(
            (fill - entry_plan) if bullish else (entry_plan - fill), 2)

    if t["entry"] is not None and t["exit"] is not None:
        in_coverage, in_overlap, in_full = interval_coverage(
            candles, t["entry"], t["exit"])
    else:
        in_coverage, in_overlap, in_full = _unknown_coverage(
            "missing entry or exit timestamp"), [], []

    out["path"] = (excursions(in_full, entry=entry_ref, bullish=bullish)
                   if entry_ref is not None and bullish is not None and in_full
                   else None)

    tip = CONT.canonical_key(candles[-1]) if candles else None
    out["coverage"] = {"store_last_bar": tip,
                       "store_ends_before_exit": bool(
                           tip is not None and t["exit"] is not None
                           and tip < t["exit"]),
                       "seconds_in_trade": (
                           (t["exit"] - t["entry"]).total_seconds()
                           if t["entry"] and t["exit"] else None),
                       "in_trade": in_coverage}
    out["coverage_status"] = in_coverage["status"]

    target_level = target_px if bullish is not None else None
    stop_level = stop_px if bullish is not None else None
    out["target_touched_in_trade"] = touch_evidence(
        in_coverage, in_overlap, in_full, target_level,
        above=bool(bullish) if bullish is not None else True)
    out["stop_touched_in_trade"] = touch_evidence(
        in_coverage, in_overlap, in_full, stop_level,
        above=not bool(bullish) if bullish is not None else True)

    # HOW CLOSE IT CAME. Points still needed at the best moment, and that as a
    # fraction of the distance the trade had to cover.
    mfe = (out["path"] or {}).get("mfe_points")
    actual_target_pts = None
    if fill is not None and target_px is not None and bullish is not None:
        candidate = (target_px - fill) if bullish else (fill - target_px)
        if candidate > 0:
            actual_target_pts = candidate
            out["target_points_actual_fill_relative"] = round(candidate, 2)
    if mfe is not None and actual_target_pts:
        out["points_short_of_target"] = round(actual_target_pts - mfe, 2)
        out["fraction_of_target_reached"] = round(mfe / actual_target_pts, 3)
    planned_mfe = None
    if out["path"] and entry_plan is not None and bullish is not None:
        planned_mfe = ((out["path"]["mfe_price"] - entry_plan)
                       if bullish else (entry_plan - out["path"]["mfe_price"]))
        out["mfe_points_planned_entry_relative"] = round(planned_mfe, 2)
    if planned_mfe is not None and target_pts and target_pts > 0:
        out["planned_points_short_of_target"] = round(target_pts - planned_mfe, 2)
        out["planned_fraction_of_target_reached"] = round(planned_mfe / target_pts, 3)
    actual_stop_pts = None
    if fill is not None and stop_px is not None and bullish is not None:
        candidate = (fill - stop_px) if bullish else (stop_px - fill)
        if candidate > 0:
            actual_stop_pts = candidate
    if mfe is not None and actual_stop_pts:
        out["mfe_in_R"] = round(mfe / actual_stop_pts, 2)
    mae = (out["path"] or {}).get("mae_points")
    if mae is not None and actual_stop_pts:
        out["mae_in_R"] = round(mae / actual_stop_pts, 2)

    # AFTER THE EXIT. Early vs wrong.
    if t["exit"] is not None:
        after_coverage, after_overlap, after_full = interval_coverage(
            candles, t["exit"],
            t["exit"] + timedelta(minutes=after_minutes))
        out["after_coverage"] = after_coverage
        out["after"] = (excursions(after_full, entry=entry_ref, bullish=bullish)
                         if entry_ref is not None and bullish is not None
                         and after_full else None)
        out["after_minutes"] = after_minutes
        out["target_reached_after_exit"] = touch_evidence(
            after_coverage, after_overlap, after_full, target_level,
            above=bool(bullish) if bullish is not None else True)
    if exit_px is not None and entry_ref is not None and bullish is not None:
        moved = (exit_px - entry_ref) if bullish else (entry_ref - exit_px)
        out["realised_points"] = round(moved, 2)
        if qty:
            out["realised_gross_usd"] = round(moved * POINT_VALUE * qty, 2)
    else:
        out["realised_points"] = None
        out["realised_status"] = "UNKNOWN: missing direction, fill, or exit price"
    return out


def render(a: dict) -> None:
    direction = (a.get("direction") or "UNKNOWN").upper()
    print(f"\n=== {a['mission_id']}  {direction} "
          f"{a['side'] or ''} x{a['quantity'] or '?'}  [{a['state']}] ===")
    print("  THE PLAN (authored before the order was sent)")
    print(f"    entry planned : {a['planned_entry']}")
    print(f"    stop          : {a['stop_price']}   ({a['stop_points']} pts)")
    print(f"    target        : {a['target_price']}   ({a['target_points']} pts)")
    if (a.get("stop_points") and a.get("target_points")
            and a["direction"] is not None):
        print(f"    reward:risk   : "
              f"{round(a['target_points'] / a['stop_points'], 2)} : 1")
    print("  WHAT HAPPENED")
    print(f"    filled at     : {a['fill_price']}"
          + (f"   (slippage {a['entry_slippage_points']:+} pts)"
             if a.get("entry_slippage_points") is not None else ""))
    print(f"    exited at     : {a['exit_price']}   ({a['exit_type'] or '?'})")
    if a.get("realised_points") is not None:
        print(f"    realised      : {a['realised_points']:+} pts"
              + (f"   ${a['realised_gross_usd']:+,.2f} gross"
                 if a.get("realised_gross_usd") is not None else ""))
    t = a["times"]
    print(f"    entry time    : {t['entry']}  [{t['entry_source']}]")
    print(f"    exit time     : {t['exit']}  [{t['exit_source']}]")

    cov = a.get("coverage") or {}
    path = a.get("path")
    in_cov = cov.get("in_trade") or {}
    if not path:
        secs = cov.get("seconds_in_trade")
        if a.get("direction") is None:
            why = "direction is missing/invalid, so direction-dependent path math is UNKNOWN"
        elif in_cov.get("status") != "COMPLETE":
            why = in_cov.get("reason") or "the interval is not fully evidenced"
        else:
            why = (f"the trade lived {secs:.0f}s -- shorter than one bar, so no 1m "
                   f"candle falls inside it" if secs is not None and secs < 60
                   else "no fully contained candles in the window")
        print(f"  PRICE PATH      : UNAVAILABLE ({why})")
        print("                    This is a limit of the 1m record, NOT a "
              "statement that price was flat.")
    else:
        print(f"  THE PRICE PATH WHILE THE TRADE WAS OPEN ({path['bars']} min)")
        print(f"    best it got   : {path['mfe_points']:g} pts in favour "
              f"(px {path['mfe_price']} at {path['mfe_at']})"
              + (f"   = {a['mfe_in_R']}R" if a.get("mfe_in_R") is not None else ""))
        print(f"    worst it got  : {path['mae_points']:g} pts against "
              f"(px {path['mae_price']} at {path['mae_at']})"
              + (f"   = {a['mae_in_R']}R" if a.get("mae_in_R") is not None else ""))
        if a.get("points_short_of_target") is not None:
            print(f"    target reach  : "
              f"{a['fraction_of_target_reached'] * 100:.1f}% of the way "
              f"({a['points_short_of_target']} pts short at best; actual-fill-relative)")

    def _touch(v):
        if isinstance(v, dict):
            status = v.get("status", "UNKNOWN")
            return f"{status} (at {v['at']})" if v.get("at") else \
                f"{status} ({v.get('reason') or 'reason unavailable'})"
        return "UNKNOWN" if v is None else ("YES" if v else "NO")

    print(f"    in-trade coverage: {in_cov.get('status', 'UNKNOWN')} "
          f"({in_cov.get('reason') or 'reason unavailable'})")
    print(f"    touched target: {_touch(a.get('target_touched_in_trade'))}")
    print(f"    touched stop  : {_touch(a.get('stop_touched_in_trade'))}")
    if cov.get("store_ends_before_exit"):
        print(f"    ! the journal's last bar is {cov['store_last_bar']}, "
              f"BEFORE this trade exited. The final minutes -- including "
              f"whatever price the exit filled at -- are not in the record.")

    after = a.get("after")
    if after:
        print(f"  AFTER THE EXIT ({a['after_minutes']} min) -- early vs wrong")
        print(f"    best it would : {after['mfe_points']:g} pts in favour "
              f"(px {after['mfe_price']} at {after['mfe_at']})")
        print(f"    worst it would: {after['mae_points']:g} pts against")
    elif a.get("after_coverage"):
        print(f"  AFTER THE EXIT ({a.get('after_minutes')} min) -- "
              f"UNAVAILABLE ({a['after_coverage'].get('status', 'UNKNOWN')}: "
              f"{a['after_coverage'].get('reason') or 'reason unavailable'})")
    if a.get("after_coverage"):
        print(f"    target reached later: "
              f"{_touch(a.get('target_reached_after_exit'))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--store-dir", default=STORE_DIR)
    ap.add_argument("--candles-dir", default=CANDLES)
    ap.add_argument("--after-minutes", type=int, default=120)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    missions = load_missions(args.store_dir, args.session)
    if not missions:
        print(f"no missions for {args.session} under {args.store_dir}")
        return 2
    plans = load_geometry(args.store_dir, args.session)

    results = []
    for m in missions:
        candles = load_candles(args.candles_dir, m.get("contract_id") or "")
        plan = plans.get(m.get("mission_id")) or {}
        if not plan:
            print(f"  ! {m.get('mission_id')}: no geometry in the flight "
                  f"recorder; the plan cannot be reconstructed")
        results.append(analyse(m, plan, candles, args.after_minutes))

    print(f"TRADE POST-MORTEM -- {args.session}")
    print("READ-ONLY. Measurements only; no verdict is drawn here.")
    if args.json:
        print(json.dumps(results, default=str, indent=2))
        return 0
    for a in results:
        render(a)

    pts = [a["realised_points"] for a in results
           if a.get("realised_points") is not None]
    if pts:
        print(f"\n  SESSION: {len(pts)} trade(s), "
              f"{sum(pts):+.2f} points net of direction "
              f"(gross of fees and commissions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

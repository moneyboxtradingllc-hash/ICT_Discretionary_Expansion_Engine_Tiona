"""
ADAPT-LOOP-3B — Brain Thesis Quality grading (replay side, 2026-07-10).

A correct trading thesis is NOT a correct closing-price prediction. This module
grades every healthy-LLM directional Brain call on what an ICT thesis actually
claims:

  THESIS RESOLUTION — did price REACH the called liquidity draw before the
  thesis invalidation reference was violated? (fulfilled / invalidated /
  expired, with bar counts; protected-swing violations tracked)

  TRADE PATH — for scans with a derivable stop (invalidation_level, else the
  opposing protected swing level): 1R/2R/3R-before-stop, stop-first, MFE/MAE,
  bars to 1R / to stop, realized R under live management (SimBroker BE@1R,
  TP@2R), opportunity R (MFE).

  CONTEXT — each row joined with the stored live snapshot: qualification tier,
  trigger status, Market Commander environment, volatility state, session,
  sovereignty. Rows persist to brain_thesis_rows.jsonl so ANY decomposition is
  computable later; aggregates + report cards are derived views.

SEPARATE LEDGERS doctrine: this writes brain_thesis_quality.json and NEVER
touches brain_accuracy.json (direction ledger), execution_quality.json, or
adaptive_effect_metrics.json (intervention ledger). No blended score exists.

DESCRIPTIVE ONLY. Coverage is explicit: every metric reports its own n; a scan
without a parseable draw or stop contributes only the metrics it supports.

CLI:
  python -m replay_validation.brain_thesis_quality --dates 20260708 20260709
  python -m replay_validation.brain_thesis_quality --card direction=bearish family=liquidity_sweep_reversal
"""
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from replay_validation.candle_archive import load_session, list_archived
from replay_validation.recorded_brain import load_brain_records, _parse_ts
from replay_validation.sim_broker import simulate_trade

_ET = ZoneInfo("America/New_York")
THESIS_HORIZON_BARS = 60
_NON_FAMILIES = {"", "none", "unknown", "confirmation_required", "n/a", "null"}
_ROWS_FILE = "brain_thesis_rows.jsonl"
_TABLE_FILE = "brain_thesis_quality.json"


# ── field extraction ───────────────────────────────────────────────────────────

def parse_draw_price(active_draw) -> "float | None":
    """'sell_side@699.6' / prose with a price → float; honest-none → None."""
    m = re.search(r"(\d{3,5}(?:\.\d+)?)", str(active_draw or ""))
    try:
        return float(m.group(1)) if m else None
    except (TypeError, ValueError):
        return None


def _swing_level(v) -> "float | None":
    if isinstance(v, dict):
        v = v.get("level")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def derive_stop(direction: str, invalidation_level, protected_high,
                protected_low) -> "tuple[float | None, str | None]":
    """(stop, source). invalidation_level first, else the OPPOSING protected
    swing (a bearish thesis dies above the protected high, bullish below the
    protected low)."""
    try:
        if invalidation_level is not None:
            return float(invalidation_level), "invalidation_level"
    except (TypeError, ValueError):
        pass
    opp = protected_high if str(direction).lower() == "bearish" else protected_low
    lvl = _swing_level(opp)
    return (lvl, "protected_swing") if lvl is not None else (None, None)


def session_label(ts) -> str:
    t = _parse_ts(ts)
    if t is None:
        return "unknown"
    et = t.astimezone(_ET)
    hm = et.hour * 60 + et.minute
    if hm < 9 * 60 + 30:
        return "premarket"
    if hm < 10 * 60 + 30:
        return "ny_open"
    if hm < 12 * 60:
        return "ny_am"
    if hm < 13 * 60 + 30:
        return "lunch"
    if hm < 16 * 60:
        return "ny_pm"
    return "after_hours"


def _conf_bucket(c) -> str:
    try:
        c = int(c)
    except (TypeError, ValueError):
        return "unknown"
    if c >= 90:
        return "90+"
    if c >= 80:
        return "80-89"
    if c >= 70:
        return "70-79"
    if c >= 50:
        return "50-69"
    return "<50"


def _family_present(v) -> bool:
    items = v if isinstance(v, list) else [v]
    return any(str(i).lower().strip() not in _NON_FAMILIES
               for i in items if i is not None)


# ── grading walks ──────────────────────────────────────────────────────────────

def grade_thesis_resolution(fwd: list, direction: str, draw_price,
                            stop, protected_high, protected_low) -> dict:
    """Walk THESIS_HORIZON bars: liquidity touch vs invalidation cross."""
    is_long = str(direction).lower() == "bullish"
    ph, pl = _swing_level(protected_high), _swing_level(protected_low)
    out = {"liquidity_reached": None if draw_price is None else False,
           "thesis_invalidated": None if stop is None else False,
           "protected_high_violated": None if ph is None else False,
           "protected_low_violated": None if pl is None else False,
           "bars_to_fulfillment": None, "bars_to_invalidation": None,
           "resolution": "ungradeable" if draw_price is None else "expired"}
    for i, c in enumerate(fwd, 1):
        hi, lo = float(c["high"]), float(c["low"])
        if ph is not None and hi > ph and not out["protected_high_violated"]:
            out["protected_high_violated"] = True
        if pl is not None and lo < pl and not out["protected_low_violated"]:
            out["protected_low_violated"] = True
        if (stop is not None and not out["thesis_invalidated"]
                and ((lo <= stop) if is_long else (hi >= stop))):
            out["thesis_invalidated"] = True
            out["bars_to_invalidation"] = i
            if out["resolution"] == "expired":
                out["resolution"] = "invalidated"
                break   # thesis dead before the draw — fulfilled cannot follow
        if (draw_price is not None and not out["liquidity_reached"]
                and lo <= draw_price <= hi):
            out["liquidity_reached"] = True
            out["bars_to_fulfillment"] = i
            out["resolution"] = "fulfilled"
            break
    return out


def grade_trade_path(fwd: list, direction: str, stop) -> "dict | None":
    """Raw path from next-bar-open entry: R milestones with stop-first
    pessimism inside each bar; no management (that's realized_r's job)."""
    if stop is None or not fwd:
        return None
    is_long = str(direction).lower() == "bullish"
    entry = float(fwd[0]["open"])
    risk = (entry - float(stop)) if is_long else (float(stop) - entry)
    if risk <= 0:
        return None
    out = {"r1_before_stop": False, "r2_before_stop": False,
           "r3_before_stop": False, "stop_first": False,
           "mfe_r": 0.0, "mae_r": 0.0,
           "bars_to_1r": None, "bars_to_stop": None}
    stopped = False
    for i, c in enumerate(fwd, 1):
        hi, lo = float(c["high"]), float(c["low"])
        fav = ((hi - entry) if is_long else (entry - lo)) / risk
        adv = ((entry - lo) if is_long else (hi - entry)) / risk
        out["mfe_r"] = round(max(out["mfe_r"], fav), 3)
        out["mae_r"] = round(max(out["mae_r"], adv), 3)
        hit_stop = (lo <= float(stop)) if is_long else (hi >= float(stop))
        if hit_stop and not stopped:            # pessimism: stop first in-bar
            stopped = True
            out["bars_to_stop"] = i
            if not out["r1_before_stop"]:
                out["stop_first"] = True
        if not stopped:
            if fav >= 1 and not out["r1_before_stop"]:
                out["r1_before_stop"], out["bars_to_1r"] = True, i
            if fav >= 2:
                out["r2_before_stop"] = True
            if fav >= 3:
                out["r3_before_stop"] = True
        if stopped:
            break
    return out


# ── row builder ────────────────────────────────────────────────────────────────

def _stored_context(date: str, symbol: str) -> dict:
    """timestamp -> compact context from the stored live snapshots."""
    import glob
    out = {}
    for f in sorted(glob.glob(os.path.join(
            os.getenv("LIVE_SNAPSHOTS_DIR") or os.path.join("data", "live_snapshots"),
            f"{date}_*_{symbol}.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ts = _parse_ts(d.get("timestamp"))
        if ts is None:
            continue
        mc = ((d.get("market_commander") or {}).get("environment") or {})
        vols = d.get("volatility_states") or {}
        bs = d.get("brain_sovereignty") or {}
        out[ts] = {
            "qual_status": (d.get("qualification") or {}).get("status"),
            "trigger_status": (d.get("trade_intent") or {}).get("trigger_status"),
            "mc_environment": (f"{mc.get('family')}/{mc.get('type')}"
                               if mc.get("family") else None),
            "volatility_5m": (vols.get("5m") if isinstance(vols.get("5m"), str)
                              else (vols.get("5m") or {}).get("state")
                              if isinstance(vols.get("5m"), dict) else None),
            "sovereign_persisted": bs.get("sovereign") if bs else None,
        }
    return out


def build_rows(dates: list = None, symbol: str = "QQQ",
               horizon: int = THESIS_HORIZON_BARS) -> list:
    dates = dates or [r["date"] for r in list_archived(symbol)]
    rows = []
    for date in sorted(set(dates)):
        try:
            tape = load_session(date, symbol)
        except FileNotFoundError:
            continue
        ctx_by_ts = _stored_context(date, symbol)
        for ts, rec in load_brain_records(date, symbol):
            o = rec.get("parsed_output") or {}
            d = (o.get("narrative_direction") or "").lower()
            if rec.get("source") != "llm" or d not in ("bullish", "bearish"):
                continue
            fwd = [c for c in tape
                   if (_parse_ts(c.get("timestamp")) or ts) > ts][:horizon]
            if len(fwd) < 3:
                continue
            payload = rec.get("input_payload") or {}
            swings = payload.get("protected_swings") or {}
            draw = parse_draw_price(o.get("active_draw"))
            stop, stop_source = derive_stop(
                d, o.get("invalidation_level"),
                swings.get("protected_high"), swings.get("protected_low"))

            resolution = grade_thesis_resolution(
                fwd, d, draw, stop,
                swings.get("protected_high"), swings.get("protected_low"))
            path = grade_trade_path(fwd, d, stop)
            realized = None
            if stop is not None:
                sim = simulate_trade(tape, ts.isoformat(), d, stop=stop,
                                     target_r=2.0, breakeven_r=1.0,
                                     max_bars=horizon)
                realized = sim["r"] if sim else None

            ctx = {}
            if ctx_by_ts:
                best = min(ctx_by_ts, key=lambda k: abs((k - ts).total_seconds()))
                if abs((best - ts).total_seconds()) <= 90:
                    ctx = ctx_by_ts[best]

            fam = o.get("recommended_playbook_family")
            fam_present = _family_present(fam)
            sovereign = ctx.get("sovereign_persisted")
            if sovereign is None:
                sovereign = fam_present   # record-level proxy (documented)

            tf = o.get("recommended_tool_family")
            tf0 = (tf[0] if isinstance(tf, list) and tf else tf)
            rows.append({
                "timestamp": ts.isoformat(), "date": date, "symbol": symbol,
                "direction": d,
                "family": (str(fam).lower().strip() if fam_present else "none"),
                "family_present": fam_present,
                "tool_family": str(tf0).lower().strip() if tf0 else "none",
                "confidence": o.get("phase_confidence"),
                "confidence_bucket": _conf_bucket(o.get("phase_confidence")),
                "sovereign": bool(sovereign),
                "session": session_label(ts),
                "qual_status": ctx.get("qual_status"),
                "trigger_status": ctx.get("trigger_status"),
                "trigger_confirmed": (ctx.get("trigger_status") == "confirmed"
                                      if ctx.get("trigger_status") else None),
                "mc_environment": ctx.get("mc_environment"),
                "volatility_5m": ctx.get("volatility_5m"),
                "draw_price": draw, "stop": stop, "stop_source": stop_source,
                **{f"res_{k}": v for k, v in resolution.items()},
                "path": path, "realized_r": realized,
            })
    return rows


# ── aggregation + report cards ────────────────────────────────────────────────

def _rate(hits, n):
    return round(hits / n, 3) if n else None


def summarize(rows: list) -> dict:
    """The card body: every metric with its OWN n (coverage explicit)."""
    n = len(rows)
    res = [r for r in rows if r.get("res_resolution") not in (None, "ungradeable")]
    liq = [r for r in rows if r.get("res_liquidity_reached") is not None]
    pathed = [r for r in rows if r.get("path")]
    realized = [r for r in rows if r.get("realized_r") is not None]
    ph = [r for r in rows if r.get("res_protected_high_violated") is not None]
    pl = [r for r in rows if r.get("res_protected_low_violated") is not None]
    fulfilled = [r for r in res if r["res_resolution"] == "fulfilled"]
    invalidated = [r for r in res if r["res_resolution"] == "invalidated"]

    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "n": n,
        "thesis": {
            "n_gradeable": len(res),
            "fulfilled_pct": _rate(len(fulfilled), len(res)),
            "invalidated_pct": _rate(len(invalidated), len(res)),
            "expired_pct": _rate(
                sum(1 for r in res if r["res_resolution"] == "expired"), len(res)),
            "liquidity_reached_pct": _rate(
                sum(1 for r in liq if r["res_liquidity_reached"]), len(liq)),
            "protected_high_violated_pct": _rate(
                sum(1 for r in ph if r["res_protected_high_violated"]), len(ph)),
            "protected_low_violated_pct": _rate(
                sum(1 for r in pl if r["res_protected_low_violated"]), len(pl)),
            "avg_bars_to_fulfillment": _avg(
                [r["res_bars_to_fulfillment"] for r in fulfilled]),
            "avg_bars_to_invalidation": _avg(
                [r["res_bars_to_invalidation"] for r in invalidated]),
        },
        "trade_path": {
            "n_with_stop": len(pathed),
            "r1_before_stop_pct": _rate(
                sum(1 for r in pathed if r["path"]["r1_before_stop"]), len(pathed)),
            "r2_before_stop_pct": _rate(
                sum(1 for r in pathed if r["path"]["r2_before_stop"]), len(pathed)),
            "r3_before_stop_pct": _rate(
                sum(1 for r in pathed if r["path"]["r3_before_stop"]), len(pathed)),
            "stop_first_pct": _rate(
                sum(1 for r in pathed if r["path"]["stop_first"]), len(pathed)),
            "avg_mfe_r": _avg([r["path"]["mfe_r"] for r in pathed]),
            "avg_mae_r": _avg([r["path"]["mae_r"] for r in pathed]),
            "avg_bars_to_1r": _avg([r["path"]["bars_to_1r"] for r in pathed]),
            "avg_realized_r": _avg([r["realized_r"] for r in realized]),
            "n_realized": len(realized),
            "avg_opportunity_r": _avg([r["path"]["mfe_r"] for r in pathed]),
        },
    }


def report_card(rows: list, min_n: int = 10, **filters) -> dict:
    """The mission's example card: filter rows by any dimension, summarize.
    Refuses conclusions under min_n (returns the n and a note)."""
    sel = [r for r in rows
           if all(str(r.get(k)) == str(v) for k, v in filters.items())]
    card = {"filters": filters, "n": len(sel)}
    if len(sel) < min_n:
        card["note"] = f"n={len(sel)} < {min_n}: descriptive only, no conclusions"
    if sel:
        card.update(summarize(sel))
    return card


_DIMENSIONS = ("direction", "family", "tool_family", "confidence_bucket",
               "sovereign", "session", "qual_status", "trigger_confirmed",
               "mc_environment", "volatility_5m")


def build_table(dates: list = None, symbol: str = "QQQ",
                base_dir: str = None) -> dict:
    """Build rows, persist them, and write the per-dimension aggregate table."""
    from adaptive_learning.brain_accuracy import accuracy_path
    rows = build_rows(dates, symbol)
    root = os.path.dirname(accuracy_path(symbol, base_dir))
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, _ROWS_FILE), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    table = {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_bars": THESIS_HORIZON_BARS,
        "ledger": "brain_thesis_quality",
        "authority": "descriptive_only",
        "rows": len(rows),
        "overall": summarize(rows),
        "by_dimension": {
            dim: {str(val): summarize([r for r in rows if r.get(dim) == val])
                  for val in sorted({r.get(dim) for r in rows},
                                    key=lambda x: str(x))}
            for dim in _DIMENSIONS
        },
    }
    tmp = os.path.join(root, _TABLE_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, default=str)
    os.replace(tmp, os.path.join(root, _TABLE_FILE))
    return table


def load_rows(symbol: str = "QQQ", base_dir: str = None) -> list:
    from adaptive_learning.brain_accuracy import accuracy_path
    path = os.path.join(os.path.dirname(accuracy_path(symbol, base_dir)),
                        _ROWS_FILE)
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ADAPT-LOOP-3B thesis quality")
    p.add_argument("--dates", nargs="*")
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--card", nargs="*", help="K=V filters for a report card")
    a = p.parse_args()
    if a.card is not None:
        rows = load_rows(a.symbol)
        filters = dict(kv.split("=", 1) for kv in (a.card or []))
        print(json.dumps(report_card(rows, **filters), indent=1, default=str))
    else:
        t = build_table(a.dates, a.symbol)
        print(json.dumps({"rows": t["rows"], "overall": t["overall"]},
                         indent=1, default=str))

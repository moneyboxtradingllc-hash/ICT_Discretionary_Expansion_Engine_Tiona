"""
VOLUME-WITNESS — descriptive replay report (replay side, evidence only).

Joins the participation witness (recomputed at each historical scan from the
1m candle archive) against the ADAPT-LOOP-3B thesis-quality rows, and reports
outcome relationships by volume bucket with minimum-N refusal.

DESCRIPTIVE ONLY. This report grades the witness as evidence — it creates no
doctrine, no gate, no score. The allowed verdicts are: VALIDATED AS USEFUL
DESCRIPTIVE WITNESS / NO CHANGE (no measurable relationship yet) /
INSUFFICIENT DATA / REJECTED DUE TO DATA QUALITY.

Caveats baked in: the same-minute baseline table includes the graded sessions
(in-sample, no train/test split) and volume is IEX venue-limited — both are
stated in the report header, never hidden.

CLI: python -m replay_validation.volume_witness_report [--symbol QQQ]
"""
import json
import os
from datetime import datetime, timezone

from replay_validation.candle_archive import load_session
from market_data.volume_witness import (
    _tf_witness, same_minute_percentile, load_minute_baseline,
    CALCULATION_VERSION,
)

MIN_N = 30
_ROWS = os.path.join("data", "performance", "QQQ", "brain_thesis_rows.jsonl")

REL_BUCKETS = (("dead_quiet(<0.8)", 0.0, 0.8), ("normal(0.8-1.5)", 0.8, 1.5),
               ("elevated(1.5-2.5)", 1.5, 2.5), ("climactic(>=2.5)", 2.5, 1e9))
PCT_BUCKETS = (("p0-25", 0, 25), ("p25-50", 25, 50),
               ("p50-75", 50, 75), ("p75-100", 75, 101))


def _witness_at(candles: list, ts: str, baseline) -> "dict | None":
    """1m witness computed from bars up to (and including) the scan bar."""
    cutoff = str(ts)
    prefix = [c for c in candles if str(c.get("timestamp")) <= cutoff]
    core = _tf_witness(prefix)
    if core.get("state") == "insufficient_data":
        return None
    pct = same_minute_percentile(core["last_volume"],
                                 prefix[-1].get("timestamp"), baseline)
    return {**core, **pct}


def _grade(rows: list) -> dict:
    graded = [r for r in rows if r.get("res_resolution")
              not in (None, "ungradeable")]
    n = len(graded)
    if n < MIN_N:
        return {"n": n, "verdict": "INSUFFICIENT DATA"}
    fulfilled = sum(1 for r in graded if r["res_resolution"] == "fulfilled")
    invalidated = sum(1 for r in graded if r["res_resolution"] == "invalidated")
    r1 = [bool((r.get("path") or {}).get("r1_before_stop"))
          for r in graded if isinstance(r.get("path"), dict)]
    realized = [r["realized_r"] for r in graded
                if isinstance(r.get("realized_r"), (int, float))]
    return {
        "n": n,
        "fulfilled_pct": round(100 * fulfilled / n),
        "invalidated_pct": round(100 * invalidated / n),
        "r1_before_stop_pct": (round(100 * sum(r1) / len(r1))
                               if len(r1) >= MIN_N else None),
        "r1_n": len(r1),
        "avg_realized_r": (round(sum(realized) / len(realized), 3)
                           if len(realized) >= MIN_N else None),
        "realized_n": len(realized),
    }


def build_report(symbol: str = "QQQ") -> dict:
    baseline = load_minute_baseline(symbol)
    rows = [json.loads(l) for l in open(_ROWS, encoding="utf-8")]

    candle_cache: dict = {}
    joined = skipped = 0
    for r in rows:
        date = str(r.get("date") or "").replace("-", "")
        try:
            if date not in candle_cache:
                candle_cache[date] = load_session(date, symbol)
            w = _witness_at(candle_cache[date], r["timestamp"], baseline)
        except Exception:  # noqa: BLE001
            w = None
        if w is None:
            skipped += 1
            r["_w"] = None
            continue
        joined += 1
        r["_w"] = w

    have = [r for r in rows if r.get("_w")]

    by_rel = {}
    for label, lo, hi in REL_BUCKETS:
        by_rel[label] = _grade([r for r in have
                                if lo <= r["_w"]["relative"] < hi])
    by_pct = {}
    for label, lo, hi in PCT_BUCKETS:
        by_pct[label] = _grade([
            r for r in have
            if r["_w"].get("same_minute_percentile") is not None
            and lo <= r["_w"]["same_minute_percentile"] < hi])
    by_trend = {t: _grade([r for r in have if r["_w"]["trend"] == t])
                for t in ("rising", "flat", "falling")}
    confirmed = _grade([r for r in have if r.get("trigger_confirmed")])
    confirmed_elevated = _grade([r for r in have if r.get("trigger_confirmed")
                                 and r["_w"]["relative"] >= 1.5])
    confirmed_quiet = _grade([r for r in have if r.get("trigger_confirmed")
                              and r["_w"]["relative"] < 0.8])

    return {
        "mission": "VOLUME-WITNESS descriptive report",
        "calculation_version": CALCULATION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "caveats": [
            "IEX venue-limited volume (not consolidated tape); relative "
            "metrics are IEX-vs-IEX self-consistent",
            "same-minute baseline includes the graded sessions (in-sample, "
            "descriptive only — no predictive claim)",
            f"minimum-N refusal at {MIN_N}: buckets below report "
            "INSUFFICIENT DATA rather than a number",
        ],
        "rows_total": len(rows), "rows_joined": joined,
        "rows_skipped_insufficient_history": skipped,
        "by_relative_volume": by_rel,
        "by_same_minute_percentile": by_pct,
        "by_volume_trend": by_trend,
        "trigger_confirmed_all": confirmed,
        "trigger_confirmed_elevated_volume": confirmed_elevated,
        "trigger_confirmed_quiet_volume": confirmed_quiet,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VOLUME-WITNESS descriptive report")
    p.add_argument("--symbol", default="QQQ")
    args = p.parse_args()
    rep = build_report(args.symbol)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = os.path.join("data", "replay", "reports",
                       f"volume_witness_report_{stamp}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps(rep, indent=1))
    print("wrote", out)

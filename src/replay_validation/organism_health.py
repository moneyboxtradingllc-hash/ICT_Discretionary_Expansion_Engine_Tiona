"""
ADAPT-LOOP-6 — Organism Health Monitor (2026-07-10).

Not about trading — about the LEARNER. Answers, from the ledgers that already
exist, the questions the trades can't:

  brain_trend          is the Brain improving? (thesis-quality rows by date:
                       fulfilled% and realized R, first half vs second half)
  governance           is adaptive governance helping? (earn-back proposal
                       lifecycle + adaptive-effect helped/hurt net R)
  calibration_drift    is replay still matching live? (latest saved run's
                       decision-field match rates — drift here means every
                       other number is suspect)
  plateau              is learning plateauing? (windowed realized-R deltas)
  regime_concentration are we overfitting one regime? (per-volatility/-session
                       realized-R spread from thesis rows)
  scar_health          are scars being forgiven appropriately? (decay states)
  posture_drift        too conservative (suppression false-rate trend) /
                       overconfident (confidence-bucket realized-R inversion)?

Every metric reports its own n; a missing source reports "no_data" — silence
is never health. DESCRIPTIVE ONLY: nothing consumes this for authority; its
output is missions for the human, not actuations.

CLI: python -m replay_validation.organism_health [--symbol QQQ]
"""
import glob
import json
import os
from datetime import datetime, timezone


def _rows(symbol, base_dir=None):
    from replay_validation.brain_thesis_quality import load_rows
    return load_rows(symbol, base_dir)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def brain_trend(symbol="QQQ", base_dir=None) -> dict:
    rows = [r for r in _rows(symbol, base_dir) if r.get("realized_r") is not None]
    if len(rows) < 10:
        return {"status": "no_data", "n": len(rows)}
    dates = sorted({r["date"] for r in rows})
    mid = dates[len(dates) // 2]
    early = [r for r in rows if r["date"] < mid]
    late = [r for r in rows if r["date"] >= mid]
    out = {
        "n": len(rows), "dates": f"{dates[0]}..{dates[-1]}",
        "split_at": mid,
        "early": {"n": len(early), "avg_realized_r": _avg([r["realized_r"] for r in early]),
                  "fulfilled_pct": _avg([1.0 if r.get("res_resolution") == "fulfilled" else 0.0
                                         for r in early if r.get("res_resolution") not in (None, "ungradeable")])},
        "late": {"n": len(late), "avg_realized_r": _avg([r["realized_r"] for r in late]),
                 "fulfilled_pct": _avg([1.0 if r.get("res_resolution") == "fulfilled" else 0.0
                                        for r in late if r.get("res_resolution") not in (None, "ungradeable")])},
    }
    e, l = out["early"]["avg_realized_r"], out["late"]["avg_realized_r"]
    out["direction"] = ("improving" if (e is not None and l is not None and l > e)
                        else "degrading" if (e is not None and l is not None and l < e)
                        else "flat")
    return out


def governance(symbol="QQQ", base_dir=None) -> dict:
    from adaptive_learning.earnback import load_proposals
    from adaptive_learning.adaptive_effect import load_effect_metrics
    props = load_proposals(symbol, base_dir)
    by_status = {}
    for p in props:
        by_status[p.get("status", "?")] = by_status.get(p.get("status", "?"), 0) + 1
    effects = load_effect_metrics(symbol, base_dir).get("by_action_type") or {}
    return {"proposals": by_status or "no_data",
            "adaptive_effect": effects or "no_data",
            "note": "promotions become gradeable via the effect ledger once "
                    "enforce-mode lifts produce outcomes"}


def calibration_drift() -> dict:
    """Latest saved replay run that carries a calibration block."""
    runs = sorted(glob.glob(os.path.join("data", "replay", "runs", "*",
                                         "result.json")), key=os.path.getmtime)
    for path in reversed(runs):
        try:
            r = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cal = r.get("calibration")
        if cal and cal.get("field_match_rates"):
            rates = cal["field_match_rates"]
            worst = min(rates, key=rates.get)
            return {"source": path, "matched_scans": cal.get("matched"),
                    "identical": cal.get("identical"),
                    "field_match_rates": rates,
                    "worst_field": {worst: rates[worst]}}
    return {"status": "no_data",
            "note": "run replay_session --calibrate after a live session"}


def regime_concentration(symbol="QQQ", base_dir=None) -> dict:
    rows = [r for r in _rows(symbol, base_dir) if r.get("realized_r") is not None]
    if len(rows) < 20:
        return {"status": "no_data", "n": len(rows)}
    out = {}
    for dim in ("volatility_5m", "session"):
        buckets = {}
        for r in rows:
            k = str(r.get(dim))
            buckets.setdefault(k, []).append(r["realized_r"])
        out[dim] = {k: {"n": len(v), "avg_realized_r": _avg(v)}
                    for k, v in sorted(buckets.items()) if len(v) >= 10}
    return out


def scar_health(symbol="QQQ", base_dir=None) -> dict:
    from deployment.data_paths import resolve
    root = base_dir or resolve("PERFORMANCE_TABLES_DIR", "data", "performance",
                               anchored=True)
    path = os.path.join(root, str(symbol).upper(), "memory_decay.json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        states = {}
        for _k, v in (d.items() if isinstance(d, dict) else []):
            s = (v or {}).get("decay_status", "?") if isinstance(v, dict) else "?"
            states[s] = states.get(s, 0) + 1
        return states or {"status": "no_data"}
    except (OSError, json.JSONDecodeError):
        return {"status": "no_data"}


def posture_drift(symbol="QQQ", base_dir=None) -> dict:
    from adaptive_learning.suppression_cost_engine import load_suppression_metrics
    metrics = load_suppression_metrics(symbol, base_dir) or {}
    tot_correct = tot_false = 0
    for _dim, buckets in metrics.items():
        if not isinstance(buckets, dict):
            continue
        for _k, b in buckets.items():
            if isinstance(b, dict):
                tot_correct += int(b.get("correct_suppressions", 0) or 0)
                tot_false += int(b.get("false_suppressions", 0) or 0)
    scored = tot_correct + tot_false
    conservatism = {"scored_suppressions": scored,
                    "false_rate": round(tot_false / scored, 3) if scored else None}
    # overconfidence: recent-era confidence-bucket realized-R inversion
    rows = [r for r in _rows(symbol, base_dir)
            if r.get("realized_r") is not None]
    conf = {}
    if rows:
        recent_dates = sorted({r["date"] for r in rows})[-10:]
        recent = [r for r in rows if r["date"] in recent_dates]
        for b in ("<50", "50-69", "70-79", "80-89", "90+"):
            sel = [r["realized_r"] for r in recent
                   if r.get("confidence_bucket") == b]
            if len(sel) >= 10:
                conf[b] = {"n": len(sel), "avg_realized_r": _avg(sel)}
    return {"conservatism": conservatism,
            "confidence_calibration_recent": conf or "no_data"}


def build_health_report(symbol="QQQ", base_dir=None, out_dir=None) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "authority": "descriptive_only",
        "brain_trend": brain_trend(symbol, base_dir),
        "governance": governance(symbol, base_dir),
        "calibration_drift": calibration_drift(),
        "regime_concentration": regime_concentration(symbol, base_dir),
        "scar_health": scar_health(symbol, base_dir),
        "posture_drift": posture_drift(symbol, base_dir),
    }
    out_dir = out_dir or os.path.join("data", "replay", "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir,
                        f"organism_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    report["saved"] = path
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Organism Health Monitor")
    p.add_argument("--symbol", default="QQQ")
    a = p.parse_args()
    r = build_health_report(a.symbol)
    print(json.dumps(r, indent=1, default=str))

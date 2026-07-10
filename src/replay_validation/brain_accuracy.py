"""
ADAPT-LOOP-3 — Brain Accuracy Table builder (replay side, 2026-07-10).

The Brain was fed history (friction) but never graded on its OWN theses. This
builder joins every persisted Brain call (data/ai_brain records: direction,
playbook family, confidence, source) with the archived 1m tape and grades each
healthy-LLM directional read by what price actually did next:

    entry = next 1m open after the scan; horizon = HORIZON_BARS closes later
    hit   = sign(close_H - entry) matches the called direction
    plus favorable/adverse excursion over the horizon (points)

Aggregated into data/performance/<SYM>/brain_accuracy.json by direction,
playbook family, confidence bucket, and family-present (the sovereignty
precondition) — the table adaptive_learning.brain_accuracy reads back and the
Brain payload can carry (gated) so the organism knows its own track record.

Grading is DESCRIPTIVE, not authoritative: no module may veto on it. CLI:
    python -m replay_validation.brain_accuracy --dates 20260708 20260709
"""
import json
import os
from datetime import datetime, timezone

from replay_validation.candle_archive import load_session, list_archived
from replay_validation.recorded_brain import load_brain_records, _parse_ts

HORIZON_BARS = 30
_NON_FAMILIES = {"", "none", "unknown", "confirmation_required", "n/a", "null"}


def _family_present(v) -> bool:
    items = v if isinstance(v, list) else [v]
    return any(str(i).lower().strip() not in _NON_FAMILIES
               for i in items if i is not None)


def _conf_bucket(c) -> str:
    try:
        c = int(c)
    except (TypeError, ValueError):
        return "unknown"
    if c >= 70:
        return "70+"
    if c >= 50:
        return "50-69"
    return "<50"


def grade_scan(tape: list, ts, direction: str,
               horizon: int = HORIZON_BARS) -> "dict | None":
    """Forward-grade one directional call. None when no forward tape exists."""
    t0 = _parse_ts(ts)
    if t0 is None:
        return None
    fwd = [c for c in tape if (_parse_ts(c.get("timestamp")) or t0) > t0][:horizon]
    if len(fwd) < 3:
        return None
    entry = float(fwd[0]["open"])
    close_h = float(fwd[-1]["close"])
    is_long = str(direction).lower() == "bullish"
    move = (close_h - entry) if is_long else (entry - close_h)
    fav = (max(float(c["high"]) for c in fwd) - entry) if is_long \
        else (entry - min(float(c["low"]) for c in fwd))
    adv = (entry - min(float(c["low"]) for c in fwd)) if is_long \
        else (max(float(c["high"]) for c in fwd) - entry)
    return {"hit": move > 0, "move_pts": round(move, 3),
            "fav_pts": round(fav, 3), "adv_pts": round(adv, 3)}


def _bucket():
    return {"n": 0, "hits": 0, "sum_move": 0.0}


def _add(b, g):
    b["n"] += 1
    b["hits"] += bool(g["hit"])
    b["sum_move"] = round(b["sum_move"] + g["move_pts"], 3)


def _finalize(b):
    n = b["n"]
    return {"n": n, "hits": b["hits"],
            "hit_rate": round(b["hits"] / n, 3) if n else None,
            "avg_move_pts": round(b["sum_move"] / n, 3) if n else None}


def build_brain_accuracy(dates: list = None, symbol: str = "QQQ",
                         base_dir: str = None,
                         horizon: int = HORIZON_BARS) -> dict:
    """Grade every healthy-LLM directional Brain call across the given dates
    (default: every archived session) and write the accuracy table."""
    dates = dates or [row["date"] for row in list_archived(symbol)]
    overall = _bucket()
    by_dir, by_fam, by_conf, by_fam_present = {}, {}, {}, {}
    graded = skipped = 0

    for date in dates:
        try:
            tape = load_session(date, symbol)
        except FileNotFoundError:
            continue
        for ts, rec in load_brain_records(date, symbol):
            o = rec.get("parsed_output") or {}
            d = (o.get("narrative_direction") or "").lower()
            if rec.get("source") != "llm" or d not in ("bullish", "bearish"):
                continue
            g = grade_scan(tape, ts, d, horizon)
            if g is None:
                skipped += 1
                continue
            graded += 1
            _add(overall, g)
            _add(by_dir.setdefault(d, _bucket()), g)
            fam = o.get("recommended_playbook_family")
            fam_key = str(fam).lower().strip() if _family_present(fam) else "none"
            _add(by_fam.setdefault(fam_key, _bucket()), g)
            _add(by_conf.setdefault(_conf_bucket(o.get("phase_confidence")),
                                    _bucket()), g)
            _add(by_fam_present.setdefault(
                "family_present" if _family_present(fam) else "family_none",
                _bucket()), g)

    table = {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dates": sorted(dates),
        "horizon_bars": horizon,
        "graded_scans": graded,
        "skipped_no_tape": skipped,
        "overall": _finalize(overall),
        "by_direction": {k: _finalize(v) for k, v in sorted(by_dir.items())},
        "by_family": {k: _finalize(v) for k, v in sorted(by_fam.items())},
        "by_confidence": {k: _finalize(v) for k, v in sorted(by_conf.items())},
        "by_family_present": {k: _finalize(v)
                              for k, v in sorted(by_fam_present.items())},
        "authority": "descriptive_only",
    }
    from adaptive_learning.brain_accuracy import accuracy_path
    path = accuracy_path(symbol, base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1)
    os.replace(tmp, path)
    return table


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ADAPT-LOOP-3 brain accuracy builder")
    p.add_argument("--dates", nargs="*")
    p.add_argument("--symbol", default="QQQ")
    a = p.parse_args()
    t = build_brain_accuracy(a.dates, a.symbol)
    print(json.dumps({k: t[k] for k in
                      ("graded_scans", "overall", "by_family_present",
                       "by_confidence")}, indent=1))

"""
VOLUME-WITNESS — same-minute-of-day baseline builder (replay side).

Intraday volume follows a U-shape: 09:31 is always huge, 12:30 always quiet.
A raw relative-volume number can't distinguish "elevated for lunch" from
"ordinary for the open". This builder distills the candle archive into a
per-ET-minute distribution so the live organ can report an honest
same-minute-of-day percentile with an explicit sample count.

Pattern follows brain_accuracy: replay builds the table from archived
evidence; the pipeline READS it (deterministic, local, no network). The organ
refuses to fabricate a percentile below its minimum sample — an absent or
thin table degrades honestly to unavailable.

Output: data/performance/<SYMBOL>/volume_minute_baseline.json
  {"symbol", "source": "replay_candle_archive", "feed_scope":
   "venue_limited_iex", "built_at_session": <latest date used>, "sessions": N,
   "calculation_version", "minutes": {"HH:MM": [sorted volumes...]}}

CLI: python -m replay_validation.volume_baseline [--symbol QQQ]
"""
import json
import os

from replay_validation.candle_archive import archive_dir, load_session
from market_data.volume_witness import (
    CALCULATION_VERSION, baseline_table_path, _minute_et,
)


def build_minute_baseline(symbol: str = "QQQ") -> dict:
    """One volume observation per archived session per ET minute."""
    dates = sorted(
        fn.split("_")[0] for fn in os.listdir(archive_dir())
        if fn.endswith(f"_{symbol}.json")
    )
    minutes: dict = {}
    for date in dates:
        for c in load_session(date, symbol):
            m = _minute_et(c.get("timestamp"))
            v = float(c.get("volume") or 0)
            if m and v > 0:
                minutes.setdefault(m, []).append(v)
    return {
        "symbol": symbol,
        "source": "replay_candle_archive",
        "feed_scope": "venue_limited_iex",
        "built_at_session": dates[-1] if dates else None,
        "sessions": len(dates),
        "calculation_version": CALCULATION_VERSION,
        "minutes": {m: sorted(vs) for m, vs in sorted(minutes.items())},
    }


def write_minute_baseline(symbol: str = "QQQ") -> str:
    table = build_minute_baseline(symbol)
    path = baseline_table_path(symbol)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(table, fh)
    return path


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VOLUME-WITNESS minute baseline")
    p.add_argument("--symbol", default="QQQ")
    args = p.parse_args()
    out = write_minute_baseline(args.symbol)
    with open(out, encoding="utf-8") as fh:
        t = json.load(fh)
    print(f"wrote {out}: {t['sessions']} sessions, {len(t['minutes'])} minutes")

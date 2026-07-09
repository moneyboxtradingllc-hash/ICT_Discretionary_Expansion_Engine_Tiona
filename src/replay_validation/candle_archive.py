"""
REPLAY-1 — per-session 1m candle archive (2026-07-09).

The whole mechanical organism derives from 1m candles (timeframe_builder builds
3m/5m/15m from the 1m stream), so an archived 1m tape makes every historical
session replayable through any bot revision. Live fetch_1m_candles only reaches a
rolling window — sessions age out — so this archive is the ONLY durable copy.

Archive contract:
  data/replay/candles/YYYYMMDD_SYMBOL.json  (override dir: REPLAY_CANDLES_DIR)
  {"symbol","date","source","fetched_at","bar_count","candles":[...]}
  candles = every 1m bar whose timestamp falls on the ET calendar date, sorted
  oldest-first, same dict shape the live provider emits. Sessions cross-load
  (D-1 + D) is the replay walker's job, not the archive's.

Integrity doctrine: an existing archive is never silently clobbered — re-archiving
skips unless the new fetch has MORE bars or force=True.

Read-only market data. No broker imports, no order endpoints, no trading logic.

CLI:
  python -m replay_validation.candle_archive --date 20260708 [--symbol QQQ]
  python -m replay_validation.candle_archive --backfill 30   [--symbol QQQ]
  python -m replay_validation.candle_archive --list
"""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_DEFAULT_DIR = os.path.join("data", "replay", "candles")


def archive_dir() -> str:
    return os.getenv("REPLAY_CANDLES_DIR") or _DEFAULT_DIR


def archive_path(date: str, symbol: str) -> str:
    return os.path.join(archive_dir(), f"{date}_{symbol}.json")


def _et_window_utc(date: str) -> tuple:
    """[start, end) of the ET calendar date, expressed in UTC."""
    d = datetime.strptime(date, "%Y%m%d")
    start_et = d.replace(tzinfo=_ET)
    end_et = (d + timedelta(days=1)).replace(tzinfo=_ET)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _on_et_date(ts_iso: str, date: str) -> bool:
    try:
        ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(_ET).strftime("%Y%m%d") == date
    except (ValueError, TypeError):
        return False


def archive_session(date: str, symbol: str = "QQQ", provider=None,
                    force: bool = False) -> dict:
    """Fetch the ET calendar date's 1m bars and archive them.
    Returns {"status": archived|skipped_existing|no_data, "path", "bar_count"}.
    Never clobbers a >= complete existing archive unless force=True."""
    if provider is None:
        from data_feed import get_provider
        provider = get_provider()

    start, end = _et_window_utc(date)
    raw = provider.fetch_1m_candles_range(symbol, start, end)
    candles = sorted(
        (c for c in (raw or []) if _on_et_date(c.get("timestamp"), date)),
        key=lambda c: str(c.get("timestamp")),
    )
    path = archive_path(date, symbol)

    if not candles:
        return {"status": "no_data", "path": path, "bar_count": 0}

    if os.path.exists(path) and not force:
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
            if int(existing.get("bar_count", 0)) >= len(candles):
                return {"status": "skipped_existing", "path": path,
                        "bar_count": int(existing.get("bar_count", 0))}
        except (json.JSONDecodeError, OSError):
            pass  # corrupt/unreadable archive → rewrite it

    record = {
        "symbol": symbol,
        "date": date,
        "source": type(provider).__name__,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bar_count": len(candles),
        "candles": candles,
    }
    os.makedirs(archive_dir(), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    os.replace(tmp, path)  # atomic — a crashed write never corrupts an archive
    return {"status": "archived", "path": path, "bar_count": len(candles)}


def load_session(date: str, symbol: str = "QQQ") -> list:
    """Return the archived 1m candles for the ET date, oldest-first.
    Raises FileNotFoundError when the session was never archived."""
    path = archive_path(date, symbol)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No candle archive for {date} {symbol} at {path} — "
            "run: python -m replay_validation.candle_archive --date " + date)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["candles"]


def list_archived(symbol: str = None) -> list:
    """[{date, symbol, bar_count}] for every archived session, oldest-first."""
    out = []
    d = archive_dir()
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        stem = name[:-5]
        parts = stem.split("_", 1)
        if len(parts) != 2:
            continue
        date, sym = parts
        if symbol and sym != symbol:
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                rec = json.load(fh)
            out.append({"date": date, "symbol": sym,
                        "bar_count": int(rec.get("bar_count", 0))})
        except (json.JSONDecodeError, OSError):
            out.append({"date": date, "symbol": sym, "bar_count": -1})  # corrupt
    return out


def backfill(days: int, symbol: str = "QQQ", provider=None) -> list:
    """Archive the last `days` calendar days (skipping already-archived and
    no-data days like weekends/holidays). Returns per-day summaries."""
    if provider is None:
        from data_feed import get_provider
        provider = get_provider()
    results = []
    today = datetime.now(_ET).date()
    for i in range(days, 0, -1):
        date = (today - timedelta(days=i)).strftime("%Y%m%d")
        try:
            res = archive_session(date, symbol, provider=provider)
        except Exception as exc:  # noqa: BLE001 — one bad day must not kill the backfill
            res = {"status": f"error:{exc}", "path": archive_path(date, symbol),
                   "bar_count": 0}
        res["date"] = date
        results.append(res)
    return results


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="REPLAY-1 1m candle archive")
    p.add_argument("--date", help="ET session date YYYYMMDD to archive")
    p.add_argument("--backfill", type=int, help="archive the last N calendar days")
    p.add_argument("--list", action="store_true", help="list archived sessions")
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--force", action="store_true", help="overwrite existing archive")
    args = p.parse_args()

    if args.list:
        for row in list_archived(args.symbol or None):
            print(f"{row['date']} {row['symbol']}: {row['bar_count']} bars")
        return 0
    if args.date:
        res = archive_session(args.date, args.symbol, force=args.force)
        print(f"{args.date} {args.symbol}: {res['status']} ({res['bar_count']} bars)")
        return 0 if res["status"] != "no_data" else 1
    if args.backfill:
        results = backfill(args.backfill, args.symbol)
        archived = sum(1 for r in results if r["status"] == "archived")
        for r in results:
            if r["status"] != "no_data":
                print(f"{r['date']}: {r['status']} ({r['bar_count']} bars)")
        print(f"backfill complete: {archived} newly archived, "
              f"{sum(1 for r in results if r['status'] == 'skipped_existing')} existing, "
              f"{sum(1 for r in results if r['status'] == 'no_data')} no-data days")
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())

"""DECON-2 — Rebuild performance tables from REAL reconciled journal history.

Reads every day-file in data/paper_trades/ (top level only — _archived_stale is
excluded), takes ONLY order_status=closed records, sorts them chronologically by
closed_at, and folds each through the SAME hardened production pipeline the live
loop uses (assemble_closed_trade_outcome -> update_performance_tables). The
DECON-2 strict write gate and idempotency ledger therefore apply: synthetic /
null-execution / incomplete records are rejected and printed, and re-running
this tool never double-counts.

Usage:
  python tools/rebuild_performance_tables.py            # report only (dry run)
  python tools/rebuild_performance_tables.py --apply    # fold into live tables

The tool never deletes anything — purge/quarantine of the old contaminated
tables is a separate, explicit operator action.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from adaptive_learning.outcome_assembler import assemble_closed_trade_outcome  # noqa: E402
from adaptive_learning.performance_tables import (                              # noqa: E402
    update_performance_tables, load_symbol_tables, validate_performance_write,
)

_JOURNAL_DIR = os.getenv("PAPER_TRADES_DIR") or os.path.join("data", "paper_trades")


def _closed_trades() -> list:
    """All closed journal records, chronological by closed_at."""
    rows = []
    for path in sorted(glob.glob(os.path.join(_JOURNAL_DIR, "*_paper_trades.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                day = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"  [skip file] {path}: {exc}")
            continue
        for t in day.get("trades", []):
            if (t.get("order_status") or "").lower() == "closed":
                rows.append(t)
    rows.sort(key=lambda t: str(t.get("closed_at") or ""))
    return rows


def _recon_from_journal(t: dict) -> dict:
    """Close-time reconciliation view reconstructed from the journal record
    (reconciliation wrote these fields back at close time)."""
    return {
        "status":       "closed",
        "trade_id":     t.get("trade_id"),
        "symbol":       t.get("symbol"),
        "realized_r":   t.get("realized_r"),
        "realized_pnl": t.get("realized_pnl"),
        "entry_price":  t.get("entry_price") or t.get("entry_reference"),
        "exit_price":   t.get("exit_price"),
        "close_reason": t.get("close_reason"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Rebuild performance tables from journals.")
    p.add_argument("--apply", action="store_true",
                   help="fold accepted trades into the live tables (default: dry run)")
    args = p.parse_args(argv)

    closed = _closed_trades()
    print(f"journal dir      : {_JOURNAL_DIR}")
    print(f"closed records   : {len(closed)}")
    print(f"mode             : {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    accepted, rejected, duplicates, symbols = 0, 0, 0, set()
    for t in closed:
        recon = _recon_from_journal(t)
        outcome = assemble_closed_trade_outcome(recon, t, None)
        if args.apply:
            res = update_performance_tables(outcome, t)
            skipped, reason = res["skipped"], res["reason"]
        else:
            ok, gate_reason, _ = validate_performance_write(outcome, t)
            skipped, reason = (not ok), (None if ok else f"write_gate:{gate_reason}")
        tid = t.get("trade_id")
        if not skipped:
            accepted += 1
            symbols.add(str(t.get("symbol")).upper())
            print(f"  ACCEPTED  {tid}  r={t.get('realized_r')}")
        elif reason == "duplicate_write":
            duplicates += 1
            print(f"  DUPLICATE {tid}  (already in ledger — skipped safely)")
        else:
            rejected += 1
            print(f"  REJECTED  {tid}  reason={reason}")

    print()
    print(f"accepted={accepted}  rejected={rejected}  duplicates={duplicates}")

    if args.apply:
        for sym in sorted(symbols):
            print(f"\n=== rebuilt tables: {sym} ===")
            for dim, table in load_symbol_tables(sym).items():
                print(f"  [{dim}]")
                for key, b in sorted(table.items()):
                    print(f"    {key:24} trades={b['trades']} W={b['wins']} "
                          f"L={b['losses']} BE={b['breakevens']} "
                          f"sum_r={b['sum_r']} exp={b['expectancy']} "
                          f"streak={b['loss_streak']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

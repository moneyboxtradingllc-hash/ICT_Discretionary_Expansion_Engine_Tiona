"""
Adaptive Learning — Phase 3A: Symbol-native performance tables (WRITE + READ).

Closed trades are aggregated into per-symbol expectancy tables across five
dimensions (playbook, tool, session, regime, volatility). These tables are the
factual substrate the ADAPTIVE-3 policy engine reads to produce DEFENSIVE_ONLY,
recommendation-only guidance.

DOCTRINE (3A): this layer STORES outcomes and REPORTS aggregates. It authors no
decision, confidence, risk, or permission. It never mutates a trade. Writing is
driven by the existing scar-writer close event; reading is observe-only.

DOCTRINE (DECON-2 — truth before memory): the tables may ONLY learn from real,
reconciled, forward-trade executions. update_performance_tables() enforces:
  * STRICT WRITE GATE — a write requires a reconciled closed trade with a real
    (non-synthetic) execution id, entry + exit timestamps, numeric realized pnl,
    and a valid symbol, playbook, and session. Test fixtures, replays, studies,
    manual inserts, and null-execution records are rejected by construction.
  * IDEMPOTENCY — every applied write is recorded in the symbol's
    applied_writes.json ledger under sha256(symbol|entry_ts|exit_ts|execution_id).
    The same trade folding twice (restart, re-reconciliation, test rerun) is
    ignored safely; double-counting is impossible.

Storage layout (symbol-native — one folder per instrument):

    data/performance/<SYMBOL>/playbook_performance.json
    data/performance/<SYMBOL>/tool_performance.json
    data/performance/<SYMBOL>/session_performance.json
    data/performance/<SYMBOL>/regime_performance.json
    data/performance/<SYMBOL>/volatility_performance.json

Each file maps a dimension key -> bucket:

    {"strong": {"wins": 3, "losses": 1, "breakevens": 0, "trades": 4,
                "sum_r": 1.10, "expectancy": 0.275, "loss_streak": 0}}

Symbol isolation is absolute: a write for one symbol never touches another
symbol's folder. Never raises out of update_performance_tables().
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from deployment.data_paths import resolve
from ai_retrieval.memory_schema import win_loss_be_from_r

# Dimension -> table filename. The five ADAPTIVE-3 performance surfaces.
TABLE_FILES = {
    "playbook":   "playbook_performance.json",
    "tool":       "tool_performance.json",
    "session":    "session_performance.json",
    "regime":     "regime_performance.json",
    "volatility": "volatility_performance.json",
}

DIMENSIONS = tuple(TABLE_FILES.keys())

# DECON-2 — per-symbol idempotency ledger (applied write keys live next to the
# five tables; a key present here means that trade has already been folded).
LEDGER_FILE = "applied_writes.json"

# HTF-MEM-1 / LINEAGE — the ORGANISM EPOCH. Trades whose entry predates the
# current sovereign organism (pre-AI-Brain / pre-FC / manual-close era) are
# HISTORY, not evidence: the write gate rejects them from adaptive memory.
# Default = 2026-07-06 (ADAPTIVE-8 forward-validation session 1).
ORGANISM_EPOCH_DEFAULT = "20260706"


def organism_epoch() -> str:
    """YYYYMMDD lineage boundary (env ORGANISM_EPOCH_DATE overrides)."""
    raw = (os.getenv("ORGANISM_EPOCH_DATE") or ORGANISM_EPOCH_DEFAULT)
    return raw.replace("-", "")[:8]


# ── path resolution ─────────────────────────────────────────────────────────

def performance_root(base_dir: "str | None" = None) -> str:
    """Root of the performance store. Explicit base_dir wins (tests), else the
    PERFORMANCE_TABLES_DIR env override, else the legacy data/performance dir."""
    if base_dir:
        return base_dir
    return resolve("PERFORMANCE_TABLES_DIR", "data", "performance", anchored=True)


def _symbol_dir(symbol: str, base_dir: "str | None" = None) -> str:
    d = os.path.join(performance_root(base_dir), _norm_symbol(symbol))
    os.makedirs(d, exist_ok=True)
    return d


def _table_path(symbol: str, dimension: str, base_dir: "str | None" = None) -> str:
    return os.path.join(_symbol_dir(symbol, base_dir), TABLE_FILES[dimension])


# ── normalization ───────────────────────────────────────────────────────────

def _norm_symbol(symbol) -> str:
    s = str(symbol or "").strip().upper()
    return s or "UNKNOWN"


def _norm_key(value) -> str:
    s = str(value or "").strip().lower().replace(" ", "_")
    return s or "unknown"


# ── bucket math ─────────────────────────────────────────────────────────────

def _new_bucket() -> dict:
    return {"wins": 0, "losses": 0, "breakevens": 0, "trades": 0,
            "sum_r": 0.0, "expectancy": 0.0, "loss_streak": 0}


def _apply_result(bucket: dict, result: str, realized_r) -> dict:
    """Fold one closed-trade outcome into a bucket (in place). Expectancy is the
    running average R across all recorded trades; loss_streak is the current run
    of consecutive losses (reset by a win, unchanged by a breakeven)."""
    bucket["trades"] += 1
    try:
        r = float(realized_r)
        bucket["sum_r"] = round(bucket["sum_r"] + r, 6)
    except (TypeError, ValueError):
        pass

    if result == "win":
        bucket["wins"] += 1
        bucket["loss_streak"] = 0
    elif result == "loss":
        bucket["losses"] += 1
        bucket["loss_streak"] += 1
    else:  # breakeven / unknown-but-recorded — does not extend or reset the streak
        bucket["breakevens"] += 1

    bucket["expectancy"] = (
        round(bucket["sum_r"] / bucket["trades"], 6) if bucket["trades"] else 0.0
    )
    return bucket


# ── file I/O ────────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


# ── read API (policy engine) ────────────────────────────────────────────────

def get_bucket(symbol: str, dimension: str, key, base_dir: "str | None" = None) -> dict:
    """Return the bucket for (symbol, dimension, key), or a fresh empty bucket
    when none exists. Read-only — never creates or writes a table."""
    if dimension not in TABLE_FILES:
        return _new_bucket()
    root = performance_root(base_dir)
    path = os.path.join(root, _norm_symbol(symbol), TABLE_FILES[dimension])
    table = _load(path)
    bucket = table.get(_norm_key(key))
    return bucket if isinstance(bucket, dict) else _new_bucket()


def load_symbol_tables(symbol: str, base_dir: "str | None" = None) -> dict:
    """Return {dimension: table_dict} for a symbol (read-only)."""
    root = performance_root(base_dir)
    sym = _norm_symbol(symbol)
    return {
        dim: _load(os.path.join(root, sym, fname))
        for dim, fname in TABLE_FILES.items()
    }


# ── write API (scar-writer close event) ─────────────────────────────────────

def record_result(symbol: str, dimension: str, key, result: str, realized_r,
                  base_dir: "str | None" = None) -> dict:
    """Update a single (symbol, dimension, key) bucket and persist. Returns the
    updated bucket."""
    path = _table_path(symbol, dimension, base_dir)
    table = _load(path)
    bkey = _norm_key(key)
    bucket = table.get(bkey)
    if not isinstance(bucket, dict):
        bucket = _new_bucket()
    _apply_result(bucket, result, realized_r)
    table[bkey] = bucket
    _save(path, table)
    return bucket


# ── DECON-2 — strict write gate + idempotency ────────────────────────────────

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compute_write_key(symbol, entry_ts, exit_ts, execution_id) -> str:
    """Idempotency key: sha256(symbol|entry_ts|exit_ts|execution_id)."""
    raw = f"{_norm_symbol(symbol)}|{entry_ts}|{exit_ts}|{execution_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ledger_path(symbol: str, base_dir: "str | None" = None) -> str:
    return os.path.join(_symbol_dir(symbol, base_dir), LEDGER_FILE)


def validate_performance_write(outcome: dict, entry_record: "dict | None") -> tuple:
    """DECON-2 STRICT WRITE GATE. Returns (ok, reason, evidence).

    A performance write is permitted ONLY for a real, reconciled, forward-trade
    execution: status closed, a real (non-synthetic) execution id, entry + exit
    timestamps, numeric realized pnl, and a valid symbol/playbook/session.
    Everything else — test fixtures, replays, studies, manual inserts,
    null-execution records — is rejected. Pure; never raises."""
    o = outcome or {}
    e = entry_record or {}
    ss = e.get("snapshot_summary") or {}

    if str(o.get("status") or "").lower() != "closed":
        return False, "not_a_reconciled_closed_trade", None

    execution_id = e.get("alpaca_order_id") or e.get("execution_id") or e.get("order_id")
    if not execution_id:
        return False, "missing_execution_id", None
    if "synthetic" in str(execution_id).lower():
        return False, "synthetic_execution_id", None

    entry_ts = e.get("timestamp") or o.get("entry_timestamp")
    if not entry_ts:
        return False, "missing_entry_timestamp", None
    # LINEAGE: pre-epoch trades are historical evidence, never adaptive memory
    if str(entry_ts).replace("-", "")[:8] < organism_epoch():
        return False, "pre_epoch_lineage", None
    exit_ts = e.get("closed_at") or o.get("exit_timestamp")
    if not exit_ts:
        return False, "missing_exit_timestamp", None

    pnl = o.get("realized_pnl") if o.get("realized_pnl") is not None else e.get("realized_pnl")
    if not _is_num(pnl):
        return False, "invalid_realized_pnl", None

    symbol = _norm_symbol(o.get("instrument") or e.get("symbol"))
    if symbol == "UNKNOWN":
        return False, "invalid_symbol", None
    if _norm_key(o.get("playbook") or ss.get("playbook")) == "unknown":
        return False, "invalid_playbook", None
    if _norm_key(o.get("session") or ss.get("session")) == "unknown":
        return False, "invalid_session", None

    return True, "ok", {
        "symbol":       symbol,
        "entry_ts":     str(entry_ts),
        "exit_ts":      str(exit_ts),
        "execution_id": str(execution_id),
        "trade_id":     e.get("trade_id"),
    }


def _dimensions_from(outcome: dict, entry_record: "dict | None") -> dict:
    """Pull the five dimension VALUES from the assembled close-outcome + the
    entry-time journal record. These mirror exactly the values the live snapshot
    exposes, so tables and the policy candidate stay aligned."""
    entry = entry_record or {}
    ss = entry.get("snapshot_summary") or {}
    return {
        "playbook":   outcome.get("playbook") or ss.get("playbook"),
        "tool":       ss.get("tool"),
        "session":    outcome.get("session") or ss.get("session"),
        "regime":     entry.get("market_regime_family") or outcome.get("regime"),
        "volatility": outcome.get("volatility_state") or entry.get("volatility_state"),
    }


def update_performance_tables(outcome: dict, entry_record: "dict | None" = None,
                              base_dir: "str | None" = None) -> dict:
    """Fold one closed trade into the correct symbol's five tables. Driven by the
    scar-writer close event. Observe/record only — never raises.

    DECON-2: the STRICT WRITE GATE runs first (only real, reconciled, forward
    trades may write); then the idempotency ledger (the same trade can never be
    folded twice). Returns telemetry:
    {symbol, result, realized_r, updated:[dims], skipped, reason, write_key}.
    """
    try:
        outcome = outcome or {}
        symbol = _norm_symbol(outcome.get("instrument") or (entry_record or {}).get("symbol"))

        # ── DECON-2 strict write gate ──
        ok, gate_reason, evidence = validate_performance_write(outcome, entry_record)
        if not ok:
            return {"symbol": symbol, "result": None,
                    "realized_r": outcome.get("realized_r"), "updated": [],
                    "skipped": True, "reason": f"write_gate:{gate_reason}",
                    "write_key": None}

        realized_r = outcome.get("realized_r")
        result = outcome.get("result") or win_loss_be_from_r(realized_r)
        if result is None:
            return {"symbol": symbol, "result": None, "realized_r": realized_r,
                    "updated": [], "skipped": True,
                    "reason": "unclassifiable_outcome", "write_key": None}

        # ── DECON-2 idempotency: the same trade never folds twice ──
        write_key = compute_write_key(evidence["symbol"], evidence["entry_ts"],
                                      evidence["exit_ts"], evidence["execution_id"])
        ledger_file = _ledger_path(symbol, base_dir)
        ledger = _load(ledger_file)
        if write_key in ledger:
            return {"symbol": symbol, "result": result, "realized_r": realized_r,
                    "updated": [], "skipped": True, "reason": "duplicate_write",
                    "write_key": write_key}

        dims = _dimensions_from(outcome, entry_record)
        updated = []
        for dimension, key in dims.items():
            record_result(symbol, dimension, key, result, realized_r, base_dir)
            updated.append(dimension)

        ledger[write_key] = {
            "trade_id":     evidence.get("trade_id"),
            "entry_ts":     evidence["entry_ts"],
            "exit_ts":      evidence["exit_ts"],
            "execution_id": evidence["execution_id"],
            "result":       result,
            "realized_r":   realized_r,
            "applied_at":   datetime.now(timezone.utc).isoformat(),
        }
        _save(ledger_file, ledger)

        return {"symbol": symbol, "result": result, "realized_r": realized_r,
                "updated": updated, "skipped": False, "reason": None,
                "write_key": write_key}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": _norm_symbol((outcome or {}).get("instrument")),
                "result": None, "realized_r": None, "updated": [],
                "skipped": True, "reason": f"error:{type(exc).__name__}",
                "write_key": None}

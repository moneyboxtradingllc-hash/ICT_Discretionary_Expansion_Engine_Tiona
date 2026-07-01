"""
Adaptive Learning — Phase 3A: Symbol-native performance tables (WRITE + READ).

Closed trades are aggregated into per-symbol expectancy tables across five
dimensions (playbook, tool, session, regime, volatility). These tables are the
factual substrate the ADAPTIVE-3 policy engine reads to produce DEFENSIVE_ONLY,
recommendation-only guidance.

DOCTRINE (3A): this layer STORES outcomes and REPORTS aggregates. It authors no
decision, confidence, risk, or permission. It never mutates a trade. Writing is
driven by the existing scar-writer close event; reading is observe-only.

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

import json
import os

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

    Returns telemetry: {symbol, result, realized_r, updated:[dims], skipped, reason}.
    """
    try:
        outcome = outcome or {}
        symbol = _norm_symbol(outcome.get("instrument") or (entry_record or {}).get("symbol"))
        realized_r = outcome.get("realized_r")
        result = outcome.get("result") or win_loss_be_from_r(realized_r)
        if result is None:
            return {"symbol": symbol, "result": None, "realized_r": realized_r,
                    "updated": [], "skipped": True, "reason": "unclassifiable_outcome"}

        dims = _dimensions_from(outcome, entry_record)
        updated = []
        for dimension, key in dims.items():
            record_result(symbol, dimension, key, result, realized_r, base_dir)
            updated.append(dimension)
        return {"symbol": symbol, "result": result, "realized_r": realized_r,
                "updated": updated, "skipped": False, "reason": None}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": _norm_symbol((outcome or {}).get("instrument")),
                "result": None, "realized_r": None, "updated": [],
                "skipped": True, "reason": f"error:{type(exc).__name__}"}

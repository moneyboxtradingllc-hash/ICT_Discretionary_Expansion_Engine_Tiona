"""
Phase 5C — Memory Record Builder.
Loads and normalizes prior intent/trade records into a common schema.
Phase 5E.1 — Deduplication fix: paper trades load first and claim their intent_ids.
Any intent archive record whose intent_id is claimed by a paper trade is skipped.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
import json
import os

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_INTENT_DIR = os.path.join(_PROJECT_ROOT, "data", "intent_archive")
_TRADES_DIR = os.path.join(_PROJECT_ROOT, "data", "paper_trades")

_CLOSED_STATUSES  = {"closed", "externally_closed"}
_CLOSED_OUTCOMES  = {"win", "loss", "breakeven"}


def _organism_epoch() -> str:
    """Lineage boundary (YYYYMMDD). Lazy import keeps this observe-only reader
    free of the adaptive stack at module-load and honors ORGANISM_EPOCH_DATE."""
    try:
        from adaptive_learning.performance_tables import organism_epoch
        return organism_epoch()
    except Exception:  # noqa: BLE001
        import os
        return os.getenv("ORGANISM_EPOCH_DATE") or "20260706"


def _record_day(rec: dict) -> str:
    """YYYYMMDD of the record's entry timestamp, or '' when unparseable."""
    ts = str(rec.get("timestamp") or "")
    day = ts.replace("-", "")[:8]
    return day if day.isdigit() and len(day) == 8 else ""


def _is_pre_epoch(rec: dict) -> bool:
    """DASHBOARD-BASELINE — a record entered before the organism epoch is
    PRE-BASELINE lineage (stale/pre-repair). Records with no parseable day are
    conservatively treated as pre-epoch (they predate timestamped journaling)."""
    day = _record_day(rec)
    if not day:
        return True
    return day < _organism_epoch()


def _load_all_records(symbol: str | None) -> list[dict]:
    """The full deduplicated normalized set (pre- and post-epoch)."""
    # Step 1: load paper trades and deduplicate by trade_id
    trade_records = _load_from_paper_trades(symbol)
    seen_trade_ids: set[str] = set()
    deduped_trades: list[dict] = []
    for rec in trade_records:
        tid = rec.get("trade_id")
        if tid and tid in seen_trade_ids:
            continue
        if tid:
            seen_trade_ids.add(tid)
        deduped_trades.append(rec)

    # Step 2: collect intent_ids already represented by a paper trade
    claimed_intent_ids: set[str] = {
        rec["intent_id"] for rec in deduped_trades if rec.get("intent_id")
    }

    # Step 3: load intent archive records, skipping any claimed intent_id
    intent_records = _load_from_intent_archive(symbol, claimed_intent_ids)

    # Paper trades first (authoritative), then unlinked intent records
    return deduped_trades + intent_records


def load_memory_records(symbol: str | None = None,
                        include_pre_epoch: bool = False) -> list[dict]:
    """
    Load and normalize available memory records for the given symbol.
    Paper trade records are loaded first and claim their linked intent_ids;
    intent archive records whose intent_id is claimed are skipped to prevent
    double-counting a single trade across both sources.

    DASHBOARD-BASELINE (2026-07-08): the ACTIVE validation baseline contains
    ONLY post-epoch trades. Pre-epoch lineage (the STALE_PRE_AI June batch
    HTF-MEM-1 quarantined from the performance TABLES, but which this read path
    still surfaced) is excluded by default — that stale memory produced the
    false "Dashboard: 5 trades | WR 0.0% | AvgR -1.40" line and polluted the
    Brain's context summary + memory-search + recommendations (all
    OBSERVE_ONLY; no authority — this is a source-of-truth repair, not an
    authority change). `include_pre_epoch=True` is the explicit, labeled
    archival-only accessor. Never raises.
    """
    all_records = _load_all_records(symbol)
    if include_pre_epoch:
        return all_records
    return [r for r in all_records if not _is_pre_epoch(r)]


def load_memory_records_partitioned(
    symbol: str | None = None,
) -> "tuple[list[dict], list[dict]]":
    """(active_post_epoch, pre_epoch_excluded). Single pass; observe-only audit
    source for the CLEAN_BASELINE dashboard label. Never raises."""
    active: list[dict] = []
    pre_epoch: list[dict] = []
    for rec in _load_all_records(symbol):
        (pre_epoch if _is_pre_epoch(rec) else active).append(rec)
    return active, pre_epoch


# ── Intent Archive ────────────────────────────────────────────────────────────

def _load_from_intent_archive(
    symbol: str | None,
    skip_intent_ids: set[str] | None = None,
) -> list[dict]:
    records: list[dict] = []
    skip = skip_intent_ids or set()
    # Also deduplicate within the intent archive itself (same intent_id in multiple files)
    seen_in_archive: set[str] = set()

    if not os.path.isdir(_INTENT_DIR):
        return records

    for fname in os.listdir(_INTENT_DIR):
        if not fname.endswith(".json"):
            continue
        if symbol and symbol.upper() not in fname.upper():
            continue
        fpath = os.path.join(_INTENT_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue

        intents = raw.get("intents", []) if isinstance(raw, dict) else raw
        if not isinstance(intents, list):
            continue
        sym = raw.get("symbol", "") if isinstance(raw, dict) else ""

        for intent in intents:
            try:
                rec = _normalize_intent(intent, sym or symbol or "")
                if not rec:
                    continue
                iid = rec.get("intent_id")
                if iid and iid in skip:
                    continue  # claimed by a paper trade
                if iid and iid in seen_in_archive:
                    continue  # duplicate within the archive
                if iid:
                    seen_in_archive.add(iid)
                records.append(rec)
            except Exception:
                continue

    return records


def _normalize_intent(intent: dict, symbol: str = "") -> dict | None:
    if not isinstance(intent, dict):
        return None

    intent_id = intent.get("intent_id", "")
    if not intent_id:
        return None

    outcome = _derive_intent_outcome(intent)

    # Top-level fields are preferred (populated by Phase 5E.1 enrichment).
    # scan_updates fallback is kept for backward compatibility but those dicts
    # do not carry session/regime fields in the current schema.
    return {
        "intent_id":             intent_id,
        "trade_id":              intent.get("linked_trade_id") or None,
        "symbol":                (intent.get("symbol") or symbol or "").upper(),
        "timestamp":             intent.get("created_at") or intent.get("last_updated") or "",
        "playbook":              (intent.get("playbook") or "").lower(),
        "direction":             (intent.get("direction") or "").lower(),
        "preferred_tool":        (intent.get("preferred_tool") or "").lower(),
        "qualification":         (intent.get("quality_at_creation") or "").lower(),
        "session":               (intent.get("session") or "").lower(),
        "market_regime_label":   (intent.get("market_regime_label") or "unknown").lower(),
        "market_regime_family":  (intent.get("market_regime_family") or "unknown").lower(),
        "volatility_state":      (intent.get("volatility_state") or "unknown").lower(),
        "expansion_state":       (intent.get("expansion_state") or "unknown").lower(),
        "intent_score_gated":    _to_int(intent.get("gated_score_at_creation")),
        "ai_confidence":         _to_int(intent.get("ai_confidence_at_entry")),
        "mechanical_score":      _to_int(intent.get("mechanical_confidence_at_entry")),
        "realized_r":            _to_float(intent.get("realized_r")),
        "realized_pnl":          _to_float(intent.get("realized_pnl")),
        "mfe":                   _to_float(intent.get("mfe")),
        "mae":                   _to_float(intent.get("mae")),
        "holding_minutes":       _to_float(intent.get("holding_minutes")),
        "outcome":               outcome,
        "record_source":         "intent_archive",
        "data_completeness":     "partial",
        "_source":               "intent_archive",
        "_status":               (intent.get("status") or "unknown").lower(),
    }


def _derive_intent_outcome(intent: dict) -> str:
    r = _to_float(intent.get("realized_r"))
    if r is not None:
        if r > 0:
            return "win"
        if r < 0:
            return "loss"
        return "breakeven"
    status = (intent.get("status") or "").lower()
    if status in ("open", "active"):
        return "open"
    return "unknown"


# ── Paper Trades Journal ──────────────────────────────────────────────────────

def _load_from_paper_trades(symbol: str | None) -> list[dict]:
    records: list[dict] = []
    if not os.path.isdir(_TRADES_DIR):
        return records

    for fname in os.listdir(_TRADES_DIR):
        if not fname.endswith(".json"):
            continue
        if symbol and symbol.upper() not in fname.upper():
            continue
        fpath = os.path.join(_TRADES_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue

        trades = raw if isinstance(raw, list) else raw.get("trades", [])
        if not isinstance(trades, list):
            continue

        for trade in trades:
            try:
                rec = _normalize_trade(trade)
                if rec:
                    records.append(rec)
            except Exception:
                continue

    return records


def _normalize_trade(trade: dict) -> dict | None:
    if not isinstance(trade, dict):
        return None

    trade_id = trade.get("trade_id", "")
    if not trade_id:
        return None

    outcome  = _derive_trade_outcome(trade)
    snap_sum = trade.get("snapshot_summary") or {}

    # Playbook: explicit > snapshot_summary > intent_type fallback
    playbook = (
        trade.get("playbook")
        or snap_sum.get("playbook")
        or trade.get("intent_type")
        or ""
    ).lower()

    # Session: explicit > snapshot_summary
    session = (trade.get("session") or snap_sum.get("session") or "").lower()

    # data_completeness: full only when a closed outcome is recorded
    completeness = "full" if outcome in _CLOSED_OUTCOMES else "partial"

    return {
        "intent_id":             trade.get("intent_id") or None,
        "trade_id":              trade_id,
        "symbol":                (trade.get("symbol") or "").upper(),
        "timestamp":             trade.get("timestamp") or trade.get("entry_time") or "",
        "playbook":              playbook,
        "direction":             (trade.get("direction") or trade.get("intent_type") or "").lower(),
        "preferred_tool":        (trade.get("preferred_tool") or "").lower(),
        "qualification":         (trade.get("qualification_status") or "").lower(),
        "session":               session,
        "market_regime_label":   (trade.get("market_regime_label") or "unknown").lower(),
        "market_regime_family":  (trade.get("market_regime_family") or "unknown").lower(),
        "volatility_state":      (trade.get("volatility_state") or "unknown").lower(),
        "expansion_state":       (trade.get("expansion_state") or "unknown").lower(),
        "intent_score_gated":    _to_int(trade.get("intent_score_gated") or trade.get("gated_score")),
        "ai_confidence":         _to_int(trade.get("ai_confidence_at_entry")),
        "mechanical_score":      _to_int(trade.get("mechanical_confidence_at_entry")),
        "realized_r":            _to_float(trade.get("realized_r")),
        "realized_pnl":          _to_float(trade.get("realized_pnl")),
        "mfe":                   _to_float(trade.get("mfe")),
        "mae":                   _to_float(trade.get("mae")),
        "holding_minutes":       _to_float(trade.get("holding_minutes")),
        "close_reason":          trade.get("close_reason") or trade.get("exit_reason") or None,
        "ai_value_label":        (trade.get("ai_value_label") or "unknown").lower(),
        "ai_was_directionally_correct": trade.get("ai_was_directionally_correct"),
        "outcome":               outcome,
        "record_source":         "paper_trade",
        "data_completeness":     completeness,
        "_source":               "paper_trades",
        "_status":               (trade.get("order_status") or "unknown").lower(),
    }


def _derive_trade_outcome(trade: dict) -> str:
    r = _to_float(trade.get("realized_r"))
    if r is not None:
        if r > 0:
            return "win"
        if r < 0:
            return "loss"
        return "breakeven"
    status = (trade.get("order_status") or "").lower()
    if status in _CLOSED_STATUSES:
        return "unknown"
    if status in ("open", "submitted", "partially_filled"):
        return "open"
    return "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _to_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None

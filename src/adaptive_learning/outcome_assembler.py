"""
Adaptive Learning — Phase 1A.5: Runtime Outcome Assembler + scar-write wiring.

Closes the write-side gap the forensic audit found: write_outcome() had zero
runtime callers, so closed trades never became scars. This module:

  1. assemble_closed_trade_outcome(reconciliation, entry_snapshot, ai_brain_state)
     — PURE assembly of the exact payload write_outcome() requires, sourced from
       the ENTRY-TIME journal record (post-PIPE-1 / post-Vector-3 state captured at
       order placement) + the close-time reconciliation metrics.
  2. record_closed_trade_scar(reconciliation, symbol, ai_brain_state)
     — runtime orchestrator: load the closed entry record, assemble, write to the
       existing vector store, and return scar-writer telemetry.

DOCTRINE (1A.5): write-side only. No influence, no authority, no confidence
modification, no 1D. Touches no execution/risk/qualification decision. Never
raises into the scan loop.
"""
from __future__ import annotations

from ai_retrieval.memory_schema import win_loss_be_from_r
from adaptive_learning.live_memory_writer import write_outcome

_SIDE_DIR = {"buy": "bullish", "long": "bullish", "sell": "bearish", "short": "bearish"}


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _side_to_dir(side):
    return _SIDE_DIR.get(str(side or "").lower())


def _compose_thesis(es: dict) -> "str | None":
    """Compact ENTRY-time thesis from the journal's narrative-at-entry fields."""
    d = _first(es, "narrative_direction_at_entry", "ai_direction_at_entry")
    p = es.get("narrative_phase_at_entry")
    c = es.get("ai_confidence_at_entry")
    if not d and not p:
        return None
    return f"{d or 'neutral'} {p or ''} at entry (ai_conf={c})".strip()


# ── pure assembly ─────────────────────────────────────────────────────────────

def assemble_closed_trade_outcome(reconciliation: dict, entry_snapshot: dict,
                                  ai_brain_state: dict = None) -> dict:
    """Build the exact dict write_outcome() expects. Pure (no I/O). Never raises.

    `entry_snapshot` is the ENTRY-TIME journal record (the durable post-PIPE-1 /
    post-Vector-3 context captured at order placement); `reconciliation` is the
    close-time metrics; `ai_brain_state` is a fallback thesis source only.
    """
    recon = reconciliation or {}
    es = entry_snapshot or {}
    ab = ai_brain_state or {}
    ss = es.get("snapshot_summary") or {}
    ab_out = ab.get("output") if isinstance(ab.get("output"), dict) else ab

    direction = _first(es, "narrative_direction_at_entry", "ai_direction_at_entry") \
        or _side_to_dir(es.get("side"))
    realized_r = recon.get("realized_r") if recon.get("realized_r") is not None \
        else es.get("realized_r")
    # ENTRY thesis preferred (memory must describe the SETUP, not the exit);
    # close-time brain is a fallback only.
    thesis = _compose_thesis(es) or (ab_out.get("dominant_reasoning")
                                     or ab_out.get("market_story"))
    direction_source = "ai_brain" if _first(
        es, "narrative_direction_at_entry", "ai_direction_at_entry") else None

    return {
        "instrument":              _first(es, "symbol") or recon.get("symbol"),
        "entry_timestamp":         es.get("timestamp"),
        "source_type":             "closed_trade",
        "status":                  "closed",
        # ── market-state (entry-time; required by embedding.py) ──
        "session":                 _first(ss, "session") or es.get("session"),
        "regime":                  es.get("market_regime_label"),
        "volatility_state":        es.get("volatility_state"),
        "expansion_state":         es.get("expansion_state"),
        "playbook":                _first(ss, "playbook") or es.get("intent_type"),
        "direction":               direction,
        "narrative_direction":     direction,
        "narrative_phase":         es.get("narrative_phase_at_entry"),
        "active_liquidity_draw":   es.get("liquidity_draw_at_entry"),
        "protected_high":          es.get("protected_high_at_entry"),
        "protected_low":           es.get("protected_low_at_entry"),
        "direction_source":        direction_source,
        # ── thesis / confidence ──
        "ai_thesis_summary":       thesis,
        "ai_confidence_at_entry":  es.get("ai_confidence_at_entry"),
        # ── prices ──
        "entry_price":             _first(recon, "entry_price") or _first(es, "entry_price", "entry_reference"),
        "stop_price":              _first(es, "stop_reference", "current_stop_reference"),
        "target_price":            _first(ss, "target", "target_price") or es.get("target_price"),
        "exit_price":              _first(recon, "exit_price") or es.get("exit_price"),
        # ── outcome ──
        "realized_r":              realized_r,
        "realized_pnl":            recon.get("realized_pnl") if recon.get("realized_pnl") is not None else es.get("realized_pnl"),
        "mfe":                     es.get("mfe"),
        "mae":                     es.get("mae"),
        "management_path":         _first(recon, "close_reason") or _first(es, "close_reason", "stop_management_state"),
        "result":                  win_loss_be_from_r(realized_r),
        "success_or_failure_reason": _first(recon, "close_reason") or es.get("close_reason"),
    }


# ── runtime orchestrator ──────────────────────────────────────────────────────

def _load_closed_trade(symbol: str, trade_id: str) -> "dict | None":
    """Load the closed entry record from today's journal (intraday; EOD-flatten
    doctrine means entry+close share a calendar day). Read-only. None if absent."""
    try:
        from paper_execution.trade_journal import load_today_trades
        for t in load_today_trades(symbol):
            if t.get("trade_id") == trade_id:
                return t
    except Exception:  # noqa: BLE001
        return None
    return None


def _telemetry(*, written=False, memory_id=None, duplicate=False, errors=None) -> dict:
    return {
        "memory_written":    bool(written),
        "memory_id":         memory_id,
        "source_type":       "closed_trade",
        "duplicate_skipped": bool(duplicate),
        "validation_errors": list(errors or []),
    }


def build_scar_telemetry(write_result: dict) -> dict:
    """Map a write_outcome() result to scar-writer telemetry."""
    res = write_result or {}
    written = bool(res.get("written"))
    duplicate = bool(res.get("skipped"))
    errors = [] if (written or duplicate) else [res.get("reason") or "unknown"]
    return _telemetry(written=written, memory_id=res.get("memory_id"),
                      duplicate=duplicate, errors=errors)


def record_closed_trade_scar(reconciliation: dict, symbol: str,
                             ai_brain_state: dict = None) -> dict:
    """Runtime entry point for the reconciliation close event. Loads the entry
    record, assembles the outcome, writes the scar, returns telemetry. Write-side
    only — influences nothing. Never raises."""
    try:
        recon = reconciliation or {}
        if recon.get("status") != "closed":
            return _telemetry(written=False, errors=["not_closed"])
        entry = _load_closed_trade(symbol, recon.get("trade_id"))
        if entry is None:
            return _telemetry(written=False, errors=["entry_record_not_found"])
        outcome = assemble_closed_trade_outcome(recon, entry, ai_brain_state)
        result = write_outcome(outcome, source_type="closed_trade")
        # ── ADAPTIVE-3 — fold the closed outcome into the symbol's performance
        # tables (playbook/tool/session/regime/volatility). Observe/record only:
        # influences NO decision, confidence, risk, or permission. Isolated in its
        # own guard so a table error can never affect the scar write. Never raises.
        try:
            from adaptive_learning.performance_tables import update_performance_tables
            update_performance_tables(outcome, entry)
        except Exception:  # noqa: BLE001
            pass
        return build_scar_telemetry(result)
    except Exception as exc:  # noqa: BLE001
        return _telemetry(written=False, errors=[f"scar_writer_error:{type(exc).__name__}"])

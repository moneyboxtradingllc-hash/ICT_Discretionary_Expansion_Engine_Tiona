"""
Phase AB-3 — June 10/11 corpus backfill.

Seeds the vector store from archived snapshots + paper-trade journals. These
pre-firewall artifacts carry no provenance field; where a sweep is recoverable
from the snapshot's narrative summary, the delivery direction is sourced
'sweep_semantics' (authoritative). Otherwise the record is stored with unknown
provenance — auditable, but NOT retrievable as an authoritative analog (T2).

Honest about the corpus: most pre-AB-2A history is non-authoritative by
provenance, which is the correct posture, not a defect.
"""
import glob
import json
import os
import re

from ai_retrieval.memory_schema import make_record, win_loss_be_from_r
from ai_retrieval.vector_store import add_records

# Legacy relative defaults + patch-points; LIVE_SNAPSHOTS_DIR / PAPER_TRADES_DIR
# (set by an active InstanceContext) override them per-instance.
_SNAP_DIR = os.path.join("data", "live_snapshots")
_TRADE_DIR = os.path.join("data", "paper_trades")


def _snap_dir() -> str:
    return os.getenv("LIVE_SNAPSHOTS_DIR") or _SNAP_DIR


def _trade_dir() -> str:
    return os.getenv("PAPER_TRADES_DIR") or _TRADE_DIR


def _sweep_from_summary(summary: str) -> tuple:
    """(delivery_direction, source) from the narrative summary text, or (None, unknown)."""
    m = re.search(r"Liquidity sweep (above_high|below_low) on \w+", summary or "")
    if not m:
        return None, "unknown"
    return ("bearish" if m.group(1) == "above_high" else "bullish"), "sweep_semantics"


def _market_record(snap: dict) -> dict:
    mr = snap.get("market_regime", {}) or {}
    qual = snap.get("qualification", {}) or {}
    pb = snap.get("playbook", {}) or {}
    summary = (snap.get("ai_context", {}) or {}).get("summary", "")
    deliv_dir, deliv_src = _sweep_from_summary(summary)
    # The pre-firewall qualification.direction is structure-authored; do NOT
    # propagate it as narrative truth. narrative_direction is populated only
    # when it has valid (sweep) provenance.
    authoritative = deliv_src == "sweep_semantics"
    return make_record(
        record_type="market",
        timestamp=snap.get("timestamp"),
        symbol=snap.get("symbol"),
        session=snap.get("session"),
        regime=mr.get("regime_label"),
        volatility_state=mr.get("volatility_state"),
        narrative_direction=(deliv_dir if authoritative else None),
        narrative_phase=None,
        delivery_direction=deliv_dir,
        delivery_direction_source=deliv_src,
        active_playbook=pb.get("selected_playbook"),
        toolbox_state=(snap.get("toolbox", {}) or {}).get("best_available_effective_status"),
        # provenance: sweep-sourced where recoverable, else unknown
        direction_source=deliv_src if authoritative else None,
    )


def _trade_record(trade: dict) -> dict:
    r = trade.get("realized_r")
    # post-NA-1 trades carry narrative_*_at_entry; June 10/11 do not
    nd = trade.get("narrative_direction_at_entry")
    dsrc = trade.get("direction_source") or (
        "sweep_semantics" if trade.get("liquidity_draw_at_entry") else None)
    return make_record(
        record_type="trade",
        timestamp=trade.get("timestamp"),
        symbol=trade.get("symbol"),
        session=(trade.get("snapshot_summary", {}) or {}).get("session"),
        regime=trade.get("market_regime_label"),
        volatility_state=trade.get("volatility_state"),
        narrative_direction=nd or trade.get("ai_direction_at_entry"),
        narrative_phase=trade.get("narrative_phase_at_entry"),
        active_liquidity_draw=trade.get("liquidity_draw_at_entry"),
        protected_high=trade.get("protected_high_at_entry"),
        protected_low=trade.get("protected_low_at_entry"),
        active_playbook=(trade.get("snapshot_summary", {}) or {}).get("playbook"),
        entry_model=None,
        trade_taken=True,
        trade_direction=trade.get("intent_type"),
        win_loss_be=win_loss_be_from_r(r),
        r_multiple=r,
        management_path=trade.get("close_reason"),
        direction_source=dsrc,
    )


def backfill_dates(dates=("20260610", "20260611"), symbol="QQQ") -> dict:
    """Load snapshots + trades for the given dates into the vector store."""
    market_records, trade_records = [], []

    for date in dates:
        for fp in sorted(glob.glob(os.path.join(_snap_dir(), f"{date}_*_{symbol}.json"))):
            try:
                snap = json.load(open(fp, encoding="utf-8"))
                market_records.append(_market_record(snap))
            except Exception:  # noqa: BLE001
                continue
        tpath = os.path.join(_trade_dir(), f"{date}_{symbol}_paper_trades.json")
        if os.path.exists(tpath):
            try:
                trades = json.load(open(tpath, encoding="utf-8")).get("trades", [])
                for t in trades:
                    trade_records.append(_trade_record(t))
            except Exception:  # noqa: BLE001
                pass

    n_market = add_records(market_records)
    n_trade = add_records(trade_records)
    return {"market_records": n_market, "trade_records": n_trade,
            "total": n_market + n_trade, "dates": list(dates)}


if __name__ == "__main__":
    from ai_retrieval.vector_store import clear, count
    clear()
    print(backfill_dates())
    print("store size:", count())

"""ADAPTIVE-8 — Forward Market Validation auditor (READ-ONLY).

Post-session truth audit for the forward-validation campaign. Reads the
DECON-3 forensic snapshots, the trade journal, the performance tables +
idempotency ledger, and the scar store — and writes NOTHING into organism
state (optionally appends a session summary to data/ops/validation/, which is
ops bookkeeping, not adaptive memory).

Usage:
  python tools/session_validation_report.py --date 20260706 [--symbol QQQ] [--record]
  python tools/session_validation_report.py --cumulative

Per session: scans, opportunities, approvals, blocks (by layer), submissions,
rejections, fills/closes, W/L/BE. Per trade: decision validity, adaptive
coherence (policy -> mutation -> consumption math), risk sizing, broker trace
integrity, forensic completeness. Stress signals: false suppression,
under-reaction, mutation drift, size drift, table/ledger mismatch.
"""
import argparse
import glob
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_SNAP_DIR    = os.getenv("LIVE_SNAPSHOTS_DIR") or os.path.join("data", "live_snapshots")
_JOURNAL_DIR = os.getenv("PAPER_TRADES_DIR") or os.path.join("data", "paper_trades")
_SCAR_STORE  = os.path.join(os.getenv("AI_RETRIEVAL_DIR") or os.path.join("data", "ai_retrieval"),
                            "memory_store.jsonl")
_TRACK_DIR   = os.path.join("data", "ops", "validation")

CONFIDENCE_PENALTY_FACTOR = 0.90   # must mirror adaptive_mutation_engine
RISK_REDUCTION_FACTOR     = 0.50
MIN_QTY                   = 1


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _session_snapshots(date: str, symbol: str) -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(_SNAP_DIR, f"{date}_*_{symbol}.json"))):
        rec = _load_json(p)
        if isinstance(rec, dict):
            rec["_file"] = os.path.basename(p)
            out.append(rec)
    return out


def _session_trades(date: str, symbol: str) -> list:
    day = _load_json(os.path.join(_JOURNAL_DIR, f"{date}_{symbol}_paper_trades.json"))
    return (day or {}).get("trades", [])


def _scar_count() -> int:
    try:
        with open(_SCAR_STORE, encoding="utf-8") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ── per-session scan aggregation ──────────────────────────────────────────────

def audit_scans(snaps: list) -> dict:
    n = len(snaps)
    decisions = Counter((s.get("decision_authority") or {}).get("decision") or "?"
                        for s in snaps)
    opportunities = sum(1 for s in snaps
                        if (s.get("decision_authority") or {}).get("decision")
                        in ("ready_for_execution", "prepare_long", "prepare_short"))
    approved = sum(1 for s in snaps
                   if (s.get("execution_gate") or {}).get("allow_execution"))
    pe_status = Counter(((s.get("paper_execution") or {}).get("status") or "?")
                        for s in snaps)
    block_layers = Counter(b.get("layer") for s in snaps
                           for b in (s.get("block_trace") or []))
    adaptive_blocks = sum(1 for s in snaps
                          if (s.get("adaptive_block") or {}).get("blocked"))
    conf_reductions = sum(1 for s in snaps
                          if (s.get("adaptive_live_consumption") or {})
                          .get("adaptive_confidence_consumed"))
    size_reductions = sum(1 for s in snaps
                          if (s.get("adaptive_live_consumption") or {})
                          .get("adaptive_size_consumed"))
    mutation_types = Counter(t for s in snaps
                             for t in ((s.get("adaptive_mutation") or {})
                                       .get("mutation_types") or []))
    risk_tiers = Counter((s.get("risk") or {}).get("risk_tier") or "?" for s in snaps)
    mc_states = Counter((s.get("market_commander") or {}).get("final_state") or "absent"
                        for s in snaps)
    forensic_complete = sum(
        1 for s in snaps
        if all(k in s for k in ("block_trace", "mutation_trace",
                                "authority_trace", "broker_trace")))
    return {
        "scans": n,
        "decisions": dict(decisions),
        "trade_opportunities": opportunities,
        "gate_approved": approved,
        "paper_execution_status": dict(pe_status),
        "submitted_orders": pe_status.get("submitted", 0),
        "rejected_orders": pe_status.get("rejected", 0),
        "block_layers": dict(block_layers),
        "adaptive_blocks": adaptive_blocks,
        "confidence_reductions": conf_reductions,
        "size_reductions": size_reductions,
        "mutation_types": dict(mutation_types),
        "risk_tiers": dict(risk_tiers),
        "market_commander_states": dict(mc_states),
        "forensic_complete_records": forensic_complete,
        "forensic_incomplete_records": n - forensic_complete,
    }


# ── per-trade validation ──────────────────────────────────────────────────────

def _find_submit_snapshot(snaps: list, trade_id: str):
    for s in snaps:
        if (s.get("paper_execution") or {}).get("trade_id") == trade_id:
            return s
    return None


def validate_trade(trade: dict, snaps: list) -> dict:
    """A/B/C/D/E per-trade checks. Returns {trade_id, checks:{name:bool|None},
    issues:[...]} — None = not verifiable from available records."""
    t = trade
    tid = t.get("trade_id")
    ss = t.get("snapshot_summary") or {}
    checks, issues = {}, []

    def _check(name, ok, why=None):
        checks[name] = ok
        if ok is False and why:
            issues.append(f"{name}: {why}")

    # A. DECISION
    _check("A_qualification_valid", ss.get("decision") == "ready_for_execution",
           f"journal decision={ss.get('decision')}")
    _check("A_playbook_valid", bool(ss.get("playbook"))
           and ss.get("playbook") != "no_playbook", f"playbook={ss.get('playbook')}")
    _check("A_tool_captured", bool(ss.get("tool")),
           "tool missing from snapshot_summary (DECON-2 capture)")
    _check("A_score_met_threshold", _is_num(ss.get("gated_score"))
           and ss.get("gated_score", 0) >= 70, f"gated_score={ss.get('gated_score')}")

    snap = _find_submit_snapshot(snaps, tid)
    if snap is None:
        _check("E_forensic_snapshot_found", False,
               "no forensic snapshot carries this trade_id")
        return {"trade_id": tid, "checks": checks, "issues": issues}
    _check("E_forensic_snapshot_found", True)

    # B. ADAPTIVE coherence (policy -> mutation -> consumption)
    pol = snap.get("adaptive_policy") or {}
    mut = snap.get("adaptive_mutation") or {}
    at = snap.get("authority_trace") or {}
    if pol:
        penalty = bool(pol.get("confidence_penalty_recommended"))
        fired_penalty = "confidence_penalty" in (mut.get("mutation_types") or [])
        _check("B_mutation_matches_policy", penalty == fired_penalty,
               f"policy penalty={penalty} but mutation fired={fired_penalty}")
        if fired_penalty and _is_num(mut.get("original_confidence")):
            expected = round(mut["original_confidence"] * CONFIDENCE_PENALTY_FACTOR, 6)
            _check("B_confidence_math", abs((mut.get("new_confidence") or 0)
                                            - expected) < 1e-6,
                   f"new={mut.get('new_confidence')} expected={expected}"
                   " (MUTATION DRIFT)")
        block_rec = bool(pol.get("trade_block_recommended"))
        blocked = bool((snap.get("adaptive_block") or {}).get("blocked"))
        _check("B_block_matches_policy", block_rec == blocked,
               f"policy block={block_rec} adaptive_block={blocked}")
    else:
        checks["B_policy_present"] = None   # pre-DECON-3 record

    # C. RISK sizing
    qty = t.get("qty")
    rps = t.get("risk_per_share")
    if _is_num(qty) and _is_num(rps) and _is_num(t.get("risk_dollars")):
        _check("C_risk_dollars_math", abs(t["risk_dollars"] - round(qty * rps, 2)) < 0.05,
               f"risk_dollars={t['risk_dollars']} != qty*rps={round(qty*rps,2)}")
        budget = (t.get("effective_risk_budget") or 0)
        if budget:
            _check("C_risk_within_budget", t["risk_dollars"] <= budget + 0.05,
                   f"risk {t['risk_dollars']} exceeds effective budget {budget}")
    q_orig, q_final = at.get("qty_original"), at.get("qty_final")
    if pol.get("risk_reduction_recommended") and _is_num(q_orig) and _is_num(q_final):
        expected_q = max(MIN_QTY, int(q_orig * RISK_REDUCTION_FACTOR))
        _check("C_size_reduction_math", q_final == min(q_orig, expected_q),
               f"final={q_final} expected={expected_q} from {q_orig} (SIZE DRIFT)")
    elif pol.get("risk_reduction_recommended"):
        _check("C_size_reduction_applied", q_final is not None,
               "risk_reduction recommended but no qty trace (UNDER-REACTION?)")

    # D. EXECUTION / broker trace
    bt = snap.get("broker_trace") or {}
    _check("D_broker_called", bt.get("broker_called") is True,
           "order in journal but broker_trace says not called")
    req = bt.get("request") or {}
    if req:
        _check("D_payload_qty_matches", req.get("qty") == qty,
               f"broker qty={req.get('qty')} journal qty={qty}")
        _check("D_payload_side_matches", req.get("side") == t.get("side"),
               f"broker side={req.get('side')} journal side={t.get('side')}")
    resp = bt.get("response") or {}
    if t.get("alpaca_order_id"):
        _check("D_order_id_preserved",
               resp.get("alpaca_order_id") == t.get("alpaca_order_id"),
               "journal order id not in broker response")
    _check("D_order_status_recorded", bool(t.get("order_status")),
           "journal missing order_status")

    # E. FORENSICS completeness
    _check("E_truth_traces_present",
           all(k in snap for k in ("block_trace", "mutation_trace",
                                   "authority_trace", "broker_trace")),
           "DECON-3 traces missing on submit-scan record")

    return {"trade_id": tid, "checks": checks, "issues": issues}


# ── stress signals ────────────────────────────────────────────────────────────

def stress_signals(snaps: list) -> list:
    """Scans deserving human review (not automatically wrong)."""
    signals = []
    for s in snaps:
        q = ((s.get("qualification") or {}).get("status") or "").lower()
        blocked_adaptive = any(b.get("layer") == "adaptive_live_authority"
                               for b in s.get("block_trace") or [])
        if blocked_adaptive and q in ("qualified", "elite"):
            signals.append({"signal": "possible_false_suppression",
                            "file": s.get("_file"), "qualification": q,
                            "reason": [b["reason"] for b in s["block_trace"]
                                       if b["layer"] == "adaptive_live_authority"]})
        pol = s.get("adaptive_policy") or {}
        pe = s.get("paper_execution") or {}
        at = s.get("authority_trace") or {}
        if (pe.get("status") == "submitted"
                and pol.get("risk_reduction_recommended")
                and _is_num(at.get("qty_original")) and _is_num(at.get("qty_final"))
                and at["qty_final"] >= at["qty_original"] > 1):
            signals.append({"signal": "possible_under_reaction",
                            "file": s.get("_file"),
                            "qty": [at["qty_original"], at["qty_final"]]})
    return signals


# ── table / ledger / scar integrity ───────────────────────────────────────────

def integrity_check(symbol: str) -> dict:
    root = os.getenv("PERFORMANCE_TABLES_DIR") or os.path.join("data", "performance")
    sym_dir = os.path.join(root, symbol)
    ledger = _load_json(os.path.join(sym_dir, "applied_writes.json")) or {}
    ledger_rs = [v.get("realized_r") for v in ledger.values() if _is_num(v.get("realized_r"))]
    ledger_sum = round(sum(ledger_rs), 6)
    out = {"ledger_trades": len(ledger), "ledger_sum_r": ledger_sum,
           "dims": {}, "mismatches": []}
    for dim in ("playbook", "tool", "session", "regime", "volatility"):
        table = _load_json(os.path.join(sym_dir, f"{dim}_performance.json")) or {}
        tot = sum(b.get("trades", 0) for b in table.values())
        sum_r = round(sum(b.get("sum_r", 0.0) for b in table.values()), 6)
        streaks = {k: b.get("loss_streak") for k, b in table.items()}
        exps = {k: b.get("expectancy") for k, b in table.items()}
        out["dims"][dim] = {"trades": tot, "sum_r": sum_r,
                            "loss_streaks": streaks, "expectancy": exps}
        if tot != len(ledger):
            out["mismatches"].append(
                f"{dim}: table trades {tot} != ledger {len(ledger)} (TABLE MISMATCH)")
        if abs(sum_r - ledger_sum) > 1e-6:
            out["mismatches"].append(
                f"{dim}: table sum_r {sum_r} != ledger {ledger_sum}")
    out["scar_records"] = _scar_count()
    return out


# ── report ────────────────────────────────────────────────────────────────────

def run_session_report(date: str, symbol: str, record: bool) -> dict:
    snaps = _session_snapshots(date, symbol)
    trades = _session_trades(date, symbol)
    scan_audit = audit_scans(snaps)
    closed = [t for t in trades if (t.get("order_status") or "") == "closed"]
    results = Counter()
    for t in closed:
        r = t.get("realized_r")
        if _is_num(r):
            results["win" if r > 0.05 else ("loss" if r < -0.05 else "be")] += 1

    trade_reports = [validate_trade(t, snaps) for t in trades
                     if t.get("order_status") in ("submitted", "closed", "rejected")]
    signals = stress_signals(snaps)
    integ = integrity_check(symbol)

    report = {
        "phase": "ADAPTIVE-8", "date": date, "symbol": symbol,
        "session_audit": {**scan_audit,
                          "journal_orders": len(trades),
                          "closed_trades": len(closed),
                          "wins": results.get("win", 0),
                          "losses": results.get("loss", 0),
                          "breakevens": results.get("be", 0)},
        "trade_validation": trade_reports,
        "stress_signals": signals,
        "integrity": integ,
    }
    if record:
        os.makedirs(_TRACK_DIR, exist_ok=True)
        path = os.path.join(_TRACK_DIR, f"adaptive8_session_{date}_{symbol}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        report["recorded_to"] = path
    return report


def run_cumulative(symbol: str) -> dict:
    """Campaign-to-date view straight from the stores (stateless)."""
    integ = integrity_check(symbol)
    all_closed, all_orders = [], 0
    for p in sorted(glob.glob(os.path.join(_JOURNAL_DIR, "*_paper_trades.json"))):
        day = _load_json(p) or {}
        for t in day.get("trades", []):
            all_orders += 1
            if t.get("order_status") == "closed":
                all_closed.append(t)
    rs = [t.get("realized_r") for t in all_closed if _is_num(t.get("realized_r"))]
    wins = sum(1 for r in rs if r > 0.05)
    losses = sum(1 for r in rs if r < -0.05)
    be = len(rs) - wins - losses
    return {
        "phase": "ADAPTIVE-8 cumulative", "symbol": symbol,
        "journal_orders_all_time": all_orders,
        "closed_trades": len(all_closed),
        "wins": wins, "losses": losses, "breakevens": be,
        "expectancy": round(sum(rs) / len(rs), 4) if rs else None,
        "integrity": integ,
        "validation_target": "20-30 closed trades over >=10 sessions",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ADAPTIVE-8 read-only session auditor")
    p.add_argument("--date", help="session date YYYYMMDD")
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--record", action="store_true",
                   help="also save the report under data/ops/validation/")
    p.add_argument("--cumulative", action="store_true")
    args = p.parse_args(argv)

    if args.cumulative:
        print(json.dumps(run_cumulative(args.symbol), indent=2, default=str))
        return 0
    if not args.date:
        p.error("--date YYYYMMDD required (or --cumulative)")
    print(json.dumps(run_session_report(args.date, args.symbol, args.record),
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

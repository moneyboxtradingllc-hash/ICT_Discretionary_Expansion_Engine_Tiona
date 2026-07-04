"""
SUPPRESS-1 — Suppression Cost Engine (shadow outcome tracking for blocked trades).

Blocked trades are not dead. They are unrealized evidence.

When the organism refuses an opportunity (risk block, gate check, adaptive soft
veto, supremacy, ops denial, intent gating ...) the refused candidate is
registered as a SHADOW trade and tracked forward against live price — no
execution, no authority, pure measurement:

    register_blocked_candidate()  — one open shadow record per (tool, direction)
    resolve_shadow_outcome()      — advance open records on each scan's candle
    score_suppression()           — outcome + suppression_cost in R

Outcomes:
    correct_suppression — shadow stop hit first   (the block SAVED us; cost -1R avoided)
    false_suppression   — shadow target hit first (the block COST us; cost +TP_R missed)
    neutral_suppression — triggered, neither hit by session end (cost = unrealized R)
    expired_suppression — entry never triggered   (cost 0 — nothing was actually offered)

Doctrine:
  * SHADOW ONLY. Registers/resolves influence nothing: no decision, confidence,
    risk, permission, or adaptive-policy flag reads this engine's output for
    authority. It is future tuning intelligence (observation only).
  * No synthetic plans: a candidate without a real entry AND stop is not
    registered (mirrors the no-bracket-no-trade doctrine).
  * Conservative fills: limit-style trigger at entry; when a candle spans both
    stop and target the STOP wins (never over-claims false suppression).
  * EOD honesty: the live organism is flat by the close, so shadow trades are
    judged only to session end (date change expires/settles them).
  * PERSIST CONTRACT (as MEM-DECAY-1): state is written ONLY by the live scan
    loop (track_suppression). All other callers use the read-only getters.
  * State lives under the performance root -> inherits PERFORMANCE_TABLES_DIR
    isolation; tests can never touch live suppression memory.
  * Never raises into the scan loop.

Files (per symbol, beside the performance tables):
    suppression_open.json      — open shadow records (updatable dict)
    suppression_resolved.jsonl — append-only resolved forensic log
    suppression_metrics.json   — per-dimension tallies (adaptive memory feed)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from adaptive_learning.performance_tables import (
    performance_root, _norm_symbol, _norm_key, DIMENSIONS,
)

OPEN_FILE     = "suppression_open.json"
RESOLVED_FILE = "suppression_resolved.jsonl"
METRICS_FILE  = "suppression_metrics.json"

OUTCOME_CORRECT = "correct_suppression"
OUTCOME_FALSE   = "false_suppression"
OUTCOME_NEUTRAL = "neutral_suppression"
OUTCOME_EXPIRED = "expired_suppression"

MAX_OPEN_RECORDS = 12   # safety valve — one per (tool, direction) makes this ample


def _tp_r() -> float:
    try:
        return float(os.getenv("TAKE_PROFIT_R", "2.0"))
    except (TypeError, ValueError):
        return 2.0


# ── persistence (performance-root co-located; isolation inherited) ────────────

def _sym_dir(symbol: str, base_dir: "str | None" = None,
             create: bool = False) -> str:
    d = os.path.join(performance_root(base_dir), _norm_symbol(symbol))
    if create:                      # writers only — readers never create dirs
        os.makedirs(d, exist_ok=True)
    return d


def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_open_suppressions(symbol: str, base_dir: "str | None" = None) -> dict:
    return _load_json(os.path.join(_sym_dir(symbol, base_dir), OPEN_FILE))


def load_suppression_metrics(symbol: str, base_dir: "str | None" = None) -> dict:
    return _load_json(os.path.join(_sym_dir(symbol, base_dir), METRICS_FILE))


def get_suppression_stats(symbol: str, dimension: str, key,
                          base_dir: "str | None" = None) -> dict:
    """Read-only per-bucket suppression tallies (adaptive memory feed)."""
    table = load_suppression_metrics(symbol, base_dir).get(dimension) or {}
    b = table.get(_norm_key(key)) or {}
    total = int(b.get("suppressed_total", 0) or 0)
    correct = int(b.get("correct_suppressions", 0) or 0)
    false_ = int(b.get("false_suppressions", 0) or 0)
    scored = correct + false_
    return {
        "suppressed_total":      total,
        "correct_suppressions":  correct,
        "false_suppressions":    false_,
        "neutral_suppressions":  int(b.get("neutral_suppressions", 0) or 0),
        "expired_suppressions":  int(b.get("expired_suppressions", 0) or 0),
        "suppression_accuracy":  round(correct / scored, 4) if scored else None,
    }


# ── plan extraction (no synthetic values, ever) ───────────────────────────────

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _candidate_plan(snapshot: dict) -> "dict | None":
    """Entry/stop/direction from the preferred toolbox candidate (+ intent when
    present). Returns None unless a REAL plan exists."""
    s = snapshot or {}
    tb = s.get("toolbox") or {}
    pref = tb.get("preferred_tool")
    if not pref:
        return None
    cand = next((c for c in tb.get("tool_candidates") or []
                 if c.get("tool") == pref), None) or {}
    pl = cand.get("price_level") or {}

    direction = (s.get("decision_authority") or {}).get("direction")
    if direction not in ("bullish", "bearish"):
        if str(pref).startswith("bullish_"):
            direction = "bullish"
        elif str(pref).startswith("bearish_"):
            direction = "bearish"
        else:
            return None

    entry = pl.get("midpoint")
    if entry is None:
        entry = ((s.get("trade_intent") or {}).get("entry_zone") or {}).get("midpoint")
    stop = pl.get("invalidation_level")
    if stop is None:
        ez = (s.get("trade_intent") or {}).get("entry_zone") or {}
        stop = ez.get("zone_low") if direction == "bullish" else ez.get("zone_high")
    if not (_is_num(entry) and _is_num(stop)) or float(entry) == float(stop):
        return None

    entry, stop = float(entry), float(stop)
    risk = abs(entry - stop)
    target = entry + risk * _tp_r() if direction == "bullish" else entry - risk * _tp_r()
    return {"tool": pref, "direction": direction, "entry": entry, "stop": stop,
            "target": round(target, 4), "risk_points": round(risk, 4)}


def _opportunity_real(snapshot: dict) -> bool:
    s = snapshot or {}
    qual = ((s.get("qualification") or {}).get("status") or "").lower()
    decision = ((s.get("decision_authority") or {}).get("decision") or "").lower()
    intent = bool((s.get("trade_intent") or {}).get("intent_created"))
    return (intent
            or decision in ("ready_for_execution", "prepare_long", "prepare_short")
            or qual in ("candidate", "qualified", "elite"))


def _dims_from_snapshot(snapshot: dict) -> dict:
    s = snapshot or {}
    mr = s.get("market_regime") or {}
    return {
        "playbook":   (s.get("playbook") or {}).get("selected_playbook"),
        "tool":       (s.get("toolbox") or {}).get("preferred_tool"),
        "session":    s.get("session"),
        "regime":     mr.get("regime_family"),
        "volatility": mr.get("volatility_state"),
    }


def _last_candle(snapshot: dict) -> "dict | None":
    for tf in ("1m", "3m", "5m", "15m"):
        c = ((snapshot.get("timeframes") or {}).get(tf) or {}).get("last_candle")
        if isinstance(c, dict) and _is_num(c.get("high")) and _is_num(c.get("low")):
            return c
    return None


def _scan_date(snapshot: dict) -> str:
    ts = str((snapshot or {}).get("timestamp") or "")
    return ts[:10] if len(ts) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── scoring ───────────────────────────────────────────────────────────────────

def score_suppression(record: dict, outcome: str,
                      unrealized_r: "float | None" = None) -> dict:
    """Attach outcome + suppression_cost (R, from the organism's perspective:
    positive = the block cost us missed profit; negative = the block saved us)."""
    rec = dict(record or {})
    if outcome == OUTCOME_FALSE:
        cost = round(_tp_r(), 4)
    elif outcome == OUTCOME_CORRECT:
        cost = -1.0
    elif outcome == OUTCOME_NEUTRAL:
        cost = round(float(unrealized_r or 0.0), 4)
    else:
        cost = 0.0
    rec["shadow_outcome"] = outcome
    rec["suppression_cost"] = cost
    return rec


# ── metrics (PHASE 6 — adaptive memory feed, bucketed by the 5 dims) ─────────

_OUTCOME_FIELD = {
    OUTCOME_CORRECT: "correct_suppressions",
    OUTCOME_FALSE:   "false_suppressions",
    OUTCOME_NEUTRAL: "neutral_suppressions",
    OUTCOME_EXPIRED: "expired_suppressions",
}


def _fold_metrics(symbol: str, record: dict, outcome: str,
                  base_dir: "str | None" = None) -> None:
    path = os.path.join(_sym_dir(symbol, base_dir, create=True), METRICS_FILE)
    metrics = _load_json(path)
    for dim in DIMENSIONS:
        key = _norm_key((record.get("dimensions") or {}).get(dim))
        table = metrics.setdefault(dim, {})
        b = table.setdefault(key, {
            "suppressed_total": 0, "correct_suppressions": 0,
            "false_suppressions": 0, "neutral_suppressions": 0,
            "expired_suppressions": 0, "suppression_accuracy": None,
        })
        b["suppressed_total"] += 1
        b[_OUTCOME_FIELD[outcome]] += 1
        scored = b["correct_suppressions"] + b["false_suppressions"]
        b["suppression_accuracy"] = (
            round(b["correct_suppressions"] / scored, 4) if scored else None)
    _save_json(path, metrics)


# ── registration ──────────────────────────────────────────────────────────────

def register_blocked_candidate(snapshot: dict, symbol: str,
                               block_trace: list,
                               base_dir: "str | None" = None) -> dict:
    """Register (or refresh) the shadow record for a blocked real opportunity.
    One open record per (tool, direction). Never raises."""
    try:
        if not block_trace:
            return {"registered": False, "reason": "no_blocks"}
        pe_status = ((snapshot.get("paper_execution") or {}).get("status") or "").lower()
        if pe_status == "submitted":
            return {"registered": False, "reason": "trade_submitted"}
        if not _opportunity_real(snapshot):
            return {"registered": False, "reason": "no_real_opportunity"}
        plan = _candidate_plan(snapshot)
        if plan is None:
            return {"registered": False, "reason": "no_complete_price_plan"}

        sym = _norm_symbol(symbol)
        open_path = os.path.join(_sym_dir(sym, base_dir, create=True), OPEN_FILE)
        open_recs = _load_json(open_path)
        owners = sorted({str(b.get("layer")) for b in block_trace if b.get("layer")})
        reasons = [f"{b.get('layer')}: {b.get('reason')}" for b in block_trace][:6]
        dedup_key = f"{plan['tool']}|{plan['direction']}"

        for rec in open_recs.values():
            if rec.get("dedup_key") == dedup_key:
                rec["times_blocked"] = int(rec.get("times_blocked", 1)) + 1
                rec["block_owners"] = sorted(set(rec.get("block_owners", [])) | set(owners))
                _save_json(open_path, open_recs)
                return {"registered": False, "reason": "already_open",
                        "suppression_id": rec.get("suppression_id")}

        if len(open_recs) >= MAX_OPEN_RECORDS:
            return {"registered": False, "reason": "open_record_cap"}

        ts = str(snapshot.get("timestamp") or datetime.now(timezone.utc).isoformat())
        sid = f"SUP_{sym}_{ts.replace(':', '').replace('-', '')[:15]}_{plan['tool']}"
        rec = {
            "suppression_id":  sid,
            "symbol":          sym,
            "dedup_key":       dedup_key,
            "registered_at":   ts,
            "registered_date": _scan_date(snapshot),
            "direction":       plan["direction"],
            "entry":           plan["entry"],
            "stop":            plan["stop"],
            "target":          plan["target"],
            "risk_points":     plan["risk_points"],
            "tp_r":            _tp_r(),
            "block_owners":    owners,
            "block_reasons":   reasons,
            "confidence":      (snapshot.get("confidence_fusion") or {}).get("combined_confidence"),
            "dimensions":      _dims_from_snapshot(snapshot),
            "times_blocked":   1,
            "triggered":       False,
            "scans_tracked":   0,
            "mfe_r":           0.0,
            "mae_r":           0.0,
        }
        open_recs[sid] = rec
        _save_json(open_path, open_recs)
        return {"registered": True, "suppression_id": sid,
                "block_owners": owners}
    except Exception as exc:  # noqa: BLE001
        return {"registered": False, "reason": f"register_error:{type(exc).__name__}"}


# ── resolution ────────────────────────────────────────────────────────────────

def _shadow_step(rec: dict, candle: dict) -> "tuple[str | None, float]":
    """Advance one shadow record by one candle. Returns (outcome | None,
    unrealized_r). Conservative: stop beats target inside one candle."""
    hi, lo = float(candle["high"]), float(candle["low"])
    close = float(candle.get("close") or (hi + lo) / 2)
    entry, stop, target = rec["entry"], rec["stop"], rec["target"]
    risk = rec["risk_points"] or 1e-9
    long = rec["direction"] == "bullish"

    if not rec.get("triggered"):
        touched = (lo <= entry) if long else (hi >= entry)
        if not touched:
            return None, 0.0
        rec["triggered"] = True
        rec["triggered_at_scan"] = rec.get("scans_tracked")

    if long:
        stop_hit, target_hit = lo <= stop, hi >= target
        unreal = (close - entry) / risk
        rec["mfe_r"] = round(max(rec.get("mfe_r", 0.0), (hi - entry) / risk), 4)
        rec["mae_r"] = round(min(rec.get("mae_r", 0.0), (lo - entry) / risk), 4)
    else:
        stop_hit, target_hit = hi >= stop, lo <= target
        unreal = (entry - close) / risk
        rec["mfe_r"] = round(max(rec.get("mfe_r", 0.0), (entry - lo) / risk), 4)
        rec["mae_r"] = round(min(rec.get("mae_r", 0.0), (entry - hi) / risk), 4)

    if stop_hit:                     # conservative: stop wins ambiguous candles
        return OUTCOME_CORRECT, -1.0
    if target_hit:
        return OUTCOME_FALSE, rec.get("tp_r", _tp_r())
    return None, round(unreal, 4)


def resolve_shadow_outcome(snapshot: dict, symbol: str,
                           base_dir: "str | None" = None) -> list:
    """Advance all open shadow records against this scan's candle; settle
    outcomes; expire on session change. Returns resolved records. Never raises."""
    try:
        sym = _norm_symbol(symbol)
        d = _sym_dir(sym, base_dir, create=True)
        open_path = os.path.join(d, OPEN_FILE)
        open_recs = _load_json(open_path)
        if not open_recs:
            return []

        candle = _last_candle(snapshot)
        today = _scan_date(snapshot)
        resolved = []

        for sid in list(open_recs.keys()):
            rec = open_recs[sid]
            outcome = None
            unreal = 0.0

            if today != rec.get("registered_date"):
                # session ended — the live organism would be flat; settle honestly
                outcome = OUTCOME_NEUTRAL if rec.get("triggered") else OUTCOME_EXPIRED
                unreal = rec.get("last_unrealized_r", 0.0)
            elif candle is not None:
                rec["scans_tracked"] = int(rec.get("scans_tracked", 0)) + 1
                outcome, unreal = _shadow_step(rec, candle)
                if outcome is None:
                    rec["last_unrealized_r"] = unreal

            if outcome is not None:
                rec = score_suppression(rec, outcome, unrealized_r=unreal)
                rec["resolved_at"] = str(snapshot.get("timestamp") or today)
                rec["suppression_duration_scans"] = rec.get("scans_tracked", 0)
                _fold_metrics(sym, rec, outcome, base_dir)
                with open(os.path.join(d, RESOLVED_FILE), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, default=str) + "\n")
                resolved.append(rec)
                del open_recs[sid]

        _save_json(open_path, open_recs)
        return resolved
    except Exception:  # noqa: BLE001
        return []


# ── scan-loop entry point (the ONLY writer per the persist contract) ─────────

def track_suppression(snapshot: dict, symbol: str,
                      base_dir: "str | None" = None) -> dict:
    """One live-scan suppression cycle: resolve open records, then register the
    current blocked opportunity (if any). SHADOW ONLY. Never raises."""
    try:
        from live_scan.snapshot_store import build_block_trace
        resolved = resolve_shadow_outcome(snapshot, symbol, base_dir)
        block_trace = build_block_trace(snapshot)
        reg = register_blocked_candidate(snapshot, symbol, block_trace, base_dir)
        open_now = load_open_suppressions(symbol, base_dir)
        return {
            "authority_level": "observe_only",
            "registered":      bool(reg.get("registered")),
            "register_detail": reg,
            "resolved_this_scan": [
                {"suppression_id": r.get("suppression_id"),
                 "shadow_outcome": r.get("shadow_outcome"),
                 "suppression_cost": r.get("suppression_cost"),
                 "block_owners": r.get("block_owners"),
                 "duration_scans": r.get("suppression_duration_scans")}
                for r in resolved
            ],
            "open_count": len(open_now),
        }
    except Exception as exc:  # noqa: BLE001
        return {"authority_level": "observe_only", "registered": False,
                "register_detail": {"reason": f"track_error:{type(exc).__name__}"},
                "resolved_this_scan": [], "open_count": 0}

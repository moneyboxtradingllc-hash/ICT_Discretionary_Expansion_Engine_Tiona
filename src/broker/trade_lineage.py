"""The flight recorder: one immutable lineage per bot trade, plus the tape.

EVIDENCE-SUBSTRATE-PHASE0 (2026-08-08). CAPTURE ONLY.

PROD-20260807 produced 23 entry proposals, zero candidates, and no persisted
reason why. Establishing the cause took a day of archaeology across 171
artifacts. This module exists so that never happens to a trade.

    decision -> candidate -> order -> fill -> exit -> reconciled outcome

`ExecutionContext` already threads the ENTRY half of that chain honestly, and
its own docstring states the law: identity is threaded, never reconstructed from
price similarity or timestamp proximity. What has never been written down is the
other half -- how the trade ENDED -- and the link back to the two brains that
produced it.

Two capture gaps are closed here:

  LINEAGE   the join from mechanical proposal / Terra decision / hybrid envelope
            through candidate, order, fill, exit and realized outcome

  TAPE      the market bars AFTER each decision, per session. This is the only
            evidence on the roadmap that expires: a session traded without it can
            never be counterfactually scored, at any future date, by any effort.

NOTHING HERE IS READ BY ANY GATE. No function returns a permission, no caller
consults it before deciding, and every write swallows its own failure. A flight
recorder that can crash the aircraft is not a flight recorder.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

LINEAGE_SCHEMA = "trade_lineage.v1"
TAPE_SCHEMA = "session_tape.v1"

#: An exit whose cause the venue did not state. Recorded as unknown rather than
#: guessed -- "it closed near the target so it must have been a target fill" is
#: the same class of inference that once attributed a manual trade to the bot.
EXIT_UNKNOWN = "UNKNOWN"


def _root(session_id: str) -> str:
    from ai_retrieval.retrieval_telemetry import session_root
    return session_root(session_id or "UNSCOPED")


def _append(session_id: str, filename: str, record: dict) -> bool:
    """Append one JSON line. Never raises."""
    try:
        root = _root(session_id)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, filename), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True
    except Exception:  # noqa: BLE001 -- capture may never cost a trade
        return False


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── lineage ──────────────────────────────────────────────────────────────────
def open_lineage(*, session_id: str, execution_context, brain_result: dict = None,
                 shadow: dict = None, decision_trace: dict = None,
                 governor: dict = None) -> dict:
    """Record the ENTRY half at fill time, joined to both brains.

    `execution_context` is the already-threaded entry identity. Everything else
    is the reasoning that produced it -- captured now because months later there
    is no honest way to recover which thesis caused which order.
    """
    ctx = getattr(execution_context, "as_dict", lambda: dict(execution_context or {}))()
    parsed = ((brain_result or {}).get("parsed") or {})
    envelope = (shadow or {}).get("envelope") or {}
    proposal = envelope.get("mechanical_proposal") or {}
    review = envelope.get("terra_review") or {}

    record = {
        "schema_version": LINEAGE_SCHEMA,
        "session_id": session_id,
        "opened_at_utc": _now(),
        "state": "OPEN",

        # identity chain, entry half
        "snapshot_id": ctx.get("snapshot_id"),
        "candidate_id": ctx.get("candidate_id"),
        "candidate_fingerprint": ctx.get("candidate_fingerprint"),
        "mission_id": ctx.get("mission_id"),
        "contract_id": ctx.get("contract_id"),
        "direction": ctx.get("direction"),
        "quantity": ctx.get("quantity"),
        "entry_order_id": ctx.get("entry_order_id"),
        "entry_trade_id": ctx.get("entry_trade_id"),
        "entry_fill_price": ctx.get("entry_fill_price"),
        "stop_order_id": ctx.get("stop_order_id"),
        "target_order_id": ctx.get("target_order_id"),
        "structural_stop_price": ctx.get("structural_stop_price"),
        "liquidity_target_price": ctx.get("liquidity_target_price"),
        # PROTECTION-STATE-AUTHORITY-1. Both are kept because they answer
        # different questions: the invalidation is where the thesis was wrong,
        # the active stop is what the venue was holding at the end. R stays
        # denominated on the AUTHORED risk above -- an advanced stop must not
        # inflate the R of the trade that was actually taken.
        "original_thesis_invalidation": ctx.get("original_thesis_invalidation"),
        "active_protective_stop": ctx.get("active_protective_stop"),
        "protection_baseline_armed": bool(ctx.get("protection_baseline_armed")),

        # what the production Brain decided
        "production_direction": parsed.get("narrative_direction"),
        "production_action": str(parsed.get("current_action") or "")[:120],
        "production_objective_id": parsed.get("objective_id"),
        "production_invalidation_id": parsed.get("invalidation_id"),
        "production_model": (brain_result or {}).get("model"),

        # what the deterministic lane and its reviewer thought, same moment
        "mechanical_proposal_id": proposal.get("mechanical_proposal_id"),
        "mechanical_direction": proposal.get("direction"),
        "mechanical_objective_id": proposal.get("objective_id"),
        "mechanical_invalidation_id": proposal.get("invalidation_id"),
        "mechanical_reward_to_risk": proposal.get("reward_to_risk"),
        "hybrid_authority_mode": envelope.get("authority_mode"),
        "hybrid_disposition": envelope.get("hybrid_disposition"),
        "hybrid_would_have_done": (shadow or {}).get("would_have_done"),
        "terra_review_verdict": review.get("verdict"),
        "terra_review_confidence": review.get("confidence"),
        "terra_material_contradictions": review.get("material_contradictions"),

        # the doctrine in force when it was taken
        "reward_to_risk": (decision_trace or {}).get("reward_risk"),
        "reward_risk_floor": (decision_trace or {}).get("reward_risk_floor"),
        "legacy_floor_verdict": (decision_trace or {}).get("legacy_floor_verdict"),
        "eligible_only_because_floor_moved": (decision_trace or {}).get(
            "eligible_only_because_floor_moved"),
        "account_regime": (governor or {}).get("account_regime"),
        "profit_governor_result": (governor or {}).get("profit_governor_result"),
        "contracts_before_profit_governor": (governor or {}).get(
            "candidate_contracts_before_profit_governor"),
        "contracts_after_profit_governor": (governor or {}).get(
            "candidate_contracts_after_profit_governor"),

        # exit half, filled in by close_lineage
        "exit_reason": None, "exit_price": None, "exit_trade_id": None,
        "closed_at_utc": None, "realized_pnl_usd": None, "realized_r": None,
        "mfe_points": None, "mae_points": None,
        "time_in_trade_seconds": None, "reconciled": False,
    }
    record["lineage_write_ok"] = _append(session_id, "trade_lineage.jsonl", record)
    return record


def close_lineage(*, session_id: str, lineage: dict, exit_price=None,
                  exit_reason: str = None, exit_trade_id=None,
                  realized_pnl_usd=None, mfe_points=None, mae_points=None,
                  reconciled: bool = False) -> dict:
    """Record the EXIT half. Appended, never overwriting the OPEN row.

    Both halves survive as separate immutable lines. Rewriting the open record
    in place would destroy the evidence that the trade was open at all, and the
    difference between the two is itself data.
    """
    closed = dict(lineage or {})
    closed.update({
        "state": "CLOSED",
        "closed_at_utc": _now(),
        "exit_price": exit_price,
        "exit_reason": exit_reason or EXIT_UNKNOWN,
        "exit_trade_id": exit_trade_id,
        "realized_pnl_usd": realized_pnl_usd,
        "mfe_points": mfe_points,
        "mae_points": mae_points,
        "reconciled": bool(reconciled),
    })
    closed["realized_r"] = realized_r(closed)
    closed["time_in_trade_seconds"] = _elapsed(lineage.get("opened_at_utc"),
                                               closed["closed_at_utc"])
    closed["lineage_write_ok"] = _append(session_id, "trade_lineage.jsonl", closed)
    return closed


def realized_r(record: dict):
    """R measured against the ORIGINAL structural risk, in points.

    Deliberately not derived from dollars: contract count varies (the profit
    governor may size a Combine trade down), and R must describe the trade, not
    the position size. Returns None rather than guessing when the geometry is
    incomplete.
    """
    try:
        entry = float(record.get("entry_fill_price"))
        stop = float(record.get("structural_stop_price"))
        exit_price = float(record.get("exit_price"))
    except (TypeError, ValueError):
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    direction = str(record.get("direction") or "").lower()
    moved = (exit_price - entry) if direction in ("long", "bullish", "buy") \
        else (entry - exit_price)
    return round(moved / risk, 3)


def _elapsed(start_iso, end_iso):
    try:
        start = _dt.datetime.fromisoformat(str(start_iso).replace("Z", "+00:00"))
        end = _dt.datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
        return round((end - start).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


def load_lineage(session_id: str) -> list:
    """Every lineage row for a session, in write order."""
    path = os.path.join(_root(session_id), "trade_lineage.jsonl")
    try:
        return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def reconcile_lineage(session_id: str) -> dict:
    """Does every opened trade have a close? Accounting, not storytelling."""
    rows = load_lineage(session_id)
    opened = [r for r in rows if r.get("state") == "OPEN"]
    closed = [r for r in rows if r.get("state") == "CLOSED"]
    closed_ids = {r.get("candidate_id") for r in closed}
    dangling = [r.get("candidate_id") for r in opened
                if r.get("candidate_id") not in closed_ids]
    return {"opened": len(opened), "closed": len(closed),
            "unclosed_candidates": dangling,
            "status": "RECONCILED" if not dangling else "LINEAGE_INCOMPLETE"}


# ── tape ─────────────────────────────────────────────────────────────────────
def archive_tape(*, session_id: str, contract_id: str, bars: list,
                 decision_timestamps: list = None) -> dict:
    """Persist the session's bars so the future can be scored.

    The rolling collector file holds a few days and is overwritten; a session
    archive is written once and kept. Without it, `did the target trade before
    the stop?` becomes permanently unanswerable for that session -- and unlike
    every other gap on the roadmap, no later work can recover it.

    Never raises.
    """
    record = {
        "schema_version": TAPE_SCHEMA,
        "session_id": session_id,
        "contract_id": contract_id,
        "archived_at_utc": _now(),
        "bar_count": len(bars or []),
        "first_bar": (bars or [{}])[0].get("timestamp") if bars else None,
        "last_bar": (bars or [{}])[-1].get("timestamp") if bars else None,
        "decision_timestamps": list(decision_timestamps or []),
        "purpose": ("counterfactual scoring: target-first vs stop-first, MFE, "
                    "MAE, and the forward path after a refusal"),
    }
    try:
        root = _root(session_id)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "session_tape.jsonl"), "w",
                  encoding="utf-8") as fh:
            for bar in bars or []:
                fh.write(json.dumps(bar, default=str) + "\n")
        with open(os.path.join(root, "session_tape_manifest.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, default=str)
        record["tape_write_ok"] = True
    except Exception as exc:  # noqa: BLE001
        record["tape_write_ok"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def tape_covers(*, session_id: str, after_timestamp: str) -> dict:
    """Is there enough forward tape to score a decision made at this time?"""
    path = os.path.join(_root(session_id), "session_tape.jsonl")
    try:
        bars = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except (OSError, json.JSONDecodeError):
        return {"scoreable": False, "reason": "no session tape archived",
                "bars_after": 0}
    after = [b for b in bars if str(b.get("timestamp") or "") > str(after_timestamp)]
    return {"scoreable": bool(after), "bars_after": len(after),
            "reason": None if after else "no bars after the decision"}

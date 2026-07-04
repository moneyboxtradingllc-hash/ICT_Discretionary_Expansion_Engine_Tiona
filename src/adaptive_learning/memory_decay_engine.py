"""
MEM-DECAY-1 — Memory Decay Engine (scar forgiveness / adaptive rehabilitation).

Closes the streak-4 deadlock: a loss-streak soft veto used to be permanent,
because the veto prevented the only reset event (a win in the vetoed bucket).
The organism must remember pain — and learn how to heal.

Per-bucket scar STATE MACHINE, persisted at
data/performance/<SYMBOL>/scar_state.json (co-located with the tables, so it
inherits PERFORMANCE_TABLES_DIR isolation):

    healthy  ── streak >= threshold ──▶ scarred (cooldown: absolute veto)
    scarred  ── COOLDOWN clean sessions observed ──▶ probation
    probation ── matching WIN closes (table streak resets) ──▶ reopened
    probation ── matching LOSS closes (streak rises) ──▶ scarred again
                 (lock_count += 1; cooldown doubles: 2 -> 4 -> 8, capped)
    probation ── breakeven ──▶ probation continues (still defensive)

DOCTRINE:
  * Decay can only SOFTEN — never amplify, never boost, never approve.
  * A cooldown "clean session" counts ONLY when the bucket is evaluated as a
    live candidate match on a NEW date with no new matching loss — healing
    advances only when real suppressed opportunities recur (time decay x
    opportunity decay combined).
  * Probation reopens DEFENSIVELY: the caller (adaptive policy) converts the
    hard block into the existing confidence-penalty + risk-reduction actuators
    (mutation halves size, -10% confidence) — no new risk math.
  * Scars are never erased: every lock / probation / re-lock / reopen event is
    appended to the record's history. Reopened records persist.
  * Never raises: any internal failure returns the SAFE verdict (keep the
    block) so a decay bug can never open a vetoed bucket.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from adaptive_learning.performance_tables import performance_root, _norm_symbol, _norm_key

SCAR_STATE_FILE = "scar_state.json"

COOLDOWN_SESSIONS_BASE = 2     # clean sessions required before first probation
COOLDOWN_CAP           = 8     # re-lock cooldown ceiling (2 -> 4 -> 8 -> 8 ...)

STATUS_HEALTHY   = "healthy"
STATUS_SCARRED   = "scarred"
STATUS_COOLDOWN  = "cooldown"    # alias reported while scarred and counting
STATUS_PROBATION = "probation"
STATUS_REOPENED  = "reopened"

AUTHORITY_NOTE = "decay_can_only_soften"


# ── persistence ───────────────────────────────────────────────────────────────

def _state_path(symbol: str, base_dir: "str | None" = None,
                create: bool = False) -> str:
    d = os.path.join(performance_root(base_dir), _norm_symbol(symbol))
    if create:                      # writers only — readers never create dirs
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, SCAR_STATE_FILE)


def _load_state(symbol: str, base_dir: "str | None" = None) -> dict:
    try:
        with open(_state_path(symbol, base_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_state(symbol: str, state: dict, base_dir: "str | None" = None) -> None:
    path = _state_path(symbol, base_dir, create=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_scar_state(symbol: str, base_dir: "str | None" = None) -> dict:
    """Read-only view of the full scar state (forensics / audits)."""
    return _load_state(symbol, base_dir)


# ── helpers ───────────────────────────────────────────────────────────────────

def _today(today) -> str:
    if today:
        return str(today)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cooldown_required(lock_count: int) -> int:
    return min(COOLDOWN_SESSIONS_BASE * (2 ** max(0, lock_count - 1)), COOLDOWN_CAP)


def _event(rec: dict, event: str, on: str, **extra) -> None:
    rec.setdefault("history", []).append({"event": event, "on": on, **extra})


def _verdict(status: str, *, block: bool, probation: bool, raw_streak: int,
             clean: int, required: int, lock_count: int, reason: str) -> dict:
    return {
        "decay_status":         status,
        "block_recommended":    bool(block),
        "probation":            bool(probation),
        "raw_loss_streak":      int(raw_streak),
        "decayed_loss_streak":  max(0, int(raw_streak) - int(clean)),
        "scar_age_sessions":    int(clean),
        "cooldown_required":    int(required),
        "lock_count":           int(lock_count),
        "rehabilitation_reason": reason,
        "authority_note":       AUTHORITY_NOTE,
    }


_HEALTHY = {
    "decay_status": STATUS_HEALTHY, "block_recommended": False,
    "probation": False, "raw_loss_streak": 0, "decayed_loss_streak": 0,
    "scar_age_sessions": 0, "cooldown_required": 0, "lock_count": 0,
    "rehabilitation_reason": "no scar", "authority_note": AUTHORITY_NOTE,
}


# ── public entry point ────────────────────────────────────────────────────────

def evaluate_bucket_decay(symbol: str, dimension: str, key, bucket: dict,
                          block_threshold: int = 4,
                          today: "str | None" = None,
                          base_dir: "str | None" = None,
                          persist: bool = True) -> dict:
    """Evaluate (and advance) the scar state for one bucket. Called by the
    adaptive policy engine for every candidate-matching bucket each scan.

    PERSIST CONTRACT (MEM-DECAY-1): only the owning live-scan call may advance
    stored scar state (persist=True — the snapshot_builder policy pass).
    Observability callers (the Brain's adaptive-context view, tests, tools)
    pass persist=False and receive the identical verdict as a pure read of
    stored state — they can never mutate adaptive memory.

    Returns the decay verdict (see _verdict). SAFE on any failure: a bucket at
    or above the block threshold keeps its block if anything goes wrong —
    decay can only soften, and only deliberately."""
    raw_streak = int((bucket or {}).get("loss_streak", 0) or 0)
    trades = int((bucket or {}).get("trades", 0) or 0)
    try:
        sym = _norm_symbol(symbol)
        skey = f"{dimension}:{_norm_key(key)}"
        day = _today(today)
        state = _load_state(sym, base_dir)
        rec = state.get(skey)

        # ── below threshold ───────────────────────────────────────────────
        if raw_streak < block_threshold:
            if rec and rec.get("status") in (STATUS_SCARRED, STATUS_PROBATION):
                # only a WIN resets the table streak → rehabilitation complete
                rec["status"] = STATUS_REOPENED
                rec["raw_streak_last_seen"] = raw_streak
                rec["trades_last_seen"] = trades
                _event(rec, "reopened", day, via="win_reset_streak")
                state[skey] = rec
                if persist:
                    _save_state(sym, state, base_dir)
            if rec:
                return _verdict(STATUS_REOPENED if rec.get("status") == STATUS_REOPENED
                                else STATUS_HEALTHY,
                                block=False, probation=False, raw_streak=raw_streak,
                                clean=0, required=0,
                                lock_count=int(rec.get("lock_count", 0)),
                                reason="bucket healthy (scar history retained)")
            return dict(_HEALTHY)

        # ── at/above threshold ────────────────────────────────────────────
        if rec is None:
            rec = {
                "status": STATUS_SCARRED,
                "locked_on": day,
                "lock_count": 1,
                "streak_at_lock": raw_streak,
                "raw_streak_last_seen": raw_streak,
                "trades_last_seen": trades,
                "clean_sessions": [],
                "cooldown_required": _cooldown_required(1),
                "probation_granted_on": None,
                "history": [],
            }
            _event(rec, "locked", day, streak=raw_streak)
            state[skey] = rec
            if persist:
                _save_state(sym, state, base_dir)
            return _verdict(STATUS_SCARRED, block=True, probation=False,
                            raw_streak=raw_streak, clean=0,
                            required=rec["cooldown_required"], lock_count=1,
                            reason=f"locked today: loss_streak {raw_streak} >= {block_threshold}")

        last_streak = int(rec.get("raw_streak_last_seen", raw_streak) or 0)
        lock_count = int(rec.get("lock_count", 1) or 1)

        # new matching LOSS since last look (probation loss, or external fold)
        if raw_streak > last_streak or rec.get("status") == STATUS_REOPENED:
            lock_count += 1
            rec.update({
                "status": STATUS_SCARRED,
                "lock_count": lock_count,
                "locked_on": day,
                "clean_sessions": [],
                "cooldown_required": _cooldown_required(lock_count),
                "probation_granted_on": None,
            })
            _event(rec, "relocked", day, streak=raw_streak, lock_count=lock_count)
            rec["raw_streak_last_seen"] = raw_streak
            rec["trades_last_seen"] = trades
            state[skey] = rec
            if persist:
                _save_state(sym, state, base_dir)
            return _verdict(STATUS_SCARRED, block=True, probation=False,
                            raw_streak=raw_streak, clean=0,
                            required=rec["cooldown_required"], lock_count=lock_count,
                            reason=f"re-locked: new matching loss (lock #{lock_count}, "
                                   f"cooldown {rec['cooldown_required']} clean sessions)")

        # probation in force (streak unchanged: no outcome yet, or breakeven)
        if rec.get("status") == STATUS_PROBATION:
            if trades > int(rec.get("trades_last_seen", trades) or 0):
                _event(rec, "probation_breakeven", day)
            rec["raw_streak_last_seen"] = raw_streak
            rec["trades_last_seen"] = trades
            state[skey] = rec
            if persist:
                _save_state(sym, state, base_dir)
            clean = len(rec.get("clean_sessions", []))
            return _verdict(STATUS_PROBATION, block=False, probation=True,
                            raw_streak=raw_streak, clean=clean,
                            required=int(rec.get("cooldown_required", 0)),
                            lock_count=lock_count,
                            reason="probation: defensive test trade allowed "
                                   "(reduced size + reduced confidence)")

        # scarred: count today as a clean session (new date, no new loss)
        clean_sessions = list(rec.get("clean_sessions", []))
        if day != rec.get("locked_on") and day not in clean_sessions:
            clean_sessions.append(day)
            rec["clean_sessions"] = clean_sessions
            _event(rec, "clean_session", day, count=len(clean_sessions))
        required = int(rec.get("cooldown_required",
                                _cooldown_required(lock_count)) or 0)

        if len(clean_sessions) >= required:
            rec["status"] = STATUS_PROBATION
            rec["probation_granted_on"] = day
            _event(rec, "probation_granted", day,
                   clean_sessions=len(clean_sessions), required=required)
            rec["raw_streak_last_seen"] = raw_streak
            rec["trades_last_seen"] = trades
            state[skey] = rec
            if persist:
                _save_state(sym, state, base_dir)
            return _verdict(STATUS_PROBATION, block=False, probation=True,
                            raw_streak=raw_streak, clean=len(clean_sessions),
                            required=required, lock_count=lock_count,
                            reason=f"cooldown served ({len(clean_sessions)}/{required} "
                                   "clean sessions) -> probation granted")

        rec["raw_streak_last_seen"] = raw_streak
        rec["trades_last_seen"] = trades
        state[skey] = rec
        if persist:
            _save_state(sym, state, base_dir)
        return _verdict(STATUS_COOLDOWN, block=True, probation=False,
                        raw_streak=raw_streak, clean=len(clean_sessions),
                        required=required, lock_count=lock_count,
                        reason=f"cooldown: {len(clean_sessions)}/{required} "
                               "clean sessions observed")
    except Exception as exc:  # noqa: BLE001
        # SAFE verdict: keep the block when at/over threshold; never open on error
        blocked = raw_streak >= block_threshold
        return _verdict(STATUS_SCARRED if blocked else STATUS_HEALTHY,
                        block=blocked, probation=False, raw_streak=raw_streak,
                        clean=0, required=COOLDOWN_SESSIONS_BASE, lock_count=1,
                        reason=f"decay_error:{type(exc).__name__} (safe verdict)")

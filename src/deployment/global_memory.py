"""DEPLOY-1 Phase 4 — Global vs Instance memory boundary.

GLOBAL memory holds ONLY broad, account-agnostic market lessons that are safe to
share across every instance (e.g. "high-impact news raises whipsaw risk"). It
must NEVER hold trade history, account outcomes, stance history, vector analogs,
or any per-instance learning — those live in instance memory (redirected by
InstanceContext into the instance folder).

This module is the explicit, separate home for global lessons so instance memory
and global memory can never be confused. Append-only JSONL; never raises.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from deployment.instance_context import GLOBAL_MEMORY_DIR

# fields that must NEVER appear in a global lesson (they are instance-scoped)
_FORBIDDEN_KEYS = {
    "trade_id", "account_id", "instance_id", "pnl", "realized_r",
    "stance_history", "position", "vector_analog", "outcome",
}


def _store() -> str:
    return os.path.join(GLOBAL_MEMORY_DIR, "global_lessons.jsonl")


def record_lesson(lesson: str, tags: "list | None" = None,
                  extra: "dict | None" = None) -> bool:
    """Store a broad market lesson. Rejects instance-scoped payloads. Never raises."""
    try:
        extra = extra or {}
        if any(k in extra for k in _FORBIDDEN_KEYS):
            return False   # guard: instance-scoped data may not enter global memory
        rec = {"lesson": lesson, "tags": tags or [],
               "recorded_at": datetime.now(timezone.utc).isoformat(), **extra}
        os.makedirs(GLOBAL_MEMORY_DIR, exist_ok=True)
        with open(_store(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def all_lessons() -> list:
    try:
        if not os.path.exists(_store()):
            return []
        with open(_store(), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:  # noqa: BLE001
        return []

"""Durable, session-scoped stop for paid trading cognition.

Only a proven terminal governor CONTAMINATED result creates this lock.  It is
keyed by the authorized session and bound to account/contract identity.  There
is intentionally no "flat clears lock" operation; a new authorization/session
gets a different record path under the existing session-boundary law.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile


SCHEMA = "session_cognition_lock.v1"
CONTAMINATED = "CONTAMINATED"


def lock_path(store_dir: str, session_id: str) -> str:
    return os.path.join(store_dir, f"session_cognition_lock_{session_id}.json")


def _read(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            row = json.load(fh)
        if not isinstance(row, dict):
            raise ValueError("terminal lock is not an object")
        return row
    except Exception as exc:  # noqa: BLE001 -- unreadable terminal state fails closed
        return {"schema": SCHEMA, "terminal": True,
                "state": "TERMINAL_STATE_UNTRUSTED",
                "reason": f"terminal_lock_unreadable:{type(exc).__name__}"}


def load(*, store_dir: str, session_id: str, account_fingerprint: str,
         contract_id: str):
    """Load this exact session's cognition lock; mismatched existing identity
    remains fail-closed instead of silently granting a different account access.
    """
    row = _read(lock_path(store_dir, session_id))
    if row is None:
        return None
    if (row.get("schema") != SCHEMA
            or row.get("session_id") != str(session_id)
            or row.get("account_fingerprint") != str(account_fingerprint)
            or row.get("contract_id") != str(contract_id)
            or row.get("state") != CONTAMINATED):
        return {"schema": SCHEMA, "terminal": True,
                "state": "TERMINAL_STATE_UNTRUSTED",
                "session_id": str(session_id),
                "reason": "terminal_lock_identity_or_schema_mismatch"}
    return dict(row, terminal=True)


def record_contaminated(*, store_dir: str, session_id: str,
                        account_fingerprint: str, contract_id: str,
                        reason: str, observed_at: str = None) -> dict:
    """Atomically record the first terminal contamination reason for a session."""
    os.makedirs(store_dir, exist_ok=True)
    path = lock_path(store_dir, session_id)
    current = load(store_dir=store_dir, session_id=session_id,
                   account_fingerprint=account_fingerprint,
                   contract_id=contract_id)
    if current is not None:
        return current
    row = {
        "schema": SCHEMA,
        "terminal": True,
        "state": CONTAMINATED,
        "reason": str(reason or "unattributable_in_session_trade"),
        "session_id": str(session_id),
        "account_fingerprint": str(account_fingerprint),
        "contract_id": str(contract_id),
        "recorded_at_utc": str(observed_at or datetime.now(timezone.utc).isoformat()),
        "cognition": "OFF",
        "safety_reconciliation": "CONTINUES",
    }
    fd, tmp = tempfile.mkstemp(dir=store_dir, prefix=".session-cognition-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(row, fh, sort_keys=True, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    verified = load(store_dir=store_dir, session_id=session_id,
                    account_fingerprint=account_fingerprint,
                    contract_id=contract_id)
    if verified is None or verified.get("state") != CONTAMINATED:
        raise OSError("terminal cognition lock did not verify after write")
    return verified

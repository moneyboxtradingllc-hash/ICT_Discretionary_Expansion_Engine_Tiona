"""
DEPLOY-2D — Topstep entry-context store (per-instance, runtime state).

Topstep's Trade/search gives realized PnL but NOT the entry-time market state the
adaptive scar embedding needs (regime/session/narrative). So when TopstepRuntime
places a bracket entry, it journals a small entry-context record here, keyed by
contractId + entry_timestamp. At reconciliation the closed trade is matched back
to its entry context to assemble a complete scar.

This is NOT the Alpaca paper journal — it is a separate, Topstep-only file. Plain
append-only JSONL; never raises. Path is instance-isolated via TOPSTEP_STATE_DIR
(falls back to data/topstep) so Maurice's data is never touched.
"""
import json
import os


def _path() -> str:
    base = os.getenv("TOPSTEP_STATE_DIR") or os.path.join("data", "topstep")
    return os.path.join(base, "entry_context.jsonl")


def record_entry(ctx: dict) -> bool:
    """Append one entry-context record. Never raises."""
    try:
        p = _path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ctx, default=str) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def load_entries() -> list:
    """Load all entry-context records. Never raises."""
    p = _path()
    out = []
    try:
        if not os.path.exists(p):
            return out
        with open(p, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return out
    return out


def mark_reconciled(entry_key: str) -> bool:
    """DEPLOY-2D.1 — settlement lifecycle state. Mark the entry with this
    entry_key as reconciled so a settled round-trip is never re-scarred. Rewrites
    the store atomically. Returns True if a record was updated. Never raises."""
    if not entry_key:
        return False
    try:
        entries = load_entries()
        changed = False
        for e in entries:
            if e.get("entry_key") == entry_key and not e.get("reconciled"):
                e["reconciled"] = True
                changed = True
        if not changed:
            return False
        p = _path()
        tmp = p + ".tmp"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e, default=str) + "\n")
        os.replace(tmp, p)
        return True
    except Exception:  # noqa: BLE001
        return False

"""BREAK-EVEN-2C — the durable effect journal. Crash-safe exactly-once EFFECT.

WHAT WAS MISSING. `break_even_actuator` classified an accepted-but-unproven
modify correctly (`AMBIGUOUS`, `retryable=False`) and the production owner
recorded it in `self.last_management` -- RAM. So the flag was ADVISORY and
nothing enforced it. Measured on the real production call path before this
module existed:

    tick 1  accepted, effect not visible   -> 1 modify sent
    tick 2  same unresolved state          -> 2 modifies sent
    ticks 3-5                              -> 5 modifies sent
    cold restart                           -> sends again, knows nothing

Five money-moving writes for one intended effect, and on a 60s management loop
roughly 180 across a session. `retryable=False` cannot bind a decision that no
durable record survives to make.

THE LAW THIS ADDS: **durable intent before the mutation, and an unresolved
latch after it.** Modelled on the entry-submission ledger, which already solved
this shape for order submission -- intent, response, reconciliation, appended
and fsynced. This is the same three-phase write-ahead for a STOP AMENDMENT, in
its own file so mutable venue-effect state never contaminates the immutable
initial-R baseline.

VENUE TRUTH STILL OUTRANKS THE JOURNAL. The journal decides whether we may
WRITE; it never decides what protection IS. A recovered unresolved effect forces
reconciliation first -- and reconciliation may well discover the effect landed,
which resolves it with no second mutation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone

SCHEMA = "break_even_effect.v1"

# ── lifecycle of ONE intended advancement ───────────────────────────────────
ELIGIBLE = "BE_ELIGIBLE"
INTENT = "BE_MODIFY_INTENT"
ACCEPTED = "BE_MODIFY_ACCEPTED"
EXPLICITLY_REJECTED = "BE_MODIFY_EXPLICITLY_REJECTED"
TRANSPORT_AMBIGUOUS = "BE_MODIFY_TRANSPORT_AMBIGUOUS"
READBACK_APPLIED = "BE_READBACK_APPLIED"
READBACK_UNPROVEN = "BE_READBACK_UNPROVEN"
HELD_ALREADY = "BE_HELD_ALREADY_AT_OR_BETTER"
POSITION_FLAT = "BE_POSITION_FLAT"
PROTECTION_DEFECT = "BE_PROTECTION_DEFECT"

#: Nothing further may be attempted for this effect identity.
TERMINAL = frozenset({READBACK_APPLIED, EXPLICITLY_REJECTED, HELD_ALREADY,
                      POSITION_FLAT, PROTECTION_DEFECT})
#: The venue may or may not hold the effect. A WRITE IS FORBIDDEN until fresh
#: venue truth resolves it.
UNRESOLVED = frozenset({INTENT, ACCEPTED, TRANSPORT_AMBIGUOUS, READBACK_UNPROVEN})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def journal_path(store_dir: str, session_id: str) -> str:
    return os.path.join(store_dir, f"break_even_effects_{session_id}.jsonl")


def effect_id(*, mission_id, contract_id, entry_order_id, stop_order_id,
              proposed_stop, account_fingerprint="", effect_kind="break_even") -> str:
    """Stable identity for ONE intended advancement.

    Deliberately NOT time-based: two processes reconstructing the same desired
    effect after a restart must derive the SAME id, or the latch cannot
    recognise its own unresolved write. Price is rounded to four places so a
    float re-read from JSON cannot mint a second identity for one intention.
    """
    try:
        px = round(float(proposed_stop), 4)
    except (TypeError, ValueError):
        px = proposed_stop
    kind = str(effect_kind or "break_even")
    basis = json.dumps({"mission_id": str(mission_id or ""),
                        "account": str(account_fingerprint or ""),
                        "contract_id": str(contract_id or ""),
                        "entry_order_id": str(entry_order_id or ""),
                        "stop_order_id": str(stop_order_id or ""),
                        "proposed_stop": px,
                        # Preserve the historical BE identity byte-for-byte;
                        # non-BE protection effects must not share its latch.
                        **({} if kind == "break_even" else {"effect_kind": kind})},
                       sort_keys=True)
    prefix = "be" if kind == "break_even" else "trail"
    return prefix + ":" + hashlib.sha256(basis.encode()).hexdigest()[:16]


def record(*, store_dir, session_id, effect_id, state, **evidence) -> bool:
    """Append one durable event. Returns False if it did NOT reach disk.

    The boolean is load-bearing: the write-ahead law says a mutation may only
    follow a PERSISTED intent, so the caller must be able to tell "recorded"
    from "tried to record". fsync for the same reason the submission ledger
    does it -- an intent still in a page cache does not survive the crash it
    exists to survive.
    """
    row = dict({"schema": SCHEMA, "at": _now(), "session_id": session_id,
                "effect_id": effect_id, "state": state}, **evidence)
    try:
        path = journal_path(store_dir, session_id)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except Exception:  # noqa: BLE001 — a journal failure is never an exception
        return False


def load(store_dir: str, session_id: str, effect_id: str = None) -> list:
    """Every recorded event, oldest first. A missing journal is simply empty."""
    rows = []
    try:
        with open(journal_path(store_dir, session_id), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 — a torn line is not authority
                    continue
                if effect_id is None or row.get("effect_id") == effect_id:
                    rows.append(row)
    except OSError:
        return []
    return rows


def latest_state(store_dir: str, session_id: str, effect_id: str) -> str:
    rows = load(store_dir, session_id, effect_id)
    return rows[-1].get("state") if rows else None


def is_unresolved(store_dir: str, session_id: str, effect_id: str) -> bool:
    """Is a previous attempt at THIS effect still epistemically open?

    Only the LATEST state counts: an effect that went INTENT -> ACCEPTED ->
    READBACK_APPLIED is resolved, and the earlier unresolved rows are history.
    """
    return latest_state(store_dir, session_id, effect_id) in UNRESOLVED


_IDENTITY_FIELDS = ("mission_id", "proposed_stop", "management_kind",
                    "contract_id", "entry_order_id", "stop_order_id")


def _identity_value_valid(field, value) -> bool:
    if value is None:
        return False
    if field == "proposed_stop":
        if isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
    return bool(str(value).strip())


def _with_recovered_identity(rows: list, effect_id: str) -> dict:
    """Return the latest state while retaining immutable intent evidence.

    Older journals recorded identity only on INTENT. Later state rows are
    allowed to contain only the actuator result, so selecting the latest row
    must not erase the fields needed to attribute an unresolved effect.
    Conflicting immutable values are marked incomplete rather than guessed.
    """
    latest = dict(rows[-1])
    values = {}
    conflicts = []
    for field in _IDENTITY_FIELDS:
        observed = [row.get(field) for row in rows
                    if _identity_value_valid(field, row.get(field))]
        if observed:
            first = observed[0]
            if any(value != first for value in observed[1:]):
                conflicts.append(field)
            else:
                values[field] = first
        elif field == "management_kind":
            prefix = str(effect_id).split(":", 1)[0]
            values[field] = "trailing" if prefix == "trail" else "break_even"
    for field, value in values.items():
        if not _identity_value_valid(field, latest.get(field)):
            latest[field] = value
    latest["effect_id"] = effect_id
    latest["identity_conflicts"] = conflicts
    latest["identity_complete"] = (
        not conflicts
        and _identity_value_valid("mission_id", latest.get("mission_id"))
        and _identity_value_valid("proposed_stop", latest.get("proposed_stop"))
        and _identity_value_valid("management_kind", latest.get("management_kind")))
    return latest


def unresolved_effects(store_dir: str, session_id: str) -> list:
    """Every unresolved effect, with immutable identity folded from history."""
    history = {}
    for row in load(store_dir, session_id):
        eid = row.get("effect_id")
        if eid:
            history.setdefault(eid, []).append(row)
    unresolved = []
    for eid, rows in history.items():
        if rows[-1].get("state") in UNRESOLVED:
            unresolved.append(_with_recovered_identity(rows, eid))
    return unresolved

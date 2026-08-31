"""Restoring a trade allowance spent by an internal failure, without lying.

PROD-20260810. Scan 2 produced a legitimate candidate with a 33.75-point stop.
The execution token had been minted with the smoke stop ceiling (10.00), so the
runner refused its own token -- but `on_attempt_consumed` fires BEFORE the token
is validated, deliberately, for crash safety. One of two authorized session
trades was therefore spent on a binding error that never reached Topstep:

    orders placed 0 · fills 0 · position flat · token invalidated, not burned

The doctrine grants two BOT TRADES. It does not grant two internal pre-venue
failures. So the allowance should be restorable. The question is how to restore
it without corrupting the evidence.

    NOT by editing the mission file. `trade_mission_PROD-20260810_1.json` is the
    only durable proof the failure happened. A system that rewrites its own
    history to make a session look clean is exactly the system that later cannot
    explain a loss. It stays byte-for-byte as written.

Instead the void is a SEPARATE, ADDITIVE artifact -- a ledger naming the mission
it excuses, why, and the venue evidence at the time. Both records survive, and
the disagreement between them is legible.

Three properties make this safe to have in the codebase at all:

  RE-VERIFIED   A ledger entry is not trusted. Every load re-reads the mission
                and re-proves it never reached the venue. A void whose mission
                no longer verifies is IGNORED and the trade counts again --
                the failure direction is always "you have fewer trades left."

  NARROW        Only ATTEMPT_CONSUMED with no order id, no spent token and a
                flat position may be voided. SUBMIT_UNKNOWN, POSITION_OPEN and
                COMPLETE are permanently unvoidable: if the venue may have seen
                it, the trade was real, whatever the outcome.

  BOUNDED       Two voids per session, maximum. Capacity restoration must not
                become a retry loop; a bug that aborts repeatedly should run out
                of session, not grind through the account.

The slot is never reused either -- the next mission opens at the next free
index, so voiding mission 1 produces mission 2 beside it, not on top of it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from broker import topstepx_mission_state as MS
from broker import topstepx_submission_record as SUB

VOID_SCHEMA = "mission_void.v1"

#: The only recognised void class: the bot's own machinery refused the trade
#: before any request left this process.
INFRASTRUCTURE_ABORT = "INFRASTRUCTURE_ABORT"
VOID_CLASSES = frozenset({INFRASTRUCTURE_ABORT})

#: Ceiling on restored capacity per session. Not a tuning knob.
MAX_VOIDED_MISSIONS_PER_SESSION = 2

#: The operator must type this. A void is a human judgement about doctrine, not
#: something a loop may decide about itself mid-session.
VOID_PHRASE = "VOID THIS MISSION AS INFRASTRUCTURE ABORT"


class VoidRefused(RuntimeError):
    """The mission may not be voided. Always fail toward fewer trades."""


def void_ledger_path(store_dir: str, session_id: str) -> str:
    return os.path.join(store_dir, f"mission_voids_{session_id}.json")


def submission_evidence_for(store_dir: str, session_id: str, mission_id: str,
                            token_id: str = "") -> dict:
    """What the submission ledger knows about this mission's requests.

    `token_id` is the strongest join available -- minted per attempt and carried
    into the venue's own customTag -- so pass it whenever the mission has one.
    """
    return SUB.mission_venue_evidence(store_dir, session_id, mission_id,
                                      token_id=token_id)


# ── the mechanical proof ──────────────────────────────────────────────────────
#: Sentinel meaning "nobody looked at the submission ledger". Distinct from an
#: empty ledger, which is a real answer. Absence of a lookup is never proof.
LEDGER_NOT_CONSULTED = object()


def never_reached_venue(mission, *, submission_evidence=LEDGER_NOT_CONSULTED) -> tuple:
    """Can we PROVE this mission placed nothing? Returns (ok, reasons).

    PROD-20260810 broke the previous version of this function. It read
    `mission.order_id is not None` and concluded the venue had seen nothing --
    while Topstep held order 3385801549, already rejected. The local record was
    blank because `place_order` raised before the order id was ever assigned.

    A local field can only prove the venue DID see something. It can never
    prove the venue did NOT, because the failure that loses the order id is
    exactly the failure that happens after the request goes out. So the claim
    now has to be earned from the submission ledger, and the default answer
    when nobody looked is False.

    `submission_evidence` comes from
    `topstepx_submission_record.mission_venue_evidence`. Omitting it is not a
    convenience -- it is refused.
    """
    reasons = []
    state = getattr(mission, "state", None)
    if state != MS.ATTEMPT_CONSUMED:
        reasons.append(f"state is {state}, not {MS.ATTEMPT_CONSUMED}; "
                       "only a pre-submission abort is voidable")
    if getattr(mission, "order_id", None) is not None:
        reasons.append(f"an order id exists ({mission.order_id}); the venue saw it")
    if getattr(mission, "token_spent", False):
        reasons.append("the execution token was spent")
    position = str(getattr(mission, "position_state", "") or "")
    if position != "flat":
        reasons.append(f"position_state is {position!r}, not flat")
    if str(getattr(mission, "completion_state", "") or ""):
        reasons.append(f"mission completed as {mission.completion_state!r}")

    # ── the part that PROD-20260810 was missing ──────────────────────────────
    if submission_evidence is LEDGER_NOT_CONSULTED:
        reasons.append("the submission ledger was not consulted; non-delivery "
                       "cannot be proven from the mission record alone")
    elif not (submission_evidence or {}).get("ledger_consulted"):
        reasons.append("submission evidence is malformed or absent; failing closed")
    else:
        # PROD-20260811-V13. The join keys disagreed -- mission
        # `PROD-20260811-V13-T1` against a row stamped `PROD-20260811-V13`, in a
        # file named for the retired `PROD-20260811` -- so the search returned
        # zero rows and `venue_may_have_seen` came back False. Every other check
        # passes for a stopped-out trade (flat, no order id, token unspent), so
        # a real fill evaluated as never_reached_venue=True.
        #
        # ABSENCE OF MATCHING VENUE EVIDENCE != PROOF THE VENUE WAS NEVER
        # REACHED. Nothing found means the ledger cannot answer, and an
        # unanswerable question fails closed.
        absent = (submission_evidence.get("evidence_absent")
                  or submission_evidence.get("venue_may_have_seen") is None
                  or not submission_evidence.get("submission_count"))
        strong = submission_evidence.get("search_key_strength") == "token"
        token = str(getattr(mission, "token_id", "") or "")
        if absent and not (strong and token):
            # Nothing found, by a search that could plausibly have missed
            # something. That is an unanswered question, not an answer.
            reasons.append(
                "the submission ledger holds no rows for this mission and the "
                "search key was too weak to prove absence "
                f"(searched {submission_evidence.get('searched')})")
        elif absent and str(submission_evidence.get("searched", {}).get(
                "token_id") or "") != token:
            reasons.append(
                f"the ledger was searched for token "
                f"{submission_evidence.get('searched', {}).get('token_id')!r} "
                f"but this mission carries {token!r}; that answer is about a "
                "different attempt")
        if submission_evidence.get("venue_may_have_seen"):
            reasons.append(
                f"the submission ledger shows the venue may have seen this "
                f"request (states={submission_evidence.get('states')}, "
                f"order_ids={submission_evidence.get('venue_order_ids')})")
        for order_id in submission_evidence.get("venue_order_ids") or []:
            reasons.append(f"venue order {order_id} exists for this mission")
    return (not reasons), reasons


def _read_ledger(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != VOID_SCHEMA:
        return {}
    return data


def load_voids(store_dir: str, session_id: str) -> dict:
    """Voided mission slots as {index: entry}. Unreadable ledger -> no voids."""
    entries = _read_ledger(void_ledger_path(store_dir, session_id)).get("voids") or []
    out = {}
    for entry in entries[:MAX_VOIDED_MISSIONS_PER_SESSION]:
        try:
            index = int(entry["mission_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if entry.get("void_class") in VOID_CLASSES:
            out[index] = entry
    return out


def record_void(*, store_dir: str, session_id: str, mission_index: int, mission,
                phrase: str, reason: str, venue_evidence: dict,
                operator: str = "operator", now=None) -> dict:
    """Append a void to the ledger. Refuses far more often than it accepts."""
    if phrase != VOID_PHRASE:
        raise VoidRefused("VOID_PHRASE_MISMATCH: the operator phrase is required")
    if not str(reason or "").strip():
        raise VoidRefused("VOID_REASON_REQUIRED: state why in the record")

    ok, reasons = never_reached_venue(
        mission, submission_evidence=submission_evidence_for(
            store_dir, session_id, getattr(mission, "mission_id", None),
            token_id=getattr(mission, "token_id", "") or ""))
    if not ok:
        raise VoidRefused("MISSION_MAY_HAVE_REACHED_VENUE: " + "; ".join(reasons))

    positions = venue_evidence.get("open_positions")
    orders = venue_evidence.get("working_orders")
    fills = venue_evidence.get("fills_today")
    if positions != 0 or orders != 0:
        raise VoidRefused(
            f"VENUE_NOT_FLAT: {positions} position(s), {orders} working order(s)")
    if fills not in (0, None):
        raise VoidRefused(f"VENUE_SHOWS_FILLS: {fills} fill(s) today")

    path = void_ledger_path(store_dir, session_id)
    ledger = _read_ledger(path)
    voids = list(ledger.get("voids") or [])
    if any(int(v.get("mission_index", -1)) == int(mission_index) for v in voids):
        raise VoidRefused(f"ALREADY_VOIDED: mission {mission_index}")
    if len(voids) >= MAX_VOIDED_MISSIONS_PER_SESSION:
        raise VoidRefused(
            f"VOID_ALLOWANCE_EXHAUSTED: {len(voids)}/"
            f"{MAX_VOIDED_MISSIONS_PER_SESSION} already voided this session")

    stamp = (now or datetime.now(timezone.utc)).isoformat()
    entry = {
        "mission_index": int(mission_index),
        "mission_id": getattr(mission, "mission_id", None),
        "void_class": INFRASTRUCTURE_ABORT,
        "reason": reason,
        "operator": operator,
        "voided_at": stamp,
        # what the mission itself said, copied so a later audit can compare the
        # ledger against the untouched original
        "mission_state_at_void": getattr(mission, "state", None),
        "mission_attempt_count": getattr(mission, "attempt_count", None),
        "mission_order_id": getattr(mission, "order_id", None),
        "mission_token_id": getattr(mission, "token_id", None),
        "mission_token_spent": bool(getattr(mission, "token_spent", False)),
        "mission_position_state": getattr(mission, "position_state", None),
        "venue_evidence": dict(venue_evidence),
        "mission_record_preserved": True,
    }
    voids.append(entry)
    payload = {"schema_version": VOID_SCHEMA, "session_id": session_id,
               "updated_at": stamp, "voids": voids,
               "note": ("Additive recovery record. The referenced mission files "
                        "are NOT edited and remain the primary evidence.")}

    os.makedirs(store_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)
    return entry

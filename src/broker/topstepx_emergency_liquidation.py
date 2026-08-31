"""TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1 — converge to flat WITHOUT reversing.

THE INCIDENT THIS CLOSES. 2026-08-26, venue-proven:

    13:37:58.943  SELL 15 @ 29257.50   legitimate short
    13:37:59.718  BUY  15 @ 29264.50   emergency flatten -> FLAT      -$210.00
    13:37:59.804  BUY  15 @ 29266.25   the still-working protective STOP fired
                                       into a flat account -> LONG 15
    13:38:07.430  SELL 15 @ 29256.00   cleanup -> FLAT                -$307.50

86 milliseconds. The unintended reversal cost more than the trade it was
protecting.

AUTHORITY IS RELATIONAL, NOT INTRINSIC. Order 3451056003 did not change. At
13:37:59.717 it was protection, because a short position existed. At
13:37:59.718 it was an ENTRY, because the position did not. The object was
identical; its authority changed because the surrounding state did.

    SHORT 15 + working BUY stop  ->  PROTECTIVE_AUTHORITY
    FLAT     + the same BUY stop ->  ENTRY_AUTHORITY

`emergency_flatten` closed the parent while children were still executable, so
protection became entry. `risk_above_cap` was that day's trigger, not the cause:
an audit found NINE call sites that can hand this primitive an account whose
child-order authority is working, ambiguous or mid-mutation.

WHAT THIS MODULE REFUSES TO INFER:

    a submitted cancel is not a cancelled order
    PendingCancellation is not Cancelled
    Suspended is not harmless
    absence from `searchOpen` is not non-existence -- the official Gateway
        contract omits Suspended bracket children from it entirely
    a caller's belief that "no protection exists" is not evidence
    a failed/timeout mutation is not proof the venue did nothing

Safety is granted ONLY by a positive terminal witness from the venue. Every
ambiguity routes to INCIDENT_HALT, which is deliberately not a success state.

THE SET IS NOT "CHILDREN". A partially filled entry leaves a working remainder
that can reopen exposure exactly as the orphan stop did:

    SELL 15 requested -> 8 fill -> emergency BUY 8 -> FLAT
    -> remaining SELL 7 fills -> SHORT 7

So the object of protection is every bot-owned order from the old trade
lifecycle still capable of changing net exposure -- entry remainder, stop,
target, any re-anchored replacement, and any emergency close already in flight.

NO ATOMIC PRIMITIVE EXISTS. The official Gateway exposes `Order/cancel`,
`Position/closeContract` and `Position/closeContractPartial` as separate
operations, and `PlaceOrderRequest` carries no reduce-only or close-only flag.
The UI's "Flatten All" and the separate User API are not this bot's contract.
A client-side convergence protocol is therefore not a preference; it is the
only shape the venue permits.

NO ORDERS ARE SUBMITTED BY THIS MODULE'S PLANNER. It computes decisions; the
caller executes them through the existing certified write paths.
"""
from __future__ import annotations

# ── ORDER AUTHORITY ─────────────────────────────────────────────────────────
#: Would protect an existing position.
PROTECTIVE_AUTHORITY = "PROTECTIVE_AUTHORITY"
#: Would OPEN a position if it filled right now. The dangerous one.
ENTRY_AUTHORITY = "ENTRY_AUTHORITY"
#: Proven by the venue to be incapable of further execution.
NON_EXECUTABLE = "NON_EXECUTABLE"
#: Anything the venue has not positively resolved. Never treated as safe.
UNKNOWN_AUTHORITY = "UNKNOWN_AUTHORITY"

#: Official Gateway OrderStatus. Pinned so client drift cannot silently
#: re-interpret every terminality decision in this file.
STATUS_NONE = 0
STATUS_OPEN = 1
STATUS_FILLED = 2
STATUS_CANCELLED = 3
STATUS_EXPIRED = 4
STATUS_REJECTED = 5
STATUS_PENDING = 6
STATUS_PENDING_CANCELLATION = 7
STATUS_SUSPENDED = 8

TERMINAL_STATUSES = frozenset({STATUS_FILLED, STATUS_CANCELLED,
                               STATUS_EXPIRED, STATUS_REJECTED})
#: `PendingCancellation` is NOT cancelled -- a cancel in flight can still fill.
#: `Suspended` is a staged bracket child, and is exactly what `searchOpen` hides.
ACTIVE_STATUSES = frozenset({STATUS_OPEN, STATUS_PENDING,
                             STATUS_PENDING_CANCELLATION, STATUS_SUSPENDED})

#: Statuses that mean exposure MAY have moved, so position must be re-read even
#: though the order itself is finished.
POSITION_MAY_HAVE_MOVED = frozenset({STATUS_FILLED, STATUS_CANCELLED})

# ── STATE MACHINE ───────────────────────────────────────────────────────────
E0_ENTER = "E0_ENTER"
E1_NEUTRALISE = "E1_NEUTRALISE"
E2_PROVE_TERMINAL = "E2_PROVE_TERMINAL"
E3_REREAD_POSITION = "E3_REREAD_POSITION"
#: Position open, every old-trade order proven non-executable. GENUINELY
#: unprotected, and we caused it. Named rather than defined away: for the
#: post-fill-authorization caller the cancelled stop was VALID protection, so
#: this is a real new naked window, bounded by convergence rather than open.
E3A_EMERGENCY_NAKED = "E3A_EMERGENCY_NAKED"
E4_CLOSE_MEASURED = "E4_CLOSE_MEASURED"
E5_SAFE_TERMINAL = "E5_SAFE_TERMINAL"
#: NOT a success state. Automation stops mutating; responsibility does not end.
E9_INCIDENT_HALT = "E9_INCIDENT_HALT"

#: Why an E9 fired, when the cause is unresolved ORDER AUTHORITY rather than an
#: unreadable account or an ambiguous close. Named because this halt is the one
#: that keeps a live position open on purpose, and an operator reading the
#: report needs to know it is a proof problem, not a venue failure.
OWNERSHIP_AMBIGUOUS = "OWNERSHIP_AMBIGUOUS"

#: Why an E9 fired when the ORDER SET ITSELF is not trustworthy. Distinct from
#: `OWNERSHIP_AMBIGUOUS`: there we can see every order and cannot attribute one;
#: here we cannot be sure we have seen them all.
DISCOVERY_INCOMPLETE = "DISCOVERY_INCOMPLETE"

# ── EMERGENCY CLOSE LIFECYCLE ───────────────────────────────────────────────
#: The close is itself an exposure-changing order. Submitting a second one
#: because the position "still looks open" is another reversal machine.
CLOSE_NOT_SUBMITTED = "CLOSE_NOT_SUBMITTED"
CLOSE_ACKNOWLEDGED = "CLOSE_ACKNOWLEDGED"
CLOSE_FILL_PENDING = "CLOSE_FILL_PENDING"
CLOSE_PARTIALLY_FILLED = "CLOSE_PARTIALLY_FILLED"
CLOSE_FILLED = "CLOSE_FILLED"
CLOSE_REJECTED = "CLOSE_REJECTED"
CLOSE_STATE_UNKNOWN = "CLOSE_STATE_UNKNOWN"

#: What the planner asks the caller to do next. One step at a time; every step
#: is followed by a fresh venue read.
ACTION_CANCEL = "CANCEL_ORDER"
ACTION_PROVE = "PROVE_TERMINAL"
ACTION_CLOSE = "CLOSE_MEASURED_EXPOSURE"
ACTION_DONE = "DONE"
ACTION_HALT = "HALT"

#: A convergence budget, not a timeout. Exceeding it means the venue is not
#: resolving, which is an incident -- never a licence to guess.
DEFAULT_MAX_ROUNDS = 8


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def classify_order(order, *, position_size) -> str:
    """What authority does this order hold RIGHT NOW, given the position?

    `position_size` is SIGNED net exposure: positive long, negative short, 0
    flat. The same order is protection or entry depending on it, which is the
    whole lesson of the incident.
    """
    if not isinstance(order, dict):
        return UNKNOWN_AUTHORITY
    status = _int(order.get("status"))
    if status is None or status == STATUS_NONE:
        return UNKNOWN_AUTHORITY
    if status in TERMINAL_STATUSES:
        return NON_EXECUTABLE
    if status not in ACTIVE_STATUSES:
        # An unrecognised future status is not assumed harmless.
        return UNKNOWN_AUTHORITY
    size = _int(position_size, 0) or 0
    if size == 0:
        # NOTHING TO PROTECT. Anything still executable would OPEN a position.
        return ENTRY_AUTHORITY
    side = _int(order.get("side"))
    if side is None:
        return UNKNOWN_AUTHORITY
    # side 0 = buy, 1 = sell. An order that opposes the position reduces it.
    reduces = (size > 0 and side == 1) or (size < 0 and side == 0)
    return PROTECTIVE_AUTHORITY if reduces else ENTRY_AUTHORITY


def exposure_authority_set(orders, *, owns, position_size) -> dict:
    """OLD_TRADE_EXPOSURE_AUTHORITY_SET, split by what we can prove.

    `owns(order) -> bool` is the caller's lineage predicate. Ownership requires
    PROOF: an order on our contract with no provable lineage is `unproven` and
    is never cancelled -- it may be the operator's. But it is also never
    ignored, because an unproven order that can still execute means we cannot
    honestly claim a safe terminal state.
    """
    ours, unproven, terminal, unknown = [], [], [], []
    for order in orders or []:
        if not isinstance(order, dict):
            unknown.append(order)
            continue
        authority = classify_order(order, position_size=position_size)
        if authority == NON_EXECUTABLE:
            terminal.append(order)
            continue
        try:
            mine = bool(owns(order))
        except Exception:  # noqa: BLE001 — an ownership test that throws proves nothing
            mine = False
            authority = UNKNOWN_AUTHORITY
        if authority == UNKNOWN_AUTHORITY:
            # UNRESOLVED ALWAYS SURFACES, OWNED OR NOT. Filing an owned-but-
            # unresolved order under `ours` hid it twice over: it was not in
            # `executable_ours` (its status is not a known active one) and not
            # in `unknown` (it was ours), so nothing halted and the planner
            # walked on to close a position while an order of unknown authority
            # was still out there. Ownership decides whether we may CANCEL it;
            # it never decides whether we may IGNORE it.
            unknown.append(dict(order, _owned=mine))
        elif mine:
            ours.append(order)
        else:
            unproven.append(order)
    return {"ours": ours, "unproven": unproven, "terminal": terminal,
            "unknown": unknown,
            "executable_ours": [o for o in ours
                                if _int(o.get("status")) in ACTIVE_STATUSES],
            "any_unresolved": bool(unknown) or bool(unproven)}


def plan(*, position_size, orders, owns, close_state=CLOSE_NOT_SUBMITTED,
         round_index=0, max_rounds=DEFAULT_MAX_ROUNDS,
         discovery_complete=True) -> dict:
    """One step toward the compound terminal state. PURE — submits nothing.

    THE SAFE TERMINAL CONDITION IS COMPOUND:

        venue position is FLAT
            AND
        every member of the old-trade exposure set is positively terminal

    Flat alone is never success. That was exactly the state at 13:37:59.718 --
    flat, and 86 milliseconds from being long 15.

    ORDER OF OPERATIONS. Ownership ambiguity is settled FIRST, before anything
    is cancelled -- see the gate below. Then children are neutralised BEFORE the
    position is closed, because an old-trade order can create unintended
    exposure whenever its executable quantity exceeds the REMAINING opposing
    position. Flat is only the cleanest case of that: SHORT 6 against a resting
    BUY stop for 15 flattens six and goes LONG NINE.
    Removing entry authority first is what makes the flatten safe. For eight of
    the nine callers the protection was already untrustworthy, so cancelling it
    removes nothing real; for the post-fill-authorization caller it does open a
    real naked window, which is reported as E3A rather than hidden.
    """
    size = _int(position_size)
    if size is None:
        return _halt("position size unreadable; no position-changing action "
                     "may be taken on an unknown account state",
                     state=E9_INCIDENT_HALT)
    if round_index >= max_rounds:
        return _halt(f"convergence budget of {max_rounds} rounds exhausted; the "
                     f"venue is not resolving and guessing is not permitted",
                     state=E9_INCIDENT_HALT)

    # ── COMPLETENESS IS AN AUTHORITY INPUT, AND IT IS CHECKED FIRST ─────────
    #
    # `_emergency_venue_read` has always LABELLED the degraded `searchOpen`
    # fallback `INCOMPLETE`. Nothing consumed the label. So on 2026-08-27 a
    # certification specimen reproduced this:
    #
    #     v2/query down -> searchOpen returns [] -> planner sees no old-trade
    #     authority -> closes the position -> account FLAT with a Suspended
    #     stop still armed -> safe_terminal True
    #
    # The system knew epistemically that it did not know enough, and acted as
    # if it did. That is the 2026-08-26 causal family reached through
    # incompleteness rather than through ordering.
    #
    # AN INCOMPLETE ORDER SET MAY NEVER BE CONSUMED AS PROOF OF ABSENCE,
    # OWNERSHIP-SET COMPLETENESS, PROTECTION ABSENCE, CLOSE PERMISSION, OR
    # SAFE_TERMINAL.
    #
    # WHY BEFORE E1, NOT MERELY BEFORE THE CLOSE. If convergence cannot legally
    # complete, cancelling the protection we CAN see leaves the live position
    # strictly worse off than doing nothing. The gate belongs before the first
    # mutation, not before the last one.
    #
    # This is a RECOVERABLE epistemic halt: the planner is pure, so the tick on
    # which authoritative discovery returns re-decides from current venue truth.
    if not discovery_complete:
        return _halt(
            "order discovery is INCOMPLETE -- the venue's complete surface did "
            "not answer and the fallback omits Suspended bracket children by "
            "contract. An order set that may be missing members cannot prove "
            "absence, cannot authorize a close, and cannot establish a safe "
            "terminal state",
            state=E9_INCIDENT_HALT, reason=DISCOVERY_INCOMPLETE,
            position_size=size)

    found = exposure_authority_set(orders, owns=owns, position_size=size)

    # ── OWNERSHIP AMBIGUITY, BEFORE ANY MUTATION AT ALL ─────────────────────
    #
    # THE ASYMMETRY THIS REPLACES. This planner already halted on an unresolved
    # order when the position was FLAT -- "cancelling requires proof; claiming
    # safety requires certainty; neither is available" -- but with a position
    # OPEN it fell through to ACTION_CLOSE. A nonzero position quantity is not
    # a proof of anything, so the distinction had nothing behind it.
    #
    #     AN EXECUTABLE ORDER WHOSE AUTHORITY IS UNPROVEN MAY NOT BE MUTATED
    #     AROUND BY CREATING OR CHANGING FLATNESS.
    #
    # Closing the position changes the semantic authority of every remaining
    # order on the contract. The same resting order that was reducing exposure
    # becomes a reverse-position entry the moment the exposure it opposed is
    # gone -- and we do not know whose order it is:
    #
    #     it is OUR lost child      -> it is an ENTRY against a flat account
    #     it is the operator's      -> it now acts on a net position he did
    #                                  not choose
    #
    # 2026-08-26 proved the first case is not hypothetical: that mission's
    # `protective_order_ids` was empty, so the bot could not recognise its own
    # bracket. Ownership ambiguity and lost lineage are the same condition seen
    # from two sides.
    #
    # WHY BEFORE E1 AND NOT AFTER. E1 cancels our own protective legs so that
    # the close cannot be reversed by them. That trade is only worth making if
    # the close actually follows. Here it never will, so cancelling first would
    # strip a live position of real protection and then halt anyway -- ending
    # in a strictly worse account state than doing nothing. Nothing is
    # dismantled for a sequence that cannot complete.
    #
    # NO GEOMETRY EXCEPTION. Side and size do not grant permission. An
    # opposite-side order no larger than the position still races the close and
    # invalidates the measured quantity the close is built on, and SHORT 6
    # against a BUY 15 becomes LONG 9.
    if size != 0 and (found["unproven"] or found["unknown"]):
        return _halt(
            "position is OPEN and orders on this contract are executable but "
            "not provably ours. Closing would change what those orders mean, "
            "and their authority is exactly what is unproven. Cancelling "
            "requires proof; closing around them requires certainty; neither "
            "is available",
            state=E9_INCIDENT_HALT, reason=OWNERSHIP_AMBIGUOUS, found=found,
            position_size=size)

    # ── E1/E2: neutralise everything of ours that can still execute ─────────
    executable = found["executable_ours"]
    if executable:
        pending = [o for o in executable
                   if _int(o.get("status")) == STATUS_PENDING_CANCELLATION]
        cancellable = [o for o in executable
                       if _int(o.get("status")) != STATUS_PENDING_CANCELLATION]
        if cancellable:
            return {"state": E1_NEUTRALISE, "action": ACTION_CANCEL,
                    "order_ids": [o.get("id") for o in cancellable],
                    "detail": ("cancel every owned order that can still change "
                               "exposure, before the position is closed"),
                    "found": found, "round": round_index}
        # Everything left is a cancel already in flight. PendingCancellation is
        # NOT cancelled -- it can still fill -- so we wait on venue truth
        # rather than proceeding as though it were gone.
        return {"state": E2_PROVE_TERMINAL, "action": ACTION_PROVE,
                "order_ids": [o.get("id") for o in pending],
                "detail": ("cancellation in flight; PendingCancellation is not "
                           "Cancelled and may still fill -- re-read each order "
                           "by id until the venue reports a terminal status"),
                "found": found, "round": round_index}

    # ── unresolved evidence blocks any claim of safety ──────────────────────
    if found["unknown"]:
        return _halt("owned-or-unknown orders whose authority the venue has not "
                     "resolved; safety cannot be claimed and no further "
                     "position-changing order may be issued",
                     state=E9_INCIDENT_HALT, reason=OWNERSHIP_AMBIGUOUS,
                     found=found, position_size=size)

    # ── E3: what is the exposure NOW? a child may have filled meanwhile ─────
    if size == 0:
        if found["unproven"]:
            return _halt("position is flat, but orders on this contract remain "
                         "executable and are not provably ours -- they may be "
                         "the operator's. Cancelling requires proof; claiming "
                         "safety requires certainty. Neither is available",
                         state=E9_INCIDENT_HALT, reason=OWNERSHIP_AMBIGUOUS,
                         found=found, position_size=size)
        return {"state": E5_SAFE_TERMINAL, "action": ACTION_DONE,
                "detail": ("position flat AND every old-trade order positively "
                           "terminal"),
                "found": found, "round": round_index}

    # Position is still open with nothing of ours left working.
    if close_state in (CLOSE_ACKNOWLEDGED, CLOSE_FILL_PENDING):
        return {"state": E4_CLOSE_MEASURED, "action": ACTION_PROVE,
                "detail": ("an emergency close is already in flight; prove it "
                           "terminal and re-read position before considering "
                           "another -- a second close would be a new reversal "
                           "machine"),
                "found": found, "round": round_index}
    if close_state == CLOSE_STATE_UNKNOWN:
        return _halt("the previous emergency close has an unknown outcome; "
                     "submitting another could reverse the account",
                     state=E9_INCIDENT_HALT, found=found)

    return {"state": E3A_EMERGENCY_NAKED, "action": ACTION_CLOSE,
            "close_size": abs(size), "close_side": "buy" if size < 0 else "sell",
            "detail": ("position is open and now genuinely unprotected -- close "
                       "the MEASURED exposure, never a remembered size"),
            "naked": True, "found": found, "round": round_index}


def _halt(detail, *, state, found=None, reason=None, position_size=None) -> dict:
    """INCIDENT_HALT. Automation stops mutating; responsibility does not end.

    Deliberately NOT terminal success. New entry authority off, blind position
    mutation off -- but venue reads and reconciliation continue, the operator is
    alerted, and any live exposure stays this organism's responsibility until
    the venue proves a safe terminal state. Throwing an exception at an open
    position would be abandoning it.
    """
    return {"state": state, "action": ACTION_HALT, "detail": detail,
            "reason": reason, "found": found or {}, "terminal_success": False,
            "new_entry_authority": False, "blind_mutation": False,
            "venue_reconciliation": True, "operator_alert": True,
            "position_responsibility": "ACTIVE",
            # EXPLICIT, never inferred from the absence of a close. A halt with
            # a live position is a different operational fact from a halt on a
            # flat account, and the operator acts on the difference.
            "unresolved_live_exposure": bool(position_size)}


def is_safe_terminal(decision) -> bool:
    return (decision or {}).get("state") == E5_SAFE_TERMINAL


def discovery_statuses() -> list:
    """Statuses discovery must ask for. `searchOpen` omits Suspended bracket
    children by contract, so it can never define this set."""
    return sorted(ACTIVE_STATUSES)

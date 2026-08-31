"""BREAK-EVEN-2 — the venue actuator. The write that moves a live stop.

This module does NOT decide whether break-even should happen. `break_even.evaluate`
owns that, `break_even.cost_adjusted_break_even` owns the price, and
`protection_state.evaluate_advance` owns the monotonic law. This is the smallest
safe mutation that carries an already-authorized decision to the venue.

EXACTLY-ONCE EFFECT, NOT EXACTLY-ONCE REQUEST. A modify may time out, duplicate,
be acknowledged late, or land the instant before the process dies. None of those
are answerable from our HTTP result, so final truth is always read back off the
venue's CURRENT protection state. An acknowledgement proves a request was
accepted; only a readback proves a stop moved.

WHY FAILURE HERE IS NOT `reanchor_protection_to_structure`'S FAILURE.
Re-anchoring runs when protection is still provisional, so every failure there is
terminal and the position gets flattened -- an unprotected or wrongly-protected
position is the worse outcome. HERE THE POSITION IS ALREADY PROTECTED at its
original structural stop. A break-even advance that fails leaves a healthy
managed trade behind it, so the failure doctrine is inverted: HOLD, never
flatten, never cancel, never widen. Killing a protected position to resolve our
own bookkeeping would be the worse outcome, exactly as PROTECTION-STATE-AUTHORITY
already ruled for the armed case.

NO COGNITION. Nothing here calls a model. It runs inside MANAGEMENT_ONLY after
entry authority is exhausted (SESSION-CAP-GRACEFUL-SHUTDOWN-1), where by law no
provider may be consulted.
"""
from __future__ import annotations

from broker import protection_state as PS
from broker import topstepx_mission_reconciler as RECON
from broker import topstepx_order_discovery as DISC

SCHEMA = "break_even_actuator.v1"

APPLIED = "break_even_applied"        # venue readback proves the stop moved
HELD = "hold"                         # lawful, nothing to do; no mutation sent
REJECTED = "venue_rejected"           # venue refused; original protection stands
AMBIGUOUS = "ambiguous_unreconciled"  # effect unknown; NEVER auto-retried here
PROTECTION_DEFECT = "protection_missing"  # position open, owned stop gone
REFUSED = "refused"                   # preconditions not provable

# ── reasons ─────────────────────────────────────────────────────────────────
VENUE_UNKNOWN = "venue_truth_unavailable"
NO_POSITION = "no_open_position"
SIZE_MISMATCH = "position_size_changed"
NO_STOP = "no_owned_protective_stop"
AMBIGUOUS_LINEAGE = "protective_lineage_ambiguous"
ALREADY_PROTECTED = "protection_already_at_or_better"
NOT_A_PRICE = "proposed_stop_is_not_a_price"
DIRECTION_MISMATCH = "venue_position_side_disagrees"
EFFECT_PROVEN = "effect_proven_by_readback"
EFFECT_ABSENT = "effect_absent_at_venue"
EFFECT_UNPROVEN = "accepted_but_effect_not_yet_proven"
EXPLICIT_REJECTION = "venue_explicitly_rejected"
EFFECT_UNKNOWN = "effect_unknown_at_venue"
POSITION_GONE = "position_closed_during_modify"
TARGET_CHANGED = "target_was_altered"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


#: `_owned`'s third answer. A distinct object, not a message an operator could
#: accidentally reproduce: it is compared by identity wherever the difference
#: between "no stop" and "no complete view" decides whether a live position is
#: destroyed.
UNKNOWN_PROBLEM = "protective discovery incomplete; stop presence UNKNOWN"

#: Outcome/reason for that third answer. `PROTECTION_UNKNOWN` is NOT a defect
#: report -- nothing is known to be wrong. It is a refusal to conclude.
PROTECTION_UNKNOWN = "PROTECTION_UNKNOWN"
DISCOVERY_INCOMPLETE = "discovery_incomplete"


def _observe(session, contract_id):
    """Fresh venue truth, or an explicit unknown. Never an empty-list guess.

    `known` means the venue ANSWERED. It deliberately does not mean the answer
    was complete -- `seen["orders_complete"]` carries that separately, because
    an answer we received and an answer that saw everything are different facts
    and only one of them licenses concluding that a stop does not exist.
    """
    seen = RECON.MissionReconciler(venue=session, contract_id=contract_id).observe()
    known = bool(seen.get("positions_answered")) and bool(seen.get("orders_answered"))
    return seen, known


def _owned(orders, *, contract_id, entry_order_id, complete=True):
    """(stop_order, target_order, problem) by PROVEN lineage only.

    `complete=False` means discovery ran on `searchOpen`, which omits Suspended
    bracket children by venue contract. Finding no stop there is not a finding
    about the account, so the problem returned is `UNKNOWN_PROBLEM` -- a third
    answer that must never be routed to the no-protection response.

    `child.parent_order_id == entry_order_id`, per MISSION-RECONCILIATION-VENUE-
    TRUTH-1. Never nearest price, never newest order, never same-contract-and-
    side: a foreign mission's stop must be unreachable from here.
    """
    ours = RECON.lineage_orders(orders, contract_id=contract_id,
                                entry_order_id=entry_order_id)
    stops, targets = RECON.split_protective(ours)
    if len(stops) != 1:
        # THREE different defects, three different diagnoses. None-under-a-
        # complete-view means protection is genuinely missing; several means
        # ownership is not decidable; none-under-an-INCOMPLETE-view means we
        # never got to look, and collapsing that into the first is what lets a
        # query gap masquerade as an unprotected position.
        if stops:
            return None, None, (f"{len(stops)} owned stops provable for entry "
                                f"{entry_order_id}; ownership is not decidable")
        if not complete:
            return None, None, UNKNOWN_PROBLEM
        return None, None, f"no owned stop provable for entry {entry_order_id}"
    stop = next(o for o in ours if o.get("id") == stops[0])
    target = None
    if len(targets) == 1:
        target = next(o for o in ours if o.get("id") == targets[0])
    return stop, target, None


def _stop_price(order):
    return None if order is None else _num(order.get("stop_price"))


def _is_at_or_better(direction, *, active, wanted):
    """Is live protection already at least as good as what we would ask for?

    Reuses the ONE monotonic authority rather than re-deriving the comparison:
    anything that is not a strict risk-reducing advance is something we must not
    send. NO_OP (already there) and REFUSED (would restore risk) both mean HOLD.
    """
    verdict = PS.evaluate_advance(direction=direction, active_protective_stop=active,
                                  proposed_stop=wanted, armed=True)
    return verdict["outcome"] != PS.ADVANCE, verdict


def inspect_protection(*, session, contract_id, entry_order_id) -> dict:
    """READ ONLY. The owned stop/target as the venue currently holds them.

    Exists so the production owner can derive a STABLE effect identity -- which
    needs the stop order id -- before any mutation, without duplicating lineage
    rules. Mutates nothing and never raises.
    """
    seen, known = _observe(session, contract_id)
    if not known:
        return {"known": False, "complete": False, "stop": None, "target": None,
                "presence": DISC.UNKNOWN, "errors": seen.get("errors") or []}
    complete = bool(seen.get("orders_complete"))
    stop, target, problem = _owned(seen["orders"], contract_id=contract_id,
                                   entry_order_id=entry_order_id,
                                   complete=complete)
    return {"known": True, "complete": complete, "stop": stop, "target": target,
            "problem": problem, "discovery": seen.get("discovery"),
            # PRESENT / ABSENT / UNKNOWN. The caller that decides whether to
            # flatten reads THIS, not the truthiness of `stop`.
            "presence": DISC.protection_presence(stop=stop, complete=complete),
            "errors": seen.get("errors") or [],
            "position_size": RECON.position_size(seen["positions"], contract_id)}


def apply_break_even(*, session, contract_id, entry_order_id, direction,
                     proposed_stop, expected_size=None, may_write=True) -> dict:
    """Advance the owned protective stop to `proposed_stop`. One effect, or none.

    Returns APPLIED / HELD / REJECTED / AMBIGUOUS / PROTECTION_DEFECT / REFUSED
    with the evidence each conclusion rests on. Never raises, never flattens,
    never cancels, never touches the target.

    `may_write=False` runs every gate and every readback but STOPS before the
    mutation. That is how the durable unresolved latch reconciles a prior
    in-flight effect: it must be able to discover the effect landed without
    risking a second one.
    """
    def out(outcome, reason=None, detail="", **extra):
        return dict({"schema": SCHEMA, "outcome": outcome, "reason": reason,
                     "detail": detail, "direction": PS.normalized_direction(direction),
                     "entry_order_id": entry_order_id,
                     "proposed_stop": _num(proposed_stop)}, **extra)

    want = _num(proposed_stop)
    if want is None:
        return out(REFUSED, NOT_A_PRICE, f"proposed {proposed_stop!r}")

    # ── PRE-MODIFY RECONCILIATION. Positive proof, immediately before the write.
    seen, known = _observe(session, contract_id)
    if not known:
        return out(REFUSED, VENUE_UNKNOWN,
                   "; ".join(seen.get("errors") or ["venue did not answer"]))
    pos = RECON.position_for(seen["positions"], contract_id)
    size = RECON.position_size(seen["positions"], contract_id)
    if not size:
        return out(HELD, NO_POSITION, "no live exposure to protect")
    # THE POSITION MUST STILL BE THE ONE WE ARE MANAGING. `position_size` is an
    # ABSOLUTE magnitude, so a flip from short to long presents an identical
    # number -- and the stop would then be "advanced" under the wrong side's
    # law, widening real risk while reporting success. Side is checked
    # explicitly, and an `undefined` side fails closed.
    side_now = PS.normalized_direction(pos.get("side"))
    want_side = PS.normalized_direction(direction)
    if side_now is None or want_side is None or side_now != want_side:
        return out(REFUSED, DIRECTION_MISMATCH,
                   f"managing {want_side}, venue holds {pos.get('side')!r}",
                   position_size=size)
    if expected_size is not None and int(expected_size) != int(size):
        # FAIL CLOSED. A stop sized to a position that changed underneath us is
        # not this unit's problem to solve; partial management is not built here.
        return out(REFUSED, SIZE_MISMATCH,
                   f"expected {expected_size}, venue holds {size}",
                   position_size=size)

    complete = bool(seen.get("orders_complete"))
    stop, target, problem = _owned(seen["orders"], contract_id=contract_id,
                                   entry_order_id=entry_order_id,
                                   complete=complete)
    if problem is UNKNOWN_PROBLEM:
        # NO BLIND MUTATION, NO FABRICATED ABSENCE. We cannot see the whole
        # order set, so we can neither move a stop we have not proven nor claim
        # there is none. Refusing costs one management tick; guessing either way
        # costs the trade.
        return out(PROTECTION_UNKNOWN, DISCOVERY_INCOMPLETE,
                   f"{seen.get('discovery')}: protective children may exist "
                   f"unseen; no mutation and no absence conclusion",
                   position_size=size, discovery=seen.get("discovery"))
    if problem or stop is None:
        # Position open, protection not provable: a real defect, and NOT
        # something a stop-price amendment can repair. Existing protection-
        # failure policy owns it.
        many = bool(problem) and "owned stops" in problem
        return out(PROTECTION_DEFECT, AMBIGUOUS_LINEAGE if many else NO_STOP,
                   problem or "no owned protective stop at the venue",
                   position_size=size)

    stop_id = stop.get("id")
    active = _stop_price(stop)
    target_before = {"id": None if target is None else target.get("id"),
                     "limit_price": None if target is None
                     else _num(target.get("limit_price"))}

    already, verdict = _is_at_or_better(direction, active=active, wanted=want)
    if already:
        # Covers a prior successful actuator call, a restart after a landed
        # modify, a duplicated management tick, and an operator who moved the
        # stop further than break-even. None of them may produce a second write.
        return out(HELD, ALREADY_PROTECTED,
                   f"venue stop {active} vs proposed {want}: {verdict['outcome']}",
                   active_protective_stop=active, stop_order_id=stop_id,
                   verdict=verdict, target=target_before, position_size=size)

    if not may_write:
        # RECONCILIATION-ONLY. An advance is still wanted, but a previous
        # attempt at this same effect is unresolved, so writing again could
        # duplicate a money-moving mutation that is merely slow to appear.
        return out(AMBIGUOUS, EFFECT_UNPROVEN,
                   f"an advance to {want} is still wanted and the venue holds "
                   f"{active}; writing is latched off until the prior effect "
                   "resolves",
                   stop_order_id=stop_id, active_protective_stop=active,
                   position_size=size, target=target_before, retryable=False,
                   write_suppressed=True)

    # ── THE MUTATION. In place, by the SAME stop order id. The stop is never
    # cancelled first: there must be no deliberate unprotected gap.
    # THREE EPISTEMICALLY DIFFERENT OUTCOMES, NEVER COLLAPSED.
    #
    # `TopstepXClient._post` RAISES `TopstepXError` when the venue answers
    # `success: false`, carrying the structured body -- so an explicit refusal
    # arrives as an exception, and a RETURNED body means the venue ACCEPTED.
    # The same exception type is also raised for transport/HTTP failures, where
    # the effect is genuinely unknown. The discriminator is therefore the body,
    # not the exception class:
    #
    #   venue_body.success is False  -> the venue said no        (definitive)
    #   exception, no such body      -> we cannot know           (unknown)
    #   normal return                -> the venue said yes       (accepted)
    #
    # Collapsing "accepted but not yet visible" into "rejected" would be the
    # dangerous one: a modify still propagating could land AFTER we recorded a
    # refusal, and the next tick would treat a moved stop as unexplained.
    response, error, rejection = None, None, None
    try:
        response = session.modify_order(stop_id, stop_price=want)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        body = getattr(exc, "venue_body", None)
        if isinstance(body, dict) and body.get("success") is False:
            rejection = body

    # ── ACK IS NOT AUTHORITY. Read the venue back either way.
    after, after_known = _observe(session, contract_id)
    if not after_known:
        return out(AMBIGUOUS, EFFECT_UNKNOWN,
                   "modify sent; venue could not be re-read, so the effect is "
                   "unknown. NOT retried: a duplicate write is worse than a "
                   "late confirmation.",
                   stop_order_id=stop_id, active_protective_stop=active,
                   error=error, response=response, retryable=False)

    size_after = RECON.position_size(after["positions"], contract_id)
    stop_after, target_after, problem_after = _owned(
        after["orders"], contract_id=contract_id, entry_order_id=entry_order_id)
    now = _stop_price(stop_after)

    if not size_after:
        # Stop or target filled, or the operator closed it, while we were
        # writing. Nothing to protect and nothing to retry.
        return out(HELD, POSITION_GONE,
                   "position closed during the modify; no retry",
                   stop_order_id=stop_id, error=error, response=response,
                   retryable=False)

    if stop_after is None:
        return out(PROTECTION_DEFECT, NO_STOP,
                   "position is open but no owned protective stop can be proven "
                   f"after the modify ({problem_after or 'none found'})",
                   stop_order_id=stop_id, position_size=size_after,
                   error=error, response=response, retryable=False)

    # THE ONLY PROOF THAT COUNTS: the owned stop now sits at the proposed price
    # or better. `_is_at_or_better` answers "would we still want to advance?" --
    # if not, the effect is present however it got there.
    landed, landed_verdict = _is_at_or_better(direction, active=now, wanted=want)
    target_now = {"id": None if target_after is None else target_after.get("id"),
                  "limit_price": None if target_after is None
                  else _num(target_after.get("limit_price"))}
    common = {"stop_order_id": stop_id, "active_protective_stop": now,
              "previous_protective_stop": active, "position_size": size_after,
              "target": target_now, "error": error, "response": response,
              "venue_rejection": rejection}

    # TARGET IMMUTABILITY. We never send a target field; if it moved, something
    # else did it and this result may not be reported as a clean application.
    if target_before["id"] is not None and (
            target_now["id"] != target_before["id"]
            or target_now["limit_price"] != target_before["limit_price"]):
        return out(AMBIGUOUS, TARGET_CHANGED,
                   f"target moved from {target_before} to {target_now} across a "
                   "stop-only modify; not claiming a clean break-even",
                   target_before=target_before, retryable=False, **common)

    # READBACK HAS PRIMACY. However the stop got there, if protection is now at
    # or better than proposed, the effect is present and must never be re-sent.
    if landed:
        return out(APPLIED, EFFECT_PROVEN,
                   f"venue protection {active} -> {now} (proposed {want})",
                   verdict=landed_verdict, retryable=False, **common)

    if rejection is not None:
        # THE VENUE SAID NO, in its own words. Definitive: nothing is in flight,
        # so nothing can land later. The original stop stands untouched.
        return out(REJECTED, EXPLICIT_REJECTION,
                   f"venue refused the modify (errorCode="
                   f"{rejection.get('errorCode')} "
                   f"{rejection.get('errorMessage') or ''}".strip()
                   + f"); protection remains at {now}",
                   retryable=False, **common)

    if error is not None:
        # Sent, threw with no venue verdict, and protection still reads the
        # previous stop: the effect did not occur. Retry is LAWFUL -- and is the
        # caller's decision under the existing bounded retry doctrine, never
        # taken automatically here.
        return out(AMBIGUOUS, EFFECT_ABSENT,
                   "modify failed or timed out with no venue verdict and the "
                   f"venue still holds the previous stop {now}; protection "
                   "intact, retry permitted after reconciliation",
                   retryable=True, **common)

    # ACCEPTED, NOT YET VISIBLE. This is NOT a rejection: the venue took the
    # request and returned success, and venue propagation is not required to be
    # synchronous. Calling it refused would let a modify land afterwards against
    # a record that says it never happened. No blind retry -- the next
    # deterministic management tick re-reads and will either see it landed
    # (HELD) or propose again from fresh truth.
    return out(AMBIGUOUS, EFFECT_UNPROVEN,
               f"venue accepted the request but protection still reads {now}; "
               "the effect is not yet provable and may still be propagating",
               retryable=False, **common)

"""End-of-session hard flatten: close what is open, cancel what is resting.

Separate from the production entrypoint on purpose. `tools/` holds an AST guard
-- `test_the_entry_point_places_no_order_unless_armed` -- that forbids the
launcher from containing `place_order`, `submit`, `close_position` or
`cancel_order` calls at all. That guard is right: the entrypoint decides WHEN,
the execution layer decides HOW, and an order-capable call sitting in the
launcher is exactly the shape of an accident. So the ruling ("flatten at 15:55")
lives with the launcher and the mechanism lives here.

Execution/lifecycle code, therefore deliberately OUTSIDE the authorization
source closure: this governs how a decision is carried out safely, not what is
decided.

═══════════════════════════════════════════════════════════════════════════════
TOPSTEP-PROTECTIVE-DISCOVERY-AND-LINEAGE-1 (2026-08-26). This module used to
carry its OWN liquidation policy, and that policy was the one
`TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` had just proven wrong:

    close the position, THEN cancel the children

Its docstring argued the case honestly -- cancelling first strips protection
from size that is still on. But the account had already answered the argument.
At 2026-08-26 13:38 a protective stop survived a close by 86 milliseconds and
reversed a flat account into LONG 15 for -$307.50. A bounded naked window
between a cancel and the close that immediately follows is a smaller risk than
an armed order pointing at an account with nothing left to protect, because the
first is measured in milliseconds and the second is unbounded exposure in the
WRONG DIRECTION.

The invariant that replaced it is not "cancel first". It is:

    AN OLD-TRADE ORDER CAN CREATE UNINTENDED EXPOSURE WHENEVER ITS EXECUTABLE
    QUANTITY EXCEEDS THE REMAINING OPPOSING POSITION.

Flat is only the cleanest case of that. SHORT 6 against a resting BUY stop for
15 flattens six and goes LONG NINE.

So there is no second policy here any more. `topstepx_emergency_liquidation`
decides; this module only supplies the venue I/O and reports what happened. Two
liquidation policies mean two chances to be wrong about the same account.
═══════════════════════════════════════════════════════════════════════════════
TOPSTEP-HARD-FLATTEN-OWNERSHIP-AUTHORITY-1 (2026-08-26). The unit above left one
contradiction standing, in the one place nobody was looking: end-of-session, with
no mission to check it against. The missionless ownership predicate was

    owns = lambda order: contract_of(order) == contract.id

while the rest of the stack enforced the opposite law -- same contract alone is
UNPROVEN, never cancelled, never claimed. That predicate promotes INSTRUMENT
COINCIDENCE into lineage.

The two claims it confused are different authorities, and only one of them is
about lineage at all:

    MISSION_ORDER_OWNERSHIP   this order is ours because lineage proves it
    LANE_SHUTDOWN_AUTHORITY   this order is ours to clear because the LANE is
                              ours, whatever its lineage says

`lane_shutdown_authority()` is the single place the broader claim could ever be
granted, and it refuses: nothing in production makes this account incapable of
holding someone else's order, and the history says the opposite -- the session
ledger exists BECAUSE the operator traded this same Combine manually. Intent is
not mechanical authority.

What remains for the missionless path is real evidence: the bot stamps
`EXPBOT-<token_id>` on everything it sends, and the session ledger holds the
token ids this session issued. Without that ledger nothing is provable, nothing
is claimed, and the shutdown escalates to the operator.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from broker import topstepx_emergency_liquidation as EL
from broker import topstepx_order_discovery as DISC
from broker import topstepx_session_ledger as LG

#: TWO AUTHORITIES, DELIBERATELY NOT ONE.
#:
#:   MISSION_ORDER_OWNERSHIP   an order is OURS because its lineage proves it
#:   LANE_SHUTDOWN_AUTHORITY   an order is ours to clear because the LANE is
#:                             ours, whatever its lineage says
#:
#: The first is `topstepx_order_discovery.order_lineage` and is unchanged: same
#: contract alone is UNPROVEN. The second is broader and would let end-of-session
#: shutdown cancel every order on our instrument -- which is only sound if this
#: account is mechanically incapable of carrying anyone else's order.
LINEAGE_ONLY = "LINEAGE_ONLY"
BOT_EXCLUSIVE_LANE = "BOT_EXCLUSIVE_LANE"


def lane_shutdown_authority(*, ledger=None) -> dict:
    """How much of this account may end-of-session shutdown claim?

    ANSWER TODAY: `LINEAGE_ONLY`, and not for want of trying.

    A `BOT_EXCLUSIVE_LANE` verdict would need this account to be mechanically
    incapable of holding an order the bot did not send. Nothing in production
    establishes that, and the evidence runs the other way:

      * `topstepx_session_ledger` EXISTS because Maurice traded this Combine
        manually on 2026-08-05 -- 5 MNQ short, same instrument, no customTag,
        while the bot was collecting candles. Shared use is not hypothetical
        here; it is the recorded history that produced the attribution module.
      * That module's default is deliberately NOT "bot". An order that cannot be
        positively attributed is `MANUAL_OPERATOR` or `UNKNOWN_EXTERNAL`, and
        `UNKNOWN_EXTERNAL` PAUSES the bot rather than trading beside it. A
        subsystem built to pause for strangers is a subsystem that expects them.
      * `TOPSTEPX_ACCOUNT_ROLE` is operator-DECLARED and documented as
        "reporting and policy only ... routing must never see it". An operator
        declaration is not a mechanical guarantee, and this one is explicitly
        forbidden from carrying authority.

    So the exclusivity claim has no mechanical backing, and INTENT IS NOT
    AUTHORITY. The operator not planning to trade manually is not the same fact
    as the account being unable to hold his order.

    This function exists so that the day exclusivity IS mechanically enforced,
    there is one place to certify it -- and so that until then, the refusal is
    stated rather than assumed.
    """
    reasons = [
        "no mechanical exclusivity invariant exists for this account",
        "session ledger classifies MANUAL_OPERATOR / UNKNOWN_EXTERNAL origins, "
        "which presupposes external order authority",
        "TOPSTEPX_ACCOUNT_ROLE is operator-declared and barred from routing",
    ]
    return {"scope": LINEAGE_ONLY, "proven_exclusive": False, "reasons": reasons,
            "token_evidence": bool(ledger is not None
                                   and getattr(ledger, "known_token_ids", None))}


def _lineage_owner(ledger):
    """`owns(order) -> bool` for the missionless path. POSITIVE ATTRIBUTION ONLY.

    Without a mission there is no entry order id to be a parent of, so the
    lineage that remains is the one the bot stamps itself: every order it sends
    carries `EXPBOT-<token_id>`, and the session ledger holds the token ids THIS
    SESSION issued. `LG.classify` already joins those, including the `-SL`/`-TP`
    suffixes the venue derives for bracket children.

    That is real evidence. Instrument equality is not, and is never substituted
    for it: with no ledger and no tokens, NOTHING is claimed, every working
    order becomes UNPROVEN, and the planner escalates instead of guessing.
    """
    known = set(getattr(ledger, "known_token_ids", None) or ())
    if not known:
        return lambda order: False
    return lambda order: LG.classify(order, known) == LG.EXPANSION_BOT


def _signed(positions, contract_id):
    """Signed net exposure, or None when it cannot be read.

    NEVER coerced to zero. "The venue did not tell us" and "the venue told us
    zero" authorize completely different actions.
    """
    if positions is None:
        return None
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        if str(DISC.contract_of(pos) or "") != str(contract_id):
            continue
        try:
            size = abs(int(pos.get("size") or 0))
        except (TypeError, ValueError):
            return None
        if not size:
            return 0
        # The venue encodes a short as type 2.
        return -size if int(pos.get("type") or 0) == 2 else size
    return 0


def hard_flatten(session, contract, *, runner=None, ledger=None,
                 max_rounds=None) -> dict:
    """Bring the account to a proven terminal state for this contract.

    When a live `runner` is available this delegates to `emergency_flatten`,
    which is the certified safety authority and already carries mission lineage,
    halt reporting and the durable ladder. The standalone path below exists only
    for the end-of-session case where no mission object is in scope, and it
    drives the SAME planner rather than inventing a second one.

    Never raises. A flatten that failed must be REPORTED as not flat, because
    the operator's next action depends on knowing the difference between
    "closed" and "tried to close".
    """
    if runner is not None:
        try:
            out = runner.emergency_flatten("end-of-session hard flatten")
        except Exception as exc:  # noqa: BLE001
            return {"positions_before": 0, "orders_before": 0, "closed": False,
                    "cancelled": [], "errors": [f"{type(exc).__name__}: {exc}"],
                    "flat": False, "delegated": True}
        return {"positions_before": out.get("position_before") or 0,
                "orders_before": len(out.get("cancelled_mission_orders") or [])
                + len(out.get("foreign_orders_left_alone") or []),
                "closed": bool(out.get("confirmed", {}).get("closed")
                               or out.get("flattened")),
                "cancelled": list(out.get("cancelled_mission_orders") or []),
                "errors": [str(h) for h in (out.get("halts") or [])]
                + [str(f) for f in (out.get("cancellation_failures") or [])],
                # FLAT MEANS SAFE AND PROVEN CLEAN, exactly as the authority
                # defines it. Not "close_position returned 2xx".
                "flat": bool(out.get("flattened")),
                # THE CERTIFIED AUTHORITY OWNS LINEAGE HERE. `emergency_flatten`
                # resolves ownership through `mission_owns_order`, so there is
                # no second ownership doctrine on this path at all.
                "authority": "MISSION_ORDER_OWNERSHIP",
                "lane_proven_exclusive": False,
                "attribution": "mission_lineage",
                "unproven": list(out.get("foreign_orders_left_alone") or []),
                "delegated": True, "emergency": out}

    authority = lane_shutdown_authority(ledger=ledger)
    owns = _lineage_owner(ledger)
    report = {"positions_before": 0, "orders_before": 0, "closed": False,
              "cancelled": [], "errors": [], "flat": False, "delegated": False,
              "rounds": 0, "unproven": [], "authority": authority["scope"],
              "lane_proven_exclusive": authority["proven_exclusive"],
              "attribution": ("session_token_lineage"
                              if authority["token_evidence"] else "none_provable")}
    rounds = int(max_rounds or EL.DEFAULT_MAX_ROUNDS)
    try:
        first = True
        for index in range(rounds):
            report["rounds"] = index + 1
            found = DISC.discover_orders(session, contract_id=contract.id)
            try:
                positions = session.open_positions()
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"open_positions: {type(exc).__name__}: {exc}")
                return report
            size = _signed(positions, contract.id)
            orders = found["working"] or []
            if first:
                report["positions_before"] = len(positions or [])
                report["orders_before"] = len(orders)
                first = False
            report["discovery"] = found["source"]
            if not found["answered"] or size is None:
                report["errors"].extend(found["errors"])
                report["errors"].append("venue state unreadable; NOT claiming flat")
                return report

            # END-OF-SESSION OWNERSHIP, BY LINEAGE.
            #
            # This predicate previously read `contract_of(order) == contract.id`
            # and called that ownership. It is not. That rule promotes INSTRUMENT
            # COINCIDENCE into lineage, and it directly contradicts the law the
            # rest of this stack enforces -- same contract alone is UNPROVEN,
            # never cancelled, never claimed. Cancelling an operator's own
            # working order is an unrecoverable act against someone else's
            # intent, and 15:55 does not make it recoverable.
            #
            # Only a certified BOT_EXCLUSIVE_LANE could justify the broader
            # claim, and `lane_shutdown_authority` refuses to grant one.
            decision = EL.plan(position_size=size, orders=orders, owns=owns,
                               round_index=index, max_rounds=rounds,
                               discovery_complete=bool(found["complete"]))
            report["unproven"] = [o.get("id") for o in
                                  (decision.get("found") or {}).get("unproven", [])]
            action = decision["action"]

            if action == EL.ACTION_DONE:
                report["flat"] = bool(found["complete"]) and EL.is_safe_terminal(decision)
                if not found["complete"]:
                    report["errors"].append(
                        "terminal state reached on an INCOMPLETE order view; "
                        "flat is not claimed")
                return report
            if action == EL.ACTION_HALT:
                report["errors"].append(
                    f"{decision.get('state')}: {decision.get('detail')}")
                if report["unproven"]:
                    # NOT A FAILURE OF THIS FUNCTION. Working orders on our
                    # instrument that we cannot attribute are exactly what we
                    # refuse to cancel -- and refusing means the account is not
                    # provably clear, so the operator is told rather than the
                    # bot guessing in either direction.
                    report["operator_escalation"] = (
                        f"{len(report['unproven'])} working order(s) on "
                        f"{contract.id} could not be attributed to this "
                        f"session; they were NOT cancelled and the account is "
                        f"NOT proven clear")
                return report
            if action == EL.ACTION_CANCEL:
                for oid in decision.get("order_ids") or []:
                    try:
                        session.cancel_order(oid)
                        if oid not in report["cancelled"]:
                            report["cancelled"].append(oid)
                    except Exception as exc:  # noqa: BLE001
                        report["errors"].append(f"cancel {oid}: {exc}")
                continue
            if action == EL.ACTION_PROVE:
                # Terminality is proven per order, by the oracle, not by absence
                # from the next discovery pass.
                for oid in decision.get("order_ids") or []:
                    try:
                        getattr(session, "order_by_id", lambda _o: None)(oid)
                    except Exception as exc:  # noqa: BLE001
                        report["errors"].append(f"prove {oid}: {exc}")
                continue
            if action == EL.ACTION_CLOSE:
                if report["unproven"]:
                    # AN UNATTRIBUTED ORDER MAKES A CLOSE A COIN FLIP.
                    #
                    # We may not cancel it -- cancelling requires proof. So if we
                    # close the position underneath it, one of two things is
                    # true and we cannot say which:
                    #
                    #   it is the operator's       -> his order now acts against
                    #                                 a net position he did not
                    #                                 choose
                    #   it is OUR orphaned child   -> it is an ENTRY the instant
                    #                                 the account goes flat
                    #
                    # The second is the 2026-08-26 incident with the ownership
                    # proof missing instead of the ordering wrong, and that
                    # session proved the bot can fail to recognise its own
                    # children. Halting keeps the exposure -- and if the resting
                    # order IS our stop, it keeps the protection too.
                    report["errors"].append(
                        "refusing to close while unattributed exposure-changing "
                        "orders rest on this contract")
                    report["operator_escalation"] = (
                        f"{len(report['unproven'])} working order(s) on "
                        f"{contract.id} could not be attributed to this "
                        f"session. They were NOT cancelled, the position was "
                        f"NOT closed, and the account is NOT proven clear")
                    return report
                try:
                    session.close_position(contract.id)
                    report["closed"] = True
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"close: {type(exc).__name__}: {exc}")
                    return report
                continue
        report["errors"].append(f"did not converge within {rounds} rounds")
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    return report

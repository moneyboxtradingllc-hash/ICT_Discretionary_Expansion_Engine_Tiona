"""THIS LANE MAY READ A TOPSTEPX ACCOUNT. IT MAY NOT CHANGE ONE.

WHY THIS MODULE EXISTS. `COMBINED-SAFETY-READINESS-CERTIFICATION-1` halted at its
second question -- "show me every piece of code that can actually change the
account" -- and found this:

    integrations/topstepx/deterministic/loop.py
        -> TopstepXLaneClient.flatten()
        -> TopstepXBrokerAdapter.flatten()
        -> TopstepXClient.close_position(account_id, contract_id)

A bare close on a real TopstepX account, reached from a lane nobody had
certified. It performed NO canonical discovery, NO ownership classification, NO
ambiguity gate, NO child neutralisation, NO terminality proof, NO measured
exposure, NO re-read and NO safe-terminal proof -- and it was not behind
`TOPSTEPX_ARM_ORDERS`, which gates this lane's ORDER path but never gated its
flatten. Placing an order required arming; flattening a live position did not.

Worse than the shape `TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` removed, because
that one at least cancelled afterwards. This one never cancelled at all, and the
same adapter attaches brackets with `place_bracket_market_order` -- so the
account it flattens is exactly the account it gave a live stop and target to.

THE BOUNDARY IS THE BROKERAGE ACCOUNT, NOT THE ENTRYPOINT WE CALL PRODUCTION.
If code can authenticate to the same account and mutate it, it is part of that
account's safety surface whether or not anyone intends to launch it.

THE RULING (2026-08-26). This lane is not the Combine execution organism and is
not being certified as one. Rather than grow Luna's certified architecture to
absorb a second execution path, the lane's mutation authority is REMOVED. If it
is ever restored for execution, that is its own project with its own safety
certification.

FROM DENYLIST TO GRANT (TOPSTEPX-ADAPTER-CAPABILITY-BOUNDARY-1). The first
version of this module refused a VOCABULARY of known mutating names. That closed
the defect and could not prove the theorem, and the certification report had to
say both things in the same breath:

    KNOWN MUTATIONS DENIED      proven
    STRUCTURALLY READ-ONLY      NOT proven

A denylist only refuses the synonyms someone thought of; `liquidate_contract` or
`replace_order` added tomorrow would pass straight through. The boundary is now
`broker.topstepx_read_capability`, which grants an explicit read surface and
denies everything else -- so an unknown name fails CLOSED, and adding a method
to the adapter does NOT make it reachable from here.

WHY NOT JUST GATE IT ON `TOPSTEPX_ARM_ORDERS`.

    1. `flatten` already bypassed that flag, which is how this survived.
    2. An environment variable is a CONVENTION. Authority should be structural.
    3. Arming presumes the lane has an execution contract to arm. It does not.

SO THE PROHIBITION IS IN CODE. The lane holds a read-only proxy; the mutating
methods are not reachable through it, and the underlying client is wrapped too
so a caller cannot climb from `adapter._client` to a live mutation.

FAIL LOUDLY, NEVER SILENTLY. A denial is distinguishable from a transport
failure, a venue rejection, an account-pin failure and an ordinary stand-down --
because an operator debugging "why did nothing happen" must not be told the same
thing by an authority refusal and a dropped connection.
"""
from __future__ import annotations

from broker.topstepx_read_capability import (
    CAPABILITY_DENIED, ADAPTER_READS, TopstepXCapabilityDenied)
from broker.topstepx_read_capability import read_only as _grant

#: The lane this authority governs. Named in every denial so a report says WHERE
#: the refusal came from, not merely that one happened.
LANE = "ninjatrader_deterministic"

#: The denial marker. A dedicated string, not a generic error message:
#: callers and tests compare it exactly. Shared with the capability
#: boundary so one refusal has one name.
DENIED = CAPABILITY_DENIED

#: Operations this lane's own surface refuses by name, for REPORTING only.
#:
#: THIS IS NO LONGER THE BOUNDARY. The boundary is the read GRANT in
#: `broker.topstepx_read_capability`, which denies everything it did not grant.
#: This set exists so the lane's public methods can name what they refused, and
#: so a call-graph guard can look for known-bad names -- a second line, never
#: the first. Nothing is safe merely because it is absent from this list.
REFUSED_OPERATIONS = frozenset({
    "place_order", "place_order_raw", "place_bracket_market_order",
    "submit_order", "submit_market_entry", "submit_oco", "deterministic_order",
    "cancel_order", "cancel_order_by_id", "modify_order",
    "close_position", "close_position_partial", "flatten",
})

#: Back-compat alias. `MUTATIONS` was the denylist; it is now only a report.
MUTATIONS = REFUSED_OPERATIONS

#: The lane's denial and the capability denial are ONE failure, so a caller
#: catching either sees both.
TopstepXMutationAuthorityDenied = TopstepXCapabilityDenied


def denial(operation: str, *, detail: str = "") -> dict:
    """A structured refusal, for call sites that return rather than raise.

    The loop treats a falsy `accepted`/`flattened` as "nothing happened", which
    is the correct outcome -- but the reason must not be mistakable for a
    connection problem, so the authority marker travels with it.
    """
    return {"accepted": False, "flattened": False, "transmitted": False,
            "authority": DENIED, "lane": LANE, "operation": operation,
            "reason": (f"{DENIED}: this lane is read-only against TopstepX"
                       + (f" ({detail})" if detail else ""))}


def refuse(operation: str, *, detail: str = ""):
    raise TopstepXCapabilityDenied(operation, LANE, detail)


def read_only(adapter):
    """The lane's TopstepX handle: an explicit READ GRANT, nothing else.

    Everything outside `ADAPTER_READS` raises `TopstepXCapabilityDenied` --
    including names that do not exist yet, which is the whole difference between
    this and the denylist it replaced.
    """
    return _grant(adapter, label=LANE)

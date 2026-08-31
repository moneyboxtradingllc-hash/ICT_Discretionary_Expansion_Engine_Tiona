"""THE ONE ANSWER to "what orders exist, and which of them are ours".

WHY THIS MODULE EXISTS. `TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` made emergency
liquidation safe even when its caller arrives with a false picture. It did not
make the picture true. Every other consumer in this stack still asked
`/api/Order/searchOpen` and treated the answer as the complete set of orders
relevant to an open trade.

The official Gateway contract says otherwise: `searchOpen` OMITS Suspended
bracket children. So these two propositions

    "this order is not in searchOpen"
    "this order does not exist"

are different claims, and the stack has been substituting the first for the
second everywhere. The consequence is not theoretical -- production's break-even
owner flattens a live position when it cannot see an owned stop, so a Suspended
stop reads as NO PROTECTION and the response to imagined danger is to destroy a
protected trade.

WHAT IS CANONICAL HERE.

    DISCOVERY      /api/Order/v2/query, UNFILTERED
    TERMINALITY    /api/Order/searchById  (the oracle; see `topstepx_client`)
    FALLBACK       /api/Order/searchOpen, and it is labelled INCOMPLETE

    Statuses (official enum):
        0 None      1 Open      2 Filled     3 Cancelled   4 Expired
        5 Rejected  6 Pending   7 PendingCancellation      8 Suspended

    TERMINAL      Filled / Cancelled / Expired / Rejected
    WORKING       Open / Pending / PendingCancellation / Suspended
    UNKNOWN       0, absent, or any value this enum has not heard of

THREE QUESTIONS THAT ARE NOT ONE QUESTION. Conflating them is what turned a
query's silence into a safety conclusion, so they are answered separately and by
different evidence:

    A. DOES IT EXIST / IS IT DISCOVERABLE     -> `discover_orders`
    B. DOES IT BELONG TO THIS MISSION         -> `order_lineage`
    C. IS IT CURRENTLY VALID PROTECTION       -> the caller, from A + B + state

A Suspended owned stop is DISCOVERED yes, OWNED yes -- and its protective
validity is a third judgement that visibility does not grant.

NO NEGATIVE OBSERVATION UPGRADES UNKNOWN INTO ABSENCE. `complete` is carried on
every result precisely so a consumer cannot read an empty list as proof of an
empty account.
"""
from __future__ import annotations

from broker import topstepx_emergency_liquidation as EL
from broker.topstepx_client import TopstepXError

# ── status vocabulary. ONE owner, re-exported ───────────────────────────────
# `topstepx_emergency_liquidation` is the certified safety authority for these
# values and its handling of them is regression-bound. Re-exporting rather than
# re-declaring is what keeps a second, quietly divergent enum from appearing;
# `tests/test_topstepx_protective_discovery.py` proves `topstepx_client` agrees.
STATUS_NONE = EL.STATUS_NONE
STATUS_OPEN = EL.STATUS_OPEN
STATUS_FILLED = EL.STATUS_FILLED
STATUS_CANCELLED = EL.STATUS_CANCELLED
STATUS_EXPIRED = EL.STATUS_EXPIRED
STATUS_REJECTED = EL.STATUS_REJECTED
STATUS_PENDING = EL.STATUS_PENDING
STATUS_PENDING_CANCELLATION = EL.STATUS_PENDING_CANCELLATION
STATUS_SUSPENDED = EL.STATUS_SUSPENDED

TERMINAL_STATUSES = EL.TERMINAL_STATUSES
WORKING_STATUSES = EL.ACTIVE_STATUSES

#: Discovery provenance. The degraded string is deliberately shouty because it
#: travels into reports an operator reads at 15:55.
COMPLETE = "query_orders"
INCOMPLETE = "open_orders_fallback_INCOMPLETE"
UNREADABLE = "unreadable"

#: Lineage verdicts. `UNPROVEN` is not a weak `FOREIGN`: it is an order on OUR
#: instrument that we cannot account for, which might be our own orphaned
#: bracket. It may never be cancelled and may never be ignored.
OWNED = "owned"
UNPROVEN = "unproven"
FOREIGN = "foreign"

#: Tri-state protection presence, so that "we could not see" stops being spelled
#: the same way as "there is none".
PRESENT = "present"
ABSENT = "absent"
UNKNOWN = "unknown"


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def _field(order, *names):
    """First present value among `names`. Tolerates both dialects.

    `TopstepXClient` normalises to snake_case, but `recent_trades()` returns raw
    venue JSON and hand-built payloads carry camelCase. Reading both is a
    decoding concern; it is not a licence to invent a value that is absent.
    """
    if not isinstance(order, dict):
        return None
    for name in names:
        got = order.get(name)
        if got is not None:
            return got
    return None


def contract_of(order):
    return _field(order, "contract_id", "contractId")


def status_of(order):
    """The venue's status, or None when it did not state one.

    None is returned both for a MISSING status and for a status of 0, which the
    official enum calls `None`. To a consumer they mean the same thing: the
    venue has not said what this order is doing.
    """
    got = _int(_field(order, "status"))
    return None if got == STATUS_NONE else got


def is_terminal(order) -> bool:
    """POSITIVELY finished. An unrecognised or absent status is never terminal."""
    return status_of(order) in TERMINAL_STATUSES


def is_working(order) -> bool:
    """Could this order still do something to the account?

    Fail-OPEN into visibility, deliberately: a status we do not recognise is
    treated as possibly-working. Being wrong in this direction leaves a dead
    order in a list, which `searchById` can resolve. Being wrong in the other
    direction hides an armed order, which is the defect class that cost $307.50.
    """
    return not is_terminal(order)


def working_orders(orders) -> list:
    """Only what could still act.

    Discovery returns terminal rows too -- v2/query is a history surface as well
    as a live one -- and a consumer that counts "working orders" must not
    suddenly start counting this morning's fills.
    """
    return [o for o in (orders or []) if is_working(o)]


def discover_orders(session, *, contract_id=None) -> dict:
    """Every order the venue will admit to, plus how far the list may be trusted.

    Returns:
        orders     everything discovered (terminal rows included)
        working    the subset that could still change the account
        complete   True ONLY from the unfiltered v2/query surface
        source     COMPLETE / INCOMPLETE / UNREADABLE
        answered   whether the venue answered at all
        errors     every failure, recorded rather than swallowed

    NO STATUS FILTER IS APPLIED. Asking only for the statuses we currently
    recognise would let the venue hide a state simply because our enum has not
    heard of it: the filter would strip the row before any consumer could call
    it UNKNOWN. Classification happens here, locally, where the value survives.
    """
    out = {"orders": None, "working": None, "complete": False,
           "source": UNREADABLE, "answered": False, "errors": []}

    query = getattr(session, "query_orders", None)
    if query is not None:
        try:
            rows = query(contract_id=contract_id)
            if rows is not None:
                out.update(orders=list(rows), working=working_orders(rows),
                           complete=True, source=COMPLETE, answered=True)
                return out
            out["errors"].append("query_orders returned None")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"query_orders: {type(exc).__name__}: {exc}")
    else:
        out["errors"].append("query_orders unavailable")

    legacy = getattr(session, "open_orders", None)
    if legacy is None:
        out["errors"].append("open_orders unavailable")
        return out
    try:
        rows = legacy()
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"open_orders: {type(exc).__name__}: {exc}")
        return out
    if rows is None:
        out["errors"].append("open_orders returned None")
        return out
    if contract_id is not None:
        rows = [o for o in rows if _same(contract_of(o), contract_id)]
    # ANSWERED, BUT NOT COMPLETE. `searchOpen` omits Suspended bracket children
    # by contract, so this list can be silent about protection that exists.
    out.update(orders=list(rows), working=working_orders(rows),
               complete=False, source=INCOMPLETE, answered=True)
    return out


def require_working_orders(session, *, contract_id=None) -> list:
    """Working orders, or RAISE. For every caller that is not the emergency path.

    `discover_orders` never throws, which is right where it is used: an
    exception mid-liquidation is worse than a labelled degraded read. But most
    callers here REPLACED a call that did throw -- `session.open_orders()` --
    and their surrounding code treats a returned list as a venue answer.

    Handing those callers `[]` for an unreadable venue converts "we cannot see"
    into "there is nothing there", which is the exact substitution this whole
    unit removes. Worse, the two gates that decide whether a trade may be placed
    both read a count: an empty list there does not merely lose information, it
    grants entry authority against a venue nobody could read.
    """
    found = discover_orders(session, contract_id=contract_id)
    if not found["answered"]:
        raise TopstepXError(
            "order discovery unavailable: " + ("; ".join(found["errors"])
                                               or "no order surface answered"))
    return found["working"] or []


def order_lineage(order, *, entry_order_id=None, contract_id=None,
                  custom_tag: str = "", token_id: str = "") -> str:
    """OWNED / UNPROVEN / FOREIGN, from POSITIVE evidence only.

    Accepted proof, in the venue's own terms:

        parent_order_id == our entry id     the venue built this child FOR us
        linked_order_id == our entry id     the OCO relationship it published
        custom_tag exactly ours, or ours + "-"    our own submission marking
        token_id present inside the tag     the authorization that bought it

    SAME CONTRACT IS NOT OWNERSHIP. An operator trading MNQ beside us produces
    orders indistinguishable by instrument, side and size; only lineage
    separates them. So a same-contract order with no lineage is UNPROVEN --
    never cancelled, never claimed, and never dismissed.
    """
    if not isinstance(order, dict):
        return FOREIGN
    if contract_id is not None and not _same(contract_of(order), contract_id):
        return FOREIGN

    if entry_order_id is not None:
        for key in ("parent_order_id", "parentOrderId",
                    "linked_order_id", "linkedOrderId"):
            if _same(order.get(key), entry_order_id):
                return OWNED

    tag = str(_field(order, "custom_tag", "customTag") or "")
    if custom_tag and (tag == custom_tag or tag.startswith(f"{custom_tag}-")):
        return OWNED
    if token_id and tag and str(token_id) in tag:
        return OWNED
    return UNPROVEN


def owns(order, **kw) -> bool:
    """Boolean face of `order_lineage`, for callers that only cancel."""
    return order_lineage(order, **kw) == OWNED


def lineage_orders(orders, *, contract_id, entry_order_id,
                   custom_tag: str = "", token_id: str = "") -> list:
    """Our children among `orders`, by the ONE ownership contract above."""
    if entry_order_id is None and not custom_tag and not token_id:
        return []
    return [o for o in orders or []
            if order_lineage(o, entry_order_id=entry_order_id,
                             contract_id=contract_id, custom_tag=custom_tag,
                             token_id=token_id) == OWNED]


def protection_presence(*, stop, complete: bool) -> str:
    """PRESENT / ABSENT / UNKNOWN -- the distinction the break-even path turns on.

    An absent stop under an INCOMPLETE discovery is UNKNOWN, never ABSENT: the
    one thing `searchOpen` is documented to hide is exactly a staged protective
    child. Only a complete surface may say ABSENT.
    """
    if stop is not None:
        return PRESENT
    return ABSENT if complete else UNKNOWN

"""SESSION-CAP-GRACEFUL-SHUTDOWN-1 — when is the organism allowed to stop?

THE LAW: **trade authority can end before process responsibility ends.**

Once the session's attempt allowance is irreversibly consumed the bot is done
thinking about new trades, but it remains responsible for anything it already
created. Only FRESH venue truth proving no exposure and no unresolved owned
orders may end the process.

WHAT 2026-08-25 SHOWED. Attempt #2 was consumed at 10:49. The process then
printed `SESSION_COMPLETE` 160 times over ~19 minutes and had to be killed
externally, because `should_continue` kept the loop alive for the whole decision
window regardless of cap state, and nothing anywhere could conclude "my job is
finished, shut down". There was no terminal transition at all -- only a terminal
LABEL, reprinted forever.

TWO INDEPENDENT FACTS, NEVER COLLAPSED:

    entry authority exhausted   -- may I still open a NEW trade?
    responsibility remains      -- do I still owe something already created?

Their four combinations are the whole state machine:

    not exhausted                     -> TRADING_ACTIVE
    exhausted + responsibility        -> MANAGEMENT_ONLY
    exhausted + venue unknown         -> WAITING_FOR_VENUE_TRUTH  (fail closed)
    exhausted + proven clean          -> SESSION_COMPLETE  -> cooperative exit

WHY THIS IS NOT `mission.state == COMPLETE`. On 2026-08-25 T2 reported
COMPLETE/flat while the venue held LONG 5 MNQ. `045c472` repaired that defect,
but session lifecycle must stay independently safe against a stale or corrupt
derived record: shutdown asks the VENUE, and a mission's own opinion can only
ever ADD responsibility, never subtract it.

UNKNOWN IS NOT CLEAN. A failed, unavailable or unanswerable venue read keeps the
process alive. The same rule the reconciler now enforces for flat.
"""
from __future__ import annotations

from broker import topstepx_mission_state as MS
from broker import topstepx_mission_reconciler as RECON

TRADING_ACTIVE = "TRADING_ACTIVE"
ENTRY_AUTHORITY_EXHAUSTED = "SESSION_ENTRY_AUTHORITY_EXHAUSTED"
MANAGEMENT_ONLY = "SESSION_MANAGEMENT_ONLY"
WAITING_FOR_VENUE_TRUTH = "SESSION_WAITING_FOR_VENUE_TRUTH"
SESSION_COMPLETE = "SESSION_COMPLETE"

#: Modes in which the process must stay alive and must NOT open a new trade.
MANAGING_MODES = frozenset({MANAGEMENT_ONLY, WAITING_FOR_VENUE_TRUTH})


def entry_authority_exhausted(mission) -> bool:
    """Has the session's attempt allowance been irreversibly consumed?

    Uses the EXISTING durable authority `ProductionSessionMission.trades_used()`
    -- derived from the mission records on disk, so it survives process death
    and cannot be reset by a restart. No parallel RAM counter is introduced.

    The cap is spent by ATTEMPTED trade authority, not by fills or by winners.
    2026-08-25 T1 is the proof: it filled, failed to establish protection,
    auto-flattened, and still consumed attempt #1.
    """
    try:
        allowance = int(mission.authorization.maximum_trades)
        return int(mission.trades_used()) >= allowance
    except Exception:  # noqa: BLE001 — an unreadable allowance is not permission
        return False


def unresolved_missions(mission) -> list:
    """Missions the venue has not yet proven terminal. Responsibility, not state."""
    try:
        return [m for m in (mission.trade_missions or [])
                if m.state not in MS.TERMINAL_STATES]
    except Exception:  # noqa: BLE001
        return []


def _owned_order_ids(mission) -> set:
    out = set()
    try:
        for m in (mission.trade_missions or []):
            if m.order_id is not None:
                out.add(str(m.order_id))
    except Exception:  # noqa: BLE001
        pass
    return out


def classify_orders(orders, *, contract_id, mission) -> dict:
    """Split governed-contract working orders into ours and unexplained.

    OURS is the repaired lineage from `045c472`: a child whose `parent_order_id`
    is one of this session's entry orders. UNEXPLAINED is any other working
    order on the governed contract.

    Both block shutdown, for different reasons. Ours is obvious. Unexplained is
    the subtler one: an order on our account and contract that we cannot prove
    is ours may still be orphaned risk WE created, and exiting past it would
    abandon exposure on the theory that we could not identify it. Ambiguity is
    resolved toward staying alive -- never toward declaring ourselves finished.
    """
    entries = _owned_order_ids(mission)
    ours, unexplained = [], []
    for order in orders or []:
        if not RECON._same(RECON._contract_of(order), contract_id):  # noqa: SLF001
            continue                        # a different instrument is not ours
        parent = order.get("parent_order_id")
        oid = order.get("id")
        if (parent is not None and str(parent) in entries) or \
                (oid is not None and str(oid) in entries):
            ours.append(order)
        else:
            unexplained.append(order)
    return {"ours": ours, "unexplained": unexplained}


def resolve(*, mission, venue, contract_id) -> dict:
    """The session's current lifecycle mode, from durable + venue truth.

    Pure decision: it reads the venue and reports. It cancels nothing, closes
    nothing and never mutates a mission -- this unit decides WHETHER the process
    may stop, never HOW to flatten. No cancellation authority is invented here.
    """
    if not entry_authority_exhausted(mission):
        return {"mode": TRADING_ACTIVE, "exhausted": False, "reasons": [],
                "exposure": None, "owned_orders": None, "unexplained_orders": None,
                "venue_known": None, "may_exit": False}

    reasons = []
    unresolved = unresolved_missions(mission)
    if unresolved:
        reasons.append(
            "unresolved mission "
            + ", ".join(f"{m.mission_id}({m.state})" for m in unresolved))

    seen = RECON.MissionReconciler(venue=venue, contract_id=contract_id).observe()
    known = bool(seen.get("positions_answered")) and bool(seen.get("orders_answered"))
    if not known:
        # FAIL CLOSED. We cannot see the venue, so we cannot claim to be done.
        reasons.append("venue truth unavailable: "
                       + "; ".join(seen.get("errors") or ["no answer"]))
        return {"mode": WAITING_FOR_VENUE_TRUTH, "exhausted": True,
                "reasons": reasons, "exposure": None, "owned_orders": None,
                "unexplained_orders": None, "venue_known": False,
                "may_exit": False, "errors": seen.get("errors") or []}

    exposure = RECON.position_size(seen["positions"], contract_id)
    split = classify_orders(seen["orders"], contract_id=contract_id, mission=mission)
    if exposure:
        reasons.append(f"venue exposure {exposure}")
    if split["ours"]:
        reasons.append("working protective orders "
                       + ", ".join(str(o.get("id")) for o in split["ours"]))
    if split["unexplained"]:
        reasons.append("unexplained working orders on the governed contract "
                       + ", ".join(str(o.get("id")) for o in split["unexplained"]))

    clean = not exposure and not split["ours"] and not split["unexplained"] \
        and not unresolved
    return {"mode": SESSION_COMPLETE if clean else MANAGEMENT_ONLY,
            "exhausted": True, "reasons": reasons, "exposure": exposure,
            "owned_orders": [o.get("id") for o in split["ours"]],
            "unexplained_orders": [o.get("id") for o in split["unexplained"]],
            "venue_known": True, "may_exit": clean,
            "errors": seen.get("errors") or []}

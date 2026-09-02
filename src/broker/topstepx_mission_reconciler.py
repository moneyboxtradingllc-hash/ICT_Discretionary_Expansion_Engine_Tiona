"""Venue reality -> durable mission reality. The subsystem V13 did not have.

WHAT WAS MISSING. `ProductionLoop.reconcile_after_fill` / `reconcile_after_exit`
existed, and the second even carried the `COMPLETE` transition -- but repo-wide
their only callers were in `tests/test_production_scan_loop.py`. Production
never called them, `scan_once` never reconciled anything, and there was no fill,
exit or position observer of any kind. On 2026-08-11 order 3391019204 filled and
stopped out for -$138.30 while its mission still read ATTEMPT_CONSUMED. Because
`ATTEMPT_CONSUMED` is not terminal, `active_mission` wedged and the session's
second authorized trade became permanently unreachable.

WHY THIS IS A SEPARATE OWNER. Those two methods are MEASUREMENT and LINEAGE --
slippage observation, execution context, trade lineage. Lifecycle authority was
bolted onto one of them. Wiring them into production would have put the durable
state machine inside the slippage recorder. Measurement stays where it is; this
module owns the ladder, and nothing else does.

OBSERVATION MODEL: authoritative REST reads on the existing session, not a
stream. `topstepx_realtime.py` does implement a user hub with
SubscribeOrders/Positions/Trades, but production has never connected it (only
the readiness preflight does), and adding it would introduce a second account
authority whose dropped frames become silent lifecycle gaps. The venue's own
answer to "what positions and orders do I have" cannot drop a frame, and it
re-derives correctly after a restart instead of depending on events that were
delivered to a process that no longer exists. The hub can be added later as an
accelerator without changing this contract.

CONSEQUENCE OF COARSE OBSERVATION. A scan tick is 60 seconds and today's entire
trade was born and stopped out inside one. So a single pass may advance several
rungs -- ACK -> POSITION_OPEN -> EXIT -> COMPLETE -- and each one is written,
in order, with its evidence. History stays complete even when observation was
not continuous. What a pass may never do is walk the ladder backward: "no
position this tick" is not evidence that no position ever existed.

═══════════════════════════════════════════════════════════════════════════════
MISSION-RECONCILIATION-VENUE-TRUTH-1 (2026-08-25). Two proven defects, one
common consequence: mission truth could diverge from venue truth.

**A -- THIS MODULE WAS BLIND TO THE PRODUCTION OBJECT GRAPH.** `TopstepXClient`
normalises venue JSON to snake_case; every selector here read camelCase. Fed the
real `open_positions()` output, `position_for` returned `{}` -- so `size` was
ALWAYS 0. Fed the real `open_orders()` output, `lineage_orders` returned `[]`
-- it required `customTag`, which the normalised order contract does not publish
at all. Both guards were structurally dead, so every mission raced to COMPLETE
as soon as an entry fill appeared in trade history. On 2026-08-25 T2 completed
as `flat` while the venue held LONG 5 MNQ with a live stop (29192.00) and target
(29409.25). T1 completed correctly only because it happened to be genuinely
flat -- the bug hid itself. `protective_order_ids` was empty on BOTH missions:
that was never a one-off, lineage could not be seen at all.

The tests passed because they hand-built `contractId` / `averagePrice` /
`customTag` dicts -- an object graph production never emits. **Fixtures here are
now built from the real client shapes.**

**B -- `classify_exit` STOLE OTHER MISSIONS' TRADES.** It returned the first
account trade whose orderId was not this mission's own entry. T2 therefore
recorded T1's ENTRY (order 3446530387 @ 29229.50) as its own exit. Identity now
comes from lineage, never from "the next trade that isn't mine".

TWO LAWS FALL OUT, and they are separate epistemic claims:

    FLAT is a POSITIVE venue fact, never the absence of something a selector
    failed to match. Unknown venue state is not flat.

    An exit may populate price/order id only if it is positively bound to THIS
    mission. "The position is closed" and "we know which execution closed it"
    are different claims; the second may be UNATTRIBUTED without weakening the
    first.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from broker import topstepx_mission_state as MS
from broker import topstepx_order_discovery as DISC

#: What closed the position. `EXIT_UNCLASSIFIED` is deliberate: we know the
#: position closed and cannot yet say which leg did it. A guess here would put
#: a fabricated cause into permanent history.
EXIT_STOP = "stop"
EXIT_TARGET = "target"
EXIT_UNCLASSIFIED = "closed"
#: Venue-proven flat, with no trade that can be bound to this mission -- a
#: manual close is the ordinary cause. Distinct from `EXIT_UNCLASSIFIED`, which
#: still names a real execution we could not classify into stop/target.
EXIT_UNATTRIBUTED = "unattributed"

#: `TopstepXClient.open_orders()` publishes the venue's numeric order type.
ORDER_TYPE_LIMIT = 1
ORDER_TYPE_STOP = 4


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def _contract_of(obj) -> object:
    """THE CANONICAL KEY, with one narrow tolerance.

    `TopstepXClient` normalises to `contract_id`; that is the production
    contract and what this module is written against. `contractId` is accepted
    only as a fallback because `recent_trades()` returns RAW venue JSON while
    positions and orders are normalised -- one module therefore legitimately
    sees both dialects. This is not a compatibility shim for the old tests.
    """
    if not isinstance(obj, dict):
        return None
    got = obj.get("contract_id")
    return got if got is not None else obj.get("contractId")


def position_for(positions: list, contract_id: str) -> dict:
    for pos in positions or []:
        if _same(_contract_of(pos), contract_id):
            return pos
    return {}


def position_size(positions: list, contract_id: str) -> int:
    """Absolute exposure for the governed contract. 0 means the venue answered
    and showed none -- callers must separately know the read SUCCEEDED."""
    return abs(_int(position_for(positions, contract_id).get("size")) or 0)


def lineage_orders(orders: list, *, contract_id: str, entry_order_id,
                   custom_tag: str = "", token_id: str = "") -> list:
    """OUR working orders: the venue's own children of OUR entry order.

    Ownership used to be asserted via `customTag`, which the normalised order
    contract never publishes -- so this returned `[]` for every mission ever
    run. The venue does publish `parent_order_id`, and a bracket's stop and
    target are created by the venue AS CHILDREN OF THE ENTRY. That relationship
    is observable, unforgeable by another mission (a different entry has a
    different order id), and was confirmed live on 2026-08-25: entry 3446535520
    -> stop 3446535522 / target 3446535523.

    A foreign order on the same contract has a different parent and is somebody
    else's, which is the property the old customTag rule was reaching for.

    TOPSTEP-PROTECTIVE-DISCOVERY-AND-LINEAGE-1: the rule itself now lives in
    `topstepx_order_discovery`, because two ownership implementations that
    disagree are worse than either one alone -- this module accepted only
    `parent_order_id` while the execution runner also accepted `linkedOrderId`
    and the submission tag, so the same order could be OURS to one subsystem and
    a stranger to the other. One contract, both callers.
    """
    return DISC.lineage_orders(orders, contract_id=contract_id,
                               entry_order_id=entry_order_id,
                               custom_tag=custom_tag, token_id=token_id)


def fills_for_order(trades: list, order_id) -> list:
    return [t for t in trades or [] if _same(t.get("orderId"), order_id)]


def classify_exit(trades: list, mission) -> tuple:
    """(exit_type, price, order_id) -- POSITIVELY BOUND TO THIS MISSION ONLY.

    The previous rule was "the first trade whose orderId is not my entry",
    which is not an identity test at all: with two missions in one session it
    hands mission B whatever mission A did. On 2026-08-25 that wrote T1's ENTRY
    price and order id into T2's exit.

    Identity now comes from the mission's own protective children. Anything not
    bound to them is UNATTRIBUTED with a null price -- never a borrowed number.
    Price is not evidence of ownership; neither is recency, side or quantity.
    """
    protective = {str(o) for o in (mission.protective_order_ids or []) if o is not None}
    # THE PARENT IS NEVER ITS OWN EXIT. Belt and braces beside
    # `protective_child_ids`: a mission PERSISTED before that filter existed
    # restores a contaminated list from disk, and this function is the one that
    # turns the list into an exit identity. Excluding the entry here means an
    # already-written record cannot resurrect the defect on the next restart.
    entry = getattr(mission, "order_id", None)
    if entry is not None:
        protective.discard(str(entry))
    if not protective:
        return EXIT_UNATTRIBUTED, None, None
    stop_ids = {str(o) for o in (getattr(mission, "stop_order_ids", None) or [])}
    target_ids = {str(o) for o in (getattr(mission, "target_order_ids", None) or [])}
    for trade in reversed(trades or []):
        oid = trade.get("orderId")
        if oid is None or str(oid) not in protective:
            continue
        price = trade.get("price")
        if str(oid) in stop_ids:
            return EXIT_STOP, price, oid
        if str(oid) in target_ids:
            return EXIT_TARGET, price, oid
        return EXIT_UNCLASSIFIED, price, oid
    return EXIT_UNATTRIBUTED, None, None


def _merge(known, seen) -> list:
    """Union, order-preserving. NEVER a replacement.

    A protective identity is HISTORY once observed. Overwriting the list with
    whatever the current tick happens to see deletes the stop id at exactly the
    moment the exit needs it: the tick that watches a bracket resolve is the
    tick on which its children vanish from active discovery.
    """
    out = list(known or [])
    have = {str(o) for o in out}
    for oid in seen or []:
        if oid is not None and str(oid) not in have:
            out.append(oid)
            have.add(str(oid))
    return out


def _ids(orders: list) -> list:
    return [o.get("id") for o in orders or [] if o.get("id") is not None]


def protective_child_ids(orders: list, *, entry_order_id) -> list:
    """The mission's protective CHILDREN -- never the entry parent.

    LUNA-PROTECTIVE-CHILD-LINEAGE-1 (2026-09-02). `lineage_orders` answers
    "which orders are OURS", and the entry qualifies on its own `custom_tag`.
    Feeding that set straight into `protective_order_ids` made the parent a
    member of its own protective children, and `classify_exit` -- which trusts
    that set as exit authority -- then bound the ENTRY as the mission's exit:

        exit_order_id  3479178244   the entry order
        exit_price     29097.75     the ENTRY fill price
        exit_type      closed

    while the real closing order was a venue-minted flatten the mission never
    learned about. A mission lineage set and a protective-children set are
    different claims: the first says "we own this", the second says "this can
    close the position". Only the second may answer which leg ended a trade.

    Filtering by IDENTITY, not by order type: a protective child is defined by
    not being the parent, so an unrecognised child type is still carried
    (that is what kept a Suspended bracket leg in the lineage), while the
    parent is excluded no matter how it presents itself.
    """
    return [oid for oid in _ids(orders)
            if entry_order_id is None or not _same(oid, entry_order_id)]


def split_protective(orders: list) -> tuple:
    """(stop_ids, target_ids) from the venue's own order types."""
    stops = [o.get("id") for o in orders or []
             if _int(o.get("type")) == ORDER_TYPE_STOP and o.get("id") is not None]
    targets = [o.get("id") for o in orders or []
               if _int(o.get("type")) == ORDER_TYPE_LIMIT and o.get("id") is not None]
    return stops, targets


class MissionReconciler:
    """Advances ONE mission against authoritative venue state.

    `venue` needs `open_positions()`, order discovery, and `recent_trades()`.
    The last is optional -- absence costs fill prices and exit classification,
    never correctness of the ladder.

    ORDER DISCOVERY IS `query_orders()`, not `open_orders()`. The legacy
    endpoint remains an accepted fallback and is labelled INCOMPLETE when used,
    because `searchOpen` omits Suspended bracket children by venue contract --
    and a mission may not be closed out on a view that can be silent about a
    child still resting at the venue.
    """

    def __init__(self, *, venue, contract_id: str, clock=None):
        self.venue = venue
        self.contract_id = contract_id
        self.clock = clock

    # ── venue reads, each failing LOUD rather than defaulting to empty ────────
    def _read(self, name: str, default):
        """Returns (value, error, answered).

        `answered` is the load-bearing part: a venue object that does not
        implement the read has NOT told us there are no positions. Collapsing
        "cannot ask" into an empty list is precisely how a live position becomes
        a closed mission.
        """
        fn = getattr(self.venue, name, None)
        if fn is None:
            return default, f"{name} unavailable", False
        try:
            return fn(), None, True
        except Exception as exc:  # noqa: BLE001
            # An unreadable venue is UNKNOWN, never flat.
            return None, f"{name} failed: {type(exc).__name__}: {exc}", False

    def observe(self) -> dict:
        """Venue truth, with the completeness of the order view stated openly.

        `orders` is the WORKING subset -- the ladder counts what can still act,
        and v2/query is a history surface too, so an unfiltered list would keep
        a mission out of COMPLETE forever on the strength of this morning's
        already-filled stop. `all_orders` carries the terminal rows so lineage
        can still be recovered from a child that has already died.

        `orders_complete` is the load-bearing new fact. `searchOpen` omits
        Suspended bracket children by contract, so an empty list from that
        surface is a gap in the QUERY and never evidence about the ACCOUNT.
        """
        positions, perr, pok = self._read("open_positions", [])
        trades, terr, _ = self._read("recent_trades", [])
        found = DISC.discover_orders(self.venue, contract_id=self.contract_id)
        oerr = "; ".join(found["errors"]) if found["errors"] else None
        ook = bool(found["answered"])
        orders = found["working"]
        return {"positions": positions, "orders": orders,
                "all_orders": found["orders"] or [], "trades": trades or [],
                "errors": [e for e in (perr, oerr, terr) if e],
                "positions_answered": pok and positions is not None,
                "orders_answered": ook and orders is not None,
                "orders_complete": bool(found["complete"]),
                "discovery": found["source"],
                "readable": pok and ook
                and positions is not None and orders is not None}

    def reconcile(self, mission, *, custom_tag: str = "") -> dict:
        """Advance the mission as far as the venue's own state justifies.

        Returns what was observed and which transitions were written. Never
        raises: a reconciliation that throws mid-ladder would leave the record
        it was trying to repair in a worse state than it found it.

        `custom_tag` is accepted for call-compatibility and is no longer used
        for ownership -- see `lineage_orders`.
        """
        applied, refused = [], []
        if mission is None:
            return {"skipped": "no mission", "applied": applied}
        if mission.state in MS.TERMINAL_STATES:
            return {"skipped": f"terminal ({mission.state})", "applied": applied}

        seen = self.observe()
        if not seen["readable"]:
            # Explicitly NOT a state change. We learned nothing this tick.
            return {"skipped": "venue unreadable", "errors": seen["errors"],
                    "applied": applied}

        positions, orders, trades = seen["positions"], seen["orders"], seen["trades"]
        size = position_size(positions, self.contract_id)
        ours = lineage_orders(orders, contract_id=self.contract_id,
                              entry_order_id=mission.order_id,
                              custom_tag=custom_tag)
        # LINEAGE IS RECOVERED FROM HISTORY, NOT ONLY FROM LIVE ORDERS.
        # `ours` is the WORKING set and is empty the moment a bracket resolves.
        # On 2026-08-26 the entry filled and the position closed inside a single
        # 60-second tick, so the only reconciliation this mission ever got saw
        # zero working children -- and `protective_order_ids` stayed empty,
        # which left the exit permanently UNATTRIBUTED. A child that has already
        # died is still OUR child, and its identity is still the evidence for
        # which leg closed the trade.
        every = lineage_orders(seen.get("all_orders") or [],
                               contract_id=self.contract_id,
                               entry_order_id=mission.order_id,
                               custom_tag=custom_tag)
        # Carried for `classify_exit`; ONE owner of the stop/target split.
        # ONLY WHEN OBSERVED. The tick that sees the exit usually sees the
        # working orders already gone, so overwriting unconditionally would
        # erase the split at exactly the moment the exit needs it and demote a
        # knowable stop-fill to "closed".
        if every:
            stop_ids, target_ids = split_protective(every)
            mission.stop_order_ids = _merge(getattr(mission, "stop_order_ids", None),
                                            stop_ids)
            mission.target_order_ids = _merge(
                getattr(mission, "target_order_ids", None), target_ids)

        def step(fn, label, **kwargs):
            try:
                fn(**kwargs)
                applied.append(label)
            except MS.MissionStateError as exc:
                refused.append(f"{label}: {exc}")

        # ── rung: the position is open ───────────────────────────────────────
        if size and MS.lifecycle_rank(mission.state) < MS.lifecycle_rank(MS.POSITION_OPEN):
            entry_fills = fills_for_order(trades, mission.order_id)
            pos = position_for(positions, self.contract_id)
            step(mission.observe_position_open, MS.POSITION_OPEN,
                 filled_quantity=size,
                 fill_price=(entry_fills[-1].get("price") if entry_fills
                             else pos.get("avg_price", pos.get("averagePrice"))),
                 protective_order_ids=protective_child_ids(
                     every, entry_order_id=mission.order_id),
                 evidence=f"venue position size {size}")
        elif size and every:
            mission.observe_protection(
                protective_order_ids=protective_child_ids(
                    every, entry_order_id=mission.order_id),
                evidence="venue working orders")

        # ── rung: it closed ──────────────────────────────────────────────────
        # Only meaningful once the venue has acknowledged an order. A mission
        # that never got an order id is flat because it never traded, and
        # calling that an exit would invent a trade.
        #
        # `positions_answered` is required: "no position" may only be read off a
        # venue answer we actually received.
        acknowledged = mission.order_id is not None
        if acknowledged and seen["positions_answered"] and not size \
                and MS.lifecycle_rank(mission.state) >= \
                MS.lifecycle_rank(MS.VENUE_ACKNOWLEDGED):
            if MS.lifecycle_rank(mission.state) < MS.lifecycle_rank(
                    MS.EXIT_PENDING_RECONCILIATION):
                # Reached POSITION_OPEN or not, the position is gone now. If we
                # never saw it open, the ladder still has to pass through the
                # rung -- history records what happened, not what we watched.
                if MS.lifecycle_rank(mission.state) < MS.lifecycle_rank(MS.POSITION_OPEN):
                    entry_fills = fills_for_order(trades, mission.order_id)
                    if entry_fills:
                        # PROTECTIVE IDS TRAVEL ON THIS RUNG TOO.
                        # This branch fires when the fill is visible only in
                        # trade history because the position had already closed
                        # -- and it USED TO OMIT `protective_order_ids`
                        # ENTIRELY. It is the branch mission PRAC-20260826-T1
                        # actually took ("venue trade history (fill seen only
                        # after close)"), which is why its protective ids are
                        # empty and its exit is `unattributed`. A rung that
                        # cannot carry lineage guarantees the lineage is lost.
                        step(mission.observe_position_open, MS.POSITION_OPEN,
                             filled_quantity=abs(_int(entry_fills[-1].get("size")) or 1),
                             fill_price=entry_fills[-1].get("price"),
                             protective_order_ids=protective_child_ids(
                                 every, entry_order_id=mission.order_id),
                             evidence="venue trade history (fill seen only after close)")
                if MS.lifecycle_rank(mission.state) >= MS.lifecycle_rank(MS.POSITION_OPEN):
                    kind, price, oid = classify_exit(trades, mission)
                    step(mission.observe_exit, MS.EXIT_PENDING_RECONCILIATION,
                         exit_type=kind, exit_price=price, exit_order_id=oid,
                         evidence=("venue reports no open position"
                                   if kind != EXIT_UNATTRIBUTED else
                                   "venue reports no open position; no trade "
                                   "bound to this mission (exit unattributed)"))

        # ── rung: terminal ───────────────────────────────────────────────────
        # POSITIVE PROOF ONLY. Both reads must have been answered; a selector
        # that matched nothing because it was looking at the wrong shape is not
        # evidence of anything.
        if (mission.state == MS.EXIT_PENDING_RECONCILIATION
                and seen["positions_answered"] and seen["orders_answered"]
                # COMPLETENESS IS PART OF THE PROOF. "No working lineage order"
                # read off `searchOpen` is compatible with a Suspended child
                # still resting at the venue, and closing the mission on that
                # basis is how a live order becomes an orphan nobody owns.
                and seen.get("orders_complete")
                and not size and not ours):
            step(mission.reconcile_flat, MS.COMPLETE,
                 positions=len([p for p in positions
                                if _same(_contract_of(p), self.contract_id)]),
                 working_orders=len(ours),
                 evidence="venue flat, no lineage orders working")

        return {"state": mission.state, "applied": applied, "refused": refused,
                "position_size": size, "lineage_orders": len(ours),
                "lineage_known": len(every), "discovery": seen.get("discovery"),
                "orders_complete": bool(seen.get("orders_complete")),
                "errors": seen["errors"]}

"""DAILY LOSS BUDGET — a spending limit on NEW ENTRY, not a promise about fills.

LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 (2026-08-31).

WHAT THIS IS. Before a new trade may be sized, the session's realized loss so
far is subtracted from a signed budget, and what remains becomes an additional
ceiling on planned risk:

    allowed_planned_risk = min(PRODUCTION_MAX_RISK_USD, remaining_daily_room)

WHAT THIS IS NOT, AND THE DISTINCTION IS THE WHOLE POINT. It is NOT a guaranteed
maximum realized loss. A protective stop becomes a market order when it
triggers; a gap fills it wherever the book is. If a stop slips and the session
realizes -$760 against a $725 budget, this governor did not fail and must never
claim it prevented the overshoot. What it does is refuse the NEXT entry.

That is still materially stronger than what existed before. The prior law was
two attempts x $350 PLANNED, which would happily authorize a full second $350
trade after the first one slipped well past its planned loss.

OWNERSHIP IS PROVEN, NEVER ASSUMED. Realized P&L counts only from venue trades
whose order is positively OWNED by this session's certified lineage --
`parent_order_id`, `linked_order_id`, our `custom_tag`, or our `token_id`. Same
contract is not ownership. A practice-account POLICY that says nobody trades
manually is not a mechanism, and this account's own history proves the point: it
carries four 15-lot manual fills from 2026-08-28 that no lineage would claim.

    unattributable in-session trade  ->  CONTAMINATED  ->  no new entry
    incomplete discovery             ->  UNKNOWN       ->  no new entry
    venue unreadable                 ->  UNKNOWN       ->  no new entry

MANAGEMENT IS NEVER GOVERNED. This decides whether a NEW position may be opened.
Protective stops, targets, break-even and safety convergence all run earlier in
the tick by existing SESSION-CAP-GRACEFUL-SHUTDOWN-1 ordering, so an exhausted
or unknown budget cannot reach them.

Pure except for `resolve`, which reads the venue. Never raises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from broker import topstepx_order_discovery as DISC

SCHEMA = "daily_loss_budget.v1"

# ── state ────────────────────────────────────────────────────────────────────
OK = "OK"                      # room remains; entry may proceed under the cap
EXHAUSTED = "EXHAUSTED"        # the budget is spent; no new entry
CONTAMINATED = "CONTAMINATED"  # an in-session trade we cannot claim
UNKNOWN = "UNKNOWN"            # truth could not be established

STATES = (OK, EXHAUSTED, CONTAMINATED, UNKNOWN)

#: States in which a new entry may be considered at all. Everything else refuses
#: -- and refuses BEFORE an attempt is consumed, because failing to establish
#: risk truth is not a trade the session should pay for.
_ENTRY_PERMITTED = (OK,)

# ── reasons ──────────────────────────────────────────────────────────────────
NO_BUDGET = "authorization_carries_no_daily_loss_budget"
BAD_BUDGET = "daily_loss_budget_is_not_a_positive_number"
NO_VENUE = "venue_truth_unavailable"
DISCOVERY_INCOMPLETE = "order_discovery_incomplete"
UNOWNED_TRADE = "unattributable_in_session_trade"
ROOM_SPENT = "daily_loss_budget_spent"


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def session_start_utc(*, session_date: str, window_start: str, tz_name: str):
    """The exact UTC instant this session's decision window opened.

    NOT `recent_trades`' UTC-midnight default. On a Monday that default reaches
    back to Sunday 20:00 ET and would let a prior session's realized P&L leak
    into today's budget. The window is derived from the authorization's own
    session identity so no second trading-day owner is created.
    """
    try:
        from zoneinfo import ZoneInfo
        d = datetime.strptime(str(session_date), "%Y%m%d").date()
        hh, mm = (int(x) for x in str(window_start).split(":")[:2])
        local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(str(tz_name)))
        return local.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 — an unusable window is an UNKNOWN, not a crash
        return None


def owned_order_ids(orders, *, missions, contract_id) -> dict:
    """Every venue order this session can PROVE is its own.

    Three independent proofs, all from durable facts the session already holds:
    the ids it recorded (entry / protective children / exit), and the certified
    `order_lineage` contract, which additionally claims children the VENUE
    linked to our entry or tagged with our own tag or token.
    """
    owned, by_mission = set(), []
    for m in missions or []:
        entry = getattr(m, "order_id", None)
        token = str(getattr(m, "token_id", "") or "")
        tag = str(getattr(m, "custom_tag", "") or "")
        recorded = {entry, getattr(m, "exit_order_id", None)}
        recorded.update(getattr(m, "protective_order_ids", None) or [])
        recorded = {str(x) for x in recorded if x not in (None, "")}
        owned |= recorded
        lineage = DISC.lineage_orders(orders or [], contract_id=contract_id,
                                      entry_order_id=entry, custom_tag=tag,
                                      token_id=token)
        claimed = {str(o.get("id")) for o in lineage if o.get("id") is not None}
        owned |= claimed
        by_mission.append({"mission_id": getattr(m, "mission_id", None),
                           "entry_order_id": entry,
                           "recorded": sorted(recorded),
                           "lineage_claimed": sorted(claimed)})
    return {"owned": owned, "by_mission": by_mission}


def budget_pnl(trades) -> dict:
    """ECONOMIC_BUDGET_PNL over already-attributed venue trade rows.

    ALL THREE INPUTS ARE ACTUAL VENUE FIELDS. Nothing here is estimated.

        profitAndLoss   PROVEN GROSS, 2026-08-31, against two real 15-lot MNQ
                        round trips on this account: (29765.00-29773.75)x$2x15
                        = -$262.50 and (29782.75-29732.25)x$2x15 = +$1515.00,
                        both matching to the cent. `pnl` is NULL on the OPENING
                        leg and populated on the CLOSING leg, so summing across
                        rows is correct.
        fees            $5.40 per 15-lot leg = $0.72/contract round trip
        commissions     $3.75 per 15-lot leg = $0.50/contract round trip

    WHY COMMISSIONS ARE SUBTRACTED SEPARATELY. `fees` alone is NOT the account's
    cost. Calling `pnl - fees` conservative would have left the budget short by
    exactly the commission -- and this whole unit exists because "$700 planned"
    and "$725 realized" are not the same number. Closing that mismatch while
    opening a smaller one would be the same mistake at a smaller scale.

    Both cost halves independently confirmed the repository's own measured model
    (`FIXED_ROUND_TRIP_FEES_PER_CONTRACT` 0.72, `..._COMMISSIONS_...` 0.50) on
    2026-08-31, so the venue fields and the certified model agree.

    SLIPPAGE IS NOT SUBTRACTED, and must never be. Actual execution slippage is
    already inside the fill prices that produced `profitAndLoss`; the sizing
    layer's slippage RESERVE is a forward-looking allowance for a trade not yet
    taken. Subtracting it here would charge the session twice for the same
    thing, once as a fact and once as a forecast.
    """
    pnl = 0.0
    fees = 0.0
    commissions = 0.0
    counted = 0
    missing_cost = 0
    for t in trades or []:
        p = _num((t or {}).get("pnl", (t or {}).get("profitAndLoss")))
        if p is not None:
            pnl += p
            counted += 1
        f = _num((t or {}).get("fees"))
        c = _num((t or {}).get("commissions"))
        if f is None or c is None:
            # A row that will not state its own cost cannot be charged for one.
            # Recorded rather than silently treated as free.
            missing_cost += 1
        fees += abs(f) if f is not None else 0.0
        commissions += abs(c) if c is not None else 0.0
    gross = round(pnl, 4)
    cost = round(fees + commissions, 4)
    return {"gross_session_pnl": gross,
            "actual_exchange_fees": round(fees, 4),
            "commission_cost": round(commissions, 4),
            "total_transaction_cost": cost,
            "budget_session_pnl": round(gross - cost, 4),
            "rows_with_pnl": counted, "rows_missing_cost_fields": missing_cost,
            "label": "ECONOMIC_BUDGET_PNL",
            "note": ("venue profitAndLoss (PROVEN GROSS) less ACTUAL venue fees "
                     "and commissions; no estimate, and no slippage reserve -- "
                     "real slippage is already inside the fill prices")}


def compute(*, budget_usd, orders, trades, missions, contract_id,
            session_start, max_risk_usd, discovery_complete=True) -> dict:
    """The governor's whole decision. Pure: no venue, no clock, no config."""
    def out(state, reason=None, **extra):
        allowed = 0.0
        room = extra.get("remaining_daily_room", 0.0)
        if state in _ENTRY_PERMITTED:
            allowed = min(float(max_risk_usd), float(room))
        return dict({"schema": SCHEMA, "state": state, "reason": reason,
                     "entry_permitted": state in _ENTRY_PERMITTED,
                     "allowed_planned_risk": round(allowed, 4),
                     "daily_loss_budget_usd": _num(budget_usd),
                     "max_risk_usd": _num(max_risk_usd),
                     "guarantees_max_realized_loss": False}, **extra)

    b = _num(budget_usd)
    if b is None:
        return out(UNKNOWN, NO_BUDGET, remaining_daily_room=0.0)
    if b <= 0:
        return out(UNKNOWN, BAD_BUDGET, remaining_daily_room=0.0)
    if not discovery_complete:
        # An incomplete order view cannot prove ownership, and unproven
        # ownership is exactly what contamination looks like from the inside.
        return out(UNKNOWN, DISCOVERY_INCOMPLETE, remaining_daily_room=0.0)
    if orders is None or trades is None or session_start is None:
        return out(UNKNOWN, NO_VENUE, remaining_daily_room=0.0)

    own = owned_order_ids(orders, missions=missions, contract_id=contract_id)
    mine, foreign = [], []
    for t in trades:
        if (t or {}).get("voided"):
            continue
        created = str((t or {}).get("created") or "")
        if created and created < session_start:
            continue                      # a prior session may not leak forward
        if str((t or {}).get("order_id")) in own["owned"]:
            mine.append(t)
        else:
            foreign.append({"order_id": (t or {}).get("order_id"),
                            "created": created,
                            "size": (t or {}).get("size")})

    if foreign:
        # NOT SILENTLY EXCLUDED. An in-session trade we cannot claim means we
        # cannot claim the session's P&L either, so the budget is unknowable.
        return out(CONTAMINATED, UNOWNED_TRADE, remaining_daily_room=0.0,
                   unattributed=foreign[:5],
                   unattributed_count=len(foreign),
                   owned_order_ids=sorted(own["owned"]),
                   attribution=own["by_mission"])

    acct = budget_pnl(mine)
    loss_used = max(0.0, -acct["budget_session_pnl"])
    room = max(0.0, round(b - loss_used, 4))
    common = {"remaining_daily_room": room, "loss_used": round(loss_used, 4),
              "accounting": acct, "attributed_trades": len(mine),
              "owned_order_ids": sorted(own["owned"]),
              "attribution": own["by_mission"]}
    if room <= 0:
        return out(EXHAUSTED, ROOM_SPENT, **common)
    return out(OK, None, **common)


def resolve(*, session, contract_id, missions, authorization,
            max_risk_usd, window_start=None, tz_name=None) -> dict:
    """Read the venue, then decide. Never raises: a failure is an UNKNOWN.

    Called BEFORE a trade mission is opened, so a failure here refuses the entry
    WITHOUT consuming an attempt -- risk truth we could not establish is not a
    trade the session should pay for.
    """
    budget = getattr(authorization, "daily_loss_budget_usd", None)
    start = session_start_utc(
        session_date=getattr(authorization, "session_date", ""),
        window_start=window_start or "09:00",
        tz_name=tz_name or "America/New_York")
    orders = trades = None
    complete = False
    try:
        found = DISC.discover_orders(session)
        orders = found.get("orders")
        complete = bool(found.get("complete"))
    except Exception:  # noqa: BLE001
        orders, complete = None, False
    try:
        if start is not None:
            trades = session.recent_trades(since=start)
    except Exception:  # noqa: BLE001
        trades = None
    return compute(budget_usd=budget, orders=orders, trades=trades,
                   missions=missions, contract_id=contract_id,
                   session_start=None if start is None else start.isoformat(),
                   max_risk_usd=max_risk_usd, discovery_complete=complete)

"""TopstepX transport for the deterministic lane — no NinjaTrader anywhere.

The lane was written against NinjaTraderBridgeClient and calls ten methods on it.
Rather than rewrite the loop, this presents the SAME ten and answers them from
the ProjectX Gateway API. The loop does not learn a second way to trade; it keeps
the one it has and the venue underneath changes.

That matters beyond convenience: the lane's fail-closed author reads
account_known, position_known, orders_known and armed off these calls. A transport
that answered a slightly different shape would not fail — it would silently
degrade those gates into "unknown", and an unknown gate is a refusal that looks
like a quiet market.

WHERE THE TWO VENUES GENUINELY DIFFER, AND WHAT IS DONE ABOUT IT

  quote — ProjectX REST has no quote endpoint (real-time prices live on the
      SignalR market hub, which this lane does not use). `last` is therefore the
      close of the most recent CLOSED bar. That is honest for a 1-minute lane
      whose decisions are made on closed bars anyway, and it is reported as
      `derived_from: last_closed_bar` rather than passed off as a tick.

  realized_pnl — no trade-level P&L endpoint is published in the swagger. It is
      derived as balance minus the prior session's close, which is exactly the
      quantity Topstep measures its own daily loss limit against, so the bot's
      notion of "today's P&L" and the venue's now agree by construction.

  arm_orders — NinjaTrader's bridge owns an ArmOrders switch that physically
      refuses orders while false. TopstepX has no equivalent, so the safety has
      to live here: orders are refused unless TOPSTEPX_ARM_ORDERS=true. It
      defaults OFF, so importing or running this transport arms nothing.

  working_order_count — the lane proves protection by seeing exactly 2 working
      orders after a fill. A ProjectX bracket produces precisely that (the stop
      and the target), so the check transfers unchanged.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from broker.topstepx_adapter import TopstepXBrokerAdapter
from integrations.topstepx.deterministic.topstepx_mutation_authority import (
    denial as _deny, read_only as _read_only)
from broker import topstepx_order_discovery as DISC
from broker.topstepx_client import TopstepXError

__all__ = ["TopstepXLaneClient", "topstepx_lane_enabled"]


def topstepx_lane_enabled() -> bool:
    """True when the lane should route through TopstepX instead of NinjaTrader."""
    return os.getenv("DETERMINISTIC_VENUE", "topstepx").strip().lower() == "topstepx"


#: How old the newest bar may be before the lane refuses to act on the window.
#: Generous enough to survive a slow poll or a thin minute, tight enough that a
#: closed market or a mis-truncated window cannot masquerade as live data.
_STALE_BAR_MINUTES = 15.0


def _armed() -> bool:
    return os.getenv("TOPSTEPX_ARM_ORDERS", "false").strip().lower() in ("1", "true", "yes", "on")


class TopstepXLaneClient:
    """Speaks NinjaTraderBridgeClient's surface, backed by TopstepX."""

    def __init__(self, adapter: Optional[TopstepXBrokerAdapter] = None) -> None:
        # STRUCTURALLY READ-ONLY. The proxy refuses the mutating surface by
        # NAME at access time -- including on objects reached THROUGH it, so a
        # caller cannot climb from `_adapter._client` to a live `close_position`
        # one attribute later. A method added to the adapter tomorrow is still
        # governed, which is what makes this a prohibition rather than a
        # snapshot of today's API.
        self._adapter = _read_only(adapter or TopstepXBrokerAdapter())
        self._connected = False
        self._bars_cache: list[dict] = []
        self._prior_close: Optional[float] = None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def connect(self) -> bool:
        try:
            self._adapter.connect()
        except Exception as exc:  # noqa: BLE001 — the loop treats False as "no trade"
            print(f"[topstepx] connect failed: {type(exc).__name__}: {exc}")
            self._connected = False
            return False
        self._connected = True
        self._prior_close = self._load_prior_close()
        return True

    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self._connected = False

    def _load_prior_close(self) -> Optional[float]:
        """Yesterday's closing balance, from the Topstep durable state if present.

        Without it, realized P&L for the day cannot be computed and the lane is
        told `known: False` rather than being handed a zero that would read as
        'flat on the day'.
        """
        label = os.getenv("TOPSTEP_ACCOUNT_SIZE", "").strip()
        if not label:
            return None
        try:
            from risk.topstep_limits import load_state, spec_for
            return load_state(spec_for(label)).prior_day_close
        except Exception:  # noqa: BLE001 — absence is reported, never invented
            return None

    # ── reads ─────────────────────────────────────────────────────────────────
    def account_state(self) -> dict:
        if not self._connected:
            return {"account": None, "known": False}
        try:
            a = self._adapter.get_account()
        except TopstepXError as exc:
            return {"account": None, "known": False, "error": str(exc)}
        realized = (None if self._prior_close is None
                    else round(float(a["cash_value"]) - float(self._prior_close), 2))
        return {"account": a["account"], "account_id": a["account_id"],
                "cash_value": a["cash_value"], "balance": a["balance"],
                "realized_pnl": realized if realized is not None else 0.0,
                "realized_pnl_known": realized is not None,
                "simulated": a["simulated"], "can_trade": a["can_trade"],
                "known": True}

    def environment_proof(self) -> dict:
        if not self._connected:
            return {"accounts": [], "known": False}
        a = self._adapter.get_account()
        return {"accounts": [a["account"]], "arm_orders": _armed(),
                "venue": "topstepx", "simulated": a["simulated"], "known": True}

    def connection_state(self) -> dict:
        return {"connected": self._connected, "known": True, "venue": "topstepx"}

    def instrument_metadata(self, instrument_name: str) -> dict:
        if not self._connected:
            return {"known": False}
        a = self._adapter.get_account()
        return {"known": True, "instrument": a["instrument"],
                "contract_id": a["contract_id"], "tick_size": a["tick_size"],
                "point_value": a["tick_value"] / a["tick_size"] if a["tick_size"] else None}

    def position(self, instrument_name: str = "") -> dict:
        """Signed quantity, matching the bridge: positive long, negative short."""
        if not self._connected:
            return {"qty": 0, "known": False}
        try:
            p = self._adapter.get_position()
        except TopstepXError as exc:
            return {"qty": 0, "known": False, "error": str(exc)}
        if p.get("flat"):
            return {"qty": 0, "known": True, "avg_price": None, "flat": True}
        size = int(p.get("size") or 0)
        signed = size if p.get("side") == "long" else -size
        return {"qty": signed, "known": True, "avg_price": p.get("avg_price"),
                "flat": False, "side": p.get("side")}

    def order_summary(self) -> dict:
        if not self._connected:
            return {"working_order_count": None, "known": False}
        account, contract = self._adapter._require()   # noqa: SLF001 — same package intent
        try:
            # SAME VENUE, SAME OMISSION. This lane reads the TopstepX client
            # directly, so `searchOpen` hides Suspended bracket children from it
            # exactly as it did from the production lane.
            orders = self._adapter._client.query_orders(  # noqa: SLF001
                account.id, contract_id=contract.id)
        except TopstepXError as exc:
            return {"working_order_count": None, "known": False, "error": str(exc)}
        orders = DISC.working_orders(orders)
        return {"working_order_count": len(orders), "orders": orders, "known": True}

    def working_orders(self) -> list:
        return self.order_summary().get("orders", []) or []

    def quote(self, instrument_name: str = "") -> dict:
        """Last CLOSED bar's close. See the module docstring — not a tick."""
        bars = self._bars_cache or self.historical_1m(instrument_name, 5)
        if not bars:
            return {"known": False}
        return {"last": bars[-1]["close"], "known": True,
                "derived_from": "last_closed_bar",
                "as_of": bars[-1]["timestamp"]}

    def historical_1m(self, instrument_name: str = "", lookback: int = 400,
                      days_back: Optional[int] = None,
                      max_bars: Optional[int] = None) -> list:
        if not self._connected:
            return []

        # Size the WINDOW to the bars actually wanted, and set the limit to
        # match. The lane asks for a 10-day window and 2000 bars; MNQ prints
        # ~1380 a day, so a naive translation requests ~13,800 and caps at 2000 —
        # and nothing documents WHICH 2000 come back. If ProjectX truncates from
        # the start, the lane would warm up on bars from ten days ago and trade a
        # market that no longer exists. Asking for roughly what is needed removes
        # the ambiguity instead of betting on it.
        want = max(int(lookback or 0), int(max_bars or 0)) or 400
        minutes = int(want * 3)          # headroom for the daily break/weekends
        try:
            bars = self._adapter.bars_1m(minutes_back=minutes, limit=want + 200)
        except TopstepXError as exc:
            print(f"[topstepx] bar fetch failed: {exc}")
            return []

        # And verify it anyway. A stale window is indistinguishable from a quiet
        # market downstream, so freshness is asserted here rather than inferred
        # from a chart later. No bars is a NO TRADE, which is the safe answer.
        if bars:
            age = self._bar_age_minutes(bars[-1]["timestamp"])
            if age is not None and age > _STALE_BAR_MINUTES:
                print(f"[topstepx] REFUSING BARS: newest is {age:.0f} min old "
                      f"({bars[-1]['timestamp']}). Market closed, or the venue "
                      f"truncated the window from the wrong end. No trade.")
                return []
        for b in bars:
            b["instrument"] = instrument_name or "MNQ"
        if max_bars:
            bars = bars[-int(max_bars):]
        self._bars_cache = bars
        return bars[-lookback:] if lookback else bars

    @staticmethod
    def _bar_age_minutes(stamp) -> Optional[float]:
        """Minutes since `stamp`, or None if it cannot be read.

        Unreadable never means stale — an unparseable timestamp must not silently
        halt trading, it must be visible as a parsing problem instead.
        """
        if not stamp:
            return None
        text = str(stamp).strip().replace("Z", "+00:00")
        try:
            when = datetime.fromisoformat(text)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() / 60.0

    def buffered_bars(self) -> list:
        return []

    # ── writes ────────────────────────────────────────────────────────────────
    def deterministic_order(self, payload: dict) -> dict:
        """DENIED. This lane holds no TopstepX mutation authority.

        The body that built and submitted a bracket has been REMOVED, not merely
        made unreachable. Unreachable order-submission code beside a live
        credential is an invitation: the next person to read it sees a working
        implementation one `return` away from running.

        It was gated on `TOPSTEPX_ARM_ORDERS`, and that gate is exactly what
        made the sixth defect survive -- `flatten` never had it, so the lane
        could not place an order without arming but could close a real position
        without it. An environment variable is a convention; authority should be
        structural.

        If this lane is ever restored for execution, it needs its own
        execution-authority project and its own safety certification, against
        the same convergence law the production organism obeys.
        """
        return _deny("deterministic_order")

    def flatten(self, instrument_name: str = "") -> dict:
        """DENIED. "Emergency" is not an authority.

        This was the sixth defect: a bare `close_position` on a real account,
        with no discovery, no ownership, no cancellation and no proof -- and it
        was NOT behind `TOPSTEPX_ARM_ORDERS`, so placing an order required
        arming while flattening a live position did not.

        The words `flatten`, `emergency`, `safety` and `cleanup` do not grant
        account mutation authority. A safety action taken without certified
        authority is still an unauthorized mutation, and this lane has none.
        """
        return _deny("flatten")

    def submit_market_entry(self, intent: dict) -> dict:
        return _deny("submit_market_entry")

    def submit_oco(self, stop: dict, target: dict) -> dict:
        return {"accepted": False,
                "reason": "brackets are attached to the entry on TopstepX; "
                          "a separate OCO is never submitted"}

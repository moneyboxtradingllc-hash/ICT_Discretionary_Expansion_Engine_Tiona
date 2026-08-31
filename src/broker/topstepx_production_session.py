"""The production orchestration layer: candidate -> execution -> measurement.

Before this module the production path had no caller. `build_production_bracket`
had zero callers anywhere in the repository, and the only code reaching
`gated_submit` was smoke tooling running smoke caps. Everything downstream was
proven in isolation and unreachable in practice.

This is deliberately thin. It owns no decisions: Luna authors the thesis, the
producer resolves it, `build_production_bracket` sizes it, the runner gates it,
and the slippage module measures it. What lives here is the ORDER those happen
in, and the threading of candidate identity through every layer so the exit can
be attributed to the entry that caused it.

    reconcile -> candidate -> production bracket -> gated submit (quote captured)
    -> entry fills -> entry observation -> execution context
    -> protection -> exit fills -> exit observation -> paired round trip

Nothing here places an order on import or construction.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from broker import topstepx_execution_runner as R
from broker import topstepx_session_ledger as LG
from broker import topstepx_slippage as SL
from broker.topstepx_combine_risk import (
    ABSOLUTE_MAX_STOP_POINTS, MIN_REWARD_TO_RISK, PRODUCTION_MAX_CONTRACTS,
    PRODUCTION_MAX_RISK_USD, RiskRejection, build_production_bracket,
)
from broker.topstepx_quote_provider import LiveQuoteProvider, QuoteProviderError

CONTEXT_FILENAME = "active_execution_context.json"


class ProductionLaneRefused(RuntimeError):
    """The production lane will not open. Never a warning — a refusal."""


class ProductionSession:
    """One production execution lane for one pinned account and contract."""

    def __init__(self, *, session, account_fingerprint: str, contract,
                 mission_id: str, store_dir: str, ledger=None,
                 slippage_ledger=None, quote_provider=None, clock=None,
                 runtime=None, max_market_age: float = 30.0,
                 session_id: str = "",
                 fill_deadline_seconds: float = R.FILL_DEADLINE_SECONDS) -> None:
        self.session = session
        self.runtime = runtime
        # EXEC-PRICE-ANCHOR-1: how long the prompt post-fill lifecycle waits for
        # the authoritative full fill before failing closed. Injectable so a
        # harness can exercise the deadline without spending it in wall-clock.
        self.fill_deadline_seconds = float(fill_deadline_seconds)
        self.max_market_age = float(max_market_age)
        self.account_fingerprint = account_fingerprint
        self.contract = contract
        self.mission_id = mission_id
        self.store_dir = store_dir
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ledger = ledger or LG.SessionLedger.load_or_new(
            account_fingerprint, self.clock().strftime("%Y%m%d"), store_dir)
        self.slippage = slippage_ledger or SL.SlippageLedger.load(
            os.path.join(store_dir, "slippage_observations.jsonl"))
        self.quote_provider = quote_provider
        self.context_path = os.path.join(store_dir, CONTEXT_FILENAME)
        self.runner = None
        # EVIDENCE-SUBSTRATE-PHASE0 — flight recorder. Capture only: nothing on
        # this object is consulted before a trade, and every write swallows its
        # own failure. `_lineage` carries the OPEN row from entry to exit so the
        # two halves join on threaded identity rather than on a timestamp.
        self.session_id = session_id or f"PROD-{self.clock().strftime('%Y%m%d')}"
        self._lineage = None

    # ── quote flow ────────────────────────────────────────────────────────────
    # This session deliberately owns NO transport. It does not pump, reconnect,
    # or close the market hub — `TopstepXMarketRuntime` is the sole authority for
    # all three. An execution session that could also drain the socket gave the
    # process two readers competing for one stream, each seeing part of it.

    def start_pump(self, owner_id: str = None) -> None:
        """Delegate to the shared runtime. Never starts a reader of its own."""
        if self.runtime is None:
            raise ProductionLaneRefused(
                "no shared market runtime: this session will not start its own "
                "pump; attach it to the runtime that owns the market hub")
        self.runtime.start(owner_id or self.runtime.pump_owner_id or "market-runtime")

    def stop_pump(self) -> None:
        """Detach only. Stopping the shared stream is the runtime owner's call."""
        return None

    # ── startup ───────────────────────────────────────────────────────────────
    def assert_single_pump(self) -> dict:
        """Ownership is proven from runtime state, never assumed from comments."""
        rt = self.runtime
        if rt is None:
            return {}
        h = rt.health()
        if not h["pump_owner"]:
            raise ProductionLaneRefused(
                "AMBIGUOUS_PUMP_OWNERSHIP: the market runtime has no pump owner")
        if not h["pump_thread_alive"]:
            raise ProductionLaneRefused(
                f"PUMP_THREAD_DEAD: '{h['pump_owner']}' owns the market hub but its "
                f"pump thread is not alive; the feed is not being read")
        if self.contract.id not in h["active_contracts"]:
            raise ProductionLaneRefused(
                f"CONTRACT_MISMATCH: the shared runtime streams "
                f"{h['active_contracts']}, this lane trades {self.contract.id}")
        if self.quote_provider is not None and rt.hub is not None:
            if getattr(self.quote_provider, "hub", None) is not rt.hub:
                raise ProductionLaneRefused(
                    "FOREIGN_HUB: the quote provider is attached to a different hub "
                    "than the shared market runtime owns")
        return h

    def open_lane(self) -> dict:
        """Refuse the lane unless every measurement prerequisite is real."""
        if self.quote_provider is None and self.runtime is not None:
            self.quote_provider = LiveQuoteProvider(self.runtime.hub or
                                                    self.runtime.connect(),
                                                    self.contract, clock=self.clock)
        if self.quote_provider is None:
            hub = getattr(self.session, "market_hub", None)
            if hub is None:
                raise ProductionLaneRefused(
                    "no market hub: the production lane requires a live quote "
                    "provider and will not run blind to the executable price")
            try:
                self.quote_provider = LiveQuoteProvider(hub, self.contract,
                                                        clock=self.clock)
            except QuoteProviderError as exc:
                raise ProductionLaneRefused(str(exc)) from None

        if self.quote_provider.contract.id != self.contract.id:
            raise ProductionLaneRefused(
                f"quote provider serves {self.quote_provider.contract.id}, "
                f"lane trades {self.contract.id}")
        if self.runtime is not None:
            self.runtime.note_subscriber("quote-provider")
        ownership = self.assert_single_pump()

        # CANONICAL DISCOVERY, AND IT RAISES. This resolves the LANE, and an
        # "OPEN" lane carries `new_entry_permitted: True`. A Suspended residual
        # child must be able to refuse a session that believes it is starting
        # flat -- and an unreadable venue must never be able to authorize one.
        from broker import topstepx_order_discovery as _DISC
        positions = self.session.open_positions()
        orders = _DISC.require_working_orders(
            self.session, contract_id=self.contract.id)
        unresolved = SL.ExecutionContext.load(self.context_path)
        if unresolved is not None and (positions or orders):
            # An unfinished lifecycle is reconciled, never re-entered.
            return {"lane": "RECOVERY", "context": unresolved.as_dict(),
                    "positions": len(positions), "working_orders": len(orders),
                    "new_entry_permitted": False, "ownership": ownership}
        if positions or orders:
            raise ProductionLaneRefused(
                f"account is not flat ({len(positions)} position(s), "
                f"{len(orders)} working order(s)) and no context explains it")
        return {"lane": "OPEN", "new_entry_permitted": True,
                "ownership": ownership,
                "quote_provider": self.quote_provider.describe()}

    # ── entry ─────────────────────────────────────────────────────────────────
    def build_runner(self, candidate, *, max_risk_usd: float = None) -> "R.ExecutionRunner":
        """Size the candidate under PRODUCTION doctrine and arm a runner.

        LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1. `max_risk_usd` lets the session loss
        budget lower the ceiling for THIS candidate. It may only ever be lower:
        the caller passes min($350, remaining daily room), and omitting it keeps
        the production cap exactly as before.

        ONE VALUE, THREE USES. The ceiling reaches the sizing call, the geometry
        governance stamp and the runner's own recheck. They must not diverge --
        the recheck exists precisely so the final gate cannot fall back to a
        laxer default, and a governor that reduced only the first would be
        undone by the third.

        THE STRUCTURAL STOP IS NEVER TOUCHED. A lower ceiling reduces QUANTITY.
        Moving the invalidation inward to fit a budget would be inventing a
        different trade and calling it the same one.
        """
        effective_max_risk = (
            PRODUCTION_MAX_RISK_USD if max_risk_usd is None
            else min(float(PRODUCTION_MAX_RISK_USD), float(max_risk_usd)))
        sized = build_production_bracket(
            direction=candidate.direction, entry_price=candidate.entry_price,
            invalidation_level=candidate.invalidation_price,
            target_price=candidate.objective.price, contract=self.contract,
            evidence=(candidate.extras or {}).get("volatility_evidence")
            or {"volatility_state": (candidate.extras or {}).get("volatility_state", ""),
                "expansion_state": (candidate.extras or {}).get("expansion_state", ""),
                "structural_level_identity": (candidate.extras or {})
                .get("structural_invalidation", {}).get("structure_identity", "")},
            max_risk_usd=effective_max_risk,
            max_contracts=PRODUCTION_MAX_CONTRACTS,
            min_reward_to_risk=MIN_REWARD_TO_RISK)

        runner = R.ExecutionRunner(session=self.session,
                                   account_fingerprint=self.account_fingerprint,
                                   contract=self.contract, clock=self.clock)
        runner.execution_lane = "production"
        # The evidence block must name the ceilings that actually judged this
        # trade, not the smoke defaults its module happens to import.
        runner.geometry = sized["geometry"].governed_by(
            max_risk_usd=effective_max_risk,
            max_stop_points=ABSOLUTE_MAX_STOP_POINTS,
            lane="production")
        # Production caps travel WITH the runner so the final risk recheck cannot
        # fall back to smoke defaults.
        runner.max_risk_usd = effective_max_risk
        runner.max_stop_points = ABSOLUTE_MAX_STOP_POINTS
        runner.max_contracts = PRODUCTION_MAX_CONTRACTS
        runner.min_reward_to_risk = MIN_REWARD_TO_RISK
        # EXEC-PRICE-ANCHOR-1 (2026-08-18). PRODUCTION owns the prompt post-fill
        # lifecycle: submit does not return successfully until the full fill is
        # proven and the venue is holding the AUTHORIZED absolute structural
        # invalidation and objective, not the tick offsets it derived from the
        # fill. This is the ONLY place it is enabled -- the smoke tools and the
        # gating unit tests keep asserting what they were written to assert.
        runner.prompt_fill_authority = True
        runner.fill_deadline_seconds = self.fill_deadline_seconds
        # PROD-20260810: production ALWAYS flight-records its submissions. The
        # session id is what makes the ledger findable after a restart, which
        # is the whole point -- a rejection has to outlive the process.
        runner.submission_store_dir = self.store_dir
        runner.submission_session_id = self.session_id
        # The PER-TRADE mission id (`...-T1`) when one exists, not the
        # session-level id. V13 stamped the session-level id while the mission
        # record carried the per-trade one, and the evidence join that was
        # supposed to prove the venue had seen the order found nothing.
        runner.submission_mission_id = (getattr(self, "trade_mission_id", "")
                                        or self.mission_id)
        runner.submission_authorization_fingerprint = getattr(
            self, "authorization_fingerprint", "") or ""
        # MISSION-LIFECYCLE. The venue's order id must reach the durable mission
        # record before the ack is reported upward -- on V13 it reached the
        # flight recorder and stopped there.
        runner.on_venue_acknowledged = getattr(self, "acknowledgement_hook", None)
        self.runner = runner
        self.sizing = sized
        return runner

    def submit(self, *, candidate, market: dict, latest_price: float, mint_token,
               account_id, refresh=None, on_attempt_consumed=None) -> dict:
        """Gated submission with the LIVE quote provider attached."""
        if self.runner is None:
            self.build_runner(candidate)
        return self.runner.gated_submit(
            account_id=account_id, ledger=self.ledger, candidate_snapshot=candidate,
            market=market, latest_price=latest_price, mint_token=mint_token,
            refresh=refresh, on_attempt_consumed=on_attempt_consumed,
            quote_provider=self.quote_provider)

    # ── reconciliation ────────────────────────────────────────────────────────
    def _orders_index(self, orders: list) -> dict:
        idx = {}
        for o in orders or []:
            if o.get("id") is not None:
                idx[o["id"]] = o
                idx[str(o["id"])] = o
        return idx

    def attribution_for(self, order_id, orders: list) -> str:
        """Trade.orderId -> Order.id -> Order.customTag, never price similarity."""
        return LG.classify({"orderId": order_id}, self.ledger.known_token_ids,
                           self._orders_index(orders))

    def reconcile_entry(self, *, candidate, trades: list, orders: list,
                        fill_event: dict, stop_order_id=None,
                        target_order_id=None) -> dict:
        """Measure the entry, then persist the context the exit will need.

        Measurement failure is reported and swallowed: protection must never wait
        on evidence.

        EXEC-PRICE-ANCHOR-1 (2026-08-18) DELIBERATELY DOES NOT HOOK HERE. The
        re-anchor was wired into this method and then withdrawn, for two reasons
        that both matter:

          * this method is NOT on the production route -- the mission-reconciler
            docstring records that `reconcile_after_fill`'s only callers were in
            tests, which is the same wedge that lost PROD-20260811; and
          * this is a MEASUREMENT path. `tests/test_production_caller.py` drives
            it with a session that raises on any venue call, because measurement
            is not allowed to touch the venue. Putting an order modification
            here would put execution authority inside the slippage recorder --
            precisely the layering the reconciler was split out to prevent.

        The re-anchor needs a PROMPT post-fill hook, which production does not
        currently have. See `ExecutionRunner.reanchor_protection_to_structure`.
        """
        order_id = self.runner.order_id
        fills = [t for t in (trades or []) if str(t.get("orderId")) == str(order_id)]
        attribution = self.attribution_for(order_id, orders)
        observation = None
        try:
            observation = self.runner.measure_entry_slippage(
                fill_event=fill_event, candidate_snapshot=candidate,
                ledger=self.slippage, attribution=attribution, fills=fills or None)
        except Exception as exc:  # noqa: BLE001 — evidence never blocks protection
            observation = {"error": f"{type(exc).__name__}", "reliable": False}

        ctx = self.runner.build_execution_context(
            candidate_snapshot=candidate, mission_id=self.mission_id,
            fill_event=fill_event, stop_order_id=stop_order_id,
            target_order_id=target_order_id, path=self.context_path)
        self.ledger.save()
        self._lineage = self._record_entry_lineage(ctx, candidate)
        return {"observation": observation, "context": ctx.as_dict(),
                "attribution": attribution, "fill_count": len(fills)}

    def reconcile_exit(self, *, candidate, exit_type: str, trades: list,
                       orders: list, exit_order_id=None, fill_price=None,
                       quantity=None) -> dict:
        """Measure the exit against the right reference for its type."""
        ctx = self.runner.execution_context
        fills = [t for t in (trades or []) if str(t.get("orderId")) == str(exit_order_id)]
        attribution = self.attribution_for(exit_order_id, orders)

        if exit_type == SL.EXIT_TARGET:
            requested = ctx.liquidity_target_price if ctx else candidate.objective.price
            quote = self.quote_provider.capture()
        elif exit_type == SL.EXIT_STOP:
            # PROTECTION-STATE-AUTHORITY-1: a stop exit is measured against the
            # stop that was ACTUALLY WORKING. Once protection has advanced,
            # comparing the fill against the originating thesis invalidation
            # reports enormous fake positive slippage and poisons the measured
            # cost ledger. The invalidation is an audit fact, not an execution
            # reference. The older fields remain the fallback for a position
            # whose baseline never armed.
            requested = None
            if ctx is not None:
                requested = ctx.active_protective_stop
                if requested is None:
                    requested = ctx.structural_stop_price
            if requested is None:
                requested = candidate.invalidation_price
            quote = self.quote_provider.capture()
        else:
            # A market flatten is measured against the CURRENT executable price,
            # never against a stop or target it was never aimed at.
            requested = None
            quote = self.quote_provider.capture()

        observation = self.runner.measure_exit_slippage(
            exit_type=exit_type, fill_price=fill_price, quantity=quantity,
            quote_capture=quote, requested_price=requested,
            candidate_snapshot=candidate, ledger=self.slippage,
            attribution=attribution, order_id=exit_order_id,
            fills=fills or None)
        self.ledger.save()
        self._record_exit_lineage(exit_type=exit_type, fill_price=fill_price,
                                  exit_order_id=exit_order_id,
                                  observation=observation,
                                  attribution=attribution, fills=fills)
        return {"observation": observation, "attribution": attribution,
                "requested_price": requested, "fill_count": len(fills),
                "sample": self.slippage.sample_status()}

    # ── flight recorder (EVIDENCE-SUBSTRATE-PHASE0) ──────────────────────────
    # Both methods are pure capture. They are called AFTER the fact is
    # authoritative, they return nothing any caller reads, and they cannot
    # raise -- a recorder that can halt the aircraft is not a recorder.
    def _record_entry_lineage(self, ctx, candidate):
        try:
            from broker.trade_lineage import open_lineage
            snap = getattr(candidate, "extras", None) or {}
            return open_lineage(
                session_id=self.session_id, execution_context=ctx,
                brain_result=snap.get("brain_result"),
                shadow=snap.get("two_brain_shadow"),
                decision_trace=snap.get("decision_trace"),
                governor=snap.get("profit_governor"))
        except Exception:  # noqa: BLE001 -- capture may never cost a trade
            return None

    def _record_exit_lineage(self, *, exit_type, fill_price, exit_order_id,
                             observation, attribution, fills):
        try:
            if not self._lineage:
                return None
            from broker import topstepx_session_ledger as _LG
            from broker.trade_lineage import close_lineage
            obs = observation if isinstance(observation, dict) else {}
            closed = close_lineage(
                session_id=self.session_id, lineage=self._lineage,
                exit_price=fill_price,
                # The venue states the exit type. It is never inferred from how
                # close the price landed to a target.
                exit_reason=exit_type,
                exit_trade_id=(fills or [{}])[0].get("id") if fills else None,
                realized_pnl_usd=obs.get("realized_pnl"),
                mfe_points=obs.get("mfe_points"), mae_points=obs.get("mae_points"),
                reconciled=(attribution == _LG.EXPANSION_BOT))
            self._lineage = None
            return closed
        except Exception:  # noqa: BLE001
            return None

    # ── telemetry ─────────────────────────────────────────────────────────────
    def market_evidence_stale(self) -> bool:
        """Report staleness. A stale feed rejects a candidate; it never causes
        this session to build a replacement pump or connection."""
        if self.runtime is None:
            return False
        return self.runtime.is_stale(self.max_market_age)

    def telemetry(self) -> str:
        from broker.topstepx_production_doctrine import render, resolve
        d = resolve(self.slippage)
        qp = self.quote_provider.describe() if self.quote_provider else {}
        lines = [render(d), "",
                 "  SLIPPAGE CAPTURE             : WIRED THROUGH LIVE CALLER",
                 f"  QUOTE PROVIDER               : {qp.get('source', 'ABSENT')}",
                 "  ENTRY MEASUREMENT            : ACTIVE",
                 "  EXIT MEASUREMENT             : ACTIVE"]
        return "\n".join(lines + self.ownership_telemetry())

    def ownership_telemetry(self) -> list:
        """Transport ownership, read from live runtime state."""
        rt = self.runtime
        if rt is None:
            return ["", "  TOPSTEP MARKET RUNTIME       : NOT SHARED (session-local)"]
        h = rt.health()

        def age(v):
            return "never" if v is None else f"{v:.2f}s"

        return ["",
                "  TOPSTEP MARKET RUNTIME       : SHARED",
                f"  SIGNALR CONNECTIONS          : {1 if h['hub_connected'] else 0}",
                "  PUMP OWNERS                  : 1",
                f"  PUMP OWNER                   : {h['pump_owner']}",
                f"  PUMP THREAD                  : {'alive' if h['pump_thread_alive'] else 'DEAD'}",
                f"  RECONNECT AUTHORITY          : {h['pump_owner']}",
                f"  CONNECTION GENERATION        : {h['connection_generation']}",
                f"  SUBSCRIBERS                  : {h['subscriber_count']} "
                f"({', '.join(h['subscribers']) or 'none'})",
                f"  ACTIVE CONTRACT              : {', '.join(h['active_contracts']) or 'none'}",
                f"  LAST QUOTE AGE               : {age(h['last_quote_age'])}",
                f"  LAST TRADE AGE               : {age(h['last_trade_age'])}",
                "  DUPLICATE PUMP PROTECTION    : ENFORCED"]

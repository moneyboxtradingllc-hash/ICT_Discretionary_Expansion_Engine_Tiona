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
        if positions:
            recovery = self._startup_recovery_submission()
            if recovery is not None:
                return {"lane": "RECOVERY",
                        "submission_id": recovery.get("submission_id"),
                        "mission_id": recovery.get("mission_id"),
                        "positions": len(positions),
                        "working_orders": len(orders),
                        "new_entry_permitted": False, "ownership": ownership}
        if positions or orders:
            raise ProductionLaneRefused(
                f"account is not flat ({len(positions)} position(s), "
                f"{len(orders)} working order(s)) and no context explains it")
        return {"lane": "OPEN", "new_entry_permitted": True,
                "ownership": ownership,
                "quote_provider": self.quote_provider.describe()}

    def _startup_recovery_submission(self):
        """Return one durable active-mission entry, or refuse ambiguity.

        This is lane admission only. It grants no mutation: the scan owner later
        re-proves full fills, child lineage, prices and authorization from venue
        truth before completing establishment.
        """
        from broker import topstepx_mission_state as MS
        from broker import topstepx_submission_record as SUBREC
        prefix = f"trade_mission_{self.session_id}_"
        missions = []
        try:
            names = sorted(os.listdir(self.store_dir))
        except OSError:
            return None
        for name in names:
            if not (name.startswith(prefix) and name.endswith(".json")):
                continue
            mission = MS.load(os.path.join(self.store_dir, name))
            if mission is None or mission.state in MS.TERMINAL_STATES:
                continue
            if (str(mission.account_fingerprint) != str(self.account_fingerprint)
                    or str(mission.contract_id) != str(self.contract.id)):
                continue
            missions.append(mission)
        rows = SUBREC.recoverable_entry_submissions(
            store_dir=self.store_dir, session_id=self.session_id,
            account_fingerprint=self.account_fingerprint,
            contract_id=self.contract.id)
        joined = [(m, row) for m in missions for row in rows
                  if str(row.get("mission_id")) == str(m.mission_id)
                  and str(row.get("venue_order_id")) == str(m.order_id)]
        if len(joined) > 1:
            raise ProductionLaneRefused(
                "ambiguous establishment recovery: more than one active "
                "mission/submission owns the live position")
        return joined[0][1] if len(joined) == 1 else None

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
        extras = candidate.extras or {}
        # A present canonical block owns this handoff even when malformed. Do
        # not let `{}` or another falsey corrupt value fall through to legacy
        # top-level fields and accidentally earn the extended lane. Candidates
        # that genuinely predate the block retain the explicit legacy shape.
        if "volatility_evidence" in extras:
            volatility_evidence = extras.get("volatility_evidence")
        else:
            volatility_evidence = {
                "volatility_state": extras.get("volatility_state", ""),
                "expansion_state": extras.get("expansion_state", ""),
                "structural_level_identity": extras.get(
                    "structural_invalidation", {}).get("structure_identity", ""),
            }
        sized = build_production_bracket(
            direction=candidate.direction, entry_price=candidate.entry_price,
            invalidation_level=candidate.invalidation_price,
            target_price=candidate.objective.price, contract=self.contract,
            evidence=volatility_evidence,
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
        structural = extras.get("structural_invalidation")
        runner.submission_structural_invalidation = (
            dict(structural) if isinstance(structural, dict) else None)
        # MISSION-LIFECYCLE. The venue's order id must reach the durable mission
        # record before the ack is reported upward -- on V13 it reached the
        # flight recorder and stopped there.
        runner.on_venue_acknowledged = getattr(self, "acknowledgement_hook", None)
        # PROD-20260904 RULING C. The REJECTION has to reach the durable mission
        # too, and by the same route -- it was the one venue boundary with no
        # production writer at all, so PROD-20260810 and PROD-20260904-T1 both
        # ended as phantom active missions. Assigned from the loop beside
        # `acknowledgement_hook`; a hook nothing ever assigns is not wiring.
        runner.on_venue_rejected = getattr(self, "rejection_hook", None)
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
    def arm_break_even_after_submit(self, owner, mission, candidate) -> dict:
        """Real production seam, AFTER full fill and structural readback.

        Recording failure removes BE authority, never changes the entry result
        or destroys protection which the runner has already established.
        """
        from broker import break_even_binding as BIND
        from broker import break_even_actuator as ACT
        from broker import topstepx_submission_record as SUBREC
        try:
            BIND.identity(owner, mission, self)
            runner = self.runner
            BIND.same(runner.order_id, mission.order_id, "fresh runner entry")
            if runner.execution_context is not None:
                raise BIND.BindingRefused("fresh lifecycle already has context")
            outcome = runner.protection_outcome or {}
            fill, anchor = outcome.get("fill") or {}, outcome.get("anchor") or {}
            if (outcome.get("established") is not True or fill.get("complete") is not True
                    or anchor.get("reanchored") is not True
                    or (anchor.get("verification") or {}).get("verified") is not True):
                raise BIND.BindingRefused("full fill and structural readback not proven")
            # Re-read order-linked fills and the current position; no intent or
            # contract-only reconciler fallback may seed management authority.
            trades = [t for t in self.session.recent_trades()
                      if str(t.get("orderId")) == str(mission.order_id)]
            qty = sum(int(t.get("size") or 0) for t in trades)
            if not trades or qty <= 0:
                raise BIND.BindingRefused("no order-linked fill evidence")
            vwap = sum(float(t["price"]) * int(t["size"]) for t in trades) / qty
            BIND.number(qty, fill.get("size"), "full fill quantity")
            BIND.number(vwap, fill.get("fill_price"), "full fill price")
            pos = BIND.position(self.session.open_positions(), contract_id=self.contract.id,
                direction=BIND.BB._side(runner.geometry.direction), quantity=qty, fill=vwap)
            ids = anchor["child_ids"]
            mission.observe_position_open(filled_quantity=qty, fill_price=vwap,
                protective_order_ids=list(ids.values()), evidence="bound prompt full fill and structural readback")
            baseline = BIND.recover(owner, mission, self)
            # Build without saving/arming; all identities and fresh children
            # must agree before the durable flag can become authoritative.
            ctx = runner.build_execution_context(candidate_snapshot=candidate,
                mission_id=mission.mission_id, fill_event={"price": vwap},
                stop_order_id=ids["stop"], target_order_id=ids["target"])
            ctx.session_id = baseline["session_id"]
            ctx.token_id = baseline["token_id"]
            ctx.authorization_fingerprint = baseline["authorization_fingerprint"]
            ctx.position_id = pos["id"]
            # Validate geometry before arm; no baseline may be silently rebuilt
            # from the current stop (which is allowed to move later).
            BIND.number(ctx.structural_stop_price, baseline["original_initial_stop"], "fresh stop")
            BIND.number(ctx.liquidity_target_price, baseline["original_target_price"], "fresh target")
            probe = ACT.inspect_protection(session=self.session, contract_id=self.contract.id,
                                           entry_order_id=mission.order_id)
            BIND.protection(probe, ctx, target_price=BIND.aligned_target(ctx, self.contract))
            BIND.number(probe["stop"]["stop_price"], anchor["authorization"]["aligned_stop_price"],
                        "fresh structural stop")
            armed = runner._arm_protection_baseline(
                thesis_invalidation=baseline["original_initial_stop"],
                proven_stop_price=probe["stop"]["stop_price"])
            BIND.context(baseline, ctx, runner)
            ctx.path = self.context_path
            ctx.save()
            recorded = runner._record_establishment(
                SUBREC.ESTABLISHMENT_COMPLETE,
                {"mission_id": mission.mission_id,
                 "entry_order_id": mission.order_id,
                 "actual_fill_price": vwap,
                 "actual_quantity": qty,
                 "structural_stop_price": baseline["original_initial_stop"],
                 "proven_stop_price": probe["stop"]["stop_price"],
                 "target_price": baseline["original_target_price"],
                 "stop_order_id": ids["stop"],
                 "target_order_id": ids["target"],
                 "position_id": pos["id"],
                 "context_path": os.path.basename(self.context_path)})
            if not recorded:
                raise BIND.BindingRefused(
                    "structural baseline armed but completion evidence did not persist")
            return {"status": "armed", "mission_id": mission.mission_id, "arming": armed}
        except Exception as exc:  # management failure cannot undo a protected entry
            if self.runner is not None:
                self.runner.execution_context = None
            return {"status": "management_unavailable", "reason": str(exc)[:200]}

    def _bound_entry_submission(self, mission) -> dict:
        from broker import topstepx_submission_record as SUBREC
        rows = [row for row in SUBREC.latest_by_submission(
                    self.store_dir, self.session_id, mission.mission_id).values()
                if row.get("operation") == SUBREC.OPERATION_ORDER_PLACE
                and str(row.get("venue_order_id")) == str(mission.order_id)]
        if len(rows) != 1:
            raise ProductionLaneRefused(
                f"establishment recovery requires one bound entry submission; "
                f"found {len(rows)}")
        return rows[0]

    @staticmethod
    def _geometry_from_submission(row: dict):
        from broker.topstepx_combine_risk import BracketGeometry
        geo = row.get("geometry") or {}
        if geo.get("governing_caps_declared") is not True:
            raise ProductionLaneRefused(
                "submission does not preserve the effective mission risk ceiling")
        required = (
            "direction", "side", "side_code", "entry_price", "stop_price",
            "target_price", "stop_points", "target_points", "stop_ticks",
            "target_ticks", "size", "risk_usd", "reward_usd",
            "effective_cap_usd", "max_stop_points", "governing_lane")
        missing = [name for name in required if geo.get(name) is None]
        if missing:
            raise ProductionLaneRefused(
                "submission geometry is incomplete: " + ", ".join(missing))
        if geo.get("governing_lane") != "production":
            raise ProductionLaneRefused("submission was not governed by production risk")
        return BracketGeometry(
            direction=str(geo["direction"]), side=str(geo["side"]),
            side_code=int(geo["side_code"]), entry_price=float(geo["entry_price"]),
            stop_price=float(geo["stop_price"]),
            target_price=float(geo["target_price"]),
            stop_points=float(geo["stop_points"]),
            target_points=float(geo["target_points"]),
            stop_ticks=int(geo["stop_ticks"]), target_ticks=int(geo["target_ticks"]),
            size=int(geo["size"]), risk_usd=float(geo["risk_usd"]),
            reward_usd=float(geo["reward_usd"]),
            governing_max_risk_usd=float(geo["effective_cap_usd"]),
            governing_max_stop_points=float(geo["max_stop_points"]),
            governing_lane=str(geo["governing_lane"]))

    def recover_structural_establishment(self, owner, mission) -> dict:
        """Complete the existing post-fill establishment after a cold crash."""
        from broker import break_even_binding as BIND
        from broker import topstepx_order_discovery as DISC
        from broker import topstepx_submission_record as SUBREC
        try:
            baseline = BIND.recover(owner, mission, self)
            row = self._bound_entry_submission(mission)
            geometry = self._geometry_from_submission(row)
            runner = R.ExecutionRunner(
                session=self.session, account_fingerprint=self.account_fingerprint,
                contract=self.contract, clock=self.clock)
            runner.execution_lane = "production"
            runner.geometry = geometry
            runner.max_risk_usd = float(geometry.governing_max_risk_usd)
            runner.max_stop_points = float(geometry.governing_max_stop_points)
            runner.max_contracts = PRODUCTION_MAX_CONTRACTS
            runner.min_reward_to_risk = MIN_REWARD_TO_RISK
            runner.prompt_fill_authority = True
            runner.order_id = mission.order_id
            runner._entry_attempted = True
            runner.submission_store_dir = self.store_dir
            runner.submission_session_id = self.session_id
            runner.submission_mission_id = mission.mission_id
            runner.submission_authorization_fingerprint = baseline[
                "authorization_fingerprint"]
            runner.submission_record = row
            runner.submission_custom_tag = str(row.get("custom_tag") or "")
            structural = (row.get("geometry") or {}).get("structural_invalidation")
            runner.submission_structural_invalidation = (
                dict(structural) if isinstance(structural, dict) else None)

            fill = runner.acquire_full_fill(
                deadline_seconds=self.fill_deadline_seconds)
            if not fill.get("complete"):
                return {"status": "establishment_unavailable",
                        "reason": fill.get("reason"), "fill": fill}
            BIND.number(fill["size"], baseline["quantity"], "recovery fill quantity")
            BIND.number(fill["fill_price"], baseline["entry_fill_price"],
                        "recovery fill VWAP")
            found = DISC.discover_orders(self.session, contract_id=self.contract.id)
            if not found.get("answered") or not found.get("complete"):
                return {"status": "establishment_unavailable",
                        "reason": "complete protection discovery unavailable",
                        "discovery": found}
            children = runner.protective_children(found.get("working") or [])
            position = BIND.position(
                self.session.open_positions(), contract_id=self.contract.id,
                direction=baseline["direction"], quantity=fill["size"],
                fill=fill["fill_price"])
            # Do not turn a COMPLETE proof of missing/ambiguous children into
            # a passive recovery hold.  The existing re-anchor owner already
            # owns that fail-closed decision and its emergency-flat path.  The
            # provisional context carries only identities positively present;
            # it is never persisted or accepted as a baseline unless re-anchor
            # subsequently proves the whole bracket.
            stop_child = children.get("stop") or {}
            target_child = children.get("target") or {}
            ctx = SL.ExecutionContext(
                candidate_id="", candidate_fingerprint=mission.candidate_fingerprint or "",
                snapshot_id="", mission_id=mission.mission_id,
                account_fingerprint=self.account_fingerprint,
                contract_id=self.contract.id, direction=baseline["direction"],
                quantity=fill["size"], entry_order_id=mission.order_id,
                entry_trade_id=(fill.get("trade_ids") or [None])[0],
                entry_fill_price=fill["fill_price"],
                structural_stop_price=baseline["original_initial_stop"],
                liquidity_target_price=baseline["original_target_price"],
                stop_order_id=stop_child.get("id"),
                target_order_id=target_child.get("id"),
                session_id=baseline["session_id"], token_id=baseline["token_id"],
                authorization_fingerprint=baseline["authorization_fingerprint"],
                position_id=position["id"], path=self.context_path)
            runner.execution_context = ctx
            self.runner = runner
            anchor = runner.reanchor_protection_to_structure(
                fill_event={"price": fill["fill_price"], "size": fill["size"],
                            "contract_id": self.contract.id},
                working_orders=found.get("working") or [], recovery_mode=True)
            if not (anchor.get("reanchored") or anchor.get("already_established")):
                return {"status": "establishment_failed", "anchor": anchor,
                        "fill": fill}
            BIND.context(baseline, ctx, runner)
            complete = {
                "mission_id": mission.mission_id, "entry_order_id": mission.order_id,
                "actual_fill_price": fill["fill_price"],
                "actual_quantity": fill["size"],
                "structural_stop_price": baseline["original_initial_stop"],
                "proven_stop_price": ctx.active_protective_stop,
                "target_price": baseline["original_target_price"],
                "stop_order_id": ctx.stop_order_id,
                "target_order_id": ctx.target_order_id,
                "position_id": ctx.position_id,
                "context_path": os.path.basename(self.context_path),
                "recovered": True,
            }
            if not runner._record_establishment(SUBREC.ESTABLISHMENT_COMPLETE,
                                                complete):
                return {"status": "establishment_unavailable",
                        "reason": "completed baseline could not be recorded"}
            runner.protection_outcome = {"established": True, "fill": fill,
                                         "anchor": anchor, "recovered": True}
            return {"status": "establishment_recovered",
                    "mission_id": mission.mission_id, "fill": fill,
                    "anchor": anchor}
        except Exception as exc:
            return {"status": "establishment_unavailable",
                    "reason": str(exc)[:200]}

    def restore_break_even_management(self, owner, mission) -> dict:
        """Restore only management authority. No entry, reanchor or order write."""
        from broker import break_even_binding as BIND
        from broker import break_even_actuator as ACT
        try:
            if SL.ExecutionContext.load(self.context_path) is None:
                return self.recover_structural_establishment(owner, mission)
            baseline = BIND.recover(owner, mission, self)
            ctx = SL.ExecutionContext.load(self.context_path)
            runner = R.ExecutionRunner(session=self.session,
                account_fingerprint=self.account_fingerprint, contract=self.contract, clock=self.clock)
            runner.order_id = mission.order_id
            runner.execution_context = ctx
            BIND.context(baseline, ctx, runner)
            BIND.venue_position(self.session, baseline, ctx)
            probe = ACT.inspect_protection(session=self.session, contract_id=self.contract.id,
                                           entry_order_id=mission.order_id)
            BIND.protection(probe, ctx, target_price=BIND.aligned_target(ctx, self.contract))
            # Existing venue->local truth law; never writes local belief back
            # to the venue, and never substitutes this moving stop for R.
            from broker import protection_state as PROTECTION
            adoption = PROTECTION.reconcile_with_venue(direction=ctx.direction,
                active_protective_stop=ctx.active_protective_stop,
                venue_stop_price=probe["stop"]["stop_price"])
            ctx.active_protective_stop = adoption["adopted"]
            ctx.save()
            runner.submission_store_dir = self.store_dir
            runner.submission_session_id = self.session_id
            runner.submission_mission_id = mission.mission_id
            runner.submission_authorization_fingerprint = baseline["authorization_fingerprint"]
            self.runner = runner
            return {"status": "restored", "mission_id": mission.mission_id, "adoption": adoption}
        except Exception as exc:
            return {"status": "management_unavailable", "reason": str(exc)[:200]}

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

"""
DEPLOY-2C — Broker runtime abstraction (execution side).

Separates Maurice's Alpaca PAPER execution from Tiona's TOPSTEP execution so the
Topstep runtime NEVER imports or calls the Alpaca paper_execution / paper_broker
modules. All Alpaca imports are lazy (inside methods) so importing this module on
the Topstep path pulls in no Alpaca code.

SAFETY DOCTRINE (Topstep):
  * TOPSTEP_EXECUTION_ENABLED defaults FALSE  → observe only, no orders.
  * TOPSTEP_PRACTICE_ONLY defaults TRUE       → practice/sim accounts only.
  * Live/funded account routing is refused.
  * NO BRACKET, NO TRADE (DEPLOY-2D): every entry must carry a native ProjectX
    bracket (stopLossBracket + takeProfitBracket) derived from the bot's existing
    trade plan. There is NO unbracketed override — naked entries are impossible by
    construction. We never synthesise a bracket.
  * Reconciliation reads actual trade records (Trade/search) + orders
    (Order/search), computes realized R from profitAndLoss, and writes an adaptive
    scar per CLOSED trade. Open/incomplete trades write NO scar.

Never raises from run_cycle / reconcile.
"""
from __future__ import annotations

import os


def _flag(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


# DEPLOY-2D — instrument metadata for tick/R math. Keyed by symbol prefix.
#   tick_size   : minimum price increment (points)
#   point_value : USD per 1.0 point per contract
# MNQ (Micro E-mini Nasdaq-100): 0.25 tick, $2.00 / point.
_INSTRUMENTS = {
    "MNQ": {"tick_size": 0.25, "point_value": 2.0},
    "MES": {"tick_size": 0.25, "point_value": 5.0},
    "NQ":  {"tick_size": 0.25, "point_value": 20.0},
    "ES":  {"tick_size": 0.25, "point_value": 50.0},
}


def _instrument_meta(symbol: str):
    s = (symbol or "").upper()
    # longest prefixes first so MNQ matches before NQ, MES before ES
    for key in sorted(_INSTRUMENTS, key=len, reverse=True):
        if s.startswith(key):
            return _INSTRUMENTS[key]
    return None


# ── interface ─────────────────────────────────────────────────────────────────

class BrokerRuntime:
    name = "base"

    def get_account_state(self) -> dict: raise NotImplementedError
    def get_positions(self) -> list: raise NotImplementedError
    def get_open_orders(self) -> list: raise NotImplementedError
    def is_execution_enabled(self) -> bool: raise NotImplementedError
    def is_practice_safe(self) -> bool: raise NotImplementedError
    def submit_order(self, decision: dict) -> dict: raise NotImplementedError
    def cancel_order(self, order_id) -> dict: raise NotImplementedError
    def close_position(self, contract_id) -> dict: raise NotImplementedError
    def reconcile(self) -> dict: raise NotImplementedError

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default


# ── Maurice — Alpaca paper (thin wrappers; lazy Alpaca imports) ────────────────

class AlpacaPaperRuntime(BrokerRuntime):
    name = "alpaca_paper"

    def __init__(self, symbol: str = None, config=None):
        self.symbol = symbol
        self.config = config

    def is_execution_enabled(self) -> bool:
        return _flag("EXECUTION_ENABLED")

    def is_practice_safe(self) -> bool:
        return _flag("PAPER_TRADING_ONLY", "true")

    def get_positions(self) -> list:
        from paper_execution.paper_broker import get_position
        p = self._safe(lambda: get_position(self.symbol), None)
        return [p] if p and "error" not in (p or {}) else []

    def reconcile(self) -> dict:
        from paper_execution.trade_reconciliation import reconcile_trade
        return reconcile_trade(self.symbol)

    # Maurice's live loop (run_scan_loop) keeps its proven inline Alpaca block;
    # these wrappers exist for interface symmetry + tests.


# ── Tiona — Topstep (ProjectX); never touches Alpaca ───────────────────────────

class TopstepRuntime(BrokerRuntime):
    name = "topstep"

    def __init__(self, symbol: str = None, config=None):
        from broker.topstep_adapter import TopstepBrokerAdapter
        self.symbol = symbol
        self.config = config
        self.adapter = TopstepBrokerAdapter(config)

    # ── safety gates ──────────────────────────────────────────────────────────
    def is_execution_enabled(self) -> bool:
        cfg_enabled = bool(getattr(self.config, "execution_enabled", False))
        return _flag("TOPSTEP_EXECUTION_ENABLED") and cfg_enabled

    def is_practice_safe(self) -> bool:
        practice_only = _flag("TOPSTEP_PRACTICE_ONLY", "true")
        env_practice = self._safe(self.adapter._is_practice, False)
        acct = self._safe(self.adapter.get_account, {})
        acct_practice = bool(acct.get("simulated")) if acct.get("connected") else env_practice
        return bool(practice_only and env_practice and acct_practice)

    # ── reads ───────────────────────────────────────────────────────────────
    def get_account_state(self) -> dict:
        return self._safe(self.adapter.get_account, {"connected": False})

    def get_positions(self) -> list:
        return self._safe(self.adapter.get_positions, []) or []

    def get_open_orders(self) -> list:
        return self._safe(self.adapter.get_open_orders, []) or []

    def _contract_size(self) -> int:
        try:
            return int(getattr(self.config, "contract_size", 1) or 1)
        except (TypeError, ValueError):
            return 1

    # ── trade plan + bracket (DEPLOY-2D) ──────────────────────────────────────
    def _resolve_contract(self, symbol: str):
        try:
            contracts = self.adapter.client.search_contract(symbol)
        except Exception:  # noqa: BLE001
            return None
        for c in contracts or []:
            name = str(c.get("name") or c.get("symbol") or c.get("contractId") or "")
            if symbol.upper() in name.upper():
                return c.get("id") or c.get("contractId")
        if contracts:
            return contracts[0].get("id") or contracts[0].get("contractId")
        return None

    def _trade_plan(self, snapshot: dict, decision: dict):
        """Entry/stop/target from the bot's EXISTING plan (toolbox price level).
        Returns (plan, None) on success, or (None, reason) naming the EXACT missing
        field. No synthetic stop is EVER invented — an absent invalidation level
        blocks the trade. Every failure carries the 'no_trade_plan' tag plus the
        precise cause so the block is self-diagnosing in the live log."""
        tb = snapshot.get("toolbox", {}) or {}
        if not tb:
            return None, "no_trade_plan: toolbox absent from snapshot"
        pref = tb.get("preferred_tool")
        if not pref:
            return None, "no_trade_plan: no preferred_tool selected (no tool to price)"
        cand = next((c for c in tb.get("tool_candidates", []) if c.get("tool") == pref), None)
        if not cand:
            return None, f"no_trade_plan: preferred_tool '{pref}' has no scored candidate"
        pl = cand.get("price_level", {}) or {}
        if not pl:
            return None, f"no_trade_plan: preferred_tool '{pref}' has no price_level"
        entry = pl.get("midpoint") if pl.get("midpoint") is not None else pl.get("current_price")
        stop = pl.get("invalidation_level")
        if entry is None:
            return None, (f"no_trade_plan: entry unavailable for '{pref}' "
                          "(price_level.midpoint and current_price both absent)")
        if stop is None:
            return None, (f"no_trade_plan: stop unavailable for '{pref}' "
                          "(price_level.invalidation_level absent) — no synthetic stop invented")
        try:
            entry, stop = float(entry), float(stop)
        except (TypeError, ValueError):
            return None, f"no_trade_plan: entry/stop not numeric for '{pref}'"
        if entry == stop:
            return None, f"no_trade_plan: entry == stop (zero risk distance) for '{pref}'"
        risk_pts = abs(entry - stop)
        rmult = float(os.getenv("TAKE_PROFIT_R", "2.0"))
        side = decision.get("side")
        target = entry + risk_pts * rmult if side == "buy" else entry - risk_pts * rmult
        return ({"entry": entry, "stop": stop, "target": target,
                 "risk_points": risk_pts, "target_points": risk_pts * rmult, "rmult": rmult}, None)

    def _bracket_legs(self, plan: dict):
        """Convert the plan's stop/target distances to native ProjectX bracket
        legs (ticks). Returns None if the instrument is unknown (no faking)."""
        meta = _instrument_meta(self.symbol)
        if not meta:
            return None
        tick = meta["tick_size"]
        stop_ticks = max(1, round(plan["risk_points"] / tick))
        tgt_ticks = max(1, round(plan["target_points"] / tick))
        # ProjectX bracket type enum: 4=Stop, 1=Limit
        return ({"ticks": stop_ticks, "type": 4}, {"ticks": tgt_ticks, "type": 1})

    # ── writes (heavily guarded; NO bracket → NO trade) ───────────────────────
    def submit_order(self, decision: dict, snapshot: dict = None) -> dict:
        if not self.is_execution_enabled():
            return {"action": "observe", "placed": False,
                    "reason": "execution_disabled (TOPSTEP_EXECUTION_ENABLED=false)",
                    "would": decision}
        if not self.is_practice_safe():
            return {"action": "blocked", "placed": False,
                    "reason": "account_not_practice_sim — live/funded routing refused"}
        side = decision.get("side")
        if side not in ("buy", "sell"):
            return {"action": "skip", "placed": False, "reason": "no_directional_side"}

        # DOCTRINE: no bracket, no trade. The plan (entry+stop+target) and the
        # native ProjectX bracket legs MUST both resolve, or the order is blocked.
        plan, plan_reason = self._trade_plan(snapshot or {}, decision)
        if plan is None:
            return {"action": "blocked", "placed": False,
                    "reason": f"{plan_reason}; no bracket, no trade"}
        legs = self._bracket_legs(plan)
        if legs is None:
            return {"action": "blocked", "placed": False,
                    "reason": f"unknown_instrument_tick_size for {self.symbol} — cannot "
                              "build native bracket; no bracket, no trade"}
        stop_leg, tp_leg = legs

        contract_id = self._resolve_contract(self.symbol)
        order = {
            "symbol": self.symbol, "contractId": contract_id, "side": side,
            "type": "market", "size": decision.get("qty", self._contract_size()),
            "stopLossBracket": stop_leg, "takeProfitBracket": tp_leg,
        }
        try:
            res = self.adapter.submit_order(order)
        except Exception as exc:  # noqa: BLE001
            return {"action": "error", "placed": False,
                    "reason": f"{type(exc).__name__}: {exc}"}

        # Journal entry-time context so the closed trade can later become a scar.
        journaled = self._journal_entry(snapshot or {}, decision, plan, contract_id, res)
        out = {"action": "submitted", "placed": True, "order": order,
               "plan": plan, "broker_response": res, "entry_journaled": bool(journaled)}
        if not journaled:
            # Order is live but its reconciliation context failed to persist —
            # surfaced loudly (NOT silent); this trade may not produce a scar.
            out["warning"] = "entry_journal_failed — trade may be unreconcilable"
        return out

    def _journal_entry(self, snapshot, decision, plan, contract_id, broker_response) -> bool:
        """Journal entry-time context so the closed trade can later become a scar.
        Returns True on success; caller surfaces a failure (no silent loss)."""
        from broker.topstep_entry_store import record_entry
        na = snapshot.get("narrative_authority", {}) or {}
        mr = snapshot.get("market_regime", {}) or {}
        ai = snapshot.get("ai_brain", {}) or {}
        ab_out = ai.get("output") if isinstance(ai.get("output"), dict) else {}
        order_id = None
        if isinstance(broker_response, dict):
            order_id = broker_response.get("orderId") or broker_response.get("id")
        ts = snapshot.get("timestamp")
        # Stable settlement key: contract + entry order + entry timestamp.
        entry_key = f"{contract_id}|{order_id}|{ts}"
        # shaped so outcome_assembler.assemble_closed_trade_outcome reads it directly
        return record_entry({
            "provider": "topstep", "entry_key": entry_key,
            "order_id": order_id, "contract_id": contract_id,
            "symbol": self.symbol,
            "timestamp": ts,
            "side": decision.get("side"),
            "entry_reference": plan["entry"], "stop_reference": plan["stop"],
            "target_price": plan["target"], "qty": decision.get("qty", self._contract_size()),
            "point_value": (_instrument_meta(self.symbol) or {}).get("point_value"),
            "market_regime_label": mr.get("regime_label"),
            "volatility_state": mr.get("volatility_state"),
            "expansion_state": mr.get("expansion_state"),
            "narrative_direction_at_entry": decision.get("direction"),
            "narrative_phase_at_entry": ab_out.get("narrative_phase"),
            "ai_confidence_at_entry": ab_out.get("phase_confidence"),
            "liquidity_draw_at_entry": na.get("active_liquidity_draw"),
            "snapshot_summary": {"session": snapshot.get("session"),
                                 "playbook": decision.get("playbook")},
            "ai_thesis_summary": (ab_out.get("dominant_reasoning") or "")[:240],
            "reconciled": False,
        })

    def cancel_order(self, order_id) -> dict:
        if not self.is_execution_enabled():
            return {"action": "observe", "placed": False, "reason": "execution_disabled"}
        return self._safe(lambda: self.adapter.cancel_order(order_id), {"action": "error"})

    def close_position(self, contract_id) -> dict:
        if not self.is_execution_enabled():
            return {"action": "observe", "placed": False, "reason": "execution_disabled"}
        return self._safe(lambda: self.adapter.flatten_position(contract_id), {"action": "error"})

    # ── reconciliation (Trade/search + Order/search → realized R → scar) ───────
    def _account_id(self):
        acct = self._safe(lambda: self.adapter._resolve_account(), {})
        return acct.get("id")

    def _session_start_iso(self):
        from datetime import datetime, timezone, timedelta
        lookback_days = int(os.getenv("TOPSTEP_RECON_LOOKBACK_DAYS", "1"))
        return (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    @staticmethod
    def _realized_r(pnl, entry, stop, point_value, size):
        """R = realized PnL / dollar risk. dollar_risk = |entry-stop| * pt_value * size."""
        try:
            dollar_risk = abs(float(entry) - float(stop)) * float(point_value) * int(size)
            if dollar_risk <= 0:
                return None
            return round(float(pnl) / dollar_risk, 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fetch(fn):
        """Run an API read; return (rows, error). Errors are surfaced, NOT
        silently swallowed to an empty list."""
        try:
            return (fn() or []), None
        except Exception as exc:  # noqa: BLE001
            return [], exc

    @staticmethod
    def _settle_round_trips(trades: list) -> list:
        """Fold ProjectX half-turn executions into per-contract round-trips.

        Walks executions chronologically per contract, tracking signed net size.
        Same-direction executions are scale-INs (build the weighted entry + opened
        size); opposite-direction executions are scale-OUTs (exits). A round-trip
        is FLAT (settled) only when net size returns to 0. Partial fills, scale-in
        and scale-out are all handled. Leftover open size is emitted as unsettled
        (flat=False) → no scar. Never raises."""
        from collections import defaultdict
        by_contract = defaultdict(list)
        for t in trades:
            if t.get("voided"):
                continue
            by_contract[str(t.get("contractId") or "")].append(t)

        out = []
        for cid, execs in by_contract.items():
            execs.sort(key=lambda e: str(e.get("creationTimestamp") or ""))
            net, rt = 0, None
            for e in execs:
                try:
                    size = int(e.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                if size <= 0:
                    continue
                signed = size if e.get("side") == 0 else -size   # 0=buy,1=sell
                price = e.get("price")
                if net == 0:
                    rt = {"contractId": cid, "open_ts": str(e.get("creationTimestamp") or ""),
                          "dir": 1 if signed > 0 else -1, "open_num": 0.0, "opened_size": 0,
                          "pnl": 0.0, "exit_price": None, "exit_ts": None, "flat": False}
                rt["pnl"] += float(e.get("profitAndLoss") or 0.0)
                if (signed > 0) == (rt["dir"] > 0):       # opening / scale-in
                    if price is not None:
                        rt["open_num"] += float(price) * size
                    rt["opened_size"] += size
                else:                                      # closing / scale-out
                    rt["exit_price"] = price
                    rt["exit_ts"] = str(e.get("creationTimestamp") or "")
                net += signed
                if net == 0:
                    rt["weighted_entry"] = (rt["open_num"] / rt["opened_size"]
                                            if rt["opened_size"] else None)
                    rt["flat"] = True
                    out.append(rt)
                    rt = None
            if rt is not None:   # position still open at end of window → unsettled
                rt["weighted_entry"] = (rt["open_num"] / rt["opened_size"]
                                        if rt["opened_size"] else None)
                out.append(rt)
        return out

    @staticmethod
    def _match_entry(entries, contract_id, open_ts):
        """FIFO pairing: earliest UNRECONCILED journaled entry on this contract at
        or before the round-trip's open. Falls back to any unreconciled entry on
        the contract (tolerates entry/exec timestamp-format differences)."""
        cands = [e for e in entries
                 if str(e.get("contract_id") or "") == contract_id
                 and str(e.get("timestamp") or "") <= str(open_ts or "")]
        if not cands:
            cands = [e for e in entries if str(e.get("contract_id") or "") == contract_id]
        if not cands:
            return None
        cands.sort(key=lambda e: str(e.get("timestamp") or ""))
        return cands[0]   # earliest unreconciled → FIFO

    def reconcile(self) -> dict:
        """DEPLOY-2D.1 — settlement-based reconciliation. Reads executions
        (Trade/search) + orders (Order/search), folds them into per-contract
        round-trips (scale-in/out, partials), and on each FLAT round-trip pairs
        FIFO to its journaled entry, computes SIZE-AWARE realized R, writes ONE
        scar, and marks the entry reconciled (so reruns/restarts never re-scar).
        Open/unsettled round-trips write NO scar. API failures are surfaced.
        Never raises."""
        from broker.topstep_entry_store import load_entries, mark_reconciled
        acct_id = self._account_id()
        if acct_id is None:
            return {"provider": "topstep", "status": "no_account",
                    "closed_trades": 0, "scars_written": 0,
                    "errors": ["account_unresolved"]}

        start = self._session_start_iso()
        trades, t_err = self._fetch(lambda: self.adapter.client.search_trades(acct_id, start))
        orders, o_err = self._fetch(lambda: self.adapter.client.search_orders(acct_id, start))
        errors = []
        if o_err:
            errors.append(f"order_search_failed:{type(o_err).__name__}")
        if t_err:
            # No trade truth → cannot reconcile. Surface loudly, write nothing.
            errors.append(f"trade_search_failed:{type(t_err).__name__}")
            return {"provider": "topstep", "status": "trade_search_error",
                    "errors": errors, "closed_trades": 0, "scars_written": 0}

        round_trips = self._settle_round_trips(trades)
        entries = [e for e in load_entries() if not e.get("reconciled")]

        scars, results = 0, []
        for rt in sorted(round_trips, key=lambda r: str(r.get("open_ts") or "")):
            if not rt.get("flat"):
                results.append({"contractId": rt["contractId"], "settled": False,
                                "reason": "position_open"})
                continue
            entry = self._match_entry(entries, rt["contractId"], rt["open_ts"])
            if entry is None:
                results.append({"contractId": rt["contractId"], "matched": False,
                                "reason": "no_journaled_entry_context",
                                "realized_pnl": rt["pnl"]})
                continue
            realized_r = self._realized_r(
                rt["pnl"], entry.get("entry_reference"), entry.get("stop_reference"),
                entry.get("point_value"), rt["opened_size"])
            wrote = self._write_scar(entry, rt, realized_r)
            if wrote.get("written") or wrote.get("skipped"):
                # settled (written now or already deduped) → lifecycle close
                mark_reconciled(entry.get("entry_key"))
                entries = [e for e in entries
                           if e.get("entry_key") != entry.get("entry_key")]
            scars += 1 if wrote.get("written") else 0
            results.append({"contractId": rt["contractId"], "matched": True,
                            "opened_size": rt["opened_size"],
                            "realized_pnl": rt["pnl"], "realized_r": realized_r,
                            "scar": wrote})

        return {
            "provider": "topstep", "status": "reconciled", "errors": errors,
            "account": self.get_account_state(),
            "open_positions": len(self.get_positions()),
            "open_orders": len(orders),
            "trades_seen": len(trades),
            "round_trips": len(round_trips),
            "closed_trades": sum(1 for rt in round_trips if rt.get("flat")),
            "scars_written": scars, "results": results,
        }

    def _write_scar(self, entry, rt, realized_r):
        """Assemble + write the adaptive scar from a SETTLED round-trip. Reuses the
        broker-agnostic outcome doctrine; never writes when realized_r is None."""
        if realized_r is None:
            return {"written": False, "reason": "realized_r_unavailable"}
        from adaptive_learning.outcome_assembler import assemble_closed_trade_outcome
        from adaptive_learning.live_memory_writer import write_outcome
        recon = {
            "status": "closed", "symbol": entry.get("symbol"),
            "trade_id": f"TS-{entry.get('entry_key')}",
            "realized_r": realized_r, "realized_pnl": rt.get("pnl"),
            "entry_price": entry.get("entry_reference"),
            "exit_price": rt.get("exit_price"),
            "close_reason": "topstep_bracket_exit",
        }
        outcome = assemble_closed_trade_outcome(recon, entry, None)
        return write_outcome(outcome, source_type="closed_trade")

    # ── one runtime cycle (called per scan) ────────────────────────────────────
    def run_cycle(self, snapshot: dict, symbol: str) -> dict:
        account = self.get_account_state()
        positions = self.get_positions()
        orders = self.get_open_orders()
        decision = self._proposed_decision(snapshot or {})

        if not decision.get("actionable"):
            order_result = {"action": "none", "placed": False,
                            "reason": "no_actionable_decision"}
        elif positions:
            order_result = {"action": "skip", "placed": False, "reason": "position_open"}
        else:
            order_result = self.submit_order(decision, snapshot)

        return {
            "provider": "topstep",
            "symbol": symbol,
            "mode": "execute" if self.is_execution_enabled() else "observe",
            "account_ok": bool(account.get("connected")),
            "practice_safe": self.is_practice_safe(),
            "open_positions": len(positions),
            "open_orders": len(orders),
            "decision": decision,
            "order_action": order_result.get("action"),
            "order_result": order_result,
            "reconcile": self.reconcile(),
        }

    def _proposed_decision(self, snapshot: dict) -> dict:
        pb = snapshot.get("playbook", {}) or {}
        ql = snapshot.get("qualification", {}) or {}
        risk = snapshot.get("risk", {}) or {}
        direction = (pb.get("direction") or ql.get("direction") or "neutral")
        allowed = bool(risk.get("trade_allowed", False))
        actionable = direction in ("bullish", "bearish") and allowed
        side = {"bullish": "buy", "bearish": "sell"}.get(direction)
        return {
            "direction": direction, "side": side, "actionable": actionable,
            "qualification": ql.get("status"),
            "playbook": pb.get("selected_playbook"),
            "risk_allowed": allowed, "qty": self._contract_size(),
        }


# ── factory ─────────────────────────────────────────────────────────────────

def get_runtime(execution_provider: str, symbol: str = None, config=None) -> BrokerRuntime:
    """Select the execution runtime. 'topstep' → TopstepRuntime (no Alpaca);
    'alpaca_paper'/'alpaca'/'paper' → AlpacaPaperRuntime. Unknown raises."""
    ep = (execution_provider or "alpaca_paper").lower().strip()
    if ep == "topstep":
        return TopstepRuntime(symbol, config)
    if ep in ("alpaca_paper", "alpaca", "paper"):
        return AlpacaPaperRuntime(symbol, config)
    raise ValueError(f"Unknown execution_provider: {execution_provider!r} "
                     "(supported: alpaca_paper, topstep)")

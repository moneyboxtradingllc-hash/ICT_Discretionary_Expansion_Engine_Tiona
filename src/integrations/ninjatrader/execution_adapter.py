"""Phase 9 — NinjaTrader DEMO8458533 execution adapter (DISARMED in foundation).

Sits behind the existing broker interface (broker.base.BrokerAdapter). It is a
TRANSLATOR and STATE SYNCHRONIZER, never an originator:

  * It cannot decide direction.
  * It cannot decide whether a trade is valid.
  * It cannot resize beyond the organism's authorized quantity.
  * It enforces DEMO8458533 + exact MNQ expiry + qty<=1 as DEFENSE IN DEPTH, even if
    upstream gates or NinjaTrader Global Simulation Mode are misconfigured.

In the foundation mission automated submission is DISARMED
(AUTOMATED_ORDER_SUBMISSION_ARMED is False) and there is no smoke-order
authorization token, so `submit_order` ALWAYS denies before any wire call.
Every guard is still exercised so we can prove the order path is correct and
safe before it is ever armed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError
from integrations.ninjatrader import (
    AUTOMATED_ORDER_SUBMISSION_ARMED, MAX_CONTRACTS_FOUNDATION, INTEGRATION_VERSION,
)
from integrations.ninjatrader import account_safety
from integrations.ninjatrader.account_safety import GateInputs

# Required identity/authorization fields on every order intent.
REQUIRED_INTENT_FIELDS = (
    "authorization_id", "intent_id", "thesis_id", "instrument", "account",
    "direction", "quantity", "client_order_id", "timestamp",
    "current_position_state", "risk_authorization", "stop_definition",
)

VALID_DIRECTIONS = frozenset({"long", "short", "buy", "sell"})


@dataclass
class SubmitResult:
    submitted: bool
    denied_reason: str = ""
    order_ref: Optional[str] = None
    idempotent_replay: bool = False


class NinjaTraderBrokerAdapter(BrokerAdapter):
    """DISARMED DEMO8458533 adapter. Proves the guard chain without sending orders."""

    def __init__(self, config=None, *, resolved_expiry_name: Optional[str] = None,
                 armed: bool = AUTOMATED_ORDER_SUBMISSION_ARMED,
                 smoke_authorization_token: Optional[str] = None,
                 wire=None):
        super().__init__(config)
        self.resolved_expiry_name = resolved_expiry_name
        # `armed` can never exceed the module-level constant in the foundation
        # era: hard-clamp to False.
        self._armed = bool(armed) and AUTOMATED_ORDER_SUBMISSION_ARMED
        self._smoke_token = smoke_authorization_token
        self._wire = wire                 # bridge client; None = no wire (read/deny only)
        self._seen_intents = {}           # client_order_id -> order_ref (idempotency)

    @property
    def name(self) -> str:
        return "ninjatrader"

    def capability(self) -> BrokerCapability:
        return BrokerCapability(
            name="ninjatrader", supports_orders=False, paper_only=True,
            connected=self.is_connected(),
            notes=(f"DEMO8458533-only MNQ adapter v{INTEGRATION_VERSION}; automated "
                   f"submission DISARMED (foundation). Max {MAX_CONTRACTS_FOUNDATION} "
                   f"contract; live accounts forbidden."))

    def is_connected(self) -> bool:
        if self._wire is None:
            return False
        try:
            return bool(self._wire.is_connected())
        except Exception:  # noqa: BLE001
            return False

    def get_account(self) -> dict:
        if self._wire is None:
            return {"broker": "ninjatrader", "account_id": self.account_id,
                    "connected": False, "armed": False, "known": False}
        return dict(self._wire.account_state() or {})

    def get_position(self, symbol: str) -> dict:
        if self._wire is None:
            return {"symbol": symbol, "qty": 0, "known": False}
        return dict(self._wire.position(symbol) or {})

    # ── intent validation (defense in depth) ─────────────────────────────────
    def _validate_intent(self, order: dict) -> Optional[str]:
        if not isinstance(order, dict):
            return "order intent is not a dict"
        for f in REQUIRED_INTENT_FIELDS:
            if f not in order or order.get(f) in (None, ""):
                return f"order intent missing required field {f!r}"
        if str(order["direction"]).strip().lower() not in VALID_DIRECTIONS:
            return f"invalid direction {order['direction']!r}"
        # stop_definition must be present and non-trivial.
        stop = order.get("stop_definition")
        if not isinstance(stop, dict) or "stop_price" not in stop:
            return "stop_definition must include a stop_price"
        return None

    def _safety_gate(self, order: dict, *, position_state_known: bool,
                     account_state_known: bool, connection_healthy: bool) -> account_safety.SafetyDecision:
        return account_safety.evaluate_fresh_entry(GateInputs(
            account=order.get("account"),
            instrument=order.get("instrument"),
            resolved_expiry_name=self.resolved_expiry_name,
            quantity=order.get("quantity"),
            connection_healthy=connection_healthy,
            account_state_known=account_state_known,
            position_state_known=position_state_known,
            contract_expiry_certain=bool(self.resolved_expiry_name),
        ))

    def submit_order(self, order: dict, *,
                     position_state_known: bool = False,
                     account_state_known: bool = False,
                     connection_healthy: bool = False) -> dict:
        """Attempt to submit an authorized entry intent.

        In the foundation mission this ALWAYS denies (disarmed / no smoke token),
        but only AFTER proving the intent and every safety gate. It can never
        originate direction, change direction, or increase quantity.
        """
        res = self._attempt_submit(order,
                                   position_state_known=position_state_known,
                                   account_state_known=account_state_known,
                                   connection_healthy=connection_healthy)
        return {
            "submitted": res.submitted,
            "denied_reason": res.denied_reason,
            "order_ref": res.order_ref,
            "idempotent_replay": res.idempotent_replay,
            "armed": self._armed,
        }

    def _attempt_submit(self, order, *, position_state_known, account_state_known,
                        connection_healthy) -> SubmitResult:
        # 1) Structural/authorization validation.
        problem = self._validate_intent(order)
        if problem:
            return SubmitResult(False, f"intent rejected: {problem}")

        # 2) Idempotency — a duplicate client_order_id never creates a 2nd order.
        coid = str(order["client_order_id"])
        if coid in self._seen_intents:
            return SubmitResult(False, "duplicate client_order_id — idempotent no-op",
                                order_ref=self._seen_intents[coid], idempotent_replay=True)

        # 3) Defense-in-depth safety gates (DEMO8458533 + MNQ + qty<=1 + certainty).
        gate = self._safety_gate(order,
                                 position_state_known=position_state_known,
                                 account_state_known=account_state_known,
                                 connection_healthy=connection_healthy)
        if not gate:
            return SubmitResult(False, f"safety gate: {gate.reason}")

        # 4) Quantity may never exceed authorized — clamp check (never resize UP).
        if int(float(order["quantity"])) > MAX_CONTRACTS_FOUNDATION:
            return SubmitResult(False, "quantity exceeds authorized ceiling")

        # 5) ARM + explicit smoke authorization. In the foundation mission both
        #    are absent, so we deny here BEFORE any wire call.
        if not self._armed:
            return SubmitResult(False,
                                "automated order submission DISARMED (foundation mission)")
        if not self._smoke_token:
            return SubmitResult(False,
                                "no explicit smoke-order authorization token present")

        # 6) (Only reachable in a future armed mission.) Require a live wire.
        if self._wire is None:
            return SubmitResult(False, "no bridge wire connected")

        order_ref = self._wire.submit(order)  # pragma: no cover - never armed here
        self._seen_intents[coid] = order_ref
        return SubmitResult(True, "", order_ref=order_ref)

    # ── protective-order path (SEPARATE authority) ───────────────────────────
    def submit_protective_stop(self, position_ref: str, stop_definition: dict) -> dict:
        """Managing an EXISTING position's protective stop is a distinct path from
        fresh-entry authority. It stays available even when new-entry authority is
        revoked. In the foundation mission there is no live position and no wire,
        so this is a no-op that records intent."""
        if self._wire is None:
            return {"submitted": False,
                    "reason": "no wire (foundation) — protective path is separate and "
                              "remains available when armed",
                    "position_ref": position_ref, "stop": stop_definition}
        return dict(self._wire.protective_stop(position_ref, stop_definition) or {})

    # ── reconciliation ───────────────────────────────────────────────────────
    def reconcile(self, internal_state: dict) -> dict:
        """Compare internal organism state against NinjaTrader-reported state.
        With no wire (foundation), returns an explicit UNRECONCILED-but-flat
        report rather than a false clean."""
        if self._wire is None:
            return {"reconciled": False, "reason": "no wire — read-only foundation",
                    "internal": internal_state, "platform": None}
        platform = {
            "position": self._wire.position(self.resolved_expiry_name),
            "orders": self._wire.working_orders(),
            "account": self._wire.account_state(),
        }
        pos = platform["position"] or {}
        clean = (int((internal_state or {}).get("qty", 0)) == int(pos.get("qty", 0)))
        return {"reconciled": clean, "internal": internal_state, "platform": platform}

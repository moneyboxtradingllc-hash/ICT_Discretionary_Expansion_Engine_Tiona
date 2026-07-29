"""MNQ-DEMO8458533-SMOKE-ORDER — controlled order path (Python side).

Builds and (only when every gate is satisfied) transmits EXACTLY ONE order:

    LONG 1 MNQ SEP26 MARKET on DEMO8458533
      + protective STOP  5.00 pts below the fill
      + profit  TARGET   5.00 pts above the fill
      + STOP/TARGET share one OCO id, qty 1 each

TWO INDEPENDENT CONTROLS gate transmission, per doctrine:
    (1) a valid, unused, matching one-use authorization token, AND
    (2) TRANSMIT_LATCH == True
The mere existence of a token NEVER transmits. TRANSMIT_LATCH defaults False and
must be passed True explicitly by the final SEND step. The NinjaScript bridge is
ALSO disarmed (ArmOrders=false) as a third, physical control.

Proven here (mock wire): account/instrument/quantity/direction pinning, tick
normalization, common OCO identity, stop/target qty 1, duplicate-entry
rejection, token burn on attempt, automatic re-disarm, and emergency flatten if
protection cannot be established.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

from integrations.ninjatrader import smoke_authorization as auth

# Global default: transmission is LATCHED OFF. Only the explicit SEND step passes
# transmit_latch=True into transmit().
TRANSMIT_LATCH = False

from integrations.ninjatrader.deterministic import (
    ACCOUNT as _CFG_ACCOUNT, INSTRUMENT as _CFG_INSTRUMENT)

ACCOUNT = _CFG_ACCOUNT   # per-operator config, see .env.template
INSTRUMENT = _CFG_INSTRUMENT   # per-operator config, see .env.template
TICK = 0.25
DIRECTION = "long"
ENTRY_TYPE = "market"
QUANTITY = 1


class TransmitError(RuntimeError):
    pass


class OrderWire(Protocol):
    def submit_market_entry(self, intent: dict) -> dict: ...
    def submit_oco(self, stop: dict, target: dict) -> dict: ...
    def flatten(self, instrument: str) -> dict: ...
    def position(self, instrument: str) -> dict: ...
    def order_summary(self) -> dict: ...


def normalize_tick(price: float, tick: float = TICK) -> float:
    return round(round(float(price) / tick) * tick, 6)


def build_protective_orders(fill_price: float, oco_id: str,
                            stop_points: float = 5.0, target_points: float = 5.0) -> dict:
    """Stop 5 below, target 5 above the LONG fill; both qty 1, same OCO id."""
    stop_price = normalize_tick(fill_price - stop_points)
    target_price = normalize_tick(fill_price + target_points)
    stop = {"account": ACCOUNT, "instrument": INSTRUMENT, "action": "sell",
            "order_type": "stop_market", "quantity": QUANTITY,
            "stop_price": stop_price, "oco_id": oco_id}
    target = {"account": ACCOUNT, "instrument": INSTRUMENT, "action": "sell",
              "order_type": "limit", "quantity": QUANTITY,
              "limit_price": target_price, "oco_id": oco_id}
    return {"stop": stop, "target": target}


def build_entry_intent(authorization_id: str, intent_id: str, thesis_id: str,
                       client_order_id: str) -> dict:
    return {"authorization_id": authorization_id, "intent_id": intent_id,
            "thesis_id": thesis_id, "instrument": INSTRUMENT, "account": ACCOUNT,
            "direction": DIRECTION, "entry_type": ENTRY_TYPE, "quantity": QUANTITY,
            "client_order_id": client_order_id, "timestamp": time.time(),
            "current_position_state": "flat", "risk_authorization": authorization_id,
            "stop_definition": {"points_below": 5.0}, "purpose": "EXECUTION_SMOKE_TEST"}


@dataclass
class TransmitResult:
    transmitted: bool
    reason: str
    entry: Optional[dict] = None
    fill_price: Optional[float] = None
    protective: Optional[dict] = None
    protection_established: bool = False
    emergency_flattened: bool = False
    token_id: Optional[str] = None
    telemetry: list = field(default_factory=list)


@dataclass
class SmokeOrderPath:
    wire: object
    token_path: str = auth.TOKEN_PATH
    _attempted: bool = field(default=False, init=False)     # re-disarm after one attempt
    _submitted_coids: set = field(default_factory=set, init=False)
    telemetry: list = field(default_factory=list, init=False)

    def _log(self, event: str, **kw):
        rec = {"at": time.time(), "event": event, **kw}
        self.telemetry.append(rec)
        return rec

    def transmit(self, entry_intent: dict, *, preflight_go: bool,
                 transmit_latch: bool = TRANSMIT_LATCH,
                 now: Optional[float] = None) -> TransmitResult:
        """Attempt the single smoke order. Fails closed on ANY gate.

        Order of gates (all must hold):
          re-disarm -> latch -> preflight GO -> duplicate -> token consume(burn)
          -> entry -> fill -> protective OCO -> (emergency flatten on failure).
        """
        coid = str(entry_intent.get("client_order_id"))

        # 0. Automatic re-disarm: only ever one attempt per instance.
        if self._attempted:
            return TransmitResult(False, "re-disarmed: an attempt already occurred (one-shot)")
        # Duplicate entry rejection.
        if coid in self._submitted_coids:
            return TransmitResult(False, f"duplicate client_order_id {coid} rejected")

        # 1. TRANSMIT_LATCH must be explicitly True.
        if transmit_latch is not True:
            return TransmitResult(False, "TRANSMIT_LATCH is false — transmission disabled")

        # 2. Fresh preflight must be GO (caller passes the live 12/12 result).
        if preflight_go is not True:
            return TransmitResult(False, "preflight is not GO")

        # 3. Pin every field to the authorized values (defense in depth).
        if entry_intent.get("account") != ACCOUNT:
            return TransmitResult(False, "account pin failed")
        if entry_intent.get("instrument") != INSTRUMENT:
            return TransmitResult(False, "instrument pin failed")
        if int(entry_intent.get("quantity", 0)) != QUANTITY:
            return TransmitResult(False, "quantity pin failed")
        if str(entry_intent.get("direction")).lower() != DIRECTION:
            return TransmitResult(False, "direction pin failed")
        if str(entry_intent.get("entry_type")).lower() != ENTRY_TYPE:
            return TransmitResult(False, "entry_type pin failed")

        # From here we WILL make an attempt: latch the one-shot immediately.
        self._attempted = True

        # 4. Consume (burn) the token BEFORE sending. One-use, matched to trade.
        consumed = auth.consume_token(ACCOUNT, INSTRUMENT, QUANTITY,
                                      intent_id=str(entry_intent.get("intent_id")),
                                      path=self.token_path, now=now,
                                      direction=DIRECTION, entry_type=ENTRY_TYPE)
        if not consumed:
            return TransmitResult(False, f"authorization: {consumed.reason}")
        token_id = consumed.token.token_id
        self._log("token_burned", token_id=token_id)

        # 5. Submit the market entry.
        self._submitted_coids.add(coid)
        self._log("entry_submit", intent=coid)
        ack = self.wire.submit_market_entry(entry_intent) or {}
        if not ack.get("accepted"):
            self._log("entry_rejected", ack=ack)
            return TransmitResult(False, f"entry rejected by wire: {ack.get('reason')}",
                                  token_id=token_id, telemetry=list(self.telemetry))

        fill_price = ack.get("avg_fill_price")
        if fill_price is None:
            # No fill -> nothing to protect; report (token already burned).
            self._log("entry_no_fill", ack=ack)
            return TransmitResult(False, "entry acknowledged but no fill price",
                                  entry=entry_intent, token_id=token_id,
                                  telemetry=list(self.telemetry))
        self._log("entry_filled", fill_price=fill_price)

        # 6. Build + submit protective OCO (stop 5 below, target 5 above).
        oco_id = f"SMOKE-OCO-{entry_intent.get('intent_id')}"
        protective = build_protective_orders(fill_price, oco_id)
        self._log("protective_submit", oco_id=oco_id, protective=protective)
        oco_ack = {}
        try:
            oco_ack = self.wire.submit_oco(protective["stop"], protective["target"]) or {}
        except Exception as exc:  # noqa: BLE001
            oco_ack = {"ok": False, "reason": str(exc)}

        if not oco_ack.get("ok"):
            # 7. EMERGENCY FLATTEN — protection could not be established.
            self._log("protection_failed", oco_ack=oco_ack)
            flat = {}
            try:
                flat = self.wire.flatten(INSTRUMENT) or {}
            except Exception as exc:  # noqa: BLE001
                flat = {"ok": False, "reason": str(exc)}
            self._log("emergency_flatten", result=flat)
            return TransmitResult(False, "protection unestablished — emergency flatten invoked",
                                  entry=entry_intent, fill_price=fill_price,
                                  protective=protective, protection_established=False,
                                  emergency_flattened=bool(flat.get("ok")),
                                  token_id=token_id, telemetry=list(self.telemetry))

        self._log("protection_established", oco_ack=oco_ack)
        return TransmitResult(True, "smoke order transmitted with OCO protection",
                              entry=entry_intent, fill_price=fill_price,
                              protective=protective, protection_established=True,
                              token_id=token_id, telemetry=list(self.telemetry))

    def reconcile(self) -> dict:
        pos = {}
        orders = {}
        try:
            pos = self.wire.position(INSTRUMENT) or {}
            orders = self.wire.order_summary() or {}
        except Exception as exc:  # noqa: BLE001
            return {"reconciled": False, "reason": str(exc)}
        return {"reconciled": True, "position": pos, "orders": orders}

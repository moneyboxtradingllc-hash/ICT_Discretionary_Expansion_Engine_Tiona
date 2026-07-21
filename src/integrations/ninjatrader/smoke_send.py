"""MNQ-DEMO8458533-SMOKE-ORDER — the authorized SEND executor.

Runs ONLY after Maurice's explicit "SEND THE ONE-CONTRACT SMOKE ORDER NOW" and
after the ARMED bridge (ArmOrders=true) has been recompiled + loaded.

Sequence (fail-closed at every step; the token is burned ONLY once the armed
bridge is confirmed and the entry is about to be sent):

  1. Connect bridge.
  2. Live 12-point preflight must be GO.
  3. Bridge must report arm_orders == true (armed build loaded).
  4. Consume (burn) the one-use token.
  5. Submit LONG 1 MNQ SEP26 MARKET; receive ORDER_ACK.
  6. Poll position (qty==1, avg fill) + working orders (==2 protective).
  7. Success = filled + 2 OCO orders. Else EMERGENCY FLATTEN.
  8. Reconcile, write transmit artifact, re-disarm intent.

TRANSMIT_LATCH is passed True here explicitly — this is the only place it is.
"""
from __future__ import annotations

import json
import os
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient   # noqa: E402
from integrations.ninjatrader import smoke_authorization as auth             # noqa: E402
from integrations.ninjatrader import smoke_order_path as OP                  # noqa: E402
from integrations.ninjatrader.smoke_preflight_run import gather_and_run      # noqa: E402

ACCOUNT = "DEMO8458533"
INSTRUMENT = "MNQ SEP26"
ARTIFACT = os.path.join("data", "integration", "ninjatrader", "smoke_send_result.json")


def _finish(out: dict) -> dict:
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))
    return out


def send() -> dict:
    telemetry = []

    def log(ev, **kw):
        telemetry.append({"at": time.time(), "event": ev, **kw})

    # 1-2. Preflight must be GO (this also confirms token present + unused).
    pf = gather_and_run()
    if not pf.get("connected"):
        return _finish({"transmitted": False, "reason": "bridge not connected", "telemetry": telemetry})
    if not pf.get("preflight", {}).get("go"):
        fails = [c for c in pf["preflight"]["checks"] if not c["pass"]]
        return _finish({"transmitted": False, "reason": "preflight NOT GO",
                        "failures": fails, "telemetry": telemetry})
    log("preflight_go")

    c = NinjaTraderBridgeClient(port=36901, timeout=6.0, account=ACCOUNT, instrument=INSTRUMENT)
    if not c.connect():
        return _finish({"transmitted": False, "reason": "bridge connect failed", "telemetry": telemetry})
    try:
        # 3. Armed-bridge check BEFORE burning the token.
        env = c.environment_proof()
        if env.get("arm_orders") is not True:
            return _finish({"transmitted": False,
                            "reason": "bridge is NOT armed (arm_orders != true) — recompile the "
                                      "ARMED MNQBridge and restart NT before sending",
                            "arm_orders": env.get("arm_orders"), "telemetry": telemetry})
        log("bridge_armed_confirmed")

        # 4. Consume (burn) the token — bound to the exact trade.
        intent = OP.build_entry_intent("MAURICE-SEND", "SMOKE-INTENT-1", "SMOKE-THESIS-1",
                                       "SMOKE-COID-1")
        consumed = auth.consume_token(ACCOUNT, INSTRUMENT, 1, intent_id="SMOKE-INTENT-1",
                                      direction="long", entry_type="market")
        if not consumed:
            return _finish({"transmitted": False, "reason": f"authorization: {consumed.reason}",
                            "telemetry": telemetry})
        token_id = consumed.token.token_id
        log("token_burned", token_id=token_id)

        # 5. Submit the market entry (LONG 1 MNQ SEP26).
        log("entry_submit", intent=intent)
        ack = c.submit_market_entry(intent)
        log("entry_ack", ack=ack)
        if not ack.get("accepted"):
            # Entry refused — attempt a safety flatten in case anything partial landed.
            flat = c.flatten(INSTRUMENT)
            return _finish({"transmitted": False, "reason": f"entry refused: {ack.get('reason')}",
                            "token_id": token_id, "safety_flatten": flat, "telemetry": telemetry})

        # 6. Poll for fill + protective OCO (stop + target = 2 working orders).
        fill_price = None
        working = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            pos = c.position(INSTRUMENT)
            orders = c.order_summary()
            working = orders.get("working_order_count")
            if pos.get("known") and int(pos.get("qty", 0)) == 1:
                fill_price = pos.get("avg_price")
                if working == 2:
                    log("filled_and_protected", fill=fill_price, working=working)
                    break
            time.sleep(0.5)

        pos = c.position(INSTRUMENT)
        orders = c.order_summary()
        filled = pos.get("known") and int(pos.get("qty", 0)) == 1
        protected = orders.get("working_order_count") == 2

        # 7. Verdict + emergency flatten if unprotected.
        if filled and protected:
            result = {"transmitted": True, "reason": "smoke order filled with OCO protection",
                      "token_id": token_id, "fill_price": pos.get("avg_price"),
                      "position": pos, "orders": orders, "telemetry": telemetry}
            return _finish(result)

        # Anything else -> EMERGENCY FLATTEN.
        log("protection_or_fill_incomplete", filled=filled, protected=protected,
            pos=pos, orders=orders)
        flat = c.flatten(INSTRUMENT)
        log("emergency_flatten", result=flat)
        # confirm flat
        time.sleep(0.5)
        pos2 = c.position(INSTRUMENT)
        return _finish({"transmitted": False,
                        "reason": "fill/protection incomplete — EMERGENCY FLATTEN invoked",
                        "token_id": token_id, "filled": filled, "protected": protected,
                        "flatten": flat, "post_flatten_position": pos2, "telemetry": telemetry})
    finally:
        c.close()


if __name__ == "__main__":
    send()

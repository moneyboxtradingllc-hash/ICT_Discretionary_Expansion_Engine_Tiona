"""Foundation entrypoint for the read-only and shadow launchers.

Prints the mandatory unambiguous banner, runs the preflight audit, assembles the
integration health report, and (in the read-only foundation) proves the order
path is DISARMED. It NEVER submits an order and NEVER calls OpenAI.

Modes:
  readonly  — preflight + banner + health report + submission-denial proof.
  shadow    — same, plus a note that organism decisions would run with execution
              disabled once a live MNQ bridge is available (USER ACTION REQUIRED
              until NT8 is launched and the bridge is compiled).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as a script: ensure src on path.
_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from integrations.ninjatrader import preflight as PF                     # noqa: E402
from integrations.ninjatrader.health_report import (                     # noqa: E402
    IntegrationHealth, launcher_banner)
from integrations.ninjatrader.execution_adapter import NinjaTraderBrokerAdapter  # noqa: E402

_RESOLUTION_PATH = os.path.join("data", "integration", "ninjatrader",
                                "mnq_contract_resolution.json")
_HEALTH_PATH = os.path.join("data", "integration", "ninjatrader",
                            "integration_health.json")


def _active_expiry() -> str:
    try:
        with open(_RESOLUTION_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        spec = data.get("spec") or {}
        return spec.get("ninjatrader_name") or "<unresolved>"
    except Exception:  # noqa: BLE001
        return "<unresolved>"


def _submission_denial_proof(expiry: str) -> dict:
    """Prove an order request is rejected because submission is DISARMED and no
    smoke-order authorization exists. NO ORDER IS SUBMITTED."""
    adapter = NinjaTraderBrokerAdapter(resolved_expiry_name=expiry)
    intent = dict(authorization_id="preflight", intent_id="preflight",
                  thesis_id="preflight", instrument=expiry, account="Sim101",
                  direction="long", quantity=1, client_order_id="preflight-proof",
                  timestamp=0.0, current_position_state="flat",
                  risk_authorization="preflight", stop_definition={"stop_price": 0.0})
    res = adapter.submit_order(intent, position_state_known=True,
                               account_state_known=True, connection_healthy=True)
    return {"submitted": res["submitted"], "armed": res["armed"],
            "denied_reason": res["denied_reason"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("readonly", "shadow"), default="readonly")
    args = ap.parse_args(argv)

    expiry = _active_expiry()
    print(launcher_banner(expiry))
    print(f"MODE: {args.mode.upper()}")

    report = PF.run_preflight()
    installed = report["checks"]["ninjatrader_installed"]["status"] == "verified"
    dll = report["checks"]["ninjatrader_client_dll"]["status"] == "verified"
    initialized = report["checks"]["ninjatrader_user_data_initialized"]["status"] == "verified"

    health = IntegrationHealth(
        ninjatrader_installed=installed,
        ninjatrader_running=None,
        interface_selected="ninjascript_bridge",
        interface_connected=False,               # no bridge compiled/connected yet
        sim101_visible=None,
        global_sim_mode_user_confirmed=None,
        active_mnq_expiry=expiry,
        tick_size=0.25, point_value=2.0, tick_value=0.5,
        reconciliation_state="unreconciled (read-only foundation)",
        last_error="",
    )

    denial = _submission_denial_proof(expiry)
    assert denial["submitted"] is False, "INVARIANT VIOLATED: order reported submitted"

    out = {
        "banner_account": "Sim101",
        "mode": args.mode,
        "active_mnq_expiry": expiry,
        "ninjatrader_installed": installed,
        "ninjatrader_client_dll_present": dll,
        "ninjatrader_user_data_initialized": initialized,
        "order_submission_denial_proof": denial,
        "health": health.to_dict(),
    }
    if args.mode == "shadow":
        out["shadow_note"] = ("Shadow organism decisions run with execution "
                              "DISABLED once a live MNQ bridge is available. "
                              "USER ACTION REQUIRED: launch NT8, compile the "
                              "MNQBridge AddOn, and connect a data feed.")

    os.makedirs(os.path.dirname(_HEALTH_PATH), exist_ok=True)
    with open(_HEALTH_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print(f"\nActive MNQ expiry (calendar, PENDING platform confirm): {expiry}")
    print(f"NinjaTrader installed: {installed} | user-data initialized: {initialized}")
    print(f"Order-submission denial proof: submitted={denial['submitted']} "
          f"reason={denial['denied_reason']!r}")
    print(f"Health report written: {_HEALTH_PATH}")
    print("\nNO AUTOMATED ORDER WAS SUBMITTED.")
    return out


if __name__ == "__main__":
    main()

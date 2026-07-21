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
from integrations.ninjatrader.account_safety import ALLOWED_ACCOUNTS      # noqa: E402
from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient  # noqa: E402


def _read_global_sim_mode() -> dict:
    """Read Global Simulation Mode directly from NinjaTrader's Config.xml (a
    permitted configuration-file read). Returns {value, source} or unknown."""
    cfg = os.path.join(PF.DOC_DIR, "Config.xml")
    try:
        with open(cfg, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return {"value": None, "source": "Config.xml not readable"}
    import re
    m = re.search(r"<IsGlobalSimulationMode>\s*(true|false)\s*</IsGlobalSimulationMode>",
                  text, re.IGNORECASE)
    if not m:
        return {"value": None, "source": "flag not found in Config.xml"}
    return {"value": m.group(1).lower() == "true", "source": cfg,
            "note": "persisted config value; the running session is authoritative"}


def _probe_bridge(expiry: str) -> dict:
    """Attempt the live read-only path through the loopback bridge.

    Fail-closed: if the AddOn is not compiled/running inside NinjaTrader, the
    loopback connect fails and every account/position/metadata fact stays
    'unknown'. NO order is ever sent (read-only messages only)."""
    account = sorted(ALLOWED_ACCOUNTS)[0]
    c = NinjaTraderBridgeClient(host="127.0.0.1", port=36901, timeout=1.5,
                                account=account, instrument=expiry)
    if not c.connect():
        return {"connected": False,
                "reason": "bridge not listening on 127.0.0.1:36901 — AddOn not "
                          "compiled/running inside NinjaTrader",
                "connection_state": {"known": False},
                "account_state": {"known": False},
                "instrument_metadata": {"known": False},
                "position": {"known": False}}
    try:
        return {"connected": True,
                "connection_state": c.connection_state(),
                "account_state": c.account_state(),
                "instrument_metadata": c.instrument_metadata(expiry),
                "position": c.position(expiry),
                "working_orders": c.working_orders()}
    finally:
        c.close()

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
                  thesis_id="preflight", instrument=expiry, account="DEMO8458533",
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

    ninjatrader_running = report["checks"]["ninjatrader_running"]["status"] == "verified"
    gsm = _read_global_sim_mode()
    bridge = _probe_bridge(expiry)
    acct = bridge.get("account_state", {}) or {}
    pos = bridge.get("position", {}) or {}

    health = IntegrationHealth(
        ninjatrader_installed=installed,
        ninjatrader_running=ninjatrader_running,
        interface_selected="ninjascript_bridge",
        interface_connected=bridge["connected"],
        sim_account_visible=(acct.get("account") == "DEMO8458533") if acct.get("known") else None,
        global_sim_mode_user_confirmed=gsm.get("value"),
        active_mnq_expiry=expiry,
        tick_size=0.25, point_value=2.0, tick_value=0.5,
        position_state=("flat" if pos.get("known") and int(pos.get("qty", 0)) == 0
                        else ("known" if pos.get("known") else "unknown")),
        working_order_count=(len(bridge["working_orders"]) if bridge.get("connected") else None),
        reconciliation_state=("clean" if bridge["connected"] and pos.get("known")
                              else "unreconciled (bridge not connected)"),
        last_error="" if bridge["connected"] else bridge.get("reason", ""),
    )

    denial = _submission_denial_proof(expiry)
    assert denial["submitted"] is False, "INVARIANT VIOLATED: order reported submitted"

    out = {
        "banner_account": "DEMO8458533",
        "mode": args.mode,
        "active_mnq_expiry": expiry,
        "ninjatrader_installed": installed,
        "ninjatrader_running": ninjatrader_running,
        "ninjatrader_client_dll_present": dll,
        "ninjatrader_user_data_initialized": initialized,
        "global_simulation_mode": gsm,
        "bridge_probe": bridge,
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
    print(f"NinjaTrader installed: {installed} | running: {ninjatrader_running} "
          f"| user-data initialized: {initialized}")
    print(f"Global Simulation Mode (Config.xml): {gsm.get('value')}")
    print(f"Bridge connected: {bridge['connected']}" +
          ("" if bridge["connected"] else f"  ({bridge.get('reason','')})"))
    if bridge["connected"]:
        print(f"  account_state: {acct}")
        print(f"  position: {pos}")
        print(f"  instrument_metadata: {bridge.get('instrument_metadata')}")
    print(f"Order-submission denial proof: submitted={denial['submitted']} "
          f"reason={denial['denied_reason']!r}")
    print(f"Health report written: {_HEALTH_PATH}")
    print("\nNO AUTOMATED ORDER WAS SUBMITTED.")
    return out


if __name__ == "__main__":
    main()

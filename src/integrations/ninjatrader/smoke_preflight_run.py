"""Live 12-point GO/NO-GO runner for MNQ-DEMO8458533-SMOKE-ORDER.

Connects the loopback bridge, gathers every read-only fact, reads the ATI
default account from Config.xml, runs the 12-point fail-closed preflight, prints
the result, and writes an artifact. It NEVER submits an order.

Run:  python -m integrations.ninjatrader.smoke_preflight_run
"""
from __future__ import annotations

import json
import os
import re
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from integrations.ninjatrader import preflight as PF                       # noqa: E402
from integrations.ninjatrader import smoke_preflight as PRE                # noqa: E402
from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient  # noqa: E402
from integrations.ninjatrader.instrument_spec import InstrumentSpec        # noqa: E402

from integrations.ninjatrader.deterministic import (
    ACCOUNT as _CFG_ACCOUNT, INSTRUMENT as _CFG_INSTRUMENT)

INSTRUMENT = _CFG_INSTRUMENT   # per-operator config, see .env.template
ARTIFACT = os.path.join("data", "integration", "ninjatrader", "smoke_preflight.json")


def read_ati_config() -> dict:
    """Read ATI enabled + default account + server port from NinjaTrader Config.xml."""
    cfg = os.path.join(PF.DOC_DIR, "Config.xml")
    try:
        with open(cfg, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return {"enabled": None, "default_account": None, "server_port": None}

    def _grab(tag):
        m = re.search(rf"<{tag}>([^<]*)</{tag}>", text)
        return m.group(1).strip() if m else None

    return {"enabled": (_grab("IsAtiEnabled") or "").lower() == "true",
            "default_account": _grab("DefaultAccount"),
            "server_port": _grab("ServerPort")}


def gather_and_run() -> dict:
    ati = read_ati_config()
    c = NinjaTraderBridgeClient(port=36901, timeout=6.0, account="DEMO8458533",
                               instrument=INSTRUMENT)
    connected = c.connect()
    if not connected:
        return {"connected": False,
                "reason": "bridge not listening on 127.0.0.1:36901 — recompile MNQBridge in NT",
                "ati_config": ati}
    try:
        env = c.environment_proof()
        acct = c.account_state()
        meta = c.instrument_metadata(INSTRUMENT)
        pos = c.position(INSTRUMENT)
        orders = c.order_summary()
        quote = c.quote(INSTRUMENT)
        spec = InstrumentSpec(provider_symbol=INSTRUMENT, ninjatrader_name=INSTRUMENT,
                              expiry="2026-09")
        reconcile = spec.reconcile_with_platform(meta)
        result = PRE.run(bridge_env=env, account_state=acct, position=pos,
                         order_summary=orders, instrument_metadata=meta,
                         metadata_reconcile=reconcile, quote=quote,
                         ati_default_account=ati.get("default_account"),
                         intended_quantity=1)
        return {"connected": True, "ati_config": ati,
                "environment_proof_payload": env,
                "reads": {"account_state": acct, "position": pos,
                          "order_summary": orders, "instrument_metadata": meta,
                          "metadata_verified": reconcile.get("metadata_verified"),
                          "quote": quote},
                "preflight": result.to_dict()}
    finally:
        c.close()


def main():
    out = gather_and_run()
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print("=" * 68)
    print("MNQ-DEMO8458533-SMOKE-ORDER — 12-POINT PREFLIGHT (read-only)")
    print("=" * 68)
    if not out.get("connected"):
        print(f"BRIDGE: NOT CONNECTED — {out.get('reason')}")
        print("Overall: NO-GO")
        print("\nNO AUTOMATED ORDER WAS SUBMITTED.")
        return out
    pf = out["preflight"]
    for c in pf["checks"]:
        print(f"  [{'PASS' if c['pass'] else 'NO-GO'}] {c['n']:>2}. {c['name']} — {c['detail']}")
    print("-" * 68)
    print(f"OVERALL: {'GO' if pf['go'] else 'NO-GO'}")
    print(f"Artifact: {ARTIFACT}")
    print("\nNO AUTOMATED ORDER WAS SUBMITTED.")
    return out


if __name__ == "__main__":
    main()

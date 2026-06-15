"""TOPSTEP-1 Phase 5 — Topstep connection test (READ-ONLY, no trades).

  python tools/test_topstep_connection.py --instance tiona_topstep

Confirms: API key present (masked), credentials masked, account found, account
type practice, balance visible, no open positions, no open orders, broker health
OK. Places NO orders and cancels nothing. Safe to run repeatedly. If credentials
are not configured yet, prints friendly next steps instead of failing.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from deployment.instance_context import InstanceContext   # noqa: E402
from broker.topstep_adapter import TopstepBrokerAdapter, TopstepConfig  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Topstep connection test (read-only).")
    p.add_argument("--instance", default="tiona_topstep")
    p.add_argument("--instances-root", default=os.path.join("data", "instances"))
    args = p.parse_args(argv)

    cfg_path = os.path.join(args.instances_root, args.instance, "config.yaml")
    ctx = None
    if os.path.exists(cfg_path):
        ctx = InstanceContext.from_config_file(cfg_path)
        ctx.activate()
        print(f"instance        : {ctx.instance_id} (broker={ctx.config.broker})")
    else:
        print(f"instance        : {args.instance} (no config found — using env only)")

    tcfg = TopstepConfig.from_env()
    print(f"TOPSTEP_ENV     : {tcfg.env}")
    print(f"username        : {tcfg.username or '(not set)'}")
    print(f"api_key         : {tcfg.masked_key()}")
    print(f"account_id (cfg): {tcfg.account_id or '(not set — will use first active)'}")
    print(f"base_url        : {tcfg.base_url}")

    if not tcfg.credentials_present():
        print("\n⚠️  Credentials not configured yet.")
        print("    Open .env and fill TOPSTEP_USERNAME and TOPSTEP_API_KEY")
        print("    (see docs/tiona_topstep_setup_guide.md). Then re-run this test.")
        return 2

    adapter = TopstepBrokerAdapter(ctx.config if ctx else None)
    print("\nauthenticating … (read-only)")
    auth = adapter.authenticate()
    if not auth.get("ok"):
        print(f"❌ authentication FAILED: {auth.get('error')}")
        print("   • check username/API key are correct")
        print("   • confirm your ProjectX API subscription is active")
        return 1
    print("✅ authenticated")

    health = adapter.health_check()
    acct = adapter.get_account()
    print("\n=== ACCOUNT (read-only) ===")
    print(f"  account_id    : {acct.get('account_id')}")
    print(f"  name          : {acct.get('name')}")
    print(f"  balance       : {acct.get('balance')}")
    print(f"  can_trade     : {acct.get('can_trade')}")
    print(f"  simulated     : {acct.get('simulated')}  (practice/sim)")
    print(f"  open positions: {health.get('open_positions')}")
    print(f"  open orders   : {health.get('open_orders')}")
    print(f"  health        : {'OK' if health.get('healthy') else 'NOT OK'}")

    cap = adapter.capability()
    print("\n=== SAFETY ===")
    print(f"  order placement allowed now: {cap.supports_orders} "
          f"(practice={adapter._is_practice()} + TOPSTEP_EXECUTION_ENABLED={adapter._execution_enabled()})")
    print("  this test placed NO orders and cancelled nothing.")
    ok = health.get("healthy") and adapter._is_practice()
    print(f"\n{'✅ CONNECTION TEST PASSED' if ok else '⚠️  review the items above'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

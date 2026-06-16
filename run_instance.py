"""DEPLOY-1 Phase 9 — Instance launch command.

  python run_instance.py --instance maurice_topstep

Loads ONLY that instance's config + state, activates its InstanceContext (so all
memory/journal/vector/logs/state writes are redirected into the instance
folder), selects its broker adapter, and reports the isolation map + readiness.

SAFETY (DEPLOY-1 scope): this launcher activates and validates an instance and
prints its launch plan. It does NOT connect live money or start a client-facing
trading loop — Topstep/TradeStation adapters are stubs. The paper scan loop is
invoked only with --start and only when the broker resolves to a connected
paper adapter.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from deployment.instance_context import InstanceContext        # noqa: E402
from broker.factory import get_adapter                         # noqa: E402


def resolve_start_params(ctx):
    """(symbol, data_provider) for the scan loop, derived from the instance config.
    DEPLOY-2A: topstep instances resolve to (MNQU-style symbol, 'topstep')."""
    return ctx.config.symbol, ctx.config.resolved_data_provider()


def main(argv=None):
    p = argparse.ArgumentParser(description="Launch a bot instance (isolated).")
    p.add_argument("--instance", required=True)
    p.add_argument("--instances-root", default=os.path.join("data", "instances"))
    p.add_argument("--start", action="store_true",
                   help="start the paper scan loop (paper adapter only)")
    p.add_argument("--dry-run", action="store_true",
                   help="validate isolation/freshness/broker without starting anything")
    args = p.parse_args(argv)

    cfg_path = os.path.join(args.instances_root, args.instance, "config.yaml")
    if not os.path.exists(cfg_path):
        p.error(f"no such instance config: {cfg_path}")

    ctx = InstanceContext.from_config_file(cfg_path)
    problems = ctx.config.validate()
    if problems:
        p.error("invalid config: " + "; ".join(problems))

    ctx.activate()   # redirect ALL state into this instance's folders
    adapter = get_adapter(ctx.config)

    print(f"> instance '{ctx.instance_id}'  owner={ctx.config.owner_name!r}  "
          f"broker={ctx.config.broker}  symbol={ctx.config.symbol}")
    print(f"  account_id={ctx.config.account_id!r}  execution_mode={ctx.config.execution_mode}")
    print(f"  risk: daily_loss={ctx.config.risk_profile.max_daily_loss} "
          f"max_trades={ctx.config.risk_profile.max_trades_per_day}")
    print("  isolated state (env-redirected):")
    for var, val in ctx.env_map().items():
        print(f"    {var:<22} {val}")
    print(f"  broker adapter: {adapter.describe()}")

    if args.dry_run:
        print("\n=== DRY-RUN VALIDATION ===")
        def _count(pth):
            return sum(len(f) for _, _, f in os.walk(pth)) if os.path.isdir(pth) else 0
        mem = _count(ctx.paths["brain"]) + _count(ctx.paths["intent_archive"])
        vec = _count(ctx.paths["vector_store"])
        jrn = _count(ctx.paths["journal"])
        print(f"  instance loads          : yes ({ctx.instance_id})")
        print(f"  memory empty            : {mem == 0} ({mem} files)")
        print(f"  vector store empty      : {vec == 0} ({vec} files)")
        print(f"  journal empty           : {jrn == 0} ({jrn} files)")
        print(f"  broker                  : {ctx.config.broker}")
        print(f"  account id              : {ctx.config.account_id!r}")
        print(f"  execution disabled      : "
              f"{os.getenv('EXECUTION_ENABLED', 'false').lower() != 'true'} "
              f"(EXECUTION_ENABLED={os.getenv('EXECUTION_ENABLED', 'false')})")
        # Maurice untouched: his legacy data paths are never under this instance dir
        maurice_legacy = os.path.join("data", "paper_trades")
        untouched = os.path.normpath(ctx.paths["journal"]) != os.path.normpath(maurice_legacy)
        print(f"  Maurice Alpaca untouched: {untouched} "
              f"(this journal != {maurice_legacy})")
        print("\n  (dry-run only — nothing started, no broker writes)")
        return 0

    if args.start:
        symbol, data_provider = resolve_start_params(ctx)
        if adapter.name == "paper" and adapter.is_connected():
            print(f"\n[paper] starting scan loop (data_provider={data_provider}, "
                  f"symbol={symbol})…")
            from live_scan.scan_loop import run_scan_loop  # deferred import
            run_scan_loop(symbol=symbol, data_provider=data_provider)
        elif adapter.name == "topstep":
            # DEPLOY-2A/2B — Topstep DATA path: scan loop runs against the Topstep
            # (ProjectX) market-data feed for the configured instrument (e.g. MNQU).
            # No Alpaca, no QQQ. If the Topstep feed is unavailable the provider
            # raises a clear Topstep error (no fallback). NOTE: Topstep *execution*
            # remains a stub/observe path (DEPLOY-2C); no live orders are placed.
            print(f"\n[topstep] starting scan loop (data_provider={data_provider}, "
                  f"symbol={symbol}) — execution stub/observe, no live orders…")
            from live_scan.scan_loop import run_scan_loop  # deferred import
            run_scan_loop(symbol=symbol, data_provider=data_provider)
        else:
            print(f"\n[guard] --start refused: broker '{adapter.name}' has no "
                  f"supported runtime start path.")
            return 2
    else:
        print("\n(dry plan — re-run with --start to begin the paper scan loop)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""DEPLOY-1 Phase 8 — Clone command.

Create a new, fully-isolated bot instance from a template:

  python tools/create_instance.py --template tradestation --instance maurice_tradestation \
      --owner "Maurice" --account-id TS-001

Creates data/instances/<instance>/ with config.yaml + isolated memory/,
vector_store/, journal/, logs/, state/, news_memory/ folders. Shared code is
NOT copied — every instance runs the one core in src/. Never connects a broker.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from deployment.instance_config import InstanceConfig          # noqa: E402
from deployment.instance_context import InstanceContext        # noqa: E402

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "instances", "templates")
INSTANCES_ROOT = os.path.join("data", "instances")


def main(argv=None):
    p = argparse.ArgumentParser(description="Create an isolated bot instance.")
    p.add_argument("--template", required=True, help="template name in instances/templates/")
    p.add_argument("--instance", required=True, help="unique instance_id")
    p.add_argument("--owner", default="")
    p.add_argument("--account-id", default="")
    p.add_argument("--symbol", default=None)
    p.add_argument("--broker", default=None)
    p.add_argument("--instances-root", default=INSTANCES_ROOT)
    args = p.parse_args(argv)

    tpl_path = os.path.join(TEMPLATES_DIR, f"{args.template}.yaml")
    if not os.path.exists(tpl_path):
        avail = [f[:-5] for f in os.listdir(TEMPLATES_DIR) if f.endswith(".yaml")]
        p.error(f"unknown template '{args.template}'. available: {avail}")

    cfg = InstanceConfig.load(tpl_path)
    cfg.instance_id = args.instance
    cfg.owner_name = args.owner or cfg.owner_name
    cfg.account_id = args.account_id or cfg.account_id
    if args.symbol:
        cfg.symbol = args.symbol
    if args.broker:
        cfg.broker = args.broker
    # clear auto-derived (empty-id) paths so they re-derive from the real
    # instance_id; templates intentionally do not hardcode instance paths.
    for f in ("memory_path", "vector_store_path", "journal_path",
              "log_path", "state_path", "news_memory_path"):
        setattr(cfg, f, "")
    cfg.__post_init__()   # re-derive isolated paths from the new instance_id

    problems = cfg.validate()
    if problems:
        p.error("invalid config: " + "; ".join(problems))

    inst_dir = os.path.join(args.instances_root, args.instance)
    if os.path.exists(os.path.join(inst_dir, "config.yaml")):
        p.error(f"instance already exists: {inst_dir} (refusing to overwrite)")

    os.makedirs(inst_dir, exist_ok=True)
    cfg.save(os.path.join(inst_dir, "config.yaml"))

    # create the isolated state folders
    ctx = InstanceContext(cfg)
    ctx.ensure_dirs()

    print(f"[OK] created instance '{args.instance}' (broker={cfg.broker}, "
          f"symbol={cfg.symbol})")
    print(f"   config:        {os.path.join(inst_dir, 'config.yaml')}")
    for name, path in ctx.paths.items():
        print(f"   {name:<18} {path}")
    print(f"\nLaunch with:  python run_instance.py --instance {args.instance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

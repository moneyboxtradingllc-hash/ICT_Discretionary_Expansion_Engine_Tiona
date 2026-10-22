#!/bin/zsh
# Rebind the .env to the account that exists AFTER a Topstep Combine reset
# (docs/topstep_combine_reset_runbook.md steps 2-4). Run it only with the owner's authorization.
#
#   zsh stage5_account_rebind.zsh /path/to/your/.env          # list, and rebind if exactly one account is tradeable
#   zsh stage5_account_rebind.zsh /path/to/your/.env 2        # rebind to row 2 of the list
#
# It reuses the frozen checkout and venv that stage5_startup_proof.zsh already built (~/stage5_startup_proof_*).
# Broker contact: one login and one account-list read (/api/Account/search). No contract, no positions/orders,
# no market hub and no order path. It never prints an account id, full name or fingerprint.
# It writes only your .env: a backup first (.env.before_rebind_<stamp>, readable only by you), then
# TOPSTEPX_ACCOUNT_ID, TOPSTEPX_ACCOUNT_FINGERPRINT and, if present, TOPSTEPX_ACCOUNT_NAME.
set -u
SRC=ffe00aef3db7fb2339780ed0fa9016149923c96e
ENVSRC=${1:-}
PICK=${2:-}
stop() { echo "STOPPED: $1"; exit 1; }

[[ -n $ENVSRC && -f $ENVSRC ]] || stop "give the path to your .env, e.g. zsh stage5_account_rebind.zsh ~/Trading/ICT_Discretionary_Expansion_Engine_Tiona/.env"
W=$(ls -d $HOME/stage5_startup_proof_*(N/) 2>/dev/null | tail -1)
[[ -n $W && -x $W/venv/bin/python && -d $W/repo ]] || stop "no ~/stage5_startup_proof_* folder with repo and venv found"
[[ $(git -C $W/repo rev-parse HEAD) == $SRC && -z $(git -C $W/repo status --porcelain) ]] || stop "$W/repo is not a clean checkout of $SRC"
for k in TOPSTEPX_USERNAME TOPSTEPX_API_KEY; do grep -qE "^${k}=.+" $ENVSRC || stop "$k is missing or empty in your .env"; done
echo "Using the frozen checkout in $W/repo (source $SRC)."
echo "Type GO and press Enter to log in and read the account list. Anything else stops without connecting."
read -r ANSWER
[[ $ANSWER == GO ]] || stop "operator did not type GO"

cd $W/repo
PYTHONPATH=src $W/venv/bin/python -I - "$ENVSRC" "$PICK" <<'PYEOF'
import os, re, shutil, stat, sys, time
sys.path.insert(0, "src")
envp, pick = sys.argv[1], sys.argv[2]
lines = open(envp, encoding="utf-8").read().splitlines()
vals = {}
for l in lines:
    if "=" in l and not l.lstrip().startswith("#"):
        k, v = l.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
os.environ["TOPSTEPX_USERNAME"] = vals["TOPSTEPX_USERNAME"]
os.environ["TOPSTEPX_API_KEY"] = vals["TOPSTEPX_API_KEY"]

from broker.topstepx_live_session import TopstepXLiveSession
from broker.topstepx_redaction import account_fingerprint

session = TopstepXLiveSession()
session.authenticate()
accts = session._client.accounts(only_active=True)          # noqa: SLF001 -- the one read
old_id = vals.get("TOPSTEPX_ACCOUNT_ID", "")

def kind(name):
    letters = re.sub(r"[^A-Za-z]", "", name)
    return (letters[:12] or "?") + "..."

print(f"\n{len(accts)} active account(s) visible to this key (names and ids are not shown):")
print(f"  {'row':>3}  {'kind':16} {'balance':>12}  canTrade  isVisible  simulated  currently-in-.env")
for i, a in enumerate(accts, 1):
    print(f"  {i:>3}  {kind(a.name):16} {a.balance:>12,.2f}  {str(a.can_trade):8}  {str(a.is_visible):9}  "
          f"{str(a.simulated):9}  {'yes' if str(a.id) == old_id else 'no'}")

ok = [i for i, a in enumerate(accts, 1) if a.can_trade and a.is_visible]
if pick:
    if not pick.isdigit() or not 1 <= int(pick) <= len(accts):
        sys.exit(f"STOPPED: row {pick} does not exist")
    row = int(pick)
    if row not in ok:
        sys.exit(f"STOPPED: row {row} is not canTrade=True and isVisible=True; the pin would refuse it")
elif len(ok) == 1:
    row = ok[0]
else:
    sys.exit(f"STOPPED: {len(ok)} accounts are tradeable and visible. Nothing was changed. "
             "Pick the reset account (it shows the fresh starting balance) and re-run with its row number, "
             "e.g. zsh stage5_account_rebind.zsh <your .env> 2")

a = accts[row - 1]
fp = account_fingerprint(a.id, a.name)
stamp = time.strftime("%Y%m%dT%H%M%S")
bak = f"{envp}.before_rebind_{stamp}"
shutil.copy2(envp, bak)
os.chmod(bak, stat.S_IRUSR | stat.S_IWUSR)
new = {"TOPSTEPX_ACCOUNT_ID": str(a.id), "TOPSTEPX_ACCOUNT_FINGERPRINT": fp}
if "TOPSTEPX_ACCOUNT_NAME" in vals:
    new["TOPSTEPX_ACCOUNT_NAME"] = a.name
seen, out = set(), []
for l in lines:
    k = l.split("=", 1)[0].strip() if "=" in l and not l.lstrip().startswith("#") else None
    if k in new:
        out.append(f"{k}={new[k]}"); seen.add(k)
    else:
        out.append(l)
out += [f"{k}={v}" for k, v in new.items() if k not in seen]
open(envp, "w", encoding="utf-8").write("\n".join(out) + "\n")
os.chmod(envp, stat.S_IRUSR | stat.S_IWUSR)
print(f"\nREBOUND to row {row} ({kind(a.name)}, balance {a.balance:,.2f}, canTrade True, isVisible True).")
print(f"Updated in your .env: {', '.join(new)} (values not shown; new fingerprint starts {fp[:9]}...).")
print(f"Old .env kept at {bak.replace(os.path.expanduser('~'), '~')} (readable only by you). Nothing else was read or changed.")
PYEOF

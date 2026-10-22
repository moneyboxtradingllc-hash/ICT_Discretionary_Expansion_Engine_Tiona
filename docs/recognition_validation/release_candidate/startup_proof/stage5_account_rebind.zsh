#!/bin/zsh
# Rebind the .env to the owner-intended account after a Topstep Combine reset
# (docs/topstep_combine_reset_runbook.md steps 2-4). Run it only with the owner's explicit authorization.
#
#   zsh stage5_account_rebind.zsh /path/to/your/.env
#
# Identity: you type the intended account's full name exactly as the TopstepX dashboard shows it. The helper
# selects that exact name from ONE account-list result, never by row, list order, balance or "the only
# eligible one". It refuses unless exactly one active account has that name and it is canTrade and isVisible.
# You then type YES to write. TOPSTEPX_ACCOUNT_ID and TOPSTEPX_ACCOUNT_FINGERPRINT (and TOPSTEPX_ACCOUNT_NAME if
# present) are all derived from that same selected account object. Any refusal changes nothing.
# Broker contact is hard-capped at one login and one account-list request: SDK retries are off and a request
# guard refuses any further transmission, including a re-login after HTTP 401. No contract, positions, orders,
# market hub or order path. It never prints an id, account name, fingerprint or the other accounts.
# Reuses the frozen ffe00ae checkout and venv that stage5_startup_proof.zsh built (~/stage5_startup_proof_*).
set -u
SRC=ffe00aef3db7fb2339780ed0fa9016149923c96e
ENVSRC=${1:-}
stop() { echo "STOPPED (nothing changed): $1"; exit 1; }

[[ -n $ENVSRC && -f $ENVSRC ]] || stop "give the path to your .env, e.g. zsh stage5_account_rebind.zsh ~/Trading/ICT_Discretionary_Expansion_Engine_Tiona/.env"
W=$(ls -d $HOME/stage5_startup_proof_*(N/) 2>/dev/null | tail -1)
[[ -n $W && -x $W/venv/bin/python && -d $W/repo ]] || stop "no ~/stage5_startup_proof_* folder with repo and venv found"
[[ $(git -C $W/repo rev-parse HEAD) == $SRC && -z $(git -C $W/repo status --porcelain) ]] || stop "$W/repo is not a clean checkout of $SRC"
for k in TOPSTEPX_USERNAME TOPSTEPX_API_KEY; do grep -qE "^${k}=.+" $ENVSRC || stop "$k is missing or empty in your .env"; done
ENVABS=${ENVSRC:A}
echo "Using the frozen checkout in $W/repo (source $SRC)."
cd $W/repo
$W/venv/bin/python -I - "$ENVABS" "$W/repo/src" <<'PYEOF'
# --- REBIND BODY (the offline check executes exactly this block) ---
import os, re, shutil, stat, sys, time

LOGIN, SEARCH = "/api/Auth/loginKey", "/api/Account/search"


class Stop(Exception):
    """Refusal. Raised before any configuration change."""


class RequestBudgetExceeded(Exception):
    """Raised BEFORE transmission when a request would exceed the budget."""


def budget_transport(inner, budget=None):
    budget = dict(budget or {LOGIN: 1, SEARCH: 1})
    sent = []

    def transport(url, payload, headers, timeout):
        path = next((p for p in budget if url.endswith(p)), None)
        if path is None or sent.count(path) >= budget[path]:
            raise RequestBudgetExceeded(f"request refused before sending: {path or 'other endpoint'}")
        sent.append(path)
        return inner(url, payload, headers, timeout)

    transport.sent = sent
    return transport


def kind(name):
    return (re.sub(r"[^A-Za-z]", "", name)[:12] or "?") + "..."


def read_env(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    vals = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return lines, vals


def select_intended(accounts, intended_name):
    """The owner-intended account, by exact name, from ONE list result. Never by position."""
    wanted = (intended_name or "").strip()
    if not wanted:
        raise Stop("no intended account name was typed")
    matches = [a for a in accounts if a.name.strip() == wanted]
    if not matches:
        raise Stop("no active account visible to this key has exactly that name")
    if len(matches) > 1:
        raise Stop(f"{len(matches)} active accounts have that name; identity is ambiguous")
    acct = matches[0]
    if not (acct.can_trade and acct.is_visible):
        raise Stop("that account is not canTrade=True and isVisible=True; the pin would refuse it")
    return acct


def write_binding(envp, lines, vals, acct, fingerprint):
    new = {"TOPSTEPX_ACCOUNT_ID": str(acct.id), "TOPSTEPX_ACCOUNT_FINGERPRINT": fingerprint}
    if "TOPSTEPX_ACCOUNT_NAME" in vals:
        new["TOPSTEPX_ACCOUNT_NAME"] = acct.name
    bak = f"{envp}.before_rebind_{time.strftime('%Y%m%dT%H%M%S')}"
    shutil.copy2(envp, bak)
    os.chmod(bak, stat.S_IRUSR | stat.S_IWUSR)
    seen, out = set(), []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in new:
            out.append(f"{k}={new[k]}")
            seen.add(k)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in new.items() if k not in seen]
    open(envp, "w", encoding="utf-8").write("\n".join(out) + "\n")
    os.chmod(envp, stat.S_IRUSR | stat.S_IWUSR)
    return list(new), bak


def run(envp, *, transport, ask, say=print):
    """One login + one account-list read, owner-typed identity, explicit YES, then write. Returns 0 or 1."""
    from broker.topstepx_client import TopstepXClient
    from broker.topstepx_redaction import account_fingerprint
    lines, vals = read_env(envp)
    for k in ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY"):
        if not vals.get(k):
            say(f"STOPPED (nothing changed): {k} is missing or empty in your .env")
            return 1
    try:
        intended = ask("Type the intended account's full name exactly as the TopstepX dashboard shows it: ")
        if not intended.strip():
            raise Stop("no intended account name was typed")
        if ask("Type GO to log in and read the account list once (anything else stops without connecting): ").strip() != "GO":
            raise Stop("operator did not type GO")
        client = TopstepXClient(vals["TOPSTEPX_USERNAME"], vals["TOPSTEPX_API_KEY"],
                                transport=transport, max_retries=0)
        try:
            accounts = client.accounts(only_active=True)
        except Exception as exc:  # noqa: BLE001 -- any read failure is a stop with no change
            raise Stop(f"account-list read failed ({type(exc).__name__}); no retry is made") from None
        acct = select_intended(accounts, intended)
        say(f"Matched exactly one active account with that name: {kind(acct.name)}, balance {acct.balance:,.2f}, "
            f"canTrade True, isVisible True.")
        if ask("Is this the account Maurice confirmed? Type YES to write it into your .env: ").strip() != "YES":
            raise Stop("operator did not type YES")
        fp = account_fingerprint(acct.id, acct.name)
        names, bak = write_binding(envp, lines, vals, acct, fp)
    except Stop as exc:
        say(f"STOPPED (nothing changed): {exc}")
        return 1
    say(f"REBOUND. Updated in your .env: {', '.join(names)} (values not shown), all derived from the selected account.")
    say(f"Old .env kept at {bak.replace(os.path.expanduser('~'), '~')} (readable only by you). Nothing else was read or changed.")
    return 0


def tty_ask(prompt):
    with open("/dev/tty", "r+") as tty:
        tty.write(prompt)
        tty.flush()
        return tty.readline().rstrip("\n")


if __name__ == "__main__":
    sys.path.insert(0, sys.argv[2])
    from broker.topstepx_client import _default_transport
    sys.exit(run(sys.argv[1], transport=budget_transport(_default_transport), ask=tty_ask))
# --- END REBIND BODY ---
PYEOF

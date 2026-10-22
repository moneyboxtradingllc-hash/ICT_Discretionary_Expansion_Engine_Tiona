#!/bin/zsh
# ONE supervised startup/connectivity proof (Maurice's scoped authorization of 2026-10-22).
#
#   zsh stage5_startup_proof.zsh /path/to/your/existing/.env
#
# What it does, in order:
#   1. Clones the exact frozen source into a NEW disposable folder and verifies HEAD, tree and clean state.
#   2. Builds a fresh venv from the 47 pins and checks them.
#   3. Checks that your .env has the four required names. It checks names only and never prints values.
#      It then copies the .env into the disposable folder, readable only by you.
#   4. Shows the preflight and waits for you to type GO. Anything else stops before any connection.
#   5. Runs exactly once, disarmed, with no Brain/model:
#         tools/topstepx_production_session.py --proof --observe 60
#      There is no --arm, --scans or --until-close.
#   6. Deletes the copied .env, writes a SANITIZED summary to your Desktop and keeps the raw log private.
# There is no retry, extension or scan. The proof itself places, cancels, modifies and flattens nothing.
set -u
SRC=ffe00aef3db7fb2339780ed0fa9016149923c96e
TREE=57cc69c03882efc9bd1d6a7921f4fea6792a31cc
REPO=https://github.com/moneyboxtradingllc-hash/ICT_Discretionary_Expansion_Engine_Tiona.git
ENVSRC=${1:-}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
W=$HOME/stage5_startup_proof_$STAMP
P=$W/private          # raw log and copied .env: never send this folder
mkdir -p $P && chmod 700 $W $P
OUT=$HOME/Desktop/stage5_startup_proof_SANITIZED_$STAMP.txt
stop() { echo "STOPPED BEFORE CONNECTING: $1" | tee -a $P/preflight.txt; rm -f $W/repo/.env; exit 1; }

[[ -n $ENVSRC && -f $ENVSRC ]] || stop "give the path to your existing .env, e.g. zsh stage5_startup_proof.zsh ~/tiona_bot/.env"
echo "== preflight $STAMP (UTC) / local $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee $P/preflight.txt

# 1. exact source
git clone --quiet --no-checkout $REPO $W/repo && git -C $W/repo checkout --quiet --detach $SRC || stop "clone/checkout failed"
cd $W/repo
[[ $(git rev-parse HEAD) == $SRC ]] || stop "HEAD is not $SRC"
[[ $(git rev-parse 'HEAD^{tree}') == $TREE ]] || stop "tree is not $TREE"
[[ -z $(git status --porcelain) ]] || stop "checkout not clean"
echo "source: head $SRC tree $TREE clean: yes" | tee -a $P/preflight.txt

# 2. runtime and pins
PY=""
for c in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 python3; do
  if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then PY=$(command -v $c); break; fi
done
[[ -n $PY ]] || stop "Python 3.12 not found"
$PY -m venv $W/venv && V=$W/venv/bin
$V/python -m pip install --quiet --disable-pip-version-check -r requirements.txt > $P/pip.log 2>&1 || stop "pip install failed (see $P/pip.log)"
PINS=$($V/python - <<'PYEOF'
import re, importlib.metadata as m
ok = total = 0
for raw in open("requirements.txt", encoding="utf-16"):
    line = raw.split("#")[0].strip()
    if not line:
        continue
    name, want = re.match(r"([A-Za-z0-9_.\-\[\]]+)==(\S+)", line).groups()
    total += 1
    try:
        ok += m.version(re.sub(r"\[.*\]", "", name)) == want
    except Exception:
        pass
print(f"{ok}/{total}")
PYEOF
)
[[ $PINS == 47/47 ]] || stop "pins $PINS (need 47/47)"
echo "runtime: $($V/python -V 2>&1) $(sw_vers -productVersion 2>/dev/null) $(uname -m)  pins: $PINS" | tee -a $P/preflight.txt

# 3. credentials (names only) and no armed state
for k in TOPSTEPX_USERNAME TOPSTEPX_API_KEY TOPSTEPX_ACCOUNT_ID TOPSTEPX_ACCOUNT_FINGERPRINT; do
  grep -qE "^${k}=.+" $ENVSRC || stop "$k is missing or empty in your .env"
done
if grep -qiE '^(TOPSTEPX_ARM_ORDERS|EXECUTION_ENABLED|ALLOW_PAPER_ORDERS|AUTO_EXECUTION_ENABLED)=(1|true|yes)' $ENVSRC; then
  echo "note: your .env enables an arming/execution flag; it is overridden to false for this proof" | tee -a $P/preflight.txt
fi
[[ ! -e data ]] || stop "unexpected local state directory in the fresh checkout"
cp $ENVSRC $W/repo/.env && chmod 600 $W/repo/.env
echo "credentials: 4 required names present (values not shown); no prior session/authorization state in this checkout" | tee -a $P/preflight.txt

cat <<'TXT'

------------------------------------------------------------------------
READY FOR THE ONE AUTHORIZED STARTUP PROOF (disarmed, no Brain/model, no scans)
Stay at the Mac and watch the feed until it finishes (about 1-2 minutes).
It will: log in, verify the pinned account fingerprint and contract, read
positions/orders, attach quote + candle consumers, observe up to 60 s,
print telemetry, then disconnect.
Type GO and press Enter to connect. Anything else stops without connecting.
------------------------------------------------------------------------
TXT
read -r ANSWER
[[ $ANSWER == GO ]] || stop "operator did not type GO"

# 4-5. the single proof
unset PRODUCTION_ARMED_SESSION
export TOPSTEPX_ARM_ORDERS=false EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false
export AUTO_EXECUTION_ENABLED=false AI_BRAIN_ENABLED=false AI_BRAIN_LLM=false TWO_BRAIN_MODE=off
CMD="PYTHONPATH=src python3 tools/topstepx_production_session.py --proof --observe 60"
START_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ'); START_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z')
PATH=$V:$PATH PYTHONPATH=src python3 tools/topstepx_production_session.py --proof --observe 60 > $P/proof_raw.log 2>&1 &
PID=$!
( sleep 600; kill -INT $PID 2>/dev/null && echo "WATCHDOG: interrupted after 600 s" >> $P/proof_raw.log ) &
DOG=$!
wait $PID; RC=$?
kill $DOG 2>/dev/null
END_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ'); END_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z')

# 6. sanitize (values are read here only to redact them; nothing is printed)
$V/python - "$W/repo/.env" "$P/proof_raw.log" "$P/proof_sanitized.log" "$HOME" <<'PYEOF'
import re, sys
envp, raw, out, home = sys.argv[1:5]
secrets = []
for line in open(envp, encoding="utf-8", errors="replace"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v and len(v) >= 4 and any(t in k for t in ("USERNAME", "API_KEY", "ACCOUNT", "FINGERPRINT", "PASSWORD", "TOKEN", "SECRET")):
            secrets.append(v)
text = open(raw, encoding="utf-8", errors="replace").read()
for s in sorted(set(secrets), key=len, reverse=True):
    text = text.replace(s, "[REDACTED]")
text = text.replace(home, "~")
text = re.sub(r"(Bearer\s+)\S+", r"\1[REDACTED]", text)
text = re.sub(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "[REDACTED_JWT]", text)
open(out, "w").write(text)
PYEOF
rm -f $W/repo/.env

$V/python - "$P/proof_sanitized.log" "$RC" > $P/summary_body.txt <<'PYEOF'
import re, sys
log, rc = open(sys.argv[1]).read(), int(sys.argv[2])
def grab(label):
    m = re.search(r"^\s*" + re.escape(label) + r"\s*:\s*(.*)$", log, re.M)
    return m.group(1).strip() if m else None
keys = ["ARM STATE", "ARMED", "LANE", "NEW ENTRY PERMITTED", "QUOTE CONSUMER", "EXECUTABLE BID/ASK", "CANDLE CONSUMER",
        "CANDLE CONTRACT", "QUOTE CONTRACT", "RECONNECTS OBSERVED", "ACCOUNT STILL FLAT", "SHUTDOWN", "ACCOUNT"]
vals = {k: grab(k) for k in keys}
for k in keys:
    print(f"{k:22}: {vals[k]}")
refusals = [l.strip() for l in log.splitlines() if re.search(r"REFUSED|Traceback|Error|WATCHDOG|RECOVERY", l)]
m = re.search(r"\((\d+) -> (\d+) candles\)", vals["CANDLE CONSUMER"] or "")
advanced = bool(m and int(m.group(2)) > int(m.group(1)))
checks = {
    "exit code 0": rc == 0,
    "disarmed (ARM STATE DISARMED, ARMED False)": (vals["ARM STATE"] or "").startswith("DISARMED") and vals["ARMED"] == "False",
    "lane OPEN (not RECOVERY/refused)": (vals["LANE"] or "") == "OPEN",
    "quote consumer has a live quote": bool(vals["EXECUTABLE BID/ASK"]),
    "candles advanced during observation": advanced,
    "quote and candle on the same contract": bool(vals["CANDLE CONTRACT"]) and vals["CANDLE CONTRACT"] == vals["QUOTE CONTRACT"],
    "account flat and order-clean at end": vals["ACCOUNT STILL FLAT"] == "True",
    "'No order will be placed' printed": "No order will be placed" in log,
    "clean shutdown (pump joined, hub closed)": "pump joined" in (vals["SHUTDOWN"] or ""),
    "no refusal/traceback/watchdog lines": not refusals,
}
for k, v in checks.items():
    print(f"[{'x' if v else ' '}] {k}")
print("RESULT:", "PROOF COMPLETE" if all(checks.values()) else "PROOF INCOMPLETE / STOPPED (see unchecked items; nothing is inferred as a pass)")
for l in refusals[:20]:
    print("   !", l[:200])
PYEOF

{
  echo "STAGE5 STARTUP PROOF - SANITIZED RESULT (no credentials, account identifiers or private state)"
  cat $P/preflight.txt
  echo "flags: TOPSTEPX_ARM_ORDERS=false EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false AUTO_EXECUTION_ENABLED=false AI_BRAIN_ENABLED=false AI_BRAIN_LLM=false TWO_BRAIN_MODE=off; PRODUCTION_ARMED_SESSION unset"
  echo "command: $CMD"
  echo "start: $START_UTC UTC / $START_LOCAL    end: $END_UTC UTC / $END_LOCAL    exit code: $RC"
  echo "copied .env deleted after the run: $([[ -e $W/repo/.env ]] && echo NO || echo yes)"
  echo "--- extracted telemetry and checks"
  cat $P/summary_body.txt
  echo "--- full sanitized proof output"
  cat $P/proof_sanitized.log
} > $OUT
echo; sed -n '/--- extracted telemetry and checks/,/--- full sanitized/p' $OUT
echo "Sanitized result: $OUT"
echo "Done. This was the single authorized proof; do not re-run it. Paste the extracted block above back to Claude."

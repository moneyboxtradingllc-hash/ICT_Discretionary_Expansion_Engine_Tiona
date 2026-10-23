#!/bin/zsh
# ONE supervised, armed Topstep 50K Combine session on 2026-10-23 (Maurice's conditional GO of 2026-10-23 02:50Z).
#
#   zsh stage5_combine_session.zsh setup      /path/to/.env   # offline: fresh checkout, venv, pins, config check
#   zsh stage5_combine_session.zsh preflight                  # Friday before 09:00 ET: manual OCO, read-only account
#                                                             #   preflight, signed session authorization (no orders)
#   zsh stage5_combine_session.zsh trade                      # Friday: the ONE armed session (only after preflight PASS)
#
# Existing commands only: tools/preflight_account_state.py, tools/topstepx_issue_session_authorization.py and
# tools/topstepx_production_session.py --arm --mission-id <id> --until-close. No protected source is changed.
# Everything private (raw logs, .env copy, state) stays in ~/stage5_combine_20261023/; sanitized copies go to the Desktop.
set -u
SRC=ffe00aef3db7fb2339780ed0fa9016149923c96e
TREE=57cc69c03882efc9bd1d6a7921f4fea6792a31cc
REPO=https://github.com/moneyboxtradingllc-hash/ICT_Discretionary_Expansion_Engine_Tiona.git
SESSION_ID=PROD-20261023-C1
SESSION_DATE=2026-10-23
W=$HOME/stage5_combine_20261023
P=$W/private
R=$W/repo
V=$W/venv/bin
STEP=${1:-}
stop() { echo "STOPPED ($STEP): $1" | tee -a $P/steps.log; exit 1; }
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
mkdir -p $P && chmod 700 $W $P

verify_source() {
  [[ $(git -C $R rev-parse HEAD) == $SRC ]] || stop "HEAD is not $SRC"
  [[ $(git -C $R rev-parse 'HEAD^{tree}') == $TREE ]] || stop "tree is not $TREE"
  [[ -z $(git -C $R status --porcelain --untracked-files=no) ]] || stop "tracked files modified in the checkout"
}

sanitize() {  # $1 raw log -> $2 sanitized copy (redacts every .env credential/account value)
  $V/python - "$R/.env" "$1" "$2" "$HOME" <<'PYEOF'
import re, sys
envp, raw, out, home = sys.argv[1:5]
secrets = []
for line in open(envp, encoding="utf-8", errors="replace"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v and len(v) >= 4 and re.search(r"USERNAME|API_KEY|ACCOUNT|FINGERPRINT|PASSWORD|TOKEN|SECRET", k):
            secrets.append(v)
text = open(raw, encoding="utf-8", errors="replace").read()
for s in sorted(set(secrets), key=len, reverse=True):
    text = text.replace(s, "[REDACTED]")
text = text.replace(home, "~")
text = re.sub(r"(Bearer\s+)\S+", r"\1[REDACTED]", text)
text = re.sub(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "[REDACTED_JWT]", text)
text = re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[REDACTED_KEY]", text)
open(out, "w").write(text)
PYEOF
}

case $STEP in
setup)
  ENVSRC=${2:-}
  [[ -n $ENVSRC && -f $ENVSRC ]] || stop "give the path to your .env"
  [[ -e $R ]] && stop "$R already exists; setup runs once (delete ~/stage5_combine_20261023 only if nothing was issued or traded)"
  echo "== setup $(stamp)" | tee -a $P/steps.log
  git clone --quiet --no-checkout $REPO $R && git -C $R checkout --quiet --detach $SRC || stop "clone/checkout failed"
  verify_source
  PY=""
  for c in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 python3; do
    if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then PY=$(command -v $c); break; fi
  done
  [[ -n $PY ]] || stop "Python 3.12 not found"
  $PY -m venv $W/venv && $V/python -m pip install --quiet --disable-pip-version-check -r $R/requirements.txt > $P/pip.log 2>&1 || stop "pip install failed (see $P/pip.log)"
  PINS=$(cd $R && $V/python - <<'PYEOF'
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
  for k in TOPSTEPX_USERNAME TOPSTEPX_API_KEY TOPSTEPX_ACCOUNT_ID TOPSTEPX_ACCOUNT_FINGERPRINT OPENAI_API_KEY; do
    grep -qE "^${k}=.+" $ENVSRC || stop "$k is missing or empty in your .env"
  done
  cp $ENVSRC $R/.env && chmod 600 $R/.env
  echo "source: $SRC tree $TREE clean | runtime $($V/python -V 2>&1) macOS $(sw_vers -productVersion 2>/dev/null) | pins $PINS" | tee -a $P/steps.log
  echo "credentials: 5 required names present (values not shown)" | tee -a $P/steps.log
  echo "configured (non-secret) settings in your .env; the trade step pins the four Brain/data values below:" | tee -a $P/steps.log
  grep -E "^(AI_BRAIN_ENABLED|AI_BRAIN_LLM|AI_BRAIN_MODEL|TWO_BRAIN_MODE|DATA_PROVIDER|AI_BRAIN_JSON_MODE|MARKET_COMMANDER[A-Z_]*)=" $R/.env | sed 's/^/  .env  /' | tee -a $P/steps.log
  echo "  trade AI_BRAIN_ENABLED=true AI_BRAIN_LLM=true AI_BRAIN_MODEL=gpt-6-luna DATA_PROVIDER=topstepx" | tee -a $P/steps.log
  echo "SETUP PASS. Nothing was connected. Next, Friday before 09:00 ET: zsh $0 preflight" | tee -a $P/steps.log
  ;;

preflight)
  [[ -d $R ]] || stop "run setup first"
  verify_source
  [[ ! -e $P/preflight.PASS ]] || stop "preflight already passed at $(cat $P/preflight.PASS); do not repeat it"
  echo "== preflight $(stamp) / local $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a $P/steps.log
  cat <<'TXT'

MANUAL CHECKS IN THE TOPSTEP / TOPSTEPX WEBSITE (the API cannot attest these):
  1. The reset 50K Combine is the account shown, Active, and within its trailing-drawdown limit.
  2. Auto OCO / bracket orders are ENABLED for that account (a reset can clear this setting).
  3. No open position and no working order on any account you will trade.
TXT
  print -n "Type OCO-ON only if you SAW Auto OCO / brackets enabled in the Topstep UI just now: "; read -r A
  [[ $A == OCO-ON ]] || stop "Auto OCO / brackets not confirmed"
  print -n "Type COMBINE-OK only if the 50K Combine is active, flat and within its drawdown limit: "; read -r A
  [[ $A == COMBINE-OK ]] || stop "Combine status not confirmed"
  echo "manual: Auto OCO/brackets confirmed ON by the operator; Combine active/flat/within limits confirmed by the operator ($(stamp))" | tee -a $P/steps.log
  print -n "Type GO to run the read-only account preflight and issue today's session authorization (no orders): "; read -r A
  [[ $A == GO ]] || stop "operator did not type GO"
  cd $R
  PATH=$V:$PATH PYTHONPATH=src python3 tools/preflight_account_state.py > $P/preflight_raw.log 2>&1; RC1=$?
  sanitize $P/preflight_raw.log $P/preflight_sanitized.log
  cat $P/preflight_sanitized.log
  grep -q "account mode *: COMBINE_SIMULATED" $P/preflight_sanitized.log || stop "account is not COMBINE_SIMULATED (or unreadable)"
  # The tool prints "can trade"/"is visible" via camelCase getattr on a snake_case dataclass, so both always read
  # None (display-only defect). The pin it performed already refuses canTrade=false or isVisible=false, and the
  # issuer below re-checks canTrade and the simulated role.
  grep -q "^PHASE 2 -- ACCOUNT READ-ONLY PREFLIGHT" $P/preflight_sanitized.log || stop "preflight did not pass the pin (see output)"
  grep -q "open positions *: 0$" $P/preflight_sanitized.log || stop "open position present"
  grep -q "working orders *: 0$" $P/preflight_sanitized.log || stop "working order present"
  grep -q "FLAT *: True$" $P/preflight_sanitized.log || stop "account not proven flat"
  [[ $RC1 == 0 ]] || stop "preflight exit code $RC1"
  PATH=$V:$PATH PYTHONPATH=src python3 tools/topstepx_issue_session_authorization.py --session-id $SESSION_ID --date $SESSION_DATE > $P/authorization_raw.log 2>&1; RC2=$?
  sanitize $P/authorization_raw.log $P/authorization_sanitized.log
  cat $P/authorization_sanitized.log
  [[ $RC2 == 0 ]] || stop "authorization refused (exit $RC2)"
  grep -q "AUTHORIZATION STATE *: UNSPENT" $P/authorization_sanitized.log || stop "authorization not UNSPENT"
  grep -q "ACCOUNT ROLE *: Trading Combine (simulated venue environment)" $P/authorization_sanitized.log || stop "account role not the simulated Combine"
  grep -q "CAN TRADE *: True" $P/authorization_sanitized.log || stop "issuer did not confirm canTrade"
  grep -q "Write proof: 0 write calls made" $P/authorization_sanitized.log || stop "issuer did not prove zero writes"
  cp $P/preflight_sanitized.log $HOME/Desktop/combine_20261023_preflight_SANITIZED.txt
  cat $P/authorization_sanitized.log >> $HOME/Desktop/combine_20261023_preflight_SANITIZED.txt
  stamp > $P/preflight.PASS
  echo "PREFLIGHT PASS (session $SESSION_ID). Next, at about 08:50-08:55 ET with you at the Mac: zsh $0 trade" | tee -a $P/steps.log
  ;;

trade)
  [[ -e $P/preflight.PASS ]] || stop "preflight has not passed"
  [[ ! -e $P/trade.STARTED ]] || stop "the one armed session already started at $(cat $P/trade.STARTED); no second session"
  verify_source
  cat <<TXT

READY TO ARM THE ONE SUPERVISED COMBINE SESSION ($SESSION_ID)
  Window 09:00-14:00 ET; max 2 trades, 1 attempt each; max \$350 planned all-in risk/trade; signed daily loss budget;
  max 15 MNQ; stop <=35 pts preferred, 50 pts ceiling; compounding OFF. The Brain decides; nothing is forced.
  Stay at the Mac the whole session. The Mac is kept awake for you (caffeinate).
  To stop NEW entries: press Ctrl-C ONLY while the account is FLAT. If a position is open, do NOT kill the process:
  the bot manages it to flat; its venue bracket protects it. Tell Claude immediately on any error or doubt.
Type ARM to start. Anything else stops.
TXT
  read -r A
  [[ $A == ARM ]] || stop "operator did not type ARM"
  stamp > $P/trade.STARTED
  echo "== trade start $(cat $P/trade.STARTED) / local $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a $P/steps.log
  cd $R
  unset PRODUCTION_ARMED_SESSION
  export AI_BRAIN_ENABLED=true AI_BRAIN_LLM=true AI_BRAIN_MODEL=gpt-6-luna DATA_PROVIDER=topstepx
  PATH=$V:$PATH PYTHONPATH=src caffeinate -dimsu python3 tools/topstepx_production_session.py --arm --mission-id $SESSION_ID --until-close 2>&1 | tee $P/session_raw.log
  RC=${pipestatus[1]}
  echo "== trade end $(stamp) exit $RC" | tee -a $P/steps.log
  sanitize $P/session_raw.log $P/session_sanitized.log
  OUT=$HOME/Desktop/combine_20261023_session_SANITIZED.txt
  { echo "COMBINE SESSION $SESSION_ID  source $SRC  start $(cat $P/trade.STARTED)  end $(stamp)  exit $RC"
    echo "--- key lines"
    grep -nE "ARM STATE|LANE|PRODUCTION SCANS|scan [0-9]|SUBMIT|FILL|BRACKET|STOP|TARGET|EXIT|HARD FLATTEN|FLAT|REFUSED|ERROR|OPERATOR ACTION|FINAL STATE|SESSION (GRACEFUL|COMPLETE)|P&L|PNL|SHUTDOWN|Traceback" $P/session_sanitized.log | cut -c1-240
    echo "--- full sanitized session log"; cat $P/session_sanitized.log; } > $OUT
  echo "Sanitized session record: $OUT  (paste the '--- key lines' part to Claude)"
  ;;

*) echo "usage: zsh $0 setup /path/to/.env | preflight | trade"; exit 2 ;;
esac

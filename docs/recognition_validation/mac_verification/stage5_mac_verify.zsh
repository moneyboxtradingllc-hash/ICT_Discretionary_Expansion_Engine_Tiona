#!/bin/zsh
# Stage 5 Mac verification: disposable, offline and disarmed.
#
#   zsh stage5_mac_verify.zsh          focused regression set (about 30-45 min)
#   zsh stage5_mac_verify.zsh full     focused set, then the complete suite (a few hours)
#
# It clones the exact source commit into a NEW folder under $HOME and never
# touches your trading checkout, its .env, any account, provider or venue. The
# only network use is git clone from GitHub and pip install from PyPI; every
# test runs with an emptied environment, orders disarmed and the HTTP(S) proxy
# pointed at a dead port. Results land in ~/Desktop/stage5_mac_results_<time>.tar.gz
# and a short summary is printed at the end. No secrets or .env contents are read.
set -u
SRC=5d18b4b41b45e7f895aa6b1d3aa1fd5966c40e03
REPO=https://github.com/moneyboxtradingllc-hash/ICT_Discretionary_Expansion_Engine_Tiona.git
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
W=$HOME/stage5_mac_verify_$STAMP
E=$W/evidence
mkdir -p $E $W/rt
exec > >(tee $E/console.log) 2>&1
echo "== Stage 5 Mac verification $STAMP  source $SRC  mode ${1:-focused}"

# -- 1. inventory -------------------------------------------------------------
{
  echo "sw_vers:"; sw_vers
  echo "uname: $(uname -srm)"
  echo "cpu: $(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
  echo "arm64_capable: $(sysctl -n hw.optional.arm64 2>/dev/null)  rosetta_translated: $(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)"
  echo "zsh: $ZSH_VERSION"
  echo "xcode_select: $(xcode-select -p 2>&1)"
  echo "brew_prefix: $(brew --prefix 2>/dev/null || echo none)"
  echo "git candidates:"; which -a git
  echo "git_version: $(git --version 2>&1)"
  echo "python candidates:"; which -a python3 python3.12 python3.11 python3.13 2>/dev/null
} > $E/inventory.txt 2>&1
cat $E/inventory.txt

PY=""
for c in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 python3.13 python3.11 python3; do
  if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY=$(command -v $c); break
  fi
done
if [[ -z $PY ]]; then
  echo "NO-GO: no Python >= 3.11 found. Install Python 3.12 (python.org or 'brew install python@3.12') and re-run."
  exit 1
fi
GIT=$(command -v git)
if [[ -z $GIT ]] || ! $GIT --version >/dev/null 2>&1; then
  echo "NO-GO: git is not usable. Run 'xcode-select --install' (or 'brew install git') and re-run."
  exit 1
fi
echo "using python: $PY ($($PY -V 2>&1))   git: $GIT" | tee -a $E/inventory.txt

# -- 2. isolated checkout at the exact commit ------------------------------------
git clone --quiet --no-checkout $REPO $W/repo && git -C $W/repo checkout --quiet --detach $SRC || { echo "NO-GO: clone/checkout failed"; exit 1; }
cd $W/repo
HEAD_SHA=$(git rev-parse HEAD); TREE=$(git rev-parse 'HEAD^{tree}')
echo "head $HEAD_SHA tree $TREE" | tee $E/source_identity.txt
[[ $HEAD_SHA == $SRC ]] || { echo "NO-GO: checkout is not the exact source"; exit 1; }
[[ -z $(git status --porcelain) ]] || { echo "NO-GO: checkout not clean"; exit 1; }

# -- 3. pinned environment -------------------------------------------------------
$PY -m venv $W/venv
V=$W/venv/bin
$V/python -m pip install --quiet --disable-pip-version-check --upgrade pip > $E/pip_upgrade.log 2>&1
$V/python -m pip install --disable-pip-version-check -r requirements.txt > $E/pip_install.log 2>&1
PIP_RC=$?
echo "pip install rc=$PIP_RC" | tee -a $E/inventory.txt
# The test runner is not in requirements.txt; pin the versions the Linux verification used.
$V/python -m pip install --disable-pip-version-check pytest==9.1.1 pluggy==1.7.0 iniconfig==2.3.1 packaging==26.3   > $E/pip_test_tools.log 2>&1 || { echo "NO-GO: could not install pytest"; PIP_RC=1; }
if [[ $PIP_RC -ne 0 ]]; then
  echo "bulk install failed; trying each pin to find the incompatible ones"
  $V/python - > $E/pip_per_package.txt 2>&1 <<'PYEOF'
import subprocess, sys
for raw in open("requirements.txt", encoding="utf-16"):
    pin = raw.split("#")[0].strip()
    if pin:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", pin],
                           capture_output=True, text=True)
        print(("OK   " if r.returncode == 0 else "FAIL ") + pin + ("" if r.returncode == 0 else "  " + r.stderr.strip().splitlines()[-1]))
PYEOF
  cat $E/pip_per_package.txt
fi
$V/python -m pip freeze > $E/pip_freeze.txt
$V/python - > $E/pins.json <<'PYEOF'
import json, re, sys, platform, importlib.metadata as m
rows = []
for raw in open("requirements.txt", encoding="utf-16"):
    line = raw.split("#")[0].strip()
    if not line:
        continue
    name, want = re.match(r"([A-Za-z0-9_.\-\[\]]+)==(\S+)", line).groups()
    name = re.sub(r"\[.*\]", "", name)
    try:
        have = m.version(name)
    except Exception:
        have = None
    rows.append({"package": name, "expected": want, "actual": have, "match": have == want})
print(json.dumps({"python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                  "pins_total": len(rows), "pins_matching": sum(r["match"] for r in rows),
                  "mismatches": [r for r in rows if not r["match"]]}, indent=1))
PYEOF

# -- 4. disarmed, allowlisted runner -------------------------------------------
GITDIR=${GIT:h}
run() {  # run <log> <cmd...>
  local log=$1; shift
  local rt=$(mktemp -d $W/rt/rt.XXXX)
  mkdir -p $rt/home
  env -i PATH="$V:$GITDIR:/usr/bin:/bin:/usr/sbin:/sbin" HOME=$rt/home LANG=C.UTF-8 TZ=UTC \
    PYTHONPATH=src:tests PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
    EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false AI_BRAIN_LLM=false TWO_BRAIN_MODE=off TOPSTEPX_ARM_ORDERS=false \
    OCCURRENCE_LEDGER_DIR=$rt/occurrence_ledger_dir AI_BRAIN_DIR=$rt/ai_brain_dir REPLAY_SESSIONS_DIR=$rt/replay_sessions_dir \
    AI_RETRIEVAL_DIR=$rt/ai_retrieval_dir PERFORMANCE_TABLES_DIR=$rt/performance_tables_dir HTF_MEMORY_DIR=$rt/htf_memory_dir \
    GLOBAL_MEMORY_DIR=$rt/global_memory_dir HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 NO_PROXY= \
    "$@" > $log 2>&1
  local rc=$?
  echo "  rc=$rc  $(tail -1 $log)"
  return $rc
}

echo "== child-launch environment on this Mac"
run $E/child_env_mac.json python3 -I -c '
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, "src")
from recognition_validation import child as CH
env = CH.child_environment(Path(tempfile.mkdtemp()) / "child", ecu=False)
print(json.dumps({"parent_git": shutil.which("git"), "child_path": env["PATH"].split(":"),
                  "child_finds_git": shutil.which("git", path=env["PATH"]),
                  "env_names_equal_allowlist": set(env) == CH.ENV_ALLOWLIST,
                  "disarmed": {k: env[k] for k in ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AI_BRAIN_LLM",
                                                   "TWO_BRAIN_MODE", "HTTPS_PROXY", "HTTP_PROXY")}}, indent=1))'
cat $E/child_env_mac.json

echo "== ledger and protected-source verification"
run $E/ledger_verify.json python3 tools/verify_engineering_ledger.py

echo "== focused regression set (both ECU modes are inside these tests)"
FOCUSED=(tests/test_recognition_child_portability.py tests/test_recognition_process_isolation.py
         tests/test_recognition_quote_wake_trigger.py tests/test_recognition_scoring_cli.py
         tests/test_recognition_owner_ab.py tests/test_recognition_contracts.py tests/test_recognition_rule_coverage.py
         tests/test_recognition_layer_projection.py)
run $E/focused.log python3 -m pytest -q -rfEs -p no:cacheprovider --junitxml=$E/focused.junit.xml $FOCUSED

if [[ ${1:-} == full ]]; then
  echo "== complete suite (takes a while; leave the Mac awake: caffeinate is used)"
  run $E/collect.txt python3 -m pytest -q --collect-only -p no:cacheprovider tests
  run $E/full.log caffeinate -i python3 -m pytest -q -rfE -p no:cacheprovider --junitxml=$E/full.junit.xml tests
fi

# -- 5. summary + evidence ----------------------------------------------------------
$V/python - $E > $E/SUMMARY.txt <<'PYEOF'
import json, sys, xml.etree.ElementTree as ET
from pathlib import Path
e = Path(sys.argv[1])
def junit(name):
    p = e / name
    if not p.exists():
        return None
    cases = list(ET.parse(p).iter("testcase"))
    out = {"cases": len(cases), "passed": 0, "skipped": 0, "failed": []}
    for c in cases:
        kids = [k.tag for k in c]
        if "failure" in kids or "error" in kids:
            out["failed"].append(f'{c.get("classname")}::{c.get("name")}')
        elif "skipped" in kids:
            out["skipped"] += 1
        else:
            out["passed"] += 1
    return out
pins = json.loads((e / "pins.json").read_text())
child = (e / "child_env_mac.json").read_text()
ledger = (e / "ledger_verify.json").read_text()
print("STAGE5 MAC SUMMARY")
print("source:", (e / "source_identity.txt").read_text().strip())
print("python:", pins["python"].split()[0], "|", pins["platform"], "|", pins["machine"])
print("pins matching:", pins["pins_matching"], "/", pins["pins_total"], "| mismatches:",
      [f'{m["package"]} {m["expected"]}->{m["actual"]}' for m in pins["mismatches"]])
try:
    cj = json.loads(child)
    print("child finds git:", cj["child_finds_git"], "| env == allowlist:", cj["env_names_equal_allowlist"],
          "| disarmed:", cj["disarmed"])
except Exception:
    print("child env check FAILED:", child[-300:])
print("ledger:", "LEDGER_VERIFIED" if "LEDGER_VERIFIED" in ledger else "NOT VERIFIED: " + ledger[-300:])
for name in ("focused.junit.xml", "full.junit.xml"):
    r = junit(name)
    if r:
        print(f'{name}: {r["cases"]} cases, {r["passed"]} passed, {r["skipped"]} skipped, {len(r["failed"])} failed')
        for f in r["failed"][:25]:
            print("   FAILED", f)
PYEOF
cat $E/SUMMARY.txt
# Keep usernames out of the evidence that will be shared.
LC_ALL=C find $E -type f -exec sed -i '' "s#$HOME#~#g" {} + 2>/dev/null
OUT=$HOME/Desktop/stage5_mac_results_$STAMP.tar.gz
tar -czf $OUT -C $W evidence && echo "evidence: $OUT  sha256 $(shasum -a 256 $OUT | cut -d' ' -f1)"
echo "Done. Paste the STAGE5 MAC SUMMARY block back to Claude and put the .tar.gz in your Google Drive."

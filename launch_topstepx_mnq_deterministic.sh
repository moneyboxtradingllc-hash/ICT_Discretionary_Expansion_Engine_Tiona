#!/usr/bin/env bash
# ======================================================================
# launch_topstepx_mnq_deterministic.sh
# DETERMINISTIC_MNQ_SIM_ONLY on TOPSTEPX. NinjaTrader is not involved at all.
#
# macOS/Linux port of launch_topstepx_mnq_deterministic.ps1. Same lane, same
# gates, same order in which they run — only the shell differs. The PowerShell
# launcher remains the Windows path and is unchanged.
#
# The lane's logic is identical to the NinjaTrader launcher; only the transport
# differs. Everything account-specific lives in .env, which is gitignored, so a
# `git pull` can never overwrite your account with someone else's.
# ======================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export PYTHONPATH="src"
export DETERMINISTIC_VENUE="topstepx"
export OPENAI_DISABLED_FOR_INTEGRATION="1"

# ── operator decisions carried from the NinjaTrader lane ──────────────
# These govern the shared pipeline, not a venue, so they must be repeated.
export REGIME_AUTHORITY_ENABLED="false"   # regime is observe-only
export PO3_LEG_SCOPED_METRICS="off"       # correct metric, thresholds not recalibrated

# ── ORDERS ARE DISARMED ───────────────────────────────────────────────
# NinjaTrader's bridge owns an ArmOrders switch that physically refuses orders.
# TopstepX has no equivalent, so the safety lives in the transport. Leave this
# false until a full session has run and the funnel output looks right; the lane
# scans, decides and records everything with it off, and simply never sends.
#
# Exported here deliberately: load_dotenv() does NOT override a variable already
# set in the shell, so this pins orders disarmed even if .env says otherwise.
export TOPSTEPX_ARM_ORDERS="false"

# ── which python ──────────────────────────────────────────────────────
# macOS has no bare `python` outside a virtualenv, so resolve it rather than
# failing with "command not found" three lines from the trading loop. Activate
# your venv first and this picks it up; PYTHON=... overrides.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if command -v python >/dev/null 2>&1; then
        PYTHON="python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="python3"
    else
        echo "No python interpreter found on PATH." >&2
        echo "Activate your virtual environment first, e.g.  source .venv/bin/activate" >&2
        exit 1
    fi
fi

# ── required in .env (see .env.template) ──────────────────────────────
#   TOPSTEPX_USERNAME       TOPSTEPX_API_KEY
#   TOPSTEPX_ACCOUNT_NAME   TOPSTEPX_CONTRACT
#   TOPSTEP_ACCOUNT_SIZE    50K | 100K | 150K   <- drives the trailing drawdown cap
if [ ! -f ".env" ]; then
    echo ".env not found in $(pwd)" >&2
    echo "Copy .env.template to .env and fill it in, then re-run:" >&2
    echo "    cp .env.template .env" >&2
    exit 1
fi

missing=0
for k in TOPSTEPX_USERNAME TOPSTEPX_API_KEY TOPSTEPX_ACCOUNT_NAME \
         TOPSTEPX_CONTRACT TOPSTEP_ACCOUNT_SIZE; do
    if ! grep -qE "^${k}=.+" .env; then
        echo "$k is not set in .env"
        missing=1
    fi
done
if [ "$missing" -ne 0 ]; then
    echo "Copy .env.template to .env and fill it in, then re-run."
    exit 1
fi

# ── preflight: prove the connection before the loop can decide anything ──
echo "Running TopstepX preflight..."
if ! "$PYTHON" -m broker.topstepx_preflight; then
    echo ""
    echo "Preflight failed - not starting the loop." >&2
    exit 1
fi

echo "======================================================================"
echo "MODE: DETERMINISTIC_MNQ_SIM_ONLY"
echo "VENUE: TOPSTEPX  (NinjaTrader NOT used)"
echo "AUTHOR: deterministic_sim_author"
echo "SIZING: RISK-BASED, capped by the Topstep trailing drawdown"
echo "STOP: STRUCTURAL INVALIDATION, max 25 points"
echo "TARGET: 35 POINTS"
echo "ORDERS ARMED: ${TOPSTEPX_ARM_ORDERS}"
echo "OPENAI CALLS: DISABLED"
echo "======================================================================"

stop="data/integration/ninjatrader/deterministic/STOP"
if [ -f "$stop" ]; then rm -f "$stop"; fi

"$PYTHON" -m integrations.ninjatrader.deterministic.loop

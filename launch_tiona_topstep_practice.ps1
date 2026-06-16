# ══════════════════════════════════════════════════════════════════════════════
# Tiona — ONE-CLICK Topstep PRACTICE launcher.
#
#   broker=topstep  data_provider=topstep  execution_provider=topstep
#   symbol=MNQU     practice_only=true     execution=PRACTICE (NOT live/funded)
#
# Secrets are READ from .env at runtime — never stored in this script, never
# committed. Every safety check must pass or the launcher aborts before start.
# Live/funded execution is refused. No naked entries (the bot requires a native
# bracket; see DEPLOY-2D.1).
# ══════════════════════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$Root = "C:\Users\jesus\ICT_Discretionary_Expansion_Engine"
Set-Location $Root

function Fail($m) { Write-Host "ABORT: $m" -ForegroundColor Red; exit 1 }
Write-Host "=== Tiona Topstep PRACTICE launcher ==="

# 1 — .env exists
$envPath = Join-Path $Root ".env"
if (-not (Test-Path $envPath)) { Fail ".env not found ($envPath). Create it with your PROJECTX_TOPSTEPX_* credentials." }
$envLines = Get-Content $envPath

function Get-EnvVal($name) {
    $line = $envLines | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -First 1
    if (-not $line) { return "" }
    return (($line -replace "^\s*$name\s*=", "").Trim().Trim('"').Trim("'").Trim())
}

# 2 / 3 — credentials present (values stay in memory; never printed)
$user = Get-EnvVal "PROJECTX_TOPSTEPX_USERNAME"
$key  = Get-EnvVal "PROJECTX_TOPSTEPX_API_KEY"
if ([string]::IsNullOrWhiteSpace($user)) { Fail "PROJECTX_TOPSTEPX_USERNAME missing/empty in .env" }
if ([string]::IsNullOrWhiteSpace($key))  { Fail "PROJECTX_TOPSTEPX_API_KEY missing/empty in .env" }
Write-Host "[ok] credentials present (username len=$($user.Length), api_key len=$($key.Length))"

# 4 — instance config exists
$cfg = Join-Path $Root "data\instances\tiona_topstep\config.yaml"
if (-not (Test-Path $cfg)) { Fail "instance config not found: $cfg (regenerate from instances/templates/topstep_150k.yaml)" }
$cfgText = Get-Content $cfg

# 5 — config has the required Topstep/MNQU/practice values (catches a stale config)
function Assert-Cfg($pattern, $desc) {
    if (-not ($cfgText | Where-Object { $_ -match $pattern })) { Fail "stale/incorrect config — expected '$desc' in $cfg" }
}
Assert-Cfg "^\s*symbol:\s*MNQU\s*$"                "symbol: MNQU"
Assert-Cfg "^\s*broker:\s*topstep\s*$"             "broker: topstep"
Assert-Cfg "^\s*data_provider:\s*topstep\s*$"      "data_provider: topstep"
Assert-Cfg "^\s*execution_provider:\s*topstep\s*$" "execution_provider: topstep"
Assert-Cfg "^\s*practice_only:\s*true\s*$"         "practice_only: true"
Write-Host "[ok] config: broker/data/execution=topstep, symbol=MNQU, practice_only=true"

# 8a (config gate) — account must be practice/eval/sim, never funded/live
$acctLine = ($cfgText | Where-Object { $_ -match "^\s*account_type:" } | Select-Object -First 1)
if ($acctLine -match "funded|live")       { Fail "account_type indicates funded/live — refusing practice execution" }
if ($acctLine -notmatch "practice|eval|sim") { Fail "account_type does not look practice/eval/sim — refusing" }
Write-Host "[ok] account_type practice/eval ($($acctLine.Trim()))"

# refuse double-launch
$existing = Get-Process python -ErrorAction SilentlyContinue
if ($existing.Count -gt 0) { Fail "$($existing.Count) python process(es) already running — stop them first" }

# 6 / 7 — session execution flags (PRACTICE execution; practice-only)
$env:PROJECTX_TOPSTEPX_USERNAME = $user
$env:PROJECTX_TOPSTEPX_API_KEY  = $key
# bridge to the adapter's credential names (TopstepBrokerAdapter reads TOPSTEP_*)
$env:TOPSTEP_USERNAME           = $user
$env:TOPSTEP_API_KEY            = $key
$env:TOPSTEP_ENV                = "practice"     # _is_practice() gate
$env:TOPSTEP_PRACTICE_ONLY      = "true"         # never relax
$env:TOPSTEP_EXECUTION_ENABLED  = "true"         # PRACTICE execution opt-in (this session)
$env:PYTHONUNBUFFERED           = "1"

# 8b (live gate) — refuse if the live account is not practice/sim
Write-Host "[..] verifying live account is practice/sim ..."
$pf = python -c @'
import sys
sys.path.insert(0, "src")
try:
    from broker.topstep_adapter import TopstepBrokerAdapter
    a = TopstepBrokerAdapter()
    auth = a.authenticate()
    if not auth.get("ok"):
        print("PREFLIGHT_FAIL auth_error=" + str(auth.get("error"))); raise SystemExit(0)
    acct = a.get_account()
    if acct.get("connected") and acct.get("simulated") is False:
        print("PREFLIGHT_NONPRACTICE simulated=False"); raise SystemExit(0)
    print("PREFLIGHT_OK simulated=" + str(acct.get("simulated")))
except SystemExit:
    raise
except Exception as exc:
    print("PREFLIGHT_ERROR " + type(exc).__name__)
'@
Write-Host "    $pf"
if ($pf -match "PREFLIGHT_NONPRACTICE") { Fail "live account is NOT practice/sim — refusing execution" }
if ($pf -notmatch "PREFLIGHT_OK")       { Fail "could not verify a practice account (auth/connectivity) — refusing execution" }
Write-Host "[ok] live account verified practice/sim"

# 9 — start (single command for Tiona)
Write-Host ""
Write-Host "=== launching Tiona Topstep PRACTICE bot (MNQU) ==="
Write-Host "    symbol=MNQU provider=topstep execution=PRACTICE practice_only=true (NOT live/funded)"
python run_instance.py --instance tiona_topstep --start

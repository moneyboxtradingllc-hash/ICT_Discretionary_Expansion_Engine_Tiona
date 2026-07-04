# CAPITAL-1 — Capital Intelligence Engine

Date: 2026-07-04 (pre-session — equity awareness live from ADAPTIVE-8 scan #1)

The organism understands scars. Now it understands money.

## Capital map BEFORE

Existing: equity/cash/buying_power (paper_broker.get_account), risk_used_today
(trade_journal), daily-loss halt (position_guard vs DAILY_LOSS_LIMIT_DOLLARS),
daily realized pnl derivable from journals, expectancy/win-rate from the
DECON-2 ledger. MISSING with no owner anywhere: peak_equity, drawdown,
weekly_pnl, profit_factor, risk_remaining, any equity-curve memory. The new
engine owns everything longitudinal
(`data/performance/ACCOUNT/capital_history.json`).

## State model (first match wins)

critical (daily_pnl ≤ −80% limit, or dd ≥ 10%) → **probation lock** ·
preservation (dd ≥ 6%, or weekly ≤ −2× limit) → **reduce size hard** ·
defensive (dd ≥ 3%, or daily ≤ −50% limit) → **reduce aggression** ·
probation (sample < 10 closed trades) → no contraction, no pressing ·
expansion (exp ≥ +0.5R, PF ≥ 1.5, dd ≤ 0.5%, weekly > 0) → tier press_plus ·
growth (exp > 0, dd ≤ 1%, weekly > 0) → tier press · stable → normal.

**Aggression doctrine (constitutional):** capital may CONTRACT, LOCK, or
PERMIT — never exceed. Growth/expansion "controlled aggression increase" =
permission to operate at the full risk-governor ceiling (no contraction) with
the pressing tier reported; pushing above the ceiling is deferred until
forward validation produces truth. Capital never boosts confidence, never
authors direction, never touches risk math / stop math / broker contracts.

## Wiring

scan_loop computes `track_capital(symbol)` once per scan (sole writer of
capital history — persist contract) → passed into `build_snapshot(...,
capital_report=)` → the adaptive policy merges `capital_mutation` into its
EXISTING flags (confidence_penalty / risk_reduction / trade_block) and records
`capital_actions` in the adjustments + a compact `capital` block in the
report. The unchanged mutation engine then applies −10% confidence / halving /
soft veto exactly as always. Weekly pnl uses a true trailing 7-calendar-day
window (a test caught that file-count windows let three-week-old losses put a
fresh Monday into preservation — fixed before it ever ran live).

## Forensics

`snapshot["capital_intelligence"]` persisted every scan (DECON-3 writer):
capital_authority, capital_state, aggression_tier, equity_health_score,
drawdown_pressure, growth_strength, risk_efficiency, capital_mutation,
capital_pressure (dd/daily/weekly/limit/risk_remaining/limit-used %),
capital_actions, state_reasons, metrics. Console prints on any
non-normal/pressing state.

## Live baseline at campaign start

probation (5 closed trades < 10) → contributes NOTHING — the validated
ADAPTIVE-8 baseline is bit-identical. All-time risk_efficiency from journal
truth: −1.3931 (honest).

## Regression lock

`tests/test_capital1_engine.py` (20 tests): A growth (ceiling permitted, no
contraction) · B expansion · C defensive (dd + daily-loss triggers) ·
D preservation (dd + weekly-bleed) · E critical lock + precedence (drawdown
beats performance) · F risk efficiency + pressure/health scores from journal
truth · G confidence −10% through the unchanged chain · H size halved through
the unchanged chain + critical lock + never-boosts + probation neutrality ·
fail-safe neutrality · peak-history persistence + read-only mode · stale-loss
window guard.

Suite: 1451 tests OK. Substrate hash-verified untouched; no ACCOUNT leak.

Untouched per hard rules: AI authority, trade logic, broker contracts, stop
math, suppression engine, meta engine.

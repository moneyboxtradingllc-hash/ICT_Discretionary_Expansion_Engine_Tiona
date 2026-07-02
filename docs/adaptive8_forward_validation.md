# ADAPTIVE-8 — Forward Market Validation (campaign runbook)

Started: 2026-07-02 (setup). First eligible session: Monday 2026-07-06
(2026-07-03 is the Independence Day observance — markets closed).

OBSERVATION ONLY. Hard rules for the whole campaign: no architecture changes,
no hotfixes, no threshold changes, no tuning, no manual trades, no overrides.
Replay and synthetic price action are forbidden — forward market truth only.

## Targets

- Minimum 10 live sessions; 20–30 real closed trades (outcome-based, not
  time-based). We need diversity: wins, losses, breakevens, stopouts, blocked
  trades, mutated trades, clean entries.

## Session procedure

1. Market morning: launch with `.\launch_paper_session_fc.ps1`
   (protected values verified 2026-07-02: EXECUTION_ENABLED=true,
   PAPER_TRADING_ONLY=true, MAX_TRADES_PER_DAY=2, RISK_PER_TRADE_DOLLARS=500,
   DAILY_LOSS_LIMIT_DOLLARS=500). Stale-lock self-heal confirmed
   (startup authority reclaims dead-PID locks).
2. Let it run to EOD (no-entry 15:50, flatten 15:55). Do not intervene.
3. After close:
   `python tools/session_validation_report.py --date YYYYMMDD --record`
   — read-only auditor; emits the full per-session audit, per-trade A–E
   validation, stress signals, and table/ledger/scar integrity, and archives
   the report under `data/ops/validation/`.
4. Cumulative campaign view any time:
   `python tools/session_validation_report.py --cumulative`

## Baseline entering session 1 (2026-07-02)

- Scar store: 0 records. Performance tables: 5 real trades (0W/4L/1BE,
  exp −1.40R), ledger 5 keys, integrity mismatches: none.
- Forensic snapshots: 2,227 historical (pre-DECON-3 records are expected to
  read as forensic_incomplete in the auditor; all NEW records must be
  forensic_complete).

## EXPECTED adaptive behavior (validate against, don't assume)

From the real tables, the DEFENSIVE_ONLY policy should currently:

- session `morning_continuation` (4 trades, exp −1.58, streak 3):
  confidence_penalty + risk_reduction recommended → mutation −10% confidence,
  qty halved (floor 1) at order_builder. NOT blocked (streak 3 < 4).
- regime `trend` / volatility `normal` (3 trades, exp −1.65): same
  penalty + risk_reduction for matching candidates.
- session `lunch`, regime `range`, volatility `unstable`, playbook
  `liquidity_sweep_reversal` (< 3 trades): insufficient_data → no adjustment.
- No reachable bucket at trade_block. **One more loss in a
  morning_continuation-session bucket → loss_streak 4 → first live adaptive
  soft veto.** Watch for it; it is correct behavior, not a bug.

Any deviation from the above = mutation drift / size drift / suppression
signal — record it, do NOT patch mid-campaign.

## Reviews

- MIDPOINT (~10 closed trades): proportionality of adaptive reactions,
  mutation harshness, block health, recovery balance, scar truthfulness →
  interim grade.
- FINAL (20–30 closed trades): full statistics + answers to: adaptive health,
  threshold health, mutation safety, live-authority safety, Market Commander
  promotion readiness, live-capital readiness.

Success = honest behavior under honest markets. Profit is secondary.

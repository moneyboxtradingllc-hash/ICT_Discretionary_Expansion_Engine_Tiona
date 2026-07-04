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

REWRITTEN by HTF-MEM-1 / LINEAGE PURIFICATION (2026-07-04): the five pre-AI
June trades were classified STALE_PRE_AI (+MANUAL_CLOSE_STOP_FAILURE for the
June-9 batch) and quarantined to `data/performance_quarantine_PREAI_20260704/`.
The ORGANISM_EPOCH gate (20260706) keeps them out of adaptive/capital memory
permanently.

**Monday opens from ZERO honest evidence:**

- every adaptive dimension: insufficient_data — NO penalties, NO size
  reductions, NO blocks at the open (the old morning_continuation/trend
  contractions are gone);
- capital: probation (0 closed trades) — contributes nothing;
- scar memory, suppression memory, HTF memory: empty, current-organism-only,
  accumulating from scan #1;
- first adaptive flags appear only after ≥3 real closed trades in a bucket
  (expectancy) or a real 4-loss streak (block → MEM-DECAY healing:
  2 clean sessions → probation trade → win reopens / loss re-locks at 4).
- HTF memory: memory_age 0→1 during session 1 (lookback seeds the prior
  session); htf_confidence stays low until multiple sessions accumulate —
  thin memory that claims confidence is a bug.

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

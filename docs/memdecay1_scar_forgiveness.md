# MEM-DECAY-1 — Memory Decay Engine (scar forgiveness)

Date: 2026-07-03 (pre-session — ADAPTIVE-8 validates the healing loop from scan #1)

The organism must remember pain. But it must also learn how to heal.

## Deadlock BEFORE

loss in bucket → `_apply_result` streak++ → `adaptive_policy_engine` streak≥4 →
`trade_block` → mutation soft veto → `scan_loop` entry denial for every
matching candidate → the bucket can never trade → can never win → streak never
resets (`_apply_result`: only a same-bucket WIN resets) → **permanent
amputation**.

## Decay model (all four sanctioned vectors)

Per-bucket scar state machine, persisted in
`data/performance/<SYMBOL>/scar_state.json`:

`healthy → scarred/cooldown → probation → reopened`, re-lock on probation loss.

- **Cooldown = time × opportunity decay:** a clean session counts only when
  the bucket is evaluated as a live candidate match on a NEW date with no new
  matching loss. Base 2 clean sessions; **doubles per re-lock (2→4→8, capped)**.
- **Probation = partial rehabilitation + probation trade:** the hard block
  converts into the EXISTING defensive actuators — confidence −10% + size
  halved (mutation engine unchanged; no new risk math). Persists until the
  next closed trade folds into the bucket (breakeven → probation continues).
- **Outcome:** win → table streak resets naturally → `reopened`; loss →
  streak rises → re-locked with doubled cooldown.
- **History is never erased:** every locked / clean_session /
  probation_granted / relocked / reopened event appends to the record;
  reopened records persist; `lock_count` makes repeat offenders heal slower.

## Safety doctrine

- Decay can only SOFTEN. Probation still suppresses boosts;
  `authority_level=observe_only` / `DEFENSIVE_ONLY` unchanged.
- Engine failure returns the SAFE verdict (block kept) — a decay bug can
  never open a vetoed bucket.
- **PERSIST CONTRACT:** only the live-scan owner (the `snapshot_builder`
  policy pass) advances stored scar state. The Brain's adaptive-context view
  calls with `decay_persist=False` (pure read — also prevents double-advancing
  state twice per scan). During this build a test-leak wrote a scar record
  into the live dir via unisolated `build_snapshot`/Brain tests — caught by
  the hash tripwire, purged, and closed by the persist contract +
  `PERFORMANCE_TABLES_DIR` isolation added to the two offending test modules.

## Forensics

The policy report now carries `probation_active` and a per-dimension `decay`
block (`decay_status`, `decayed_loss_streak`, `scar_age_sessions`,
`cooldown_required`, `lock_count`, `rehabilitation_reason`). DECON-3 persists
`adaptive_policy` verbatim, so every healing step lands in the forensic
snapshot automatically.

## Regression lock (tests/test_memdecay1_engine.py — 14 tests)

A block still fires · B cooldown holds (lock day never counts) · C two clean
sessions → probation · D probation is defensive (qty halved, conf −10%, no
hard block; breakeven persists) · E probation win reopens · F probation loss
re-locks with doubled cooldown (and 4 clean sessions needed next time) ·
G history never erased + reoffense after reopen re-locks history-aware ·
safety (error → safe blocked verdict; healthy buckets stateless; never boosts).

Suite: 1402 tests OK. Live substrate hash-verified untouched; no scar-state leak.

Untouched per hard rules: AI authority, Market Commander, playbooks, risk
math, execution gate, mutation engine.

# PROD-20260806 -- Session Archive Index

Safe, committed index for the first armed TopstepX/MNQ production session.
The archive itself holds raw runtime and account-derived evidence and is
**git-ignored**; this document contains no secrets, no account identity and no
complete fingerprints.

```
PROD-20260806:
ARCHIVED
INTEGRITY VERIFIED
READY FOR REPLAY ANALYSIS
```

## Session outcome

The organism ran armed against a live Trading Combine for three phases,
classified 172 scans, refused every one with a stated reason, never reached a
write endpoint, and shut down cleanly with the account flat.

**No candidate, no token, no attempt, no order, no fill.**

## Archive location

| | |
|---|---|
| Archive root | `data/replay_sessions/PROD-20260806/` (ignored) |
| Package | `data/replay_sessions/_packages/PROD-20260806_REPLAY.zip` (ignored) |
| Package size | 4.27 MB, 739 entries |
| Archived files | 738 + `SHA256SUMS.txt` |
| Integrity | 738/738 SHA-256 verified after independent extraction |

Verify:

```bash
cd data/replay_sessions/PROD-20260806 && sha256sum -c SHA256SUMS.txt
```

## Phase timeline

Today did **not** run under one static code version. Each phase is mapped to the
commit that was actually live, verified against git timestamps.

| Phase | Window (ET) | Commit | Launch mode | Exit |
|---|---|---|---|---|
| A | 09:30:02 - 10:17:23 | `fc241d9` | Claude background task | `EXTERNAL_TASK_STOP -- CAUSE UNPROVEN` |
| B | 11:05:30 - 12:24:00 | `32ce9dc` | operator's own PowerShell (PID 5104) | intentional stop while flat, for repair |
| C | 12:41:04 - 14:01:00 | `7253640` | Claude background task (PID 20972) | **clean self-termination, exit code 0** |

Phase A ended with no traceback, a flat account and no attempt consumed; the
cause remains unproven and is recorded as such rather than guessed.

## Repairs shipped mid-session

| Commit | Name | Effect |
|---|---|---|
| `df8619f` | LUNA-JSON-ENFORCED | API-enforced JSON; armed startup refuses without it |
| `096dcde` | LUNA-DEGRADED-TELEMETRY | prompt/schema tool-family contract; explicit `degraded_reason` |
| `32ce9dc` | LUNA-TOOL-FAMILY-CONTAINER | deterministic recognised string-to-list; unknown tokens still fail closed |
| `7253640` | SEPARATE-DIRECTION-FROM-ENTRY-ELIGIBILITY | direction/action split; explicit `action_declines_entry` gate |

Full diffs are archived under `git/relevant_diffs/`.

## Final account reconciliation

```
account role      : Trading Combine (simulated venue environment)  [identity REDACTED]
opening balance   : $50,042.96
closing balance   : $50,042.96      delta $0.00
positions         : 0
working orders    : 0
write calls       : 0
candidates        : 0      tokens : 0      entry attempts : 0
fills             : 0      round trips : 0      trade missions used : 0 of 2
authorization     : PROD-20260806, verify() PASS, UNSPENT (does not roll over)
```

Verified with `TopstepXReadOnlySession` (structurally write-incapable) under
account pin + expected-fingerprint enforcement at 14:23:45 ET.

## Scan census

Derived from the archived artifacts, not from prose. Boundary 12:41:00 ET
(commit `7253640`).

| | before repair | after repair |
|---|---|---|
| scans | 106 | 66 |
| sources | llm 101, degraded 3, llm_failed_fallback 2 | llm 66 |
| malformed raw JSON | 2 | **0** |
| conflicted | 88 | 22 |
| neutral | 15 | 30 |
| bearish | 2 | 9 |
| bullish | 1 | 5 |
| directional rate | **3 of 106** | **14 of 66** |

This measures **classification behaviour only**. It is not a market-performance
or profitability result -- no trade occurred.

## Proof levels

| Repair | Unit | Offline replay | Live read-only | Live armed session |
|---|---|---|---|---|
| JSON enforcement | yes | yes | yes | **yes -- 0 malformed in 66** |
| Tool-family container | yes | yes | yes | **yes -- 0 degradations** |
| Degraded telemetry | yes | yes | yes | **no post-repair degraded call occurred** |
| Direction/action split | yes | yes | yes | **yes -- 14 directional stand-downs** |

## Limitations

- No candidate, token, order or fill -- adaptive sizing, attached protection and
  entry/exit reconciliation were **never exercised against a real order**.
- Slippage remains **0/20 reliable observations, 0/10 round trips**; the $2.00
  per-contract reserve is still provisional.
- `degraded_reason` shipped but was never triggered live.
- Phase B stdout was never file-backed (operator console); its scan evidence
  survives in `brain/` and `scans/`.
- Quotes/trades are held in memory by the market runtime and are not persisted
  per scan.
- No chart screenshot was available to this session; `visuals/` is absent rather
  than fabricated.
- 16 QQQ-labelled brain artifacts written today are **test-suite output**
  (`model=None`, `source=deterministic`), not session scans. They are excluded
  from the census and listed in `scans/EXCLUDED_non_session_artifacts.json` so
  their existence is never mistaken for production scans or for retired-instrument
  contamination.

**Today proves safe no-trade operation and a clean lifecycle. It proves nothing
about profitability.**

## Replay modes

1. **HISTORICAL FAITHFUL** -- replay each phase under its own commit
   (A `fc241d9`, B `32ce9dc`, C `7253640`); output should reproduce the archived
   artifacts.
2. **FINAL-CODE COUNTERFACTUAL** -- feed all archived scan inputs through
   `7253640` to ask how the corrected organism would have classified the whole
   session, including the morning.
3. **FUTURE-CODE REGRESSION** -- same immutable inputs through a later commit,
   compared against both baselines. Not run during archival.

Historical result and counterfactual result are distinct and must never be
conflated. The archived artifacts are the historical truth.

## Automated replay status

```
ARCHIVED_NOT_YET_AUTOMATED
```

`src/replay_validation/replay_session.py:replay_session()` exists and implements
recorded-brain replay, but it was built for the QQQ/Alpaca era and has **not**
been proven against an MNQ TopstepX session. The archive emits
`market/replay_convention/20260806_MNQ.json` in that tool's expected shape, and
`REPLAY.md` in the archive specifies the minimum inputs, expected outputs and the
hard read-only constraints. Building the runner was out of scope for archival.

Replay must never construct a write-capable session, mint a token, consume an
attempt, or reach an order endpoint.

## Archive contents

```
manifest.json           schema, session identity, phases, repairs, omissions
SHA256SUMS.txt          integrity manifest over every archived file
REPLAY.md               replay modes + interface specification
git/                    branch, HEAD, history, phase_commit_map, 4 repair diffs
launcher/               phase stdout, process timeline, exit statuses, shutdown
monitors/               read-only watcher logs + the preserved UTC-display defect
market/                 211 session 1m candles, full rolling cache, runtime metadata
scans/                  172 Brain input payloads + digests, ordered
brain/                  172 artifacts: raw responses, parsed, degraded, usage, index
execution/              explicit zero-state per component + redacted authorization
account/                redacted reconciliation
analysis/               scan census (json + md), repair scorecard, limitations
```

Derived 3m/5m/15m timeframes are **not** archived: they rebuild deterministically
from the archived 1m candles via `data_feed.timeframe_builder.build_timeframes`,
and duplicating them would risk drift between the copy and the derivation.

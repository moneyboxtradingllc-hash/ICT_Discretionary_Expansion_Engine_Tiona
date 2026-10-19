# Independent owner-side Stage 5 audit

## Disposition

The submitted `ENGINEERING_COMPLETE` assertion is **not accepted**. Receipt and
integrity were verified separately from engineering acceptance. No finding in
this audit authorizes observation, live cognition, a provider connection, a
venue write, a merge or deployment.

Frozen submission: code `fb20d96a5b4675eb2998e1e269f2b977e23cfa7b`, evidence child
`a41c552e2406413a6798fc31ae583b2bb6b323cf`. Contract: the final Stage 5 engineering
package, especially documents 03, 04, 06, 07, 09, 10 and 13. Corrections are on
the separate local branch `audit/stage5-owner-corrections-20261018`, under ledger
mission `OWNER_AUDIT_01`; the original submission remains intact.

## Independently verified evidence

- Submitted archive SHA-256 `948c2dab1263b66ac12b03f26cb6aac0800728c3f59c1c533d2053953a102015`.
- Manifest SHA-256 `92f0be5d0173383f5a3ff57090fa8af9b8331438133b7ef95c363f62f9d196ce`; all 114 entries match.
- All ten submitted mission receipts, 32 protected sources and 48-entry closure verified.
- Brain `brain:3d9878ad3ff57f1f`; retrieval `retr:0c241bdb8234d1ba`.
- Independent submitted-code focused run: **167 passed, 4 failed**, 171 cases.
  Three failures expose CRLF handling in the ledger parser; one cannot create
  a Windows symlink (WinError 1314). These are not unexplained production failures.
- Sender full-suite JUnit: 8977 passed, 583 skipped, one failed; the failed
  walker assertion independently reproduces under `EXECUTION_ENABLED=false`.
  It passes unset, and an in-memory version of the corrected assertion passes
  in both states. This audit does not mislabel the sender's full run as green.

## Reproduced defects and bounded repairs

These are engineering/provenance findings, not sixteen new trading-policy rules.
Parent reproducers ran against the frozen checkout, with network denied. The
first set had 14 failures and one healthy control; the forming-release and
explicit-UNKNOWN probes each additionally failed on their intended assertions.

| ID | Parent defect | Repair and permanent proof |
|---|---|---|
| A01 | CRLF Git objects lose fenced ledger entries, producing false lineage failures | Accept CRLF framing without changing canonical receipt bytes; ledger negatives remain active |
| A02 | Deleted Brain-call file can be scored as a complete run | Reconcile declared event call counts, persisted calls and manifest counts |
| A03 | Missing prompt artifact is not checked | Verify prompt and every other referenced call artifact |
| A04 | MOCK calls can enter Mode C scoring when a caller supplies mode C | Require per-call origin compatibility before recognition inclusion |
| A05 | An annotation for another session can score this trace | Bind annotation session and corpus to the actual trajectory |
| A06 | Unoffered/unrecorded scheduled ticks can yield COMPLETE | Reconcile scheduled, processed and persisted tick/event counts |
| A07 | Unknown ratified threshold metrics are silently ignored | Reject unknown/duplicate rules; apply implemented rules to the full metric list |
| A08 | Missing cognition becomes a demonstrated entry MISS | Preserve UNPROVEN when judgment was not available |
| A09 | CLI trusts supplied SHA/fingerprint labels | Recompute checkout/tree/dirty diff, canonical closure, protected pins and Brain/retrieval fingerprints before A/B run |
| A10 | CLI ignores schedule_ref, even when its file is absent | Verify sealed schedule bytes, corpus/session bindings and override equivalence; use those actual ticks |
| A11 | MISSING quote policy becomes an invented close-based quote | Honor MISSING/CONSTRUCTED/ARCHIVED explicitly, preserve archived age, expose missing quote evidence |
| A12 | Unsupported sealed-memory policy is silently ignored | Explicitly refuse that adapter until implemented; do not pretend the seed was used |
| A13 | Fake current-model transport records CURRENT_EXTERNAL and attempted external requests | This fake-only build records MOCK and zero external requests; simulated budget tests remain meaningful |
| A14 | Source candle opening time is used as recognition/entry decision time | Score recorded decision/observation time; keep market cutoff as distinct fact identity |
| A15 | Forming/unproven releases enter the settled-candle port | Only expose releases with an actual settlement witness; elapsed time does not fabricate one |
| A16 | Explicit UNKNOWN judgment becomes a directional/entry miss | Preserve unknown judgment as UNPROVEN; no owner policy or acceptance percentage selected |

Additional repairs: the legacy walker test checks restoration of its actual
starting environment. Symlink capability is tested separately, so a platform
skip does not hide the tamper/missing-byte assertions. The offline window port
uses the actual production entrypoint's three window functions, loaded as AST
definitions without executing its dotenv/startup module. Strict close and the
dated exception are tested. No production window rule was reimplemented or changed.

Run evidence now binds its full configuration and realized schedule, records
actual source identity, seals final trace-byte references, and distinguishes
Mode A/B configuration lineage in comparisons. Existing trace fixtures were
updated to provide actual identities and sealed schedules, rather than relying
on previously ignored settings. Raw run digests are never normalized away by
the shipped comparison function.

## Remaining engineering acceptance gaps

These are engineering gaps, not owner-only choices. No fabricated owner input
can close them.

1. **Conditional quote-wake path in the Stage 5 driver remains unproven.**
   `LocalCandlePort` has no production `WakeRegistry`; the driver supports
   PREWARM/SCAN and explicitly refuses QUOTE_WAKE/RELEASE adapters. Existing
   accepted Stage 4 conditional and final-quote tests prove their own graph,
   not that this new replay driver reaches it. Minimum closure: connect the
   existing registry and actual trigger caller, then record both-lane healthy,
   stale/expired and no-new-Brain trajectories through final-quote composition
   using refusing venue doubles. Do not invent another authority layer.
2. **Per-trajectory process isolation remains unproven.** The driver redirects
   directories/environment in the current Python process. This is not the
   contract's fresh allowlisted child process, and process globals such as
   `narrative_brain._PROVIDER_CIRCUIT` survive it. Minimum closure: a real CLI
   child per trajectory plus an activated cross-trajectory contamination test.
3. **Fact/campaign/playbook scoring and audit coverage remain partial.**
   The current scorer primarily compares direction, candidate/plan outcomes
   and exact tool occurrence. It does not yet independently score campaign
   origin/objective, delivery/retracement, invalidation/transfer, full fact
   reconstruction and capture/trigger/final-quote timestamps. Event causal
   refs are empty on the current driver path. Minimum closure: project actual
   post-action producer/consumer outputs, bind causal evidence, and expose
   explicit per-layer missing-evidence cells rather than imply full coverage.
4. **Mode C remains disabled and has no real transport.** This is safe and is
   not a license to call the current Brain. Fake authorization/budget tests
   prove their mechanics only. Any eventual transport needs implementation,
   independent verification and explicit owner model/cost authorization.

## Verification checkpoint

After the repairs: the bounded contracts/ports/ledger/accounting/recorder/walker
checkpoint passed 131 tests, with one explicit symlink capability skip and
three separately selected long tests deselected. The full set of owner probes
passes 18 tests. A later checkpoint over the exact frozen correction commit
must supply the full-suite result; no in-progress or previous-SHA run is a pass.

The separate audit evidence package will record final commands, commit identity,
full-suite outcome, skips and activated controls without editing or erasing any
failed/intermediate run. The original production baseline remains
`cbfaddb5847b57442cf04f62e8c65b889a16f8f8`; all protected source policy is unchanged.

## Owner-reserved decisions

Current discretionary recognition and archive certification remain UNPROVEN.
Stage 4 independent acceptance remains pending. Corpus/admissible exports,
operator archives, sealed owner/delegate truth, scoring rules/N/tolerances and
thresholds, exact future model/price/budget authorization, archive prerequisites
and controlled-observation entry remain reserved under the existing decision
appendix. An engineering pass would not settle these decisions or authorize
trading. No routine repair request is returned to Claude or Maurice.

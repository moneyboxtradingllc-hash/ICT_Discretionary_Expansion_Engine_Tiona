# Stage 4: remaining acceptance items against the existing dependency matrix (frozen source ffe00ae)

This is a record for Maurice's owner-side review, as Codex asked on 2026-10-22. It restarts nothing and opens no new
implementation program.

Source: `docs/recognition_validation/STAGE4_DEPENDENCY_MATRIX.md` (rows S4-01 to S4-12 and T01 to T22) and
`OWNER_DECISIONS_APPENDIX.md` (D01 to D14).

**Evidence check (VERIFIED-RUN).** Every one of the 66 test references in the matrix was resolved against the final
full-suite JUnit at ffe00ae. Each one passed, with none skipped or missing, in the supported-runtime (Linux) JUnit. The operating Mac's
full run of the same source had 0 failures and 0 errors with identical totals (9,116 passed, 583 skipped), and
Codex independently checked the complete case identity sets of both runs. For the class `TestArmGatesTheOrderPath`, all 5 nodes passed. The
per-reference results are in `stage4_matrix_refs_ffe00ae.json`.

**What this does and does not establish.** Green tests establish the bounded engineering claim of each row and nothing
more.
- **Engineering:** no row has an established engineering defect.
- **Owner side:** every row's **owner acceptance is PENDING**.
- **Natural evidence:** where a row is proven only on constructed tapes, natural-session or archive evidence is UNPROVEN.
  Producing it depends on owner input first.

Blocker types:
- **OWNER** is a reserved owner decision or review.
- **OWNER-INPUT then ENG** means the owner must supply data or choose a requirement, after which engineering can run
  the existing checks.
- **NONE** means no remaining item beyond acceptance.

| Row | Required invariant | Engineering state at ffe00ae | Acceptance | Remaining item | Blocker |
|---|---|---|---|---|---|
| S4-01 | Only producer-owned formations publish executable rows | PASS-BOUNDED, PRODUCTION_REACHABLE | PENDING | Review only | OWNER |
| S4-02 | ECU structure flip / MTF carried in the Brain payload | PASS-BOUNDED, PRODUCTION_REACHABLE | PENDING | Review only | OWNER |
| S4-03 | Post-capture P3 release | PASS-BOUNDED, OFFLINE_CONSTRUCTED_REACHABLE | PENDING | Not every ACTIVE bound-premise path is evidenced; no natural tape | OWNER-INPUT then ENG (D01/D04 corpus or archive subset) |
| S4-04 | Leg death is not campaign death | PASS-BOUNDED, OFFLINE_CONSTRUCTED_REACHABLE | PENDING | Natural-session evidence | OWNER-INPUT then ENG (D01/D04) |
| S4-05 | Same-life vs distinct anchor | PASS-BOUNDED, OFFLINE_CONSTRUCTED_REACHABLE (constructed tape on a natural seed) | PENDING | Natural-session evidence | OWNER-INPUT then ENG (D01/D04) |
| S4-06 | Ordinary full graph up to the arm switch | PASS-BOUNDED, PRODUCTION_REACHABLE to the arm switch | PENDING | The armed path is proven only against refusing venue doubles; a live armed path is out of scope | OWNER (D10 controlled observation, separate authorization) |
| S4-07 | Conditional plan, brainless trigger, final quote | PASS-BOUNDED, PRODUCTION_REACHABLE through the actual trigger and runner final quote | PENDING | Review only | OWNER |
| S4-08 | Rolling alignment and missed scans | PASS-BOUNDED, PRODUCTION_REACHABLE | PENDING | The N1 length bound is relative, not a minimum-history guarantee | OWNER (whether a minimum-history guarantee is required; engineering only if it is) |
| S4-09 | History, restart, reset, custody cells | PASS-BOUNDED; bound cells OFFLINE_CONSTRUCTED_REACHABLE | PENDING | Natural restatement and restart evidence. History revision is the bound scope's only protection against restated history; the formation's settled-bar self-revocation is an independent defense | OWNER-INPUT then ENG (D03/D04) |
| S4-10 | Legacy and direct order routes fail closed | PASS-BOUNDED (static inventory over src/ and tools/) | PENDING | No live test, by design | OWNER |
| S4-11 | Source, pin and coverage integrity | SOURCE VERIFIED (LEDGER_VERIFIED: 32 pins, 48 closure entries) | PENDING | Historical archive certification: about 440 archive- or credential-dependent skips, never counted green | OWNER (D04 names the required archive subset) then ENG re-run |
| S4-12 | Source and evidence delivery | CLOSED (owner receipt 2026-10-17) | Closed | None | NONE |

**T01 to T22** (Stage 4 adversarial invariants: forming bar, future leakage, duplicate cutoff, missed scans, prefix
eviction, restatement, restart and serialization, foreign publication, retirement and opposite P3, distinct anchor,
local vs campaign death, scoped transfer, stale Draw, invalid action, stale plan, brainless trigger, final-quote zone,
quote quality, legacy route, disarmed writes, mission reuse, ECU double advance):
- Every cited proof passes at ffe00ae, and there is no established engineering gap.
- Owner acceptance is PENDING for all of them.
- T02, T03, T06 and T07 share S4-09's limit: constructed rather than natural evidence. The blocker is OWNER-INPUT then
  ENG (D01/D03/D04).

## Reserved owner decisions that bear on Stage 4 acceptance

- D01 corpus and sessions; D03 gaps, revisions and unattributed exits; D04 archive certification.
- D10 controlled observation.
- D11 WATCHING/refusal semantics.
- D13 wall-clock wake stamps. The matrix also records `thesis_lifecycle.py:214` `utcnow()` as an observation, not a
  defect.
- The observation source choice (ffe00ae or production cbfaddb).

None of these is an engineering defect. Each needs an owner decision or owner-supplied input.

## Outside the matrix (recorded, not Stage 4 rows)

Production-path functions not reached by any test at ffe00ae are listed by name in `CLOSEOUT_REPORT.md`:
- dead code with no caller;
- live-account methods;
- `_capital_identity`, `_topstep_account`, `_recover_active_path`, `in_decision_window` and `bind_exit_attribution`.

This is UNPROVEN coverage, not an established defect. If the owner wants any of them proven before acceptance, the
proposal is to add targeted tests.

**Conclusion.** No concrete Stage 4 engineering gap is established at ffe00ae. What remains is owner-side:
- acceptance review of the bounded evidence above;
- the decisions D01, D03, D04, D10, D11 and D13;
- archive and corpus input, where natural evidence is wanted.

This record claims no acceptance and grants no live, deploy, merge, arm or trade authority.

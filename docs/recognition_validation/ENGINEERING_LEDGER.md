# Stage 5 engineering ledger

Source-controlled substitute for a child commit SHA that cannot be precomputed
(contract 09). Each mission appends one `ledger-entry` block BEFORE editing,
binding its exact parent commit. The parent of mission N+1 is the last commit
of mission N, so the chain of parents is the chain of accepted children.

`python3 tools/verify_engineering_ledger.py --repo .` recomputes every bound
value from git objects (parent tree, 32 protected sources, the 48-entry Brain
closure parsed from `src/ai_brain/production_model.py`, canonical Brain and
retrieval fingerprints over an extracted parent tree, receipt chain) and fails
if any commit after a parent touches a file outside that entry's declared
scope. Recorded text is never trusted as evidence of itself.

Rules:

- `parent_sha` is a full 40-hex commit; never a symbolic or "current" head.
- `receipt_digest` = SHA-256 of canonical JSON (sorted keys, compact,
  ASCII, no NaN) of the entry without `receipt_digest`.
- `predecessor_receipt_digest` is the previous entry's `receipt_digest`; the
  previous entries must already be committed at this entry's parent.
- `protected_digest` / `closure_digest` are canonical-JSON SHA-256 of the
  CRLF-to-LF file hashes at the parent; the 32 protected hashes must equal
  `baseline/SOURCE_PINS.json` at every parent and in the working tree.
- A closure change after the latest parent requires a
  `closure_change_rationale` on that entry.
- Status labels: VERIFIED-CODE, VERIFIED-RUN, ENGINEERING-E, PROPOSED-P,
  RATIFIED. Nothing here authorizes arming, orders, deployment, merges or
  external model/provider/venue calls.

## M00: baseline and ledger

Parent f5934c015de824779352ee9c4a95400b38a44ed9 (review/reversal-foundation-wip-20261006),
verified in a fresh clone with the contract's `verify_source_baseline.py`
(VERIFIED-RUN: VERIFIED_EXACT_BASELINE, closure 48, protected 32, zero network)
and remote refs (review f5934c0, production feature/latency-1-preauthorized-plans
cbfaddb5847b57442cf04f62e8c65b889a16f8f8, main a1614aed22f45201e5d537013ed261c9bb532c55,
none modified). No production source is changed in M00.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M00",
  "parent_sha": "f5934c015de824779352ee9c4a95400b38a44ed9",
  "parent_tree": "96316d4b3ef8cd1895530cf448b2bf08bc32790f",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "STAGE5 contract 00-13 (package manifest 64fd73860d928e471e91a5a064533e53497f3a61ca3857f651517213dcbc12db)",
    "S00/S01 owner mandate 2026-10-17",
    "13_SECURITY_AND_PRODUCTION_BOUNDARY"
  ],
  "scoped_files": [
    "docs/recognition_validation/*",
    "tools/verify_engineering_ledger.py",
    "tests/test_recognition_ledger.py"
  ],
  "proof_ids": [
    "M00-BASELINE-VERIFIER",
    "M00-LEDGER-VERIFIER-POSITIVE",
    "M00-NEG-WRONG-SOURCE",
    "M00-NEG-ALTERED-PROTECTED",
    "M00-NEG-COPIED-DIGEST",
    "M00-NEG-STALE-LEDGER"
  ],
  "open_proofs": [
    "S4-05 distinct 5m/15m anchor witness UNPROVEN -> M01",
    "S4-09 cold rebuild/restatement/equal revision new process/duplicate cutoff/retirement after capture+trigger/final quote PARTLY VERIFIED -> M01",
    "S4-10 direct gated_submit caller inventory -> M01",
    "S4-11 archive-dependent certification UNPROVEN (owner D04; not closable offline)"
  ],
  "lanes": "ECU (produce_thesis pre-cognition hook) and non-ECU (live_scan.production_scan_cycle.run_narrative_brain alias) both reach participation_authority_bound -> CandidateProducer.produce; no model execution in M00",
  "predecessor_receipt_digest": null,
  "receipt_digest": "473698e2f7eb8f6973ddc13dd6b138d9c304c923a0e531865548503efd61979a"
}
```

M00 exit receipts (VERIFIED-RUN, offline runner: `env -i` allowlist, no .env,
EXECUTION_ENABLED=false, ALLOW_PAPER_ORDERS=false, AI_BRAIN_LLM=false,
TWO_BRAIN_MODE=off, isolated runtime roots, proxy pointed at a closed port):

- `tools/verify_engineering_ledger.py --repo .`: LEDGER_VERIFIED, protected 32,
  canonical fingerprints recomputed at the parent.
- `tests/test_recognition_ledger.py`: 11 passed (wrong source, symbolic parent,
  non-baseline first parent, altered protected source at parent and worktree,
  copied closure/protected/predecessor digests, unsealed edit, stale ledger by
  commit and by uncommitted change, uncommitted predecessor, undeclared closure
  change, and this repository's own ledger).
- Activated controls: 12 verifier mutants, each disabling one check, each
  killed by its named test with the other 10 passing.
- Open proofs carried to M01: S4-05 distinct anchor, S4-09 restart/history
  cross-product, S4-10 gated_submit caller inventory. S4-11 archive-dependent
  certification remains UNPROVEN under owner decision D04.

## M01: remaining Stage 4 dependency closure

Parent is the M00 child. Test-only by declaration; a source defect would
require amending this entry before the change (scope plus closure rationale).

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M01",
  "parent_sha": "6e6286c8d53cec8f7c50627cddb6c7f6249172f4",
  "parent_tree": "0157c2bfb27dc6560b5223ee2c503d59d61661e3",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M01",
    "10 T10/T11-T19",
    "03 S4-05/S4-09/S4-10",
    "S4K O1: PO3 direct-entry provenance-only; no entry-zone/formation-stop/minimum-stop rule",
    "Stage 3 D0=a D1=a roles 5m/15m K=1 D3=B/STRICT D4-D6=a"
  ],
  "scoped_files": [
    "tests/*",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M01-ROUTES-S4-10",
    "M01-DAW-S4-05",
    "M01-HISTORY-S4-09"
  ],
  "test_only": true,
  "predecessor_receipt_digest": "473698e2f7eb8f6973ddc13dd6b138d9c304c923a0e531865548503efd61979a",
  "receipt_digest": "7ad840e1e699adeaabd877833b8bf3923afbfa3764ab6de051ec66853b4cc821"
}
```

M01 progress receipts (VERIFIED-RUN, offline runner as M00):

- S4-10 `tests/test_order_route_inventory.py` (commit 6db3b47): 9 passed with
  `test_legacy_smoke_route_fail_closed.py` 13 total. Entry-capable venue
  writes are exactly 10 indexed call sites (production loop -> session ->
  runner.gated_submit -> runner.submit -> place_order; legacy smoke_wait via
  Lifecycle-gated one_scan; manual release canary and lifecycle smoke; three
  legacy Alpaca paper writers). Production entrypoint static import closure
  (205 files) reaches no manual smoke tool and no paper-order writer. Five
  activated source-text mutants each caught.
- S4-05 `tests/test_po3_distinct_anchor_premise.py`: CONSTRUCTED tape on the
  natural W5 seed. Campaign premise = 15m context life 29538 (born 15:29,
  raid 15:15 after incumbent death 14:23); PO3 formation = 5m active_leg
  life 29518.5 (born 16:19, own raid 16:15, validated 16:29). Both lanes:
  healthy twin CANDIDATE on that exact occurrence 16:39-16:44 (stop 29518.5,
  objective 29505.5); one-bar twin replaces only the 5m life at 16:39 and
  refuses `tool_not_detected` while scope, premise and Lifecycle
  (ACTIVE_DELIVERY, permitted) are identical. Activated controls: identity
  collapse (formation kept alive by the 15m context life) -> replaced twin
  executes, killed; retirement collapse (any same-side life end read as the
  premise's violation) -> healthy premise retired, killed. Observation, not
  a defect: after a retirement the authentic UNBOUND scope returns to the
  ratified D0=a local table, so participation continues under that
  authority (premise status UNKNOWN).
- S4-09 `tests/test_bound_scope_history_custody.py`: duplicate settled cutoff
  and later provider restatement in both lanes, JSON copy of the live
  snapshot, new-process replay; activated controls revision-skip (bound
  scope survives corrected history -> killed; formation independently
  self-revokes on its settled-bar witness) and serialized-view trust
  (real catalog consumer publishes the JSON formation -> killed).
- Filled matrix: `docs/recognition_validation/STAGE4_DEPENDENCY_MATRIX.md`
  (every cited node resolved against the tree).
- M01 focused run (VERIFIED-RUN): 38 passed, 1 warning (stray
  `datetime.utcnow()` in src/ai_brain/thesis_lifecycle.py:214, recorded for
  T32), 859 s; JUnit sha256 36f5678c400f3502041f1facc779892a3ddbc9d5690e0919826ca2b1a2311d82. Test-only mission: the full suite is
  deferred to the M07 final frozen child per contract 09.

## M02: input contracts, corpus/provenance, isolated ports

Parent is the M01 child. Offline package only; production never imports it.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M02",
  "parent_sha": "63d503f9fb8182b19d64552ac8b4bfbcb8d5f62a",
  "parent_tree": "3046f4b222c8df9b9a2f43841a9e68320a5d8c58",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M02",
    "04 components contracts/corpus/ports",
    "05 corpus and provenance",
    "07 schemas and canonical bytes",
    "13 security boundary"
  ],
  "scoped_files": [
    "src/recognition_validation/__init__.py",
    "src/recognition_validation/contracts.py",
    "src/recognition_validation/corpus.py",
    "src/recognition_validation/ports.py",
    "src/recognition_validation/schemas/*",
    "src/recognition_validation/examples/*",
    "tests/test_recognition_contracts.py",
    "tests/test_recognition_corpus_ports.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M02-CONTRACT-NEGATIVES",
    "M02-RELEASE-AVAILABILITY",
    "M02-ARTIFACT-INTEGRITY",
    "M02-PORTS-DENY-BY-DEFAULT",
    "M02-FIXTURE-RECONCILIATION"
  ],
  "closure_note": "new offline package is not imported by production and is outside the Brain closure",
  "predecessor_receipt_digest": "7ad840e1e699adeaabd877833b8bf3923afbfa3764ab6de051ec66853b4cc821",
  "receipt_digest": "24eafdb9478b6e9b3bd357d661a1653bb8c3adeb0ce14b3b69ce2b0ba4bacfd5"
}
```

## M03: current driver and real boundary instrumentation

Parent is the M02 child.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M03",
  "parent_sha": "f3d8a9796401c02c4f852956dce8deae0a269657",
  "parent_tree": "560f91ad677e705bf3c3d3d6e7bc84f8f94f2063",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M03",
    "04 driver/brain_gateway/recorder",
    "08 call graph",
    "13 security boundary",
    "10 T16/T20/T22/T27"
  ],
  "scoped_files": [
    "src/recognition_validation/driver.py",
    "src/recognition_validation/brain_gateway.py",
    "src/recognition_validation/recorder.py",
    "tests/test_recognition_current_path.py",
    "tests/test_recognition_recorder_gateway.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M03-ACTUAL-LOOP-BOTH-LANES",
    "M03-WRONG-TARGET-CONTROL",
    "M03-RECORDER-DURABILITY",
    "M03-GATEWAY-SEAM"
  ],
  "seam_note": "provider client object replaced only for the run; production _call_llm builds and checks every request",
  "predecessor_receipt_digest": "24eafdb9478b6e9b3bd357d661a1653bb8c3adeb0ce14b3b69ce2b0ba4bacfd5",
  "receipt_digest": "8e3c8b963eb719e0309db24220a91cdfd0d41012e597b42ec75084b1cef2608e"
}
```

M03 receipts (VERIFIED-RUN): `test_recognition_current_path.py` 3 passed
(both lanes reach the real disarmed ProductionLoop through LocalCandlePort
and DecisionClock; the distinct-anchor candidate is QUALIFIED_CANDIDATE_
OBSERVED 16:39-16:44 with zero venue writes, network attempts, tokens and
attempts; every tick recorded once in a verified chain; transported request
bytes match the recorded artifacts; wrong-patch-target control shows no
transported request and production's degraded path).
`test_recognition_recorder_gateway.py` 8 passed.

## M04: Mode B determinism and Mode A exact historical association

Parent is the M03 child.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M04",
  "parent_sha": "e046cbf1dbd50e433189d87b098bdd1da23779a6",
  "parent_tree": "36ebef08b3470259f8f455516afafd4735237817",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M04",
    "04 brain_gateway/compare",
    "05 Mode A/B semantics",
    "10 T23/T24/T25/T26/T30",
    "13 security boundary"
  ],
  "scoped_files": [
    "src/recognition_validation/compare.py",
    "src/recognition_validation/driver.py",
    "src/recognition_validation/brain_gateway.py",
    "tests/test_recognition_replay_modes.py",
    "tests/test_recognition_recorder_gateway.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M04-MODE-B-SEMANTIC-DETERMINISM",
    "M04-PROJECTION-CONTROLS",
    "M04-MODE-A-EXACT-ASSOCIATION",
    "M04-MODE-A-ATTACKS",
    "M04-DECISION-CLOCK-PROVIDER-STAMPS"
  ],
  "projection": "semantic-v1: alpha-rename process-random ids only (uuid4 custody/draw lineage); content ids, prices, times, outcomes compared raw",
  "predecessor_receipt_digest": "8e3c8b963eb719e0309db24220a91cdfd0d41012e597b42ec75084b1cef2608e",
  "receipt_digest": "2ab8ca6cee05f5fed3860bc8bc5b95f94da8837c01620a1385cc6d28f33ee8f7"
}
```

M04 receipts (VERIFIED-RUN): `test_recognition_replay_modes.py` 9 passed,
`test_recognition_recorder_gateway.py` 8 passed; M00-M03 recognition and
distinct-anchor tests 80 passed after the change.

- Two Mode B runs of the CONSTRUCTED distinct-anchor session from fresh roots
  have identical semantic-v1 event and call traces. Their raw call traces
  differ, as expected, because each run has its own process lineage.
- semantic-v1 renames only identities that production mints from a
  per-process uuid4 (VERIFIED-CODE):
  - `CampaignScopeCustody._lineage`, which feeds the campaign ids,
    premise_candidate_id and proposal ids (market_data/campaign_scope.py:203,
    145, 425, 512);
  - the `CampaignDrawTruth` namespace and episode (record_id,
    campaign_episode_id).
  The premise catalog's row order (sorted by premise_candidate_id) and its
  digest (which covers custody_lineage) are re-derived. Content-derived ids
  (proof_id, tip_digest, sweep, occurrence and formation ids), prices, times
  and outcomes are compared raw. Controls show that a moved level or a changed
  formation id still diverges.
- Mode A association is exact (cutoff, same-cutoff ordinal, purpose). If an
  archived output cites the archive process's premise ids, they are rebound
  to the current ids only when the archived input equals the transported
  input under semantic-v1. That rebinding is disclosed per call, together
  with the archived raw sha256. With rebinding, Mode A reproduces the Mode B
  semantic event trace, including the formation.
- Mode A attacks, each disclosed or refused:
  - a missing record becomes MISSING cognition, never a neighbour;
  - a duplicate or foreign-contract association refuses at load;
  - a reused record refuses;
  - a changed archived input is disclosed as
    HISTORICAL_OUTPUT_ON_CURRENT_INPUTS;
  - a foreign served model is refused by production's own check.
- Observation T32 (VERIFIED-CODE, owner-visible, production unchanged):
  narrative_brain.py:577-593 and 659 stamp provider calls with the wall clock.
  The stamp re-enters the next Brain input as
  campaign_draw_context.brain_lineage.provider_call_completed_at. Inside the
  gateway seam only, those two names read the decision clock; outside the
  seam production is restored and untouched.

## M05: disabled Mode C, owner authority, hard budgets

Parent is the M04 child.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M05",
  "parent_sha": "cecdfe796a144e9023625dc949fac03a49624749",
  "parent_tree": "04d2b1763c68afb624419ea86946533a3303a762",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M05",
    "06 C budget and transport contract",
    "13 security boundary",
    "10 model-authority rows"
  ],
  "scoped_files": [
    "src/recognition_validation/model_authority.py",
    "src/recognition_validation/brain_gateway.py",
    "tests/test_recognition_model_authority.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M05-DISABLED-DEFAULT",
    "M05-PRECONDITIONS-BEFORE-TRANSPORT",
    "M05-BUDGET-STATE-MACHINE",
    "M05-LEDGER-RESTART",
    "M05-FAKE-TRAJECTORY-BOTH-LANES",
    "M05-DRY-RUN-PLAN"
  ],
  "external_requests": 0,
  "predecessor_receipt_digest": "2ab8ca6cee05f5fed3860bc8bc5b95f94da8837c01620a1385cc6d28f33ee8f7",
  "receipt_digest": "57527198cd4fdb70c0e2a901075a3885ccb613122c504c8372559f18ee133010"
}
```

M05 receipts (VERIFIED-RUN): `test_recognition_model_authority.py` 28 passed,
`test_recognition_recorder_gateway.py` 8 passed. After the change, the
replay-mode, current-path and contract tests still pass (55 passed). External
requests made: 0. Only fake transports exist; the repository holds no key.

- Mode C is disabled by default. The disabled example document refuses with
  CURRENT_MODEL_CALLS_DISABLED even when enabling-looking environment
  variables are set, because no CLI flag or environment variable is read.
- Each of these preconditions refuses before the fake transport is reached,
  with zero reservations. The test is parametrized over 17 cases:
  - owner receipt: missing, or forged with the same byte length (digest
    checked);
  - stale source SHA, corpus, annotation set or Brain fingerprint;
  - expired or not-yet-valid authorization, judged on the real UTC clock and
    never on the market decision clock;
  - pricing: missing, unapproved or tampered;
  - tampered authorization seal, refused when the authority is built;
  - no output cap;
  - a different parameter profile;
  - a different endpoint;
  - an SDK retry not disabled;
  - an input-token bound over the cap.
- Observation (VERIFIED-CODE, production unchanged): production's request
  (narrative_brain.py `_call_llm`) sets no output-token cap, so its worst-case
  cost is unbounded. External mode therefore needs an evaluation-parameter
  profile that adds `max_completion_tokens`. That profile has its own digest,
  bound in the authorization's parameter_digest. It is not a production
  parameter change, and the Brain fingerprint is unchanged.
- Budget accounting:
  - Every attempt is reserved at the worst case
    `(max_in * uncached_input_rate + max_out * output_rate) / rate_unit`
    in a durable fsynced JSONL ledger before transport. This includes the
    primary, each repair purpose and each transport retry.
  - Unknown usage, and usage above the reservation, are charged the full
    reservation. An overrun halts the run.
  - The request, repair, retry and cost caps each stop the next request
    before transport.
  - When the ledger is reopened, a reservation that was never settled is
    ORPHANED_CHARGED. A cancellation charges zero. A duplicate id or a
    settle of an unknown reservation refuses.
  - A recorder failure refuses the next request, in every mode, before
    transport.
- Whole-trajectory tests run in both lanes through the real loop with a
  fake provider:
  - every call is CURRENT_EXTERNAL, attempted, has a unique reservation and
    matching usage;
  - the bytes sent equal production's transported input;
  - a foreign served model is refused by production as
    provider_model_mismatch, and the attempt is still counted and charged.
- The dry run prints a finite plan: ticks x lanes x trajectories x 4 calls
  per scan (primary plus three repair sites, narrative_brain.py
  1029/1046/1099/1148) x (1 + retries), capped by the request cap. Its
  maximum cost is the planned bound x the per-request bound, never above
  max_cost_usd. With the disabled authorization the plan is 0 requests,
  with blockers listed.
- No full suite is needed here: no shared adapter or production source was
  touched. The full fresh suite runs at M07.

## M06: scoring join, result/report, operator CLI, stray-clock audit

Parent is the M05 child.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M06",
  "parent_sha": "5032345090c96d3b920dde65355a4fb287deb15b",
  "parent_tree": "bd291f7a3eed9133a341752543063e65a1d08e57",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M06",
    "07 annotation/scoring/result",
    "10 T27/T28/T29/T32",
    "11 owner decisions",
    "13 security boundary"
  ],
  "scoped_files": [
    "src/recognition_validation/scoring.py",
    "src/recognition_validation/report.py",
    "src/recognition_validation/__main__.py",
    "src/recognition_validation/clock_audit.py",
    "src/recognition_validation/driver.py",
    "tests/test_recognition_scoring_cli.py",
    "tests/test_recognition_clock_audit.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M06-EXACT-CELLS-REAL-TRACE",
    "M06-SEPARATE-NOTRADE-BLOCKED-UNKNOWN",
    "M06-T29-AVAILABILITY",
    "M06-T28-TRUTH-FROZEN",
    "M06-MODE-B-NOT-CURRENT",
    "M06-DENOMINATORS-RAW-IDENTITY",
    "M06-CLI-EXIT-CODES",
    "M06-T27-INCOMPLETE",
    "M06-T32-CLOCK-AUDIT"
  ],
  "predecessor_receipt_digest": "57527198cd4fdb70c0e2a901075a3885ccb613122c504c8372559f18ee133010",
  "receipt_digest": "8f93ad3596301dc4495c3a4a1eb4fca2dd13a54a6f025eb394af160e38c60d4c"
}
```

M06 receipts (VERIFIED-RUN): `test_recognition_scoring_cli.py` 9 passed and
`test_recognition_clock_audit.py` 4 passed. All twelve Stage 4/5 modules
together gave 154 passed and 1 failed in 23m20s. The one failure is the
real-repository ledger check, run while the M06 driver change was still
uncommitted. The verifier correctly reported
STALE_LEDGER_OUT_OF_SCOPE_CHANGE (M05 does not cover driver.py). The check
was re-run after this entry was committed.

- `scoring.py` joins one chain-verified raw trace with at most one
  annotation set, after execution. It reports cells per layer:
  - FACT: the exact production occurrence identity.
  - RECOGNITION: the direction of each complete primary call.
  - TIMING.
  - REFUSAL: HIT, CORRECT_REFUSAL, FALSE_POSITIVE, MISS (CLEAR labels only),
    HONEST_UNKNOWN, AMBIGUOUS_UNSCORED, RECOGNIZED_BLOCKED_BY_<blocker>,
    UNKNOWN_TRUTH_DIRECTIONAL_OBSERVATION and UNPROVEN.
- Every metric carries a numerator, a denominator, an excluded count and an
  UNPROVEN count. A zero denominator gives UNSCORED. PASS/FAIL appears only
  under an OWNER_RATIFIED plan, on sealed owner truth, in Mode C. Mode A/B
  cells are excluded from current-recognition denominators.
- On the real CONSTRUCTED trace, the known labels give exactly:
  - entry-window HIT, with EXACT_OCCURRENCE equal to the distinct-anchor
    formation identity and the first candidate at 16:39;
  - quiet window CORRECT_REFUSAL;
  - unclear window HONEST_UNKNOWN;
  - recognition_hits 0/0 UNSCORED (3 excluded);
  - diagnostic hits 2/2.
- T28 refusals: SELF_AUTHORED_OWNER_ANNOTATION, OUTCOME_AS_TRUTH (a label
  citing this run's own evidence), ANNOTATION_SEALED_AFTER_OUTPUTS,
  SEAL_MISMATCH after mutation, NONOWNER_ANNOTATION_NOT_CERTIFIABLE and
  CORPUS_SEALED_AFTER_OUTPUTS. These are judged on real time from the new
  RUN_MANIFEST.json written by driver.run_offline.
- T29:
  - A tolerance only extends a target forward.
  - A judgment before earliest availability is EARLY_BEFORE_AVAILABILITY,
    never a hit.
  - An entry that early is EARLY_POSITIVE_AUTHORITY, an invariant failure.
  - Activated control: a tolerant-lookahead label turns the same judgment
    into a hit.
- Mode B with a ratified plan and sealed truth still yields UNPROVEN. A
  forged ELIGIBLE result for Mode B is refused (MOCK_COGNITION_LAUNDERING).
  A semantic-projected trace cannot be scored, because it has no verifiable
  chain.
- The CLI `python -m recognition_validation` provides validate, plan, run
  (A/B, and C dry-run), compare and report. Exit codes are 0/2/3/4/5 as in
  contract 07.
  - A live Mode C run exits 2 (EXTERNAL_TRANSPORT_UNAVAILABLE).
  - Output-root reuse exits 2.
  - A divergent compare exits 4.
  - A report without annotations exits 3.
  - T27: a recording error, a missing artifact or a missing manifest exits
    5 with ENGINEERING_INCOMPLETE, and never produces a passing result.
- T32 (VERIFIED-CODE/RUN):
  - STRAY_CLOCK_INVENTORY.json lists 162 production wall-clock sites
    (192 calls), and the test fails on any change to it.
  - A short Mode B run observed zero production `time.time` readers outside
    the decision-clock seam. The positive control proves the observer
    detects one.
  - `datetime.now` cannot be intercepted, so it is covered statically,
    including thesis_lifecycle `_archive_path`/`update` and narrative_brain
    `_call_llm`.
- OWNER_DECISIONS_APPENDIX.md fills D01-D10 with the safe default kept, what
  stays UNPROVEN and the exact future commands.

## M07: final integration and freeze

Parent is the M06 child. This child changes documentation only and is the
frozen final review candidate. Before freezing, checks on the M06 child
gave VERIFIED-RUN: `compileall -q src tests` OK, and `git diff --check`
from baseline f5934c0 OK (54 files, +12704, no deletions). The fresh-clone
full suite, the collection inventory, the CLI samples and the hashes for
this exact SHA travel in the single final package (contract 12). Committing
them would change the SHA they describe.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M07",
  "parent_sha": "90d8b56965d9002b39f2c3782957ea08766e1acd",
  "parent_tree": "2ee0be6a3e3038629f7628b797c9d3131ed2fd84",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M07",
    "12 final delivery template",
    "13 security boundary",
    "10 adversarial matrix"
  ],
  "scoped_files": [
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M07-FRESH-CLONE-FULL-SUITE",
    "M07-COLLECTION-INVENTORY",
    "M07-CLI-SAMPLES",
    "M07-FINAL-PACKAGE"
  ],
  "freeze_note": "docs-only child; it is the frozen final review candidate; suite and package evidence travel in the final package",
  "predecessor_receipt_digest": "8f93ad3596301dc4495c3a4a1eb4fca2dd13a54a6f025eb394af160e38c60d4c",
  "receipt_digest": "c0a9d936a87402495d2dd5c76ea47e75bc27cec7f5761da3d661317aa014f0cd"
}
```

## M07R: repair the regression found by the final suite

Parent is the M07 child 63e194f. The fresh-clone full suite of 63e194f
(VERIFIED-RUN, 1h50m) gave 8976 passed, 583 skipped and 2 failed. Both
failures were analysed against baseline f5934c0:

- `test_production_fvg_stop_ownership.py::...::test_downstream_occurrence_read_only_revalidates_conditional_plan_identity`
  is a REGRESSION from this program. It passes on f5934c0. The test is a
  source-content theorem: only three production files may name
  `selected_tool_occurrence_id`, and the M03 offline driver names it once,
  to copy the id into its event record. Repair: a scoped literal update that
  admits the harness file and pins two facts. The field appears in it exactly
  once, in that recording line. No production module mentions
  `recognition_validation`. Activated control: a planted production import of
  the harness fails on that importer assertion.
- `test_replay2_session_walker.py::TestWalker::test_end_to_end_synthetic_walk_and_forced_safety`
  is NOT this program's change. It fails identically on f5934c0 under the
  contract-13 forced environment (`EXECUTION_ENABLED=false`). It passes on
  both f5934c0 and the child once that variable is unset. The test assumes
  the variable is absent: after the run it expects the default "true", where
  the right check is the pre-run value. It is left unchanged and disclosed,
  with a proposed patch, in the final package.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M07R",
  "parent_sha": "63e194f2a528d3614c6be851cac0229a37380922",
  "parent_tree": "726410a04602b6ae8a2977aced3515f85e81fdfa",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "09 M07 (repair discovered regressions)",
    "13 scoped test literal update",
    "full suite 63e194f JUnit"
  ],
  "scoped_files": [
    "tests/test_production_fvg_stop_ownership.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M07R-OCCURRENCE-THEOREM-HARNESS-RECORD-ONLY"
  ],
  "regression": "63e194f full suite: test_downstream_occurrence_read_only_revalidates_conditional_plan_identity failed because src/recognition_validation/driver.py (M03) names the field; passes on baseline f5934c0",
  "predecessor_receipt_digest": "c0a9d936a87402495d2dd5c76ea47e75bc27cec7f5761da3d661317aa014f0cd",
  "receipt_digest": "cf7bf4c2ec953a9630cf43af4f21f772dc4e53a2304b0b41a97354f9923d807d"
}
```

## M07P: final package (evidence only)

Parent is the M07R child fb20d96, the reviewed final code. This child adds
only `docs/recognition_validation/final_package/`:

- the single portable archive `STAGE5_FINAL_fb20d96.tar.xz` and its sha256;
- the archive's MANIFEST_SHA256 (one line per payload file);
- FINAL_REPORT.md (contract 12), copied out of the archive so it can be
  read on GitHub.

The archive holds no credentials, account identifiers, operator archives or
runtime state. The fresh-clone suite of fb20d96 gave 8977 passed, 583
skipped and 1 failed (the disclosed pre-existing environmental walker
test). Its log and JUnit are inside the archive.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "M07P",
  "parent_sha": "fb20d96a5b4675eb2998e1e269f2b977e23cfa7b",
  "parent_tree": "b81d0fe680e426a040abbf4cb2e92bb46ac16ed4",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "12 final delivery (one indexed portable archive + MANIFEST_SHA256)",
    "13 artifact hygiene"
  ],
  "scoped_files": [
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "M07P-FINAL-PACKAGE-fb20d96"
  ],
  "package_note": "evidence-only child; reviewed code is fb20d96; archive sha256 948c2dab1263b66ac12b03f26cb6aac0800728c3f59c1c533d2053953a102015; manifest sha256 92f0be5d0173383f5a3ff57090fa8af9b8331438133b7ef95c363f62f9d196ce",
  "predecessor_receipt_digest": "cf7bf4c2ec953a9630cf43af4f21f772dc4e53a2304b0b41a97354f9923d807d",
  "receipt_digest": "95c84beb83fe3888d02cdf5ecc96a551e8f3ab28c11894bb873629ce07c334e0"
}
```

## Owner independent audit corrections

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "OWNER_AUDIT_01",
  "parent_sha": "a41c552e2406413a6798fc31ae583b2bb6b323cf",
  "parent_tree": "9296494e3cd8dee59c4df89316d1c274202d9c39",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "Owner final independent audit and subsequent corrections on our side",
    "Contract 04/07/09/10/13: truthful provenance, trace completeness, source/schedule binding; no trading policy change"
  ],
  "scoped_files": [
    "src/recognition_validation/*.py",
    "tests/test_recognition*.py",
    "tests/test_replay2_session_walker.py",
    "tools/verify_engineering_ledger.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "OWNER-AUDIT-PARENT-REPRODUCERS",
    "OWNER-AUDIT-REGRESSIONS",
    "OWNER-AUDIT-FINAL-SUITE"
  ],
  "predecessor_receipt_digest": "95c84beb83fe3888d02cdf5ecc96a551e8f3ab28c11894bb873629ce07c334e0",
  "receipt_digest": "d080d8d8c4b8b0be4a7da37e19fd70e7a4acae94ad24dc45095ae5f3559e7ae1"
}
```

## GAP_M1: required scoring-rule coverage

Engineering GO of 2026-10-19 (gap closure, mission 1 of 4). Parent is the
owner-audit correction commit 51eb3e1 (tree 883d8c5e), fetched from
`audit/stage5-owner-corrections-20261018` and verified; work continues on the
new branch `engineering/stage5-gap-closure-20261019`.

Parent defect (VERIFIED-RUN, the audit's own reproducer on 51eb3e1): a
ratified `recognition_hits` rule with denominator 0 got no `threshold_ref`,
dropped out of the all-pass aggregation, and `build_result` returned
ELIGIBLE_FOR_OWNER_REVIEW. The healthy failure control returned FAIL.

Repair: `scoring._threshold` keeps a zero-denominator required metric bound
to its rule as UNPROVEN. `report.rule_coverage` emits one obligation per
ratified rule per required session/trajectory (PASS, FAIL, or UNPROVEN with a
reason: ZERO_DENOMINATOR, REQUIRED_TRAJECTORY_NOT_SCORED,
NOT_CURRENT_RECOGNITION_ELIGIBLE, RULE_METRIC_ABSENT). Eligibility needs a
declared, complete, all-PASS coverage. Any scored rule failure is FAIL, and
missing coverage never becomes FAIL. The required set comes from the corpus's
EVALUATION sessions. Only an OWNER_RATIFIED corpus's own EXCLUDED session
with recorded reasons leaves it; no exclusion, threshold, N or denominator
policy is chosen here. `result/v2` carries `rule_coverage`, and the contract
validator recomputes obligation completeness and status. `result/v1` stays
readable but may not claim eligibility. Unknown/duplicate rules stay hard
refusals. No production source is touched.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "GAP_M1",
  "parent_sha": "51eb3e1c209d205891a75a1181ad2f42dd65333d",
  "parent_tree": "883d8c5e01a7091226b591db29612922441af26c",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "GO 2026-10-19 Mission 1: required scoring-rule coverage",
    "Contract 07 scoring/result; owner audit residual (zero-denominator required rule)"
  ],
  "scoped_files": [
    "src/recognition_validation/*",
    "tests/test_recognition*.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "GAP-M1-PARENT-REPRODUCER",
    "GAP-M1-RULE-COVERAGE-TESTS",
    "GAP-M1-ACTIVATED-MUTANTS"
  ],
  "predecessor_receipt_digest": "d080d8d8c4b8b0be4a7da37e19fd70e7a4acae94ad24dc45095ae5f3559e7ae1",
  "receipt_digest": "7c33aa389048a188902e9e78ed4564dd0b47dfcc252be6d0ff5172541c2e50bb"
}
```

## GAP_M2: fresh child process per trajectory

Engineering GO of 2026-10-19, mission 2 of 4. Parent: GAP_M1 exit commit
82937f0 (tree 64734e29).

Parent counterexample (VERIFIED-RUN, the audit probe on 51eb3e1):
`narrative_brain._open_hard_quota_circuit(...)` before `driver.isolation(...)`
leaves the provider circuit open inside the "new" trajectory. Environment and
CWD redirection is not a process.

Repair: `recognition_validation.child`. The CLI `run` never drives a trajectory
in its own interpreter. For each trajectory it does the following:

- It writes a sealed request: corpus path and digest, session, ticks with
  decision times, run document, a responder reference with its sha256, and
  the expected source identity.
- It starts `python -I` with an environment built from an allowlist only:
  scratch HOME/TMPDIR/cache, disarmed flags, refused proxy, and per-root
  runtime directories.

Before any runtime-authority import, the child refuses each of these:

- a non-allowlisted or credential-like environment name;
- a preloaded runtime module;
- a non-fresh runtime root;
- a non-EMPTY memory policy (MEMORY_SEED_ADAPTER_UNAVAILABLE);
- a source/fingerprint mismatch;
- an altered responder.

It installs the network deny for its whole lifetime, records the cold provider
state, and runs the actual driver. Its receipt (pid, ppid, `-I`, environment
names, cold state, source identity, request digest) is sealed into
RUN_MANIFEST.json. The parent writes CHILD_STATUS.json with the exit, timeout
and stderr digest (redacted tail). The report keeps a crashed, timed-out,
unbound or missing-status child INCOMPLETE, and keeps any in-process
trajectory at PROCESS_ISOLATION_UNPROVEN. `compare` discloses process
identities, run digests and source identity side by side.

Finding (protected source unchanged, for independent review):
`src/data_feed/__init__.py` calls `load_dotenv()` at import. That module is on
the production scan-cycle import path (`live_scan.production_scan_cycle` ->
`data_feed`), and python-dotenv searches upward from that module for a
`.env`. Any importer of the scan cycle, including an offline replay, therefore
loads an operator `.env` into its environment. In a trajectory child the load
is a recorded no-op (`dotenv_refused`), and the environment is re-checked
against the allowlist after the run. Proposed narrow fix: move the
`load_dotenv()` call to the launcher entrypoint (`tools/topstepx_production_session.py`,
which already owns startup) and leave library modules import-pure. The same
pattern appears in `src/live_scan/scan_loop.py` and `src/main.py`.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "GAP_M2",
  "parent_sha": "82937f0f7433b83bb0ad135580fdc1e23efa4537",
  "parent_tree": "64734e2988d19b9363ec32d088b9575d61a6ddc0",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "GO 2026-10-19 Mission 2: fresh child process per trajectory",
    "Contract 09 isolation; owner audit gap 2 (provider circuit survives env/CWD redirection)"
  ],
  "scoped_files": [
    "src/recognition_validation/*",
    "tests/test_recognition*.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "GAP-M2-PARENT-COUNTEREXAMPLE",
    "GAP-M2-PROCESS-ISOLATION-TESTS",
    "GAP-M2-ACTIVATED-MUTANTS"
  ],
  "predecessor_receipt_digest": "7c33aa389048a188902e9e78ed4564dd0b47dfcc252be6d0ff5172541c2e50bb",
  "receipt_digest": "7e8a0357880ac22ce573670fc81609701a6841a6cb7f738c003797ad1adc2a56"
}
```

## GAP_M3: quote wake, conditional trigger and final quote in both lanes

Engineering GO of 2026-10-19, mission 3 of 4. Parent: GAP_M2 exit commit
2c063d0.

Parent reproducer (VERIFIED-RUN on 2c063d0, CONSTRUCTED distinct-anchor tape,
MOCK Brain authoring a `watching` plan):

- `driver.TICK_KINDS` is `("PREWARM", "SCAN")`, so a QUOTE_WAKE tick is
  refused with TICK_ADAPTER_UNAVAILABLE.
- The candle port has no wake registry and the loop is built with
  `armed=False`.
- So every scan from 16:30 to 16:35 refuses the authored plan with
  `conditional_plan_watch_unavailable` and makes a fresh Brain call.
  `handle_pending_conditional_wake` never fires, and the runner's final-quote
  authentication is unreachable.

Repair (recognition_validation only; production sources unchanged):

- The driver now holds the actual `WakeRegistry`, and feeds it the way the
  launcher and the live quote provider do:
  - bootstrap before the first non-PREWARM tick, then publish it on the candle
    port;
  - `note_bar_closed` -> `consume_structure` -> `refresh_from_bars` on every
    new release;
  - `on_quote` for every delivered sided quote. Its original capture time and
    age are kept, and a historical message is delivered once.
- Each tick routes like one launcher loop iteration:
  `handle_pending_conditional_wake()` first, `scan_once()` otherwise.
- Tick kinds are now SCAN, QUOTE_WAKE, RELEASE and PREWARM.
- A run declares `venue_lane`:
  - DISARMED (the default);
  - REFUSING_VENUE_DOUBLE (Mode A/B only, refused for Mode C in both the run
    contract and the driver). This lane turns the loop's arm switch ON against
    the refusing venue double and a synthetic replay-local authorization.
- The report counts a venue write as VENUE_WRITE_OFFLINE only in the DISARMED
  lane.
- A corpus may carry an explicit sided quote stream and versioned bar
  revisions. A QUOTE_WAKE without a quote stream is refused.
- Every non-PREWARM tick writes an `offline_tick_trace/v1` artifact, referenced
  from its event. It holds:
  - the quote;
  - the route;
  - registry facts, including `interaction_pending_after_route`;
  - the plan before and after (identities, zone, structural invalidation,
    authority payload digest);
  - new production plan events;
  - changed final-quote economics;
  - mission tokens and attempts;
  - venue writes;
  - Brain calls.

Acceptance (tests/test_recognition_quote_wake_trigger.py). The plan publishes
at 16:30: bearish order block 29513.25-29517.5, 3m protected-high stop 29518.5
(INV_PH_3m_3). A sided quote at 16:32:30 wakes it, and it triggers with zero
Brain calls.

- DISARMED: QUALIFIED_CANDIDATE_OBSERVED, no venue write, no token.
- REFUSING_VENUE_DOUBLE: `validate_final_quote` passes (EXECUTE_AS_AUTHORIZED
  at the bid 29514.0, quote age 0). One place_order is refused (SUBMIT_FAILED,
  boundary PRE_VENUE), with one token and one attempt.
- Both ECU modes are covered.
- One CLI run takes the refusing lane in a fresh child.

Attacks. Each has a healthy reachable control from the same tape, differs from
it in one input, and has its decisive cause read from the tick trace and plan
events:

| Attack | Decisive outcome |
|---|---|
| expired plan (135 s lifetime) | `conditional_plan_expired` |
| stale quote (age 10 s > 5 s) | `conditional_plan_trigger_no_longer_true` |
| quote for another contract | MISSING `quote_contract_mismatch`; no wake; plan keeps waiting |
| duplicate wake after a trigger | QUOTE_WAKE_NO_INTERACTION; tokens stay 1 |
| normal (non-plan) wake | routes a fresh scan; the live plan suppresses the Brain; the plan still triggers later |
| objective reached before the trigger | `conditional_plan_review_required` |
| provider revision of the 16:31 bar (v2 at 16:32:10) | `campaign_lifecycle_refused`; history revision moves only in the revised world |
| restart after the authoring minute | no plan to trigger; the wake requests fresh cognition (one Brain call) |
| completed 3m close beyond the stop, both lanes | `invalidation_id_unknown` (control: 3m close below the stop is accepted) |
| Brain contract fingerprint changed at revalidation, both lanes | refused at plan revalidation |
| campaign Draw episode changed at the trigger | refused (Draw or Lifecycle) |
| final quote moved outside the zone between trigger and capture | `validate_final_quote` refusal, no venue write |

Semantics note (not a defect): the protected-swing stop is judged on completed
closes of its own timeframe. A 1m close above 29518.5 inside an incomplete 3m
bar does not retire the plan.

Declared limits:

- One offered tick holds one historical quote. A quote that arrives between
  the trigger scan and the runner's final capture is modelled by emitting it
  on the hub at capture time.
- An interaction raised by the route itself (for example
  `conditional_plan_armed_inside` at publication) is spent by the next offered
  tick, not by the current one. The trace records it as
  `interaction_pending_after_route`.
- The Brain fingerprint and Draw attacks are in-process instrumentation of
  values production reads at revalidation. They are not natural tapes.

Activated mutants: the m3_mutants harness in the return package. Mutants:

- route without the pending-wake call;
- quotes that skip the registry;
- the armed loop in every lane;
- no Mode C lane guard;
- a quote wake without a stream;
- a report that ignores the lane.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "GAP_M3",
  "parent_sha": "2c063d072ca43a126188a075fac646afb5599264",
  "parent_tree": "c68250ed794482887873d741fbd08115666ee8eb",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "GO 2026-10-19 Mission 3: integrated quote-wake / conditional trigger / final quote in both lanes",
    "Contract 05 ports and driver; owner audit gap 3 (no quote-wake or trigger adapter)"
  ],
  "scoped_files": [
    "src/recognition_validation/*",
    "tests/test_recognition*.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "GAP-M3-PARENT-REPRODUCER",
    "GAP-M3-QUOTE-WAKE-TRIGGER-TESTS",
    "GAP-M3-ACTIVATED-MUTANTS"
  ],
  "predecessor_receipt_digest": "7e8a0357880ac22ce573670fc81609701a6841a6cb7f738c003797ad1adc2a56",
  "receipt_digest": "8f2416056f8a205018b98a0b5706869ea1707d2be4161974f5c0a6b21094601f"
}
```

## GAP_M4: six-layer fact, campaign, causal and timing projection and scoring

Engineering GO of 2026-10-19, mission 4 of 4. Parent: GAP_M3 exit commit
a68c89a.

Parent reproducer (VERIFIED-RUN on a68c89a, the HEALTHY mission 3 world):

- Two FICTIONAL labels are identical except for their campaign, delivery and
  tool truth (one is right, the other has delivery_state TRANSFER_CONFIRMED,
  another playbook and another objective).
- Both get identical confusion cells and metrics, and no layer cells exist.
- Events carry at most one evidence ref (the tick trace).
- So the annotation's campaign origin and objective, delivery state,
  invalidation and transfer evidence, playbook and tool fields are never
  compared with what the producers produced.

Repair (recognition_validation only; production sources unchanged):

- `layers.project` runs at every non-PREWARM tick. It writes a
  `layer_projection/v1` artifact bound to the event, read only from the
  actual producer outputs. Each layer below names its source binding:
  - MARKET_FACTS: the snapshot's settled 1m bar and its sealed release
    (version, availability, settlement).
  - CAMPAIGN: `scan_participation_authority` (direction, objective,
    authority, Draw history revision), the path origin, and the Brain's own
    direction.
  - DELIVERY: the campaign Lifecycle state and the path owner, status,
    transfer flags and last invalidation. It is mapped to the annotation
    vocabulary from production's Lifecycle and ownership change only. Local
    opposing price movement never becomes a reversal.
  - TOOL: playbook, tool family, exact occurrence, zone, direction and
    structural invalidation, from the candidate or the live plan.
  - COMPOSITION: outcome, route, whether a candidate or plan is present,
    Brain calls, final-quote economics.
  - TIMING: market open, settled cutoff, latest availability, decision,
    plan capture, trigger and final-quote times, each kept separate.
- An output the producers did not produce is ABSENT, with its reason.
- The artifact holds no process-random identity. Process lineage, candidate
  and plan ids stay on the event, where `compare` alpha-renames them, and the
  per-process campaign episode id is not copied at all.
- `layers.chronology` (per projection) and `layers.sequence` (across ticks)
  report:
  - FACT_AFTER_DECISION, FUTURE_EVIDENCE, FORMING_BAR_AS_FACT and
    FACT_NOT_SEALED (checked against the sealed corpus stream);
  - TRIGGER_BEFORE_CAPTURE, FINAL_QUOTE_BEFORE_TRIGGER and
    FINAL_QUOTE_OUTSIDE_ZONE;
  - duplicate cognition cutoffs, missed scans with their catch-up,
    revisions and restarts.
- `score_trace` adds the chronology and duplicate-cutoff codes to the trace's
  invariant violations, so the result is FAIL.
- `layers.score_label` gives six cells per label. They are compared only with
  sealed admissible truth: the sealed corpus for MARKET_FACTS, and the
  annotation fields (with their typed evidence references) for the other
  layers.
  - An absent or UNKNOWN annotation field is UNSCORED.
  - Absent or unusable evidence is UNPROVEN, with its reason (for example
    EVIDENCE_ABSENT, SEALED_CORPUS_NOT_SUPPLIED, PREFIX_EVICTED, STALE_DRAW,
    CONTRADICTORY_JUDGMENT, LIFECYCLE_AUTHORITY_UNKNOWN, MISSED_SCAN_CATCH_UP,
    RESTART_IN_WINDOW or MATCH_ON_SUPERSEDED_REVISION).
  - Neither UNSCORED nor UNPROVEN is a MISS.
  - A no-trade is UNSCORED (NO_TRADE_NEVER_WRONG).
  - No win rate or economics is truth.
- Six metrics (`layer_market_facts` ... `layer_timing`) join METRIC_NAMES, so
  a ratified rule can require any layer. Mission 1 rule coverage then keeps it
  as an obligation (PASS, FAIL, or UNPROVEN ZERO_DENOMINATOR).
- result/v2 session summaries carry `layer_cells`, `layer_table`,
  `layer_findings` and `layer_projection_count`. The report renders the
  per-layer table, cells and findings. The CLI report passes the sealed
  corpus stream to the scorer.

Acceptance (tests/test_recognition_layer_projection.py):

- Healthy, both venue lanes and both ECU modes: every non-PREWARM tick is
  projected with all six layers from the actual producers. There are no
  chronology findings against the sealed corpus. Every clock stays separate:
  settled cutoff 16:32:00 < trigger and decision 16:32:30, and capture
  16:30:00 < trigger. The refusing lane composes the final quote at 29514.0
  inside the zone.
- A healthy label scores all six layers SCORED and in agreement. The 16:31
  to 16:32 rally into the order block, against the bearish campaign, stays a
  retracement.
- The healthy trace round-trips the result schema, the CLI report and the
  markdown. A forged cell state is refused. A label over prewarm-only minutes
  is UNPROVEN in every layer.
- Each layer is mutated independently, against a healthy control, and
  detected:
  - facts not sealed, look-ahead cutoff, forming bar, replayed future
    evidence;
  - campaign direction, objective, origin, stale Draw, prefix eviction;
  - false reversal and missed transfer;
  - tool occurrence and occurrence ownership;
  - trigger before capture and final quote outside the zone;
  - early and late recognition, duplicate cutoffs, restart.
- Natural producer variants:
  - The provider revision is projected (version 2 of the 16:31 bar and
    history revision 0 -> 1), with no chronology findings, and a match
    before the revision is UNPROVEN MATCH_ON_SUPERSEDED_REVISION.
  - Dropping the 16:24 to 16:27 scans is found as a 4-bar gap with catch-up
    at 16:28, and the target inside it is UNPROVEN MISSED_SCAN_CATCH_UP.
  - The healthy trace scored against the revised corpus fails end to end
    with FACT_NOT_SEALED.
- Mission 1 is rerun on layer outputs. Required layer rules are COMPLETE
  (PASS) on the healthy cells, INCOMPLETE (UNPROVEN ZERO_DENOMINATOR) on
  absent evidence, and FAIL on a scored disagreement. Each result validates.

Determinism repair (found while closing this mission):

- The first frozen focused run of the mission (9c5bf03, preserved in the
  return package) had 4 failures:
  - Three were determinism failures. Mode A/B repeats and the clean restart
    compare differed in evidence digests, because the projection artifact
    carried process lineage, the Draw campaign episode id, and candidate and
    plan ids.
  - One was the occurrence-reader theorem in
    tests/test_production_fvg_stop_ownership.py.
- Fixed:
  - The projection carries no process-random identity.
  - The mission 3 tick trace's plan authority payload, and its digest, drop
    the per-process identities `compare.INPUT_TOKEN_KEYS` already names
    (campaign episode, Draw record and scope campaign ids).
  - A refused venue write is recorded in the tick trace without its
    per-submission random `customTag`, with a flag that it was present. The
    manifest keeps the raw write.
  - The offline WakeRegistry reads the injected decision clock.
- Stray-clock finding (protected source unchanged, for independent review):
  `WakeRegistry._observed_at` (the inventoried T32 site in
  STRAY_CLOCK_INVENTORY.json) stamps an interaction raised without
  `observed_at` with the wall clock. This affects
  `publish_conditional_watch` when it publishes while already inside, and the
  armed-inside branch of `refresh`. Offline, that wall time reached the wake
  telemetry and the plan's trigger event. It is telemetry only: plan expiry
  and revalidation read the loop clock. Proposed narrow fix: the loop passes
  `observed_at=self.clock()` to `publish_conditional_watch`, and the launcher
  passes its observation time to `refresh_from_bars`.
- Scoped literal update: the occurrence-reader theorem now lists
  `src/recognition_validation/layers.py` as a second record-only harness
  reader, pinned to exactly one read in the TOOL projection, as M07R did for
  driver.py.
- Two determinism tests now pass: repeated watching trajectories in the
  refusing lane compare identical, and every wake carries the session date.

Declared limits:

- Restart, duplicate-cutoff, stale-Draw, prefix-eviction and false-reversal
  cases are mutations of copies of the real projections, not natural tapes.
  One trajectory has one process lineage, so a natural restart is two
  trajectories.
- MARKET_FACTS is verified only when the scorer receives the sealed corpus.
  Without it the cell is UNPROVEN.

Finding for owner review: the existing REFUSAL cell (contract 07
`classify_episode`) does not know `expected_action` WATCHING. A published
plan is classified as an entry, so it scores FALSE_POSITIVE against a
WATCHING label. The COMPOSITION layer scores WATCHING correctly. Changing the
REFUSAL cell is a scoring-semantics decision reserved to the owner, and it is
left unchanged here.

Activated mutants (the m4_mutants harness in the return package):

- local opposing movement read as reversal;
- early judgment not flagged;
- no-trade scored wrong;
- facts not checked against the sealed corpus;
- missed scans hidden;
- prefix eviction ignored;
- scorer drops projection violations;
- driver writes no projection.

```json ledger-entry
{
  "schema": "engineering_ledger_entry/v1",
  "mission_id": "GAP_M4",
  "parent_sha": "a68c89af3340d3ee63b79dd2618c74f181d532b9",
  "parent_tree": "2dd4838eacacb4348bc589688fff9d9982384e23",
  "parent_tracked_status": "",
  "brain_fingerprint": "brain:3d9878ad3ff57f1f",
  "retrieval_fingerprint": "retr:0c241bdb8234d1ba",
  "closure_count": 48,
  "closure_digest": "d4dbe6a3ea029c4b59f33a1deba3d7c65ccb877e33afa4aed317b68256a15cf1",
  "protected_count": 32,
  "protected_digest": "79988f0ea3e84e15e34485a8510e78efc667f6e274d41fcde5d6e3c0307ab79a",
  "policy_refs": [
    "GO 2026-10-19 Mission 4: fact/campaign/causal/timing projection and scoring in six layers",
    "Contract 07 scoring/result; owner audit gap 4 (annotation truth fields never compared with producers)"
  ],
  "scoped_files": [
    "src/recognition_validation/*",
    "tests/test_recognition*.py",
    "tests/test_production_fvg_stop_ownership.py",
    "docs/recognition_validation/*"
  ],
  "proof_ids": [
    "GAP-M4-PARENT-REPRODUCER",
    "GAP-M4-LAYER-PROJECTION-TESTS",
    "GAP-M4-ACTIVATED-MUTANTS",
    "GAP-M4-DETERMINISM-REPAIR"
  ],
  "predecessor_receipt_digest": "8f2416056f8a205018b98a0b5706869ea1707d2be4161974f5c0a6b21094601f",
  "receipt_digest": "720e059ceb7ef1ba5a283a8274a9472be492fe4401ce3c2689d1c74dea86b263"
}
```

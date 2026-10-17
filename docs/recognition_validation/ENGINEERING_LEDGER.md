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

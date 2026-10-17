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

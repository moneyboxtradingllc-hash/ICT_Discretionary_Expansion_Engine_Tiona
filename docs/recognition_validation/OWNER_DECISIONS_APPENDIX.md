# Owner-reserved decisions (filled contract 11 appendix)

This appendix asks for no daily supervision. Each row covers four things:

- what the engineering does now (VERIFIED-RUN where tested);
- the safe default it keeps;
- what stays UNPROVEN until the owner acts;
- the exact input and command that would complete it later.

Nothing here is an owner decision. Silence or elapsed time never counts as
one. In every command below, `$OUT` is a fresh, empty, isolated directory.
The commands refuse to reuse an output directory.

## Decision table

### D01: corpus and sessions

- **Built now:** `corpus.repository_fixture_inventory` lists every tracked
  fixture with its original-byte digest. `build_constructed_corpus` seals
  CONSTRUCTED tapes. Sessions are never curated from candidate wins. A
  corpus sealed after outputs exist is refused
  (CORPUS_SEALED_AFTER_OUTPUTS).
- **Still UNPROVEN:** benchmark eligibility.
- **Owner input and command:** a ratified `corpus/v1` with
  `selection_state=OWNER_RATIFIED`, `owner_decision_ref` and a seal. Check it
  with `python -m recognition_validation validate --corpus corpus.json`.

### D02: operator evidence export

- **Built now:** `corpus/v1` accepts an explicit read-only exported bundle,
  with every artifact verified by its original bytes. No private Mac,
  account, credential or provider access exists or is used.
- **Still UNPROVEN:** histories that were never exported.
- **Owner input and command:** a sanitized bars/releases/quotes/calls bundle
  with exporter provenance and digests. Load it with `validate --corpus`,
  then `plan`.

### D03: gaps, revisions and unattributed exits

- **Built now:** layers are reason-coded PARTIAL or UNPROVEN
  (`corpus.admissibility`). Nothing is deleted silently. Unseen revisions
  are never inferred.
- **Still UNPROVEN:** the admission rule.
- **Owner input and command:** the admission choice, recorded in the
  corpus's `inclusion`/`exclusion_reasons`.

### D04: archive certification

- **Built now:** the skipped/uncollected inventory is kept per node; see
  the M07 collection inventory in the final package. There is no blanket
  waiver.
- **Still UNPROVEN:** historical archive certification. Stage 4 independent
  owner acceptance is PENDING.
- **Owner input and command:** the owner names the required archive subset.
  Re-run the explicit collection command listed in the final package.

### D05: replay and model evidence

- **Built now:** Mode A (exact association, semantic-v1 rebinding
  disclosed) and Mode B (scripted, deterministic) run on the real loop in
  both lanes. Mode C is fake-transport only. Real requests: 0.
- **Still UNPROVEN:** current discretionary recognition. A and B can never
  certify it.
- **Owner input and command:** a future sealed `model_authorization/v1`
  (OWNER_AUTHORIZED) and a real transport. Neither exists in this build: a
  live `run --mode C` exits 2 (EXTERNAL_TRANSPORT_UNAVAILABLE).

### D06: exact contract and per-call identity

- **Built now:** per-call `brain_call/v1` records fingerprints
  brain:3d9878ad3ff57f1f and retr:0c241bdb8234d1ba, the requested and
  served model, provider ids and usage. Historical calls with no
  fingerprint keep it null and give a reason.
- **Still UNPROVEN:** authorization of the future evaluation build and
  model.
- **Owner input and command:** an authorization binding the exact SHA,
  fingerprints, model, endpoint and parameter profile
  (`EvaluationParameters`).

### D07: annotation ownership

- **Built now:** a DRAFT template and a FICTIONAL example.
  `scoring.admit_annotation` refuses:
  - an engineering-authored OWNER or delegate annotation
    (SELF_AUTHORED_OWNER_ANNOTATION);
  - labels that cite run outputs (OUTCOME_AS_TRUTH);
  - a post-output seal (ANNOTATION_SEALED_AFTER_OUTPUTS);
  - mutation after sealing (SEAL_MISMATCH).
- **Still UNPROVEN:** cognition scoring. No Claude-authored label is
  attributed to Maurice.
- **Owner input and command:** a SEALED `annotation/v1` by OWNER or
  AUTHORIZED_DELEGATE with `authorization_ref`. Score it with
  `report --run $RUN --annotations a.json --corpus corpus.json --out $OUT`.

### D08: scoring tolerance and UNKNOWN rule

- **Built now:** a sealed scoring plan is consumed only when
  OWNER_RATIFIED. A tolerance can only extend a target forward. A judgment
  before `earliest_available_utc` is never a hit, and an entry that early is
  a violation (EARLY_POSITIVE_AUTHORITY).
- **Still UNPROVEN:** there is no adopted tolerance (no ±5 min) and no
  UNKNOWN-as-PASS rule.
- **Owner input and command:** a `scoring/v1` with
  `state=OWNER_RATIFIED`, `tolerance_seconds` and `unknown_scoring_rule`.

### D09: thresholds and N

- **Built now:** whole-trajectory runs, denominators and the
  excluded/unproven counts. The dry-run budget planner prints a finite
  maximum.
- **Still UNPROVEN:** there is no threshold, N, win rate or recognition
  percentage, and no Stage 5 cognition PASS.
- **Owner input and command:** the ratified `thresholds[]` and
  `trajectory_count`. Re-run `run --mode C --dry-run` for the cost bound.

### D10: controlled observation

- **Built now:** an inventory only. Monitoring, kill/stand-down,
  reconciliation, budgets and rollback are listed as later prerequisites.
- **Still UNAUTHORIZED:** controlled observation, deployment, arming and
  trading.
- **Owner input and command:** a separate operating contract, outside
  Stage 5.

## Executable future sequence (offline, no credentials)

```
python -m recognition_validation validate --corpus corpus.json --annotations annotations.json --scoring scoring.json --run run.json
python -m recognition_validation plan --corpus corpus.json --out $OUT/plan --prewarm-until <warmup_end>
python -m recognition_validation run --mode B --run run-B.json --corpus corpus.json --script mode_b_script.py --out $OUT/B1
python -m recognition_validation run --mode B --run run-B.json --corpus corpus.json --script mode_b_script.py --out $OUT/B2
python -m recognition_validation compare --left $OUT/B1 --right $OUT/B2 --projection semantic-v1
python -m recognition_validation run --mode A --run run-A.json --corpus corpus.json --records historical_records.json --out $OUT/A1
python -m recognition_validation report --run $OUT/B1 --corpus corpus.json --annotations annotations.json --scoring scoring.json --out $OUT/report
python -m recognition_validation run --mode C --dry-run --run run-C.json --corpus corpus.json --authorization authorization.json --pricing pricing.json --max-completion-tokens <cap> --out $OUT/C-dry
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Command completed. This does not mean recognition passed. |
| 2 | Invalid contract, or an unauthorized request. |
| 3 | Missing prerequisite, or an UNPROVEN input. |
| 4 | Invariant or determinism failure. |
| 5 | Infrastructure or recording error, or recorded evidence that is missing or altered. |

## Future ratification receipt

The receipt has to bind every field of contract 11's "Proposed future
ratification receipt". In this build those fields are spread across the
sealed documents:

- `model_authorization/v1`: SHA, fingerprints, model, endpoint, parameter
  digest, corpus, annotation and schedule digests, caps, pricing digest,
  expiry and owner receipt bytes.
- `scoring/v1`: thresholds, tolerance and the UNKNOWN rule.
- `corpus/v1`: partitions and the selection decision.

When a bound field is absent, only the activity that depends on it fails
closed. A receipt is evidence of a human decision. It is never minted by
engineering.

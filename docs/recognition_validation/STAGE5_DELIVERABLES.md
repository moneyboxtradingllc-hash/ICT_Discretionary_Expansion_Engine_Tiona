# Stage 5 deliverables (index)

Every path below is committed on review/reversal-foundation-wip-20261006.
The proofs behind each entry are the receipts in ENGINEERING_LEDGER.md,
missions M00 to M06. The final fresh-clone suite, the samples and the
hashes travel in the single final package. They are not committed here,
because committing them would change the SHA they describe.

## Package `src/recognition_validation/`

| Module | Responsibility |
|---|---|
| `contracts.py` | Strict JSON loading: duplicate keys, NaN and naive times are refused. Also: the 2020-12 subset validator, per-kind semantics (annotation, scoring, run, release, brain_call, event, result, model_authorization, schedule, pricing), canonical digests and seals, cross-document binding and artifact verification. |
| `corpus.py` | `release/v1` streams with availability, revisions and settlement. Also: the sealed `corpus/v1` builder for CONSTRUCTED tapes, admissibility per layer, and `repository_fixture_inventory`. |
| `ports.py` | DecisionClock (market time; never runs backwards). LocalCandlePort and LocalQuotePort, which release only bars available by decision time. NetworkGuard, which denies sockets. A venue that refuses every write. The real UTC clock, used only for authorization. |
| `driver.py` | The real disarmed `ProductionLoop` driven offline, one tick per minute, in both ECU lanes. `run_offline` writes a whole-session trajectory and RUN_MANIFEST.json. |
| `recorder.py` | Append-only, fsynced, digest-chained `event/v1` and `brain_call/v1` records, plus content-addressed artifacts. Reusing an output root is refused. |
| `brain_gateway.py` | The single provider seam. It replaces only the SDK client object; production builds, checks and repairs every request. It implements Mode B `ScriptedResponder`, Mode A `HistoricalResponder` (exact association, with semantic-v1 rebinding disclosed per call) and Mode C `CurrentModelResponder` (fake transport only). A recorder failure stops the next request. Provider stamps read the decision clock. |
| `compare.py` | `semantic-v1` projection: bijective alpha-renaming of uuid4-minted process identities only. Raw and semantic hashes, and the first divergence. |
| `model_authority.py` | Owner authority (sealed receipt bytes, identity, real-UTC expiry, sealed approved pricing, evaluation output-cap profile). Durable worst-case reservation ledger with restart and orphan accounting. Dry-run planner. |
| `scoring.py` | Post-execution join of a raw verified trace with a sealed annotation. Layer cells, denominators and inclusion mask. Refusals for truth-freezing and availability violations. |
| `report.py` | `result/v1` assembly, with recognition UNPROVEN unless ratified Mode C, plus the markdown report. |
| `clock_audit.py` | T32 static wall-clock inventory and the run-time `time.time` observer. |
| `__main__.py` | The CLI: `validate`, `plan`, `run --mode A/B` (C only as `--dry-run`), `compare`, `report`. Exit codes 0, 2, 3, 4, 5. |

Schemas (`schemas/`, contract package versions): annotation/v1,
brain_call/v1, corpus/v1, event/v1, model_authorization/v1, pricing/v1,
release/v1, result/v1, run/v1, schedule/v1 and scoring/v1. `examples/`
holds the FICTIONAL and DISABLED examples from the contract.

## Tests

| Module | What it proves |
|---|---|
| `test_recognition_contracts.py`, `test_recognition_corpus_ports.py` | M02: contract laws and ports. |
| `test_recognition_current_path.py`, `test_recognition_recorder_gateway.py` | M03: the actual loop in both lanes, the wrong-target control, recorder durability and the seam. |
| `test_recognition_replay_modes.py` | M04: Mode B determinism from fresh roots, the projection controls (T30), and Mode A association and attacks (T23/T24). |
| `test_recognition_model_authority.py` | M05: T25/T26, with every refusal before the fake transport, plus the ledger, restart, whole-trajectory fake provider (both lanes) and dry run. |
| `test_recognition_scoring_cli.py` | M06: T27/T28/T29, the exact cells on the real trace, and CLI exit codes. |
| `test_recognition_clock_audit.py` | T32. |
| `test_recognition_ledger.py` with `tools/verify_engineering_ledger.py` | M00: receipt chain, lineage, pins, closure, fingerprints and scope. |
| `test_po3_distinct_anchor_premise.py`, `test_bound_scope_history_custody.py`, `test_order_route_inventory.py` | M01: Stage 4 S4-05, S4-09 and S4-10. |

## Status vocabulary for the final package

- Stage 4 internal: per STAGE4_DEPENDENCY_MATRIX.md. S4-11 archive
  certification is owner-reserved (D04).
- Stage 4 independent owner acceptance: PENDING.
- Stage 5 engineering: the M07 verdict, from the fresh suite on the exact
  final SHA.
- Current Brain recognition: UNPROVEN. No authorized Mode C run exists, and
  Mode A/B cannot certify it.
- Historical archive certification: UNPROVEN.
- Controlled observation and production: NOT AUTHORIZED.
- External model/provider/venue requests made: 0.

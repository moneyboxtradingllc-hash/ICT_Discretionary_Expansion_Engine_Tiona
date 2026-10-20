# Bounded owner-side A/B audit, 2026-10-20

Parent source: `c962a3db256eb76b7b66f9fc158f6f6f1bf01bbb`, tree `dd7cb762d772e2a2bffa38242f93982bf7ae105b`.
Submitted evidence-only child: `976d0c1efbfe22de8e9fe0cf4eba82f5038292a9`.
All 451 submitted archive manifest entries were independently verified; the original evidence is preserved.

## A: confirmed evidence-binding defect

Actual reachable path: CLI `cmd_report` -> `report.read_manifest` -> `scoring.score_trace`
(event chains, calls and artifact references verified) -> `child.verify_child_status` ->
`report.build_result(process_problems=...)` -> result JSON and Markdown.

On the exact parent, deleting/replacing CHILD_EXIT or changing its request/completion identity
does not affect report completion. Editing the manifest and recomputing its own self-seal
also passes, although the current bytes differ from the parent-observed manifest_sha256.
These attacks retained COMPLETE / READY_FOR_OWNER_REVIEW on copies of the actual submitted
CONSTRUCTED producer trace. An untouched control passes. A wrong self-seal and the existing
status request/PID defenses already refuse, so those defenses are credited rather than
misreported as defects.

Minimal repair: read the current exit receipt; require its content to equal the parent's
stored snapshot, its schema/request/completion/exit identity to denote a completed matching
child, and the current manifest bytes to match the parent's digest. The manifest argument
must also equal the on-disk object. Verify child receipt ppid against the parent's recorded
PID, alongside the existing distinct-child check. Malformed/missing evidence is incomplete.
The parent writer no longer marks RUN_INCOMPLETE complete solely because its process exited 0.
Exit JSON formatting alone may vary: the stored snapshot binds content, not whitespace.

This is relational evidence integrity, not a signed external attestation. An actor able to
rewrite every receipt, trace and parent digest is outside this checksum trust model. No new
credential, signing system, authority layer or historical evidence was introduced.

## B: semantic decision required; diagnostic scope clarified

The six-layer scorer expressly comments that TIMING is the first lawful matching Draw
direction. It does not consult the Brain-call record or require a tool opportunity. Its
ON_TIME can coexist with contradictory/missing Brain direction or a missing/wrong tool.
This is independently reproduced, including through the actual chain-verified scorer on
the returned brainless 16:31-16:33 interval: direction timing ON_TIME, Brain recognition
unavailable and first_recognition_utc null. A wrong occurrence is separately rejected by
TOOL; actual early judgment has the existing early timing indication. Those reachable
separate defenses mean this is not proof that mocked or missing cognition gained actual
current-Brain certification.

Stable output meanings, without selecting a new trading/scoring policy:

- `layer_timing` and six-layer TIMING ON_TIME/LATE measure **CAMPAIGN_DIRECTION_ONLY**.
  Each cell's source_binding now says explicitly “not Brain or opportunity recognition”.
- Session limitations repeat that scope in result JSON and the existing Markdown rendering.
- `confusion_cells` RECOGNITION and episode `first_recognition_utc` read complete primary
  Brain judgment records. These measure directional judgment, not proof of an eligible tool.
- TOOL, exact occurrence and COMPOSITION are independent opportunity/mechanical evidence.
  Missing cognition, missing records and an absent opportunity remain distinct categories.
- No numbers, denominators, metric names, threshold rules, opportunity policy or no-new-Brain
  conditional trigger semantics were changed. Existing schema versions stay readable.

Maurice retains any choice of a combined discretionary opportunity-recognition timing
criterion and its acceptance thresholds. Campaign-direction timing alone is not evidence
of that composite. The audit does not invent such a criterion or turn missing evidence
into a pass/failure. Mode A/B and fake transport still cannot certify current cognition.

## Proof and final verification

`tests/test_recognition_owner_ab.py` carries parent-failing actual CLI tampering checks,
healthy controls, a verification-bypass mutant, parent completion-writer controls, seven
direction/Brain/opportunity/availability timing situations, and JSON/Markdown scope checks.
The separate consolidated audit artifact records the final frozen commit, exact changed
files, before/after actual returned-trace reproductions, activated negative controls,
focused and full isolated-suite outcomes, uncollected/skipped inventory, and protected-source
verification. An intermediate failure is preserved, never substituted for final proof.

No production/Brain constitution, risk, economics, execution source or Stage 3/4 selections
are changed. No push, merge, deployment, arming, live credentials, provider/model call or
order is part of this audit. Stage 4 independent acceptance, current recognition, archive
certification and controlled observation remain subject to their existing evidence/owner gates.

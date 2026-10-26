# Participation-refusal telemetry (candidate_decision.v2)

Observational only. Nothing here grants, withholds or changes participation; no
participation, risk or execution module reads these fields
(`tests/test_participation_refusal_telemetry.py::test_no_participation_module_reads_the_telemetry`).

## Cause → code → schema → reader

| Parent cause (7b5218a) | Final code | Record field | Reader |
|---|---|---|---|
| `_record_decision` received `scan.snapshot.campaign_lifecycle` but persisted only `detail` text | `ProductionLoop._record_decision` → `attach_participation_evidence` | `campaign_lifecycle_assessment` (every v2 record); `participation_refusal.lifecycle_*` | `reconcile`, `refusal_problems`, `tools/topstepx_session_outcome_report.py` |
| `build_record` whitelist (`blank_trace`) drops `campaign_lifecycle_state/refusal` | unchanged whitelist; producer trace summarized separately | `producer_execution.trace_lifecycle_state/refusal` (current scan only) | same |
| `campaign_lifecycle_refused` → `UNCLASSIFIED` | `_REASON_TO_DISPOSITION["campaign_lifecycle_refused"] = PARTICIPATION_REFUSED` | `final_disposition` | `reconcile` (accounted only when `refusal_problems == []`) |
| refusing gate not distinguishable (loop binding vs producer) | `refusal=exc` passed from both NoCandidate handlers; gate from `NoCandidate.decision_trace` + current-scan marker | `participation_refusal.gate`, `gate_basis`, `downstream.producer` | same |

## `participation_refusal.v1` (only for `campaign_lifecycle_refused`)

- `code`, `gate` (`PRODUCER_LIFECYCLE_GATE` | `LOOP_PARTICIPATION_BINDING` | null), `gate_basis`
- `observed_gate_reason` (exact `NoCandidate.detail`), `observed_gate_reason_source`
- `diagnostic_reference` — a pointer to the gate function, explicitly NOT an observation
- `lifecycle_status`, `lifecycle_state`, `lifecycle_reason` (the assessment's own fields, never derived from a state label), `participation_permitted`, `authorized_direction`, `narrative_control_state`, `narrative_phase`, `campaign_episode_id`, `objective_identity`
- `identity` {scan_id, scan_count, contract, session_id, settled_cutoff}
- `draw` (bounded `scan.campaign_draw_authority`), `current_acceptance` (AVAILABLE | ABSENT `no_acceptance_published_this_scan` | UNKNOWN), `scope_proposal` (bounded `snapshot.campaign_scope_proposal_outcome` | ABSENT)
- `intent` {authored: pre-hold `authored_action`/`narrative_direction`/`pre_hold_output_digest` from the existing `authored_market_read` envelope, or UNKNOWN (absent, other contract, other cutoff); consumed: post-guard action/direction}
- `downstream` {stages_after_gate: NOT_REACHED, producer: EXECUTED_REFUSED_AT_LIFECYCLE | NOT_REACHED | UNKNOWN}
- `consistency_problems` — any disagreement between the refusal, the producer trace and the assessment

Strings ≤200 chars, lists ≤8, depth ≤2; a capture error yields a typed UNKNOWN and never raises.

## Reconciliation

- v1 (`candidate_decision.v1`) rows keep their original semantics exactly; parent journals are never rewritten.
- `PARTICIPATION_REFUSED` is accounted only for a v2 record with a known gate, observed reason, matching identity, a recognized Lifecycle state with a reason (or the producer's own `current_campaign_lifecycle_assessment_unavailable`), and no consistency problems.
- Identity is complete and belongs to the enclosing record (owner audit of 14c996c):
  - `scan_id`, `contract` and `session_id` are required and equal the record's own;
  - `settled_cutoff` is required, is a strict canonical instant (`market_data.object_identity.canonical_instant`), and equals the record's `timestamp_et`, which the loop writes from the same scan's settled `market_data_timestamp`. The scan-id clock (one minute later) is never used.
- Every duplicated Lifecycle field equals the SAME record's `campaign_lifecycle_assessment`. Those fields are status, state, reason, permission, authorized direction, control state, phase, episode and objective.
  - A producer gate's `campaign_lifecycle_refused:<STATE>` label names that state.
  - `campaign_lifecycle_direction_mismatch` and a loop-binding refusal require a permissive assessment; `ACTIVE_DELIVERY` is valid for both.
  - A missing or malformed assessment is incomplete, except the internally consistent assessment-unavailable refusal.
- Optional supporting evidence (Draw, acceptance, scope, authored intent) stays typed UNKNOWN/ABSENT and is not required. This detects inconsistency; it does not authenticate an archive that was coherently rewritten.
- A v1 row reclassified by `tools/topstepx_reclassify_decision_audit.py` (a separate copy that keeps `original_final_disposition`) becomes `PARTICIPATION_REFUSED` but stays incomplete: `legacy_record_lacks_participation_refusal_evidence`.
- A v2 record whose stored disposition contradicts its own reason is `contradictory`; unknown reasons stay `UNCLASSIFIED`.

Doctrine reconciliation (successor chronology, protected-high ownership, proof vocabulary) and
natural-model recognition remain unproven by this patch. Production remains disarmed.

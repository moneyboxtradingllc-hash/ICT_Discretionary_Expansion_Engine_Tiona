# Stage 4 internal dependency matrix (filled)

Contract 03 rows with current executable proof. Status vocabulary:
PASS-BOUNDED (the stated claim only), UNPROVEN, OWNER-RESERVED. Reachability:
PRODUCTION_REACHABLE (actual ProductionLoop / ProductionScanCycle callers),
OFFLINE_CONSTRUCTED_REACHABLE (real producers on a constructed tape),
DEFENSE_ONLY (a guard behind an earlier refusal), UNREACHED. Stage 4 owner
acceptance remains PENDING; nothing here is a trading-readiness statement.

| ID | State | Current proof (test nodes) | Reachability and limits |
|---|---|---|---|
| S4-01 formation publication (O4) | PASS-BOUNDED | test_formation_view_publication.py; test_po3_execution_identity.py::test_copied_restored_stale_and_forged_authority_cannot_publish_executable_row; test_bound_scope_history_custody.py::test_json_copy_of_the_live_snapshot_carries_no_custody (+ serialized-trust control) | PRODUCTION_REACHABLE via ProductionScanCycle; JSON copy refused at the real catalog consumer |
| S4-02 ECU flip/MTF (O3) | PASS-BOUNDED | test_ecu_structure_flip_payload.py (both nodes) | PRODUCTION_REACHABLE; Stage 5 driver must record the actual transport (M03) |
| S4-03 post-capture P3 | PASS-BOUNDED | test_po3_post_capture_release.py (both nodes) | OFFLINE_CONSTRUCTED_REACHABLE; not every ACTIVE bound-premise path |
| S4-04 leg vs campaign death | PASS-BOUNDED | test_po3_post_settlement_death.py | OFFLINE_CONSTRUCTED_REACHABLE |
| S4-05 same-life vs distinct anchor | PASS-BOUNDED (both) | same-life: test_po3_anchor_replacement_revocation.py; distinct: test_po3_distinct_anchor_premise.py (both lanes, identity-collapse and retirement-collapse controls) | OFFLINE_CONSTRUCTED_REACHABLE (CONSTRUCTED tape on the natural W5 seed). Premise 15m context 29538, formation 5m active_leg 29518.5; refusal at the PO3 tool gate with scope/premise/Lifecycle identical |
| S4-06 ordinary full graph | PASS-BOUNDED | test_po3_full_graph_production_loop.py (4 nodes); test_production_scan_loop.py::TestArmGatesTheOrderPath | PRODUCTION_REACHABLE to the arm switch; armed path only against refusing venue doubles |
| S4-07 conditional/no-Brain/final quote | PASS-BOUNDED | test_conditional_plan_authority.py; test_pre_authorized_conditional_plan.py; test_latency1_final_quote_zone.py; test_po3_participation_binding.py; test_conditional_plan_across_alignment_step.py | PRODUCTION_REACHABLE through the actual loop trigger and runner final quote |
| S4-08 rolling alignment / missed scans | PASS-BOUNDED | test_rolling_window_prefix_eviction.py; test_aligned_rolling_window_loop.py | PRODUCTION_REACHABLE; N1 length bound is relative, not a minimum-history guarantee |
| S4-09 history/restart/reset/custody | PASS-BOUNDED (cells below) | unbound/same-life cells: test_campaign_draw_temporal_authority.py::test_same_cutoff_recognition_cannot_promote_newborn_until_newer_settled_bar, test_campaign_scope.py::test_revision_boundary_voids_and_restart_never_restores, test_campaign_draw_truth.py::test_restart_does_not_resurrect_old_process_authority, test_po3_episode_retirement.py::test_cold_canonical_replay_does_not_restore_retired_episode, test_conditional_plan_authority.py::test_saved_json_cannot_restore_live_plan_authority, test_po3_participation_binding.py::test_po3_lost_formation_after_successful_trigger_refuses_final_quote; bound-scope cells: test_bound_scope_history_custody.py (duplicate cutoff and restatement in both lanes, JSON copy, new-process replay, revision-skip and serialized-trust controls) | OFFLINE_CONSTRUCTED_REACHABLE for the bound cells. Revision-skip control shows the history revision is the bound scope's only protection against restated history; the formation additionally self-revokes on its settled-bar witness (independent defense) |
| S4-10 legacy/direct routes | PASS-BOUNDED | test_order_route_inventory.py (exact entry-write index, Lifecycle literal, smoke candidate origin, production import closure, 5 controls); test_legacy_smoke_route_fail_closed.py | Static over src/ and tools/; manual smoke tools are operator diagnostics outside production closure; no live test |
| S4-11 source/pin/coverage integrity | SOURCE VERIFIED; archive certification OWNER-RESERVED (D04) | test_recognition_ledger.py; tools/verify_engineering_ledger.py | Archive-dependent modules and credentialed skips remain an explicit inventory, never counted green |
| S4-12 source/evidence delivery | CLOSED | receiver-verified by owner 2026-10-17 | No renewed transfer |

## Adversarial matrix rows T01-T22 (Stage 4 invariants)

| Row | Current proof |
|---|---|
| T01 forming bar | test_campaign_premise_shadow.py (required-bucket certificate); test_po3_post_settlement_death.py |
| T02 future leakage | test_campaign_draw_temporal_authority.py; Stage 5 driver availability tests (M02/M03) |
| T03 duplicate cutoff | test_campaign_draw_temporal_authority.py::test_same_cutoff_recognition_cannot_promote_newborn_until_newer_settled_bar; test_campaign_scope.py::test_same_cutoff_fact_conflict_cannot_republish_or_activate; test_bound_scope_history_custody.py::test_duplicate_settled_cutoff_repeats_without_advancing_bound_custody |
| T04 missed scans | test_aligned_rolling_window_loop.py::test_missed_scan_reconstruction_keeps_the_formation (+ D-parent control) |
| T05 prefix eviction | test_rolling_window_prefix_eviction.py |
| T06 restatement | test_campaign_draw_truth.py history-revision nodes; test_po3_reversal_order_block.py::TestProducerOwnedFormationLifetime::test_revised_or_removed_proving_close_retires_prior_authority; test_bound_scope_history_custody.py restatement + revision-skip control |
| T07 restart/serialized | test_campaign_scope.py::test_revision_boundary_voids_and_restart_never_restores; test_conditional_plan_authority.py::test_saved_json_cannot_restore_live_plan_authority; test_bound_scope_history_custody.py JSON + new-process + serialized-trust control |
| T08 foreign publication | test_formation_view_publication.py::test_foreign_genuine_view_cannot_revive_an_object_the_consumer_retired; test_conditional_plan_authority.py::test_plan_authority_is_process_local_and_rejects_other_producer |
| T09 retirement / opposite P3 | test_po3_post_capture_release.py; test_po3_episode_retirement.py |
| T10 distinct anchor | test_po3_distinct_anchor_premise.py |
| T11 local death vs campaign | test_po3_post_settlement_death.py; test_campaign_lifecycle.py::test_local_opposite_fact_cannot_flip_campaign_owner |
| T12 scoped transfer | test_campaign_scope_binding.py; test_campaign_scope.py |
| T13 stale Draw generation | test_campaign_draw_exact_binding.py |
| T14 invalid action/occurrence | test_po3_execution_identity.py; test_po3_full_graph_production_loop.py::test_a_replaced_anchor_refuses_at_the_tool_gate_before_any_mission |
| T15 stale/expired plan | test_pre_authorized_conditional_plan.py; test_conditional_plan_across_alignment_step.py::test_expired_plan_is_not_resurrected_by_the_step |
| T16 trigger calls Brain | test_pre_authorized_conditional_plan.py::test_production_scan_cycle_invocation_counter_is_zero_on_trigger_scan; test_conditional_plan_authority.py::test_real_production_loop_trigger_passes_sealed_plan_without_brain_call |
| T17 final quote zone/expiry | test_latency1_final_quote_zone.py |
| T18 quote quality | test_latency1_final_quote_zone.py::test_final_quote_uses_quote_capture_directional_side; test_execution_reserve.py |
| T19 legacy route | test_order_route_inventory.py; test_legacy_smoke_route_fail_closed.py |
| T20 disarmed writes | test_production_scan_loop.py::TestArmGatesTheOrderPath; test_po3_full_graph_production_loop.py::test_disarmed_produces_the_same_candidate_and_stops_at_the_arm_switch |
| T21 mission reuse | test_po3_full_graph_production_loop.py::test_a_spent_mission_refuses_every_later_candidate |
| T22 ECU double advance | test_ecu_structure_flip_payload.py::test_brainless_scans_still_advance_flips_once_without_a_brain_call |

Rows T23-T32 belong to the Stage 5 harness and are proven by
`tests/test_recognition_*.py`.

## Observations recorded, not defects

- After a premise retirement, the authentic UNBOUND scope returns
  participation to the ratified D0=a local table (premise status UNKNOWN).
  A retirement therefore changes the authority source; it does not by
  itself stop participation.
- `src/ai_brain/thesis_lifecycle.py:214` reads `datetime.utcnow()` when no
  timestamp is supplied (stray wall clock on a reached path; T32 audit item).
